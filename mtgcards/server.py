"""HTTP-Server: REST-API + Web-Oberfläche.

Wird vom Headless-Server und (eingebettet) von der Desktop-Anwendung genutzt.
"""

import hmac
import json
import mimetypes
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from . import APP_NAME, __version__
from .db import Database
from .decks import DeckStore
from .wishlist import Wishlist
from .importexport import export_csv, export_json, import_cards
from .netinfo import DiscoveryResponder, local_addresses, tailscale_dns_name
from . import tls
from .scryfall import Scryfall, ScryfallError, normalize_card

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_BODY = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class AppContext:
    """Gemeinsamer Zustand für alle Requests."""

    def __init__(self, db, scryfall, token, kind="server", port=None, desktop=None):
        self.db = db
        self.decks = DeckStore(db)
        self.wishlist = Wishlist(db)
        self.scryfall = scryfall
        self.token = token
        self.kind = kind            # "server" oder "desktop"
        self.port = port
        self.desktop = desktop      # DesktopSettings-Objekt (nur Desktop)
        self.tls_fingerprint = None

    def remote(self):
        """(url, token, fingerprint) wenn der Desktop im Remote-Modus läuft, sonst None."""
        cfg = self.desktop.cfg if self.desktop else {}
        if cfg.get("mode") == "remote" and cfg.get("remote_url"):
            return cfg["remote_url"].rstrip("/"), cfg.get("remote_token", ""), cfg.get("remote_fingerprint") or None
        return None


def normalize_token(t):
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def _first(qs, key, default=""):
    v = qs.get(key)
    return v[0] if v else default


