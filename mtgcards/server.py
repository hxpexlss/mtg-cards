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
from .importexport import export_csv, export_json, import_cards
from .netinfo import DiscoveryResponder, local_addresses, tailscale_dns_name
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
        self.scryfall = scryfall
        self.token = token
        self.kind = kind            # "server" oder "desktop"
        self.port = port
        self.desktop = desktop      # DesktopSettings-Objekt (nur Desktop)

    def remote(self):
        """(url, token) wenn der Desktop im Remote-Modus läuft, sonst None."""
        if self.desktop and self.desktop.cfg.get("mode") == "remote" and self.desktop.cfg.get("remote_url"):
            return self.desktop.cfg["remote_url"].rstrip("/"), self.desktop.cfg.get("remote_token", "")
        return None


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
        given = (self._token_from_request(qs) or "").strip().upper()
        if not hmac.compare_digest(given.encode(), token.strip().upper().encode()):
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
        base, token = remote
        body = self.read_body() if method in ("POST", "PATCH") else None
        target = base + url.path + (("?" + url.query) if url.query else "")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        req = Request(target, data=body, method=method, headers=headers)
        try:
            with urlopen(req, timeout=120) as resp:
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
        sort=_first(qs, "sort", "name"), limit=_first(qs, "limit", "500"),
        offset=_first(qs, "offset", "0"),
    )
    h.send_json({"total": total, "cards": cards, "revision": h.ctx.db.revision()})


def r_get(h, qs, cid):
    card = h.ctx.db.get(_card_id(cid))
    if not card:
        raise ApiError(404, "Karte nicht gefunden")
    h.send_json(card)


def _lookup_from(h, data):
    return h.ctx.scryfall.lookup(
        name=(data.get("name") or "").strip() or None,
        set_code=data.get("set") or data.get("set_code"),
        collector_number=data.get("cn") or data.get("collector_number"),
        lang=data.get("lang"),
        scryfall_id=data.get("id") or data.get("scryfall_id"),
    )


def r_lookup(h, qs):
    data = {k: _first(qs, k) for k in ("name", "set", "cn", "lang", "id")}
    if not any(data.values()):
        raise ApiError(400, "name oder id angeben")
    card = normalize_card(_lookup_from(h, data))
    card["owned"] = h.ctx.db.find_owned(card["scryfall_id"], card["oracle_id"])
    h.send_json(card)


def r_add(h, qs):
    data = h.read_json()
    if not (data.get("name") or data.get("scryfall_id") or data.get("id")):
        raise ApiError(400, "name oder scryfall_id angeben")
    card = normalize_card(_lookup_from(h, data))
    try:
        qty = int(data.get("quantity") or 1)
    except ValueError:
        raise ApiError(400, "Ungültige Anzahl") from None
    row, created = h.ctx.db.add(card, foil=bool(data.get("foil")), quantity=qty,
                                tags=data.get("tags") or [], notes=data.get("notes") or "")
    row["created"] = created
    row["owned"] = h.ctx.db.find_owned(row["scryfall_id"], row["oracle_id"])
    h.send_json(row, 201 if created else 200)


def r_patch(h, qs, cid):
    res = h.ctx.db.update(_card_id(cid), h.read_json())
    if res is None:
        raise ApiError(404, "Karte nicht gefunden")
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
    h.send_json(h.ctx.db.refresh_card_data(card["id"], normalize_card(raw)))


def r_refresh_all(h, qs):
    """Aktualisiert Kartendaten und Preise aller Karten per Scryfall-Sammelabfrage."""
    cards = h.ctx.db.all()
    fetched = h.ctx.scryfall.collection(sorted({c["scryfall_id"] for c in cards if c.get("scryfall_id")}))
    updated = 0
    for c in cards:
        raw = fetched.get(c.get("scryfall_id"))
        if raw:
            h.ctx.db.refresh_card_data(c["id"], normalize_card(raw))
            updated += 1
    h.send_json({"updated": updated, "total": len(cards), "missing": len(cards) - updated})


def r_autocomplete(h, qs):
    q = _first(qs, "q")
    h.send_json({"data": h.ctx.scryfall.autocomplete(q) if q else []})


def r_prints(h, qs):
    name = _first(qs, "name").strip()
    if not name:
        raise ApiError(400, "name angeben")
    out = []
    for raw in h.ctx.scryfall.prints(name):
        c = normalize_card(raw)
        out.append({k: c[k] for k in ("scryfall_id", "name", "set_code", "set_name",
                                      "collector_number", "rarity", "image_url", "lang",
                                      "price_eur", "price_usd")})
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


ROUTES = [
    ("GET", r"/api/info", r_info),
    ("GET", r"/api/revision", r_revision),
    ("GET", r"/api/stats", r_stats),
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


def test_remote(url, token):
    url = (url or "").strip().rstrip("/")
    if not url:
        return {"ok": False, "error": "Keine Server-Adresse angegeben"}
    if not re.match(r"^https?://", url):
        url = "http://" + url
    try:
        with urlopen(Request(url + "/api/health"), timeout=5) as r:
            health = json.loads(r.read().decode())
        if health.get("app") != APP_NAME:
            return {"ok": False, "error": "Gegenstelle ist kein MTG-Cards-Server"}
        req = Request(url + "/api/revision", headers={"Authorization": f"Bearer {token}"})
        with urlopen(req, timeout=5):
            pass
        return {"ok": True, "url": url, "health": health}
    except HTTPError as e:
        if e.code == 401:
            return {"ok": False, "error": "Server erreichbar, aber Token falsch"}
        return {"ok": False, "error": f"HTTP {e.code}"}
    except (URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"Nicht erreichbar: {e}"}


def cache_path_for(db_path):
    """Scryfall-Cache liegt neben der Datenbank (z.B. /var/lib/mtg-cards/scryfall-cache.db)."""
    if db_path == ":memory:":
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "scryfall-cache.db")


class Server:
    """Startet HTTP-Server (+ optional UDP-Discovery) in Hintergrund-Threads."""

    def __init__(self, db_path, token, bind="0.0.0.0", port=8765, kind="server",
                 discovery=True, desktop=None, scryfall=None):
        self.db = Database(db_path)
        if scryfall is None:
            scryfall = Scryfall(cache_path=cache_path_for(db_path))
        self.ctx = AppContext(self.db, scryfall, token, kind=kind,
                              port=port, desktop=desktop)
        handler = type("BoundHandler", (Handler,), {"ctx": self.ctx})
        ThreadingHTTPServer.allow_reuse_address = True
        self.httpd = ThreadingHTTPServer((bind, port), handler)
        self.httpd.daemon_threads = True
        self.ctx.port = self.httpd.server_address[1]
        self.discovery = DiscoveryResponder(self.ctx.port, kind) if discovery else None
        self._thread = None

    @property
    def port(self):
        return self.ctx.port

    def start(self):
        if self.discovery:
            self.discovery.start()
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="http")
        self._thread.start()
        return self

    def serve_forever(self):
        if self.discovery:
            self.discovery.start()
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.discovery:
            self.discovery.stop()
        self.db.close()