class Handler(BaseHTTPRequestHandler):
    server_version = f"MTGCards/{__version__}"
    ctx: AppContext = None  # wird per Subklasse gesetzt

    # -- Logging leiser -----------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: D401
        if os.environ.get("MTGCARDS_DEBUG"):
            super().log_message(fmt, *args)

    # -- Antwort-Helfer ----------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, X-Auth-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, PUT, DELETE, OPTIONS")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_bytes(self, body, content_type, status=200, filename=None, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Anfrage zu groß")
        return self.rfile.read(length) if length else b""

    def read_json(self):
        raw = self.read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError(400, "Ungültiges JSON") from None

    # -- Auth ----------------------------------------------------------------
    def _token_from_request(self, qs):
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self.headers.get("X-Auth-Token") or _first(qs, "token")

    def check_auth(self, qs):
        token = self.ctx.token
        if not token:
            return
        # Vergleich ohne Leerzeichen/Bindestriche und unabhängig von Groß-/Kleinschreibung,
        # damit z.B. von der Handy-Tastatur eingefügte Leerzeichen nicht stören.
        given = normalize_token(self._token_from_request(qs) or "")
        if not given or not hmac.compare_digest(given.encode(), normalize_token(token).encode()):
            raise ApiError(401, "Nicht autorisiert – Zugangs-Token fehlt oder ist falsch")

    def is_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    # -- Dispatch --------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_PUT(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        qs = parse_qs(url.query)
        try:
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(405, "Methode nicht erlaubt")
                return self.serve_static(path)
            if path == "/api/health":
                return self.send_json(self.health())
            self.check_auth(qs)
            if path.startswith("/api/desktop/"):
                return self.desktop_api(method, path)
            remote = self.ctx.remote()
            if remote:
                return self.proxy(remote, method, url)
            for m, pattern, func in ROUTES:
                if m != method:
                    continue
                match = re.fullmatch(pattern, path)
                if match:
                    return func(self, qs, *match.groups())
            raise ApiError(404, "Unbekannter Endpunkt")
        except ApiError as e:
            self.send_json({"error": str(e)}, e.status)
        except ScryfallError as e:
            status = 404 if e.status == 404 else (503 if e.status >= 500 or e.status == 503 else 502)
            self.send_json({"error": str(e), "source": "scryfall"}, status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            try:
                self.send_json({"error": f"Interner Fehler: {e}"}, 500)
            except OSError:
                pass

    # -- Statische Dateien ----------------------------------------------------
    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not full.startswith(WEB_DIR + os.sep) or not os.path.isfile(full):
            full = os.path.join(WEB_DIR, "index.html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self.send_bytes(f.read(), ctype)

    # -- Remote-Proxy (Desktop im Remote-Modus) ----------------------------------
    def proxy(self, remote, method, url):
        base, token, fingerprint = remote
        body = self.read_body() if method in ("POST", "PATCH") else None
        target = base + url.path + (("?" + url.query) if url.query else "")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        req = Request(target, data=body, method=method, headers=headers)
        try:
            with tls.urlopen(req, timeout=120, fingerprint=fingerprint) as resp:
                data = resp.read()
                status = resp.status
                ctype = resp.headers.get("Content-Type", "application/json")
                disp = resp.headers.get("Content-Disposition")
        except HTTPError as e:
            data, status = e.read(), e.code
            ctype = e.headers.get("Content-Type", "application/json")
            disp = None
            if status == 401:
                data = json.dumps({"error": "Der Server hat den Zugangs-Token abgelehnt "
                                            "(Einstellungen → Server-Token prüfen)"}).encode()
                status = 502
        except (URLError, OSError) as e:
            raise ApiError(502, f"Server {base} nicht erreichbar: {e}") from None
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if disp:
            self.send_header("Content-Disposition", disp)
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    # -- Desktop-Einstellungen --------------------------------------------------
    def desktop_api(self, method, path):
        d = self.ctx.desktop
        if d is None:
            raise ApiError(404, "Nur in der Desktop-Anwendung verfügbar")
        if path == "/api/desktop/settings":
            if method == "GET":
                return self.send_json(d.public())
            if method == "POST":
                if not self.is_loopback():
                    raise ApiError(403, "Einstellungen nur lokal änderbar")
                return self.send_json(d.update(self.read_json()))
        if path == "/api/desktop/test-remote" and method == "POST":
            data = self.read_json()
            return self.send_json(test_remote(data.get("remote_url", ""), data.get("remote_token", "")))
        raise ApiError(404, "Unbekannter Endpunkt")

    # -- Endpunkte ----------------------------------------------------------------
    def health(self):
        remote = self.ctx.remote()
        return {
            "app": APP_NAME, "version": __version__, "kind": self.ctx.kind,
            "name": socket.gethostname(), "auth_required": bool(self.ctx.token),
            "mode": "remote" if remote else "local",
            "tls": bool(self.ctx.tls_fingerprint),
        }


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------

def _card_id(s):
    try:
        return int(s)
    except ValueError:
        raise ApiError(400, "Ungültige ID") from None


def r_info(h, qs):
    db = h.ctx.db
    h.send_json({
        **h.health(),
        "port": h.ctx.port,
        "tls_fingerprint": h.ctx.tls_fingerprint,
        "addresses": local_addresses(),
        "tailscale_name": tailscale_dns_name(),
        "stats": db.stats(),
    })


def r_revision(h, qs):
    h.send_json({"revision": h.ctx.db.revision()})


def r_stats(h, qs):
    h.send_json(h.ctx.db.stats())


def r_tags(h, qs):
    h.send_json({"tags": h.ctx.db.tag_counts()})


def r_list(h, qs):
    foil = _first(qs, "foil")
    cards, total = h.ctx.db.search(
        q=_first(qs, "q"), ci=_first(qs, "ci"), ci_mode=_first(qs, "ci_mode", "within"),
        tag=_first(qs, "tag"), type_=_first(qs, "type"), rarity=_first(qs, "rarity"),
        set_code=_first(qs, "set"), foil=None if foil == "" else foil in ("1", "true"),
        dup_min=_first(qs, "dup_min", "0") or 0,
        sort=_first(qs, "sort", "name"), limit=_first(qs, "limit", "500"),
        offset=_first(qs, "offset", "0"),
    )
    res = {"total": total, "cards": cards, "revision": h.ctx.db.revision()}
    if int(_first(qs, "dup_min", "0") or 0) > 1:
        res["duplicates"] = h.ctx.db.duplicate_summary(int(_first(qs, "dup_min")))
    h.send_json(res)


def r_get(h, qs, cid):
    card = h.ctx.db.get(_card_id(cid))
    if not card:
        raise ApiError(404, "Karte nicht gefunden")
    card["decks"] = h.ctx.decks.usage_for(card.get("oracle_id"), card["name"])
    card["related"] = h.ctx.db.related(card)
    h.send_json(card)


def _lookup_from(h, data):
    alts = data.get("alt") or []
    if isinstance(alts, str):
        alts = [alts]
    return h.ctx.scryfall.lookup_any(
        name=(data.get("name") or "").strip() or None,
        alternatives=alts,
        set_code=data.get("set") or data.get("set_code"),
        collector_number=data.get("cn") or data.get("collector_number"),
        lang=data.get("lang"),
        scryfall_id=data.get("id") or data.get("scryfall_id"),
        prefer_set=data.get("prefer_set"),
        total=data.get("total") or None,
        artist=data.get("artist") or None,
        year=data.get("year") or None,
    )


def r_lookup(h, qs):
    data = {k: _first(qs, k) for k in ("name", "set", "cn", "lang", "id", "prefer_set", "total", "artist", "year")}
    if data["lang"] == "auto":
        data["lang"] = ""
    data["alt"] = qs.get("alt", [])
    if not any(v for k, v in data.items() if k != "alt"):
        raise ApiError(400, "name oder id angeben")
    card = normalize_card(_lookup_from(h, data))
    card["owned"] = h.ctx.db.find_owned(card["scryfall_id"], card["oracle_id"])
    h.send_json(card)


def _add_one(h, data):
    """Fügt eine Karte hinzu und erfüllt passende Wünsche. Gibt (zeile, neu) zurück."""
    has_code = (data.get("set") or data.get("set_code")) and (data.get("cn") or data.get("collector_number"))
    if not (data.get("name") or data.get("scryfall_id") or data.get("id") or has_code):
        raise ApiError(400, "name, scryfall_id oder Set + Sammlernummer angeben")
    card = normalize_card(_lookup_from(h, data))
    try:
        qty = int(data.get("quantity") or 1)
    except ValueError:
        raise ApiError(400, "Ungültige Anzahl") from None
    row, created = h.ctx.db.add(card, foil=bool(data.get("foil")), quantity=qty,
                                tags=data.get("tags") or [], notes=data.get("notes") or "")
    row["created"] = created
    row["owned"] = h.ctx.db.find_owned(row["scryfall_id"], row["oracle_id"])
    # Proxies erfüllen keine Wünsche
    row["wish_fulfilled"] = [] if row.get("proxy") else h.ctx.wishlist.fulfill(card, qty)
    # Optional direkt in ein Deck (Ziel-Deck beim Scannen)
    row["deck"] = None
    deck_id = data.get("deck_id")
    if deck_id:
        try:
            deck = h.ctx.decks.set_card(int(deck_id), card, qty, data.get("board") or "main", add=True)
        except (TypeError, ValueError):
            deck = None
        if deck:
            row["deck"] = {"id": deck["id"], "name": deck["name"]}
    return row, created


def r_add(h, qs):
    row, created = _add_one(h, h.read_json())
    h.send_json(row, 201 if created else 200)


def r_add_batch(h, qs):
    """Stapel-Scan: viele Karten auf einmal speichern. Fehler einzelner Karten brechen nicht ab."""
    data = h.read_json()
    results, errors, wishes = [], [], []
    for i, item in enumerate(data.get("cards") or []):
        try:
            row, created = _add_one(h, item)
            results.append({"index": i, "id": row["id"], "name": row["name"], "quantity": row["quantity"],
                            "created": created})
            wishes += row["wish_fulfilled"]
        except (ApiError, ScryfallError) as e:
            errors.append({"index": i, "name": item.get("name") or item.get("scryfall_id"), "error": str(e)})
    h.send_json({"added": sum(int(c.get("quantity") or 1) for i, c in enumerate(data.get("cards") or [])
                              if any(r["index"] == i for r in results)),
                 "results": results, "errors": errors, "wish_fulfilled": wishes})


def r_patch(h, qs, cid):
    data = h.read_json()
    new_id = data.pop("scryfall_id", None)
    if new_id:
        # Anderen Druck übernehmen (Edition / Sprache korrigieren)
        try:
            raw = h.ctx.scryfall.with_prices(h.ctx.scryfall.lookup(scryfall_id=new_id))
        except ScryfallError as e:
            raise ApiError(e.status if e.status in (400, 404) else 502, str(e)) from None
        if h.ctx.db.get(_card_id(cid)) is None:
            raise ApiError(404, "Karte nicht gefunden")
        cid = h.ctx.db.change_print(_card_id(cid), normalize_card(raw))["id"]
        if not data:
            res = h.ctx.db.get(cid)
            res["decks"] = h.ctx.decks.usage_for(res.get("oracle_id"), res["name"])
            res["related"] = h.ctx.db.related(res)
            return h.send_json(res)
    res = h.ctx.db.update(_card_id(cid), data)
    if res is None:
        raise ApiError(404, "Karte nicht gefunden")
    if not res.get("deleted"):
        res["decks"] = h.ctx.decks.usage_for(res.get("oracle_id"), res["name"])
        res["related"] = h.ctx.db.related(res)
    h.send_json(res)


def r_delete(h, qs, cid):
    if not h.ctx.db.delete(_card_id(cid)):
        raise ApiError(404, "Karte nicht gefunden")
    h.send_json({"deleted": True, "id": int(cid)})


def r_refresh(h, qs, cid):
    card = h.ctx.db.get(_card_id(cid))
    if not card:
        raise ApiError(404, "Karte nicht gefunden")
    if card.get("scryfall_id"):
        raw = h.ctx.scryfall.lookup(scryfall_id=card["scryfall_id"])
    else:
        raw = h.ctx.scryfall.lookup(name=card["name"], set_code=card.get("set_code"),
                                    collector_number=card.get("collector_number"))
    h.send_json(h.ctx.db.refresh_card_data(card["id"], normalize_card(h.ctx.scryfall.with_prices(raw))))


def refresh_all(ctx):
    """Aktualisiert Kartendaten und Preise aller Karten per Scryfall-Sammelabfrage und speichert den Wert."""
    from .db import now_iso
    cards = ctx.db.all()
    fetched = ctx.scryfall.collection(sorted({c["scryfall_id"] for c in cards if c.get("scryfall_id")}))
    # Fremdsprachige Drucke haben bei Scryfall keine Preise -> vom englischen Druck übernehmen
    if hasattr(ctx.scryfall, "fill_prices"):
        fetched = ctx.scryfall.fill_prices(fetched)
    updated = 0
    for c in cards:
        raw = fetched.get(c.get("scryfall_id"))
        if raw:
            ctx.db.refresh_card_data(c["id"], normalize_card(raw))
            updated += 1
    ctx.db.set_meta("last_price_refresh", now_iso())
    ctx.db.snapshot_value()
    wishes = None
    try:
        wishes = ctx.wishlist.refresh_prices(ctx.scryfall)
    except ScryfallError:
        pass
    try:
        ctx.decks.refresh_prices(ctx.scryfall)
    except ScryfallError:
        pass
    return {"updated": updated, "total": len(cards), "missing": len(cards) - updated, "wishlist": wishes}


def r_refresh_all(h, qs):
    h.send_json(refresh_all(h.ctx))


def r_stats_detail(h, qs):
    from .db import now_iso
    hist = h.ctx.db.value_history(1)
    if not hist or hist[-1]["day"] != now_iso()[:10]:
        h.ctx.db.snapshot_value()   # mind. ein Datenpunkt pro Tag, auch ohne Preis-Aktualisierung
    h.send_json(h.ctx.db.detailed_stats())


def r_autocomplete(h, qs):
    q = _first(qs, "q")
    h.send_json({"data": h.ctx.scryfall.autocomplete(q) if q else []})


def r_prints(h, qs):
    name = _first(qs, "name").strip()
    if not name:
        raise ApiError(400, "name angeben")
    lang = _first(qs, "lang").strip().lower()
    out = []
    for raw in h.ctx.scryfall.prints(name, lang) if lang else h.ctx.scryfall.prints(name):
        c = normalize_card(raw)
        out.append({k: c.get(k) for k in ("scryfall_id", "name", "printed_name", "set_code", "set_name",
                                          "collector_number", "rarity", "image_url", "lang",
                                          "price_eur", "price_eur_foil", "price_usd", "artist", "released_at",
                                          "illustration_id", "art_url")})
    h.send_json({"data": out})


def r_export(h, qs):
    fmt = _first(qs, "format", "json").lower()
    if fmt == "csv":
        h.send_bytes(export_csv(h.ctx.db).encode("utf-8"), "text/csv; charset=utf-8",
                     filename="mtg-cards-export.csv")
    else:
        h.send_bytes(export_json(h.ctx.db).encode("utf-8"), "application/json; charset=utf-8",
                     filename="mtg-cards-export.json")


def r_import(h, qs):
    mode = _first(qs, "mode", "add")
    if mode not in ("add", "replace"):
        raise ApiError(400, "mode muss 'add' oder 'replace' sein")
    raw = h.read_body()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        result = import_cards(h.ctx.db, h.ctx.scryfall, text, mode=mode)
    except ValueError as e:
        raise ApiError(400, f"Datei konnte nicht gelesen werden: {e}") from None
    h.send_json(result)


# -- Decks ---------------------------------------------------------------------

def _deck_or_404(deck):
    if deck is None:
        raise ApiError(404, "Deck nicht gefunden")
    return deck


def r_decks(h, qs):
    h.send_json({"decks": h.ctx.decks.list()})


def r_deck_create(h, qs):
    data = h.read_json()
    try:
        deck = h.ctx.decks.create(data.get("name"), data.get("format") or "commander", data.get("notes") or "",
                                  status=data.get("status") or "build")
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    result = {"deck": deck, "errors": []}
    if (data.get("list") or "").strip():
        res = h.ctx.decks.import_list(deck["id"], h.ctx.scryfall, data["list"])
        result = {"deck": res["deck"], "errors": res["errors"]}
    h.send_json(result, 201)


def r_deck_get(h, qs, did):
    h.send_json(_deck_or_404(h.ctx.decks.get(_card_id(did))))


def r_deck_patch(h, qs, did):
    h.send_json(_deck_or_404(h.ctx.decks.update(_card_id(did), h.read_json())))


def r_deck_delete(h, qs, did):
    if not h.ctx.decks.delete(_card_id(did)):
        raise ApiError(404, "Deck nicht gefunden")
    h.send_json({"deleted": True})


def r_deck_import(h, qs, did):
    data = h.read_json()
    try:
        res = h.ctx.decks.import_list(_card_id(did), h.ctx.scryfall, data.get("text") or "",
                                      replace=bool(data.get("replace")))
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    h.send_json(_deck_or_404(res))


def r_deck_add_card(h, qs, did):
    data = h.read_json()
    card = None
    if data.get("collection_id"):
        card = h.ctx.db.get(_card_id(str(data["collection_id"])))
        if card is None:
            raise ApiError(404, "Karte nicht in der Sammlung")
    else:
        if not (data.get("name") or data.get("scryfall_id")):
            raise ApiError(400, "name, scryfall_id oder collection_id angeben")
        card = normalize_card(_lookup_from(h, data))
    deck = h.ctx.decks.set_card(_card_id(did), card, int(data.get("quantity") or 1),
                                data.get("board") or "main", add=data.get("add", True))
    h.send_json(_deck_or_404(deck))


def r_deck_card_patch(h, qs, cid):
    h.send_json(_deck_or_404(h.ctx.decks.update_card(_card_id(cid), h.read_json())))


def r_deck_card_delete(h, qs, cid):
    h.send_json(_deck_or_404(h.ctx.decks.remove_card(_card_id(cid))))


def r_deck_export(h, qs, did):
    text = h.ctx.decks.export_text(_card_id(did), only_missing=_first(qs, "missing") in ("1", "true"))
    if text is None:
        raise ApiError(404, "Deck nicht gefunden")
    h.send_bytes(text.encode("utf-8"), "text/plain; charset=utf-8")


# -- Wunschliste -----------------------------------------------------------------

def r_wish_list(h, qs):
    h.send_json(h.ctx.wishlist.list())


def _parse_price(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".").replace("€", "").strip())
    except ValueError:
        raise ApiError(400, "Ungültiger Zielpreis") from None


def r_wish_add(h, qs):
    data = h.read_json()
    if not (data.get("name") or data.get("scryfall_id")):
        raise ApiError(400, "name oder scryfall_id angeben")
    card = normalize_card(_lookup_from(h, data))
    any_print = data.get("any_print", not data.get("scryfall_id"))
    foil = bool(data.get("foil"))
    price = pset = None
    if any_print:
        try:
            best = h.ctx.wishlist.cheapest_print(h.ctx.scryfall, card["name"], foil)
            if best:
                price, pset = best
        except ScryfallError:
            pass
    item = h.ctx.wishlist.add(card, int(data.get("quantity") or 1), _parse_price(data.get("max_price_eur")),
                              any_print=any_print, foil=foil, notes=data.get("notes") or "",
                              price=price, price_set=pset)
    h.send_json(item, 201)


def r_wish_patch(h, qs, wid):
    data = h.read_json()
    if "max_price_eur" in data:
        data["max_price_eur"] = _parse_price(data["max_price_eur"])
    res = h.ctx.wishlist.update(_card_id(wid), data)
    if res is None:
        raise ApiError(404, "Wunsch nicht gefunden")
    h.send_json(res)


def r_wish_delete(h, qs, wid):
    if not h.ctx.wishlist.delete(_card_id(wid)):
        raise ApiError(404, "Wunsch nicht gefunden")
    h.send_json({"deleted": True})


def r_wish_refresh(h, qs):
    h.send_json(h.ctx.wishlist.refresh_prices(h.ctx.scryfall))


def r_deck_to_wishlist(h, qs, did):
    """Fehlende Karten eines Decks auf die Wunschliste setzen (günstigster Druck)."""
    deck = _deck_or_404(h.ctx.decks.get(_card_id(did)))
    added = []
    for c in deck["cards"]:
        if c["board"] not in ("commander", "main") or c["missing"] <= 0:
            continue
        price = pset = None
        try:
            best = h.ctx.wishlist.cheapest_print(h.ctx.scryfall, c["name"])
            if best:
                price, pset = best
        except ScryfallError:
            pass
        card = {k: c.get(k) for k in ("name", "oracle_id", "type_line", "mana_cost", "color_identity", "image_url")}
        h.ctx.wishlist.add(card, c["missing"], None, any_print=True, price=price, price_set=pset,
                           notes=f"für Deck {deck['name']}")
        added.append(c["name"])
    h.send_json({"added": added})


# -- Editionen / Sammelfortschritt ----------------------------------------------------

_MAIN_RARITIES = ("common", "uncommon", "rare", "mythic")


def _is_main(card, printed_size):
    """Grundset = Sammlernummer innerhalb der gedruckten Setgröße (ohne Showcase/randlos/Extras)."""
    digits = "".join(ch for ch in (card.get("collector_number") or "") if ch.isdigit())
    return bool(printed_size) and digits == (card.get("collector_number") or "") and digits and \
        int(digits) <= printed_size


def _set_meta(h):
    try:
        return {s["code"].upper(): s for s in h.ctx.scryfall.sets()}
    except ScryfallError:
        return {}


def r_sets(h, qs):
    """Editionen der Sammlung mit Fortschritt (Grundset und inkl. Varianten)."""
    meta = _set_meta(h)
    out = []
    for s in h.ctx.db.owned_sets():
        m = meta.get(s["set_code"], {})
        printed = m.get("printed_size") or m.get("card_count") or 0
        total = m.get("card_count") or 0
        own = h.ctx.db.set_ownership(s["set_code"])
        main_owned = sum(1 for cn in own if cn.isdigit() and printed and int(cn) <= printed)
        out.append({
            "code": s["set_code"], "name": m.get("name") or s["set_name"], "icon": m.get("icon_svg_uri"),
            "released": m.get("released_at"), "set_type": m.get("set_type"),
            "owned_prints": s["prints"], "owned_cards": s["cards"],
            "total": total, "main_size": printed, "main_owned": main_owned,
            "percent": round(100 * main_owned / printed, 1) if printed else None,
        })
    out.sort(key=lambda x: (-(x["percent"] or 0), x["name"] or ""))
    h.send_json({"sets": out})


def r_set_detail(h, qs, code):
    """Alle Karten einer Edition mit Besitz-Status (Kartenliste von Scryfall, zwischengespeichert)."""
    code = code.upper()
    raw = h.ctx.scryfall.set_cards(code)
    if not raw:
        raise ApiError(404, f"Edition {code} nicht gefunden")
    try:
        info = h.ctx.scryfall.set_info(code)
    except ScryfallError:
        info = {}
    printed = info.get("printed_size") or info.get("card_count") or len(raw)
    own = h.ctx.db.set_ownership(code)
    cards, stats = [], {}
    for r in raw:
        c = normalize_card(r)
        o = own.get(c["collector_number"], {})
        main = _is_main(c, printed)
        try:
            price = float(c.get("price_eur") or c.get("price_eur_foil") or 0)
        except ValueError:
            price = 0.0
        entry = {k: c.get(k) for k in ("scryfall_id", "name", "collector_number", "rarity", "image_url",
                                       "mana_cost", "type_line", "color_identity", "price_eur")}
        entry.update(owned=o.get("quantity", 0), owned_foil=o.get("foil", 0), main=main,
                     price=round(price, 2), ids=o.get("ids", []))
        cards.append(entry)
        for scope in ("main", "all") if main else ("all",):
            for rar in (c["rarity"], "_all"):
                st = stats.setdefault(scope, {}).setdefault(rar, {"total": 0, "owned": 0, "missing_value": 0.0})
                st["total"] += 1
                if o.get("quantity"):
                    st["owned"] += 1
                else:
                    st["missing_value"] += price
    for scope in stats.values():
        for st in scope.values():
            st["missing_value"] = round(st["missing_value"], 2)
            st["percent"] = round(100 * st["owned"] / st["total"], 1) if st["total"] else 0
    h.send_json({"code": code, "name": info.get("name") or (cards[0]["name"] if cards else code),
                 "icon": info.get("icon_svg_uri"), "released": info.get("released_at"),
                 "main_size": printed, "stats": stats, "cards": cards})


def r_wish_bulk(h, qs):
    """Mehrere bestimmte Drucke auf die Wunschliste (z.B. fehlende Karten einer Edition)."""
    data = h.read_json()
    ids = [i for i in data.get("scryfall_ids") or [] if i]
    if not ids:
        raise ApiError(400, "Keine Karten angegeben")
    fetched = h.ctx.scryfall.collection(ids)
    added = []
    for sid in ids:
        raw = fetched.get(sid)
        if not raw:
            continue
        card = normalize_card(raw)
        h.ctx.wishlist.add(card, 1, None, any_print=False, notes=data.get("notes") or "")
        added.append(card["name"])
    h.send_json({"added": added})


# -- Proxies (PDF) -----------------------------------------------------------------

def _proxy_cache_dir(h):
    path = h.ctx.db.path
    return None if path == ":memory:" else os.path.join(os.path.dirname(os.path.abspath(path)), "proxy-images")


def _send_proxies(h, qs, items, title, filename):
    from . import proxies
    if not items:
        raise ApiError(400, "Keine Karten ausgewählt")
    entries, errors = proxies.collect_entries(h.ctx.scryfall, items, _proxy_cache_dir(h),
                                              fetch=getattr(h.ctx, "image_fetcher", proxies.fetch_image))
    if not entries:
        raise ApiError(404, "Keine Karten gefunden: " + "; ".join(errors))
    try:
        gap = float(_first(qs, "gap", "0").replace(",", "."))
    except ValueError:
        gap = 0.0
    pdf = proxies.build_pdf(entries, paper=_first(qs, "paper", "a4"), cut_marks=_first(qs, "cut", "1") != "0",
                            gap_mm=gap, title=title)
    h.send_bytes(pdf, "application/pdf", filename=filename)


def r_wish_proxies(h, qs):
    """Proxy-PDF aus der Wunschliste. ids=1,2,3 (leer = alle); copies=wish (Anzahl) oder one."""
    wanted = {int(x) for x in _first(qs, "ids").split(",") if x.strip().isdigit()}
    one = _first(qs, "copies", "wish") == "one"
    items = [{"name": w["name"], "scryfall_id": w["scryfall_id"], "copies": 1 if one else w["quantity"]}
             for w in h.ctx.wishlist.list()["items"] if not wanted or w["id"] in wanted]
    _send_proxies(h, qs, items, "MTG Cards Proxies - Wunschliste", "proxies-wunschliste.pdf")


def r_deck_proxies(h, qs, did):
    """Proxy-PDF für ein Deck: missing=1 (Standard) nur fehlende Karten, sonst alle."""
    deck = _deck_or_404(h.ctx.decks.get(_card_id(did)))
    only_missing = _first(qs, "missing", "1") != "0"
    one = _first(qs, "copies", "") == "one"
    items = []
    for c in deck["cards"]:
        if c["board"] not in ("commander", "main") or (c["basic"] and only_missing):
            continue
        n = c["missing"] if only_missing else c["quantity"]
        if n > 0:
            items.append({"name": c["name"], "copies": 1 if one else n})
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", deck["name"]).strip("-") or "deck"
    _send_proxies(h, qs, items, f"MTG Cards Proxies - {deck['name']}", f"proxies-{safe}.pdf")


ROUTES = [
    ("GET", r"/api/sets", r_sets),
    ("GET", r"/api/sets/([A-Za-z0-9]{2,8})", r_set_detail),
    ("POST", r"/api/wishlist/bulk", r_wish_bulk),
    ("GET", r"/api/wishlist/proxies\.pdf", r_wish_proxies),
    ("GET", r"/api/decks/(\d+)/proxies\.pdf", r_deck_proxies),
    ("GET", r"/api/wishlist", r_wish_list),
    ("POST", r"/api/wishlist", r_wish_add),
    ("POST", r"/api/wishlist/refresh", r_wish_refresh),
    ("PATCH", r"/api/wishlist/(\d+)", r_wish_patch),
    ("DELETE", r"/api/wishlist/(\d+)", r_wish_delete),
    ("POST", r"/api/decks/(\d+)/to-wishlist", r_deck_to_wishlist),
    ("POST", r"/api/cards/batch", r_add_batch),
    ("GET", r"/api/decks", r_decks),
    ("POST", r"/api/decks", r_deck_create),
    ("GET", r"/api/decks/(\d+)", r_deck_get),
    ("PATCH", r"/api/decks/(\d+)", r_deck_patch),
    ("DELETE", r"/api/decks/(\d+)", r_deck_delete),
    ("POST", r"/api/decks/(\d+)/import", r_deck_import),
    ("POST", r"/api/decks/(\d+)/cards", r_deck_add_card),
    ("GET", r"/api/decks/(\d+)/export", r_deck_export),
    ("PATCH", r"/api/deck-cards/(\d+)", r_deck_card_patch),
    ("DELETE", r"/api/deck-cards/(\d+)", r_deck_card_delete),
    ("GET", r"/api/info", r_info),
    ("GET", r"/api/revision", r_revision),
    ("GET", r"/api/stats", r_stats),
    ("GET", r"/api/stats/detail", r_stats_detail),
    ("GET", r"/api/tags", r_tags),
    ("GET", r"/api/cards", r_list),
    ("POST", r"/api/cards", r_add),
    ("GET", r"/api/cards/(\d+)", r_get),
    ("PATCH", r"/api/cards/(\d+)", r_patch),
    ("DELETE", r"/api/cards/(\d+)", r_delete),
    ("POST", r"/api/cards/(\d+)/refresh", r_refresh),
    ("POST", r"/api/refresh-all", r_refresh_all),
    ("GET", r"/api/lookup", r_lookup),
    ("GET", r"/api/autocomplete", r_autocomplete),
    ("GET", r"/api/prints", r_prints),
    ("GET", r"/api/export", r_export),
    ("POST", r"/api/import", r_import),
]


def test_remote(url, token, fingerprint=None):
    """Prüft Erreichbarkeit und Token eines Servers.

    Bei HTTPS mit selbstsigniertem Zertifikat ohne bekannten Fingerabdruck wird
    {"ok": False, "needs_trust": True, "fingerprint": ...} zurückgegeben – der Benutzer muss bestätigen.
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return {"ok": False, "error": "Keine Server-Adresse angegeben"}
    if not re.match(r"^https?://", url):
        url = "http://" + url
    try:
        with tls.urlopen(Request(url + "/api/health"), timeout=5, fingerprint=fingerprint) as r:
            health = json.loads(r.read().decode())
        if health.get("app") != APP_NAME:
            return {"ok": False, "error": "Gegenstelle ist kein MTG-Cards-Server"}
        req = Request(url + "/api/revision", headers={"Authorization": f"Bearer {token}"})
        with tls.urlopen(req, timeout=5, fingerprint=fingerprint):
            pass
        return {"ok": True, "url": url, "health": health, "fingerprint": fingerprint}
    except HTTPError as e:
        if e.code == 401:
            return {"ok": False, "error": "Server erreichbar, aber Token falsch"}
        return {"ok": False, "error": f"HTTP {e.code}"}
    except (URLError, OSError, ValueError) as e:
        if url.startswith("https://") and not fingerprint and tls.is_cert_verify_error(e):
            parsed = urlparse(url)
            try:
                fp = tls.fetch_fingerprint(parsed.hostname, parsed.port or 443)
            except OSError as e2:
                return {"ok": False, "error": f"Nicht erreichbar: {e2}"}
            return {"ok": False, "needs_trust": True, "fingerprint": fp, "url": url,
                    "error": "Selbstsigniertes Zertifikat – Fingerabdruck bestätigen"}
        if "Fingerabdruck" in str(e):
            return {"ok": False, "error": "Zertifikat hat sich geändert! " + str(e)}
        return {"ok": False, "error": f"Nicht erreichbar: {e}"}


def cache_path_for(db_path):
    """Scryfall-Cache liegt neben der Datenbank (z.B. /var/lib/mtg-cards/scryfall-cache.db)."""
    if db_path == ":memory:":
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "scryfall-cache.db")


class QuietHTTPServer(ThreadingHTTPServer):
    """Keine Tracebacks bei abgebrochenen Verbindungen / fehlgeschlagenen TLS-Handshakes."""
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        import ssl
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ssl.SSLError, ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class Server:
    """Startet HTTP(S)-Server (+ optional UDP-Discovery) in Hintergrund-Threads.

    tls_cert/tls_key: HTTPS aktivieren.
    local_http: zusätzlicher unverschlüsselter Listener nur auf 127.0.0.1 (für das Desktop-Fenster).
    """

    def __init__(self, db_path, token, bind="0.0.0.0", port=8765, kind="server",
                 discovery=True, desktop=None, scryfall=None, tls_cert=None, tls_key=None,
                 local_http=False, auto_refresh_hours=0):
        self.db = Database(db_path)
        if scryfall is None:
            scryfall = Scryfall(cache_path=cache_path_for(db_path))
        self.ctx = AppContext(self.db, scryfall, token, kind=kind,
                              port=port, desktop=desktop)
        handler = type("BoundHandler", (Handler,), {"ctx": self.ctx})
        self.httpd = QuietHTTPServer((bind, port), handler)
        self.servers = [self.httpd]
        self.local_port = None
        if tls_cert and tls_key:
            tls.wrap_server_socket(self.httpd, tls_cert, tls_key)
            self.ctx.tls_fingerprint = tls.fingerprint_file(tls_cert)
            if local_http:
                local = QuietHTTPServer(("127.0.0.1", 0), handler)
                self.servers.append(local)
                self.local_port = local.server_address[1]
        self.ctx.port = self.httpd.server_address[1]
        self.discovery = DiscoveryResponder(self.ctx.port, kind, tls_fingerprint=self.ctx.tls_fingerprint) \
            if discovery else None
        self._threads = []
        self.auto_refresh_hours = auto_refresh_hours
        self._stop = threading.Event()
        self._serving = False

    def _auto_refresh_loop(self):
        """Aktualisiert Preise regelmäßig (Standard: täglich) und speichert den Sammlungswert."""
        from datetime import datetime, timezone
        if self._stop.wait(60):
            return
        while not self._stop.is_set():
            try:
                if not self.ctx.remote():
                    last = self.db.get_meta("last_price_refresh")
                    age = None
                    if last:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
                    if age is None or age >= self.auto_refresh_hours:
                        res = refresh_all(self.ctx)
                        print(f"[preise] {res['updated']} Karten aktualisiert", flush=True)
            except Exception as e:  # noqa: BLE001 – offline o.ä.: später erneut versuchen
                print(f"[preise] Aktualisierung fehlgeschlagen: {e}", flush=True)
            if self._stop.wait(3600):
                return

    def _start_background(self):
        if self.auto_refresh_hours and self.auto_refresh_hours > 0:
            threading.Thread(target=self._auto_refresh_loop, daemon=True, name="price-refresh").start()

    @property
    def port(self):
        return self.ctx.port

    @property
    def scheme(self):
        return "https" if self.ctx.tls_fingerprint else "http"

    def start(self):
        self._start_background()
        if self.discovery:
            self.discovery.start()
        for srv in self.servers:
            t = threading.Thread(target=srv.serve_forever, daemon=True, name="http")
            t.start()
            self._threads.append(t)
        return self

    def serve_forever(self):
        self._serving = True
        self._start_background()
        if self.discovery:
            self.discovery.start()
        for srv in self.servers[1:]:
            threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
        self.httpd.serve_forever()

    def stop(self):
        self._stop.set()
        for srv in self.servers:
            if self._threads or srv is self.httpd and self._serving:
                srv.shutdown()          # blockiert nur, wenn serve_forever läuft
            srv.server_close()
        if self.discovery:
            self.discovery.stop()
        self.db.close()
