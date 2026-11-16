"""Proxie Maker: API-Endpunkte (unter /proxies/api/…) – werden vom MTG-Cards-Server mit ausgeliefert."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .. import __version__, tls
from ..decks import parse_decklist
from ..proxies import fetch_image
from ..scryfall import ScryfallError
from .printing import fetch_any, make_pdf, make_zip
from .store import Store, StoreError, card_fields, decode_jpeg, price_of

APP_NAME = "proxie-maker"


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class PMContext:
    """Zustand von Proxie Maker. mtg = AppContext von MTG Cards (Wunschliste/Decks direkt, ohne Netz)."""

    def __init__(self, db_path, scryfall, cache_dir=None, mtg=None, kind="server"):
        self.store = Store(db_path)
        self.scryfall = scryfall
        self.cache_dir = cache_dir
        self.mtg = mtg
        self.kind = kind
        self.image_fetcher = fetch_image
        self.any_fetcher = fetch_any

    def close(self):
        self.store.close()


class PMRequest:
    """Verbindet einen Request des MTG-Cards-Servers mit dem Proxie-Maker-Kontext."""

    def __init__(self, handler, ctx):
        self.ctx = ctx
        self.send_json = handler.send_json
        self.send_bytes = handler.send_bytes
        self.read_json = handler.read_json


def _first(qs, key, default=""):
    v = qs.get(key)
    return v[0] if v else default


def dispatch(handler, ctx, method, path, qs):
    """path ohne /proxies-Präfix, z.B. /api/projects/3. Gibt False zurück, wenn kein Endpunkt passt."""
    req = PMRequest(handler, ctx)
    for m, pattern, func in ROUTES:
        if m == method:
            match = re.fullmatch(pattern, path)
            if match:
                try:
                    func(req, qs, *match.groups())
                except ApiError as e:
                    handler.send_json({"error": str(e)}, e.status)
                except StoreError as e:
                    handler.send_json({"error": str(e)}, 400)
                except ScryfallError as e:
                    handler.send_json({"error": str(e), "source": "scryfall"}, 404 if e.status == 404 else 502)
                return True
    return False


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _id(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        raise ApiError(400, "Ungültige ID") from None


def _qty(v, default=1):
    try:
        return max(1, min(999, int(v)))
    except (TypeError, ValueError):
        if v in (None, ""):
            return default
        raise ApiError(400, "Ungültige Anzahl") from None


def _price_in(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".").replace("€", "").strip())
    except ValueError:
        raise ApiError(400, "Ungültiger Zielpreis") from None


def _project_or_404(p):
    if p is None:
        raise ApiError(404, "Druckliste nicht gefunden")
    return p


def _item_or_404(h, iid):
    it = h.ctx.store.item(_id(iid))
    if it is None:
        raise ApiError(404, "Karte nicht gefunden")
    return it


def _cheapest(h, name):
    best = None
    for raw in h.ctx.scryfall.prints(name):
        if raw.get("digital"):
            continue
        p = price_of(raw)
        if p is not None and (best is None or p < best[0]):
            best = (p, (raw.get("set") or "").upper())
    return best


def _resolve(h, data):
    """Karte nachschlagen -> (felder, preis, preis_edition, beliebig)."""
    sid = data.get("scryfall_id") or data.get("id")
    lang = (data.get("lang") or "").strip().lower() or None
    raw = h.ctx.scryfall.lookup_any(name=(data.get("name") or "").strip() or None, scryfall_id=sid, lang=lang,
                                    set_code=data.get("set"), collector_number=data.get("cn"))
    any_print = bool(data.get("any_print")) and not sid and not data.get("set")
    fields = card_fields(raw)
    price, pset = price_of(raw), None
    if any_print:
        try:
            best = _cheapest(h, fields["name"])
            if best:
                price, pset = best
        except ScryfallError:
            pass
    return fields, price, pset, any_print


def _resolve_many(h, wanted, lang=None):
    """Viele Karten auf einmal: Scryfall-Sammelabfrage (75 Karten pro Anfrage) statt einzelner Suchen.

    wanted: [{"name", "set", "cn", "scryfall_id", "any_print"}]. Gibt [(eintrag, (felder, preis, edition, beliebig)
    oder ScryfallError)] zurück. Nicht gefundene (z.B. deutsche Namen) werden einzeln nachgeschlagen. Den günstigsten
    Druck bei „beliebig“ berechnet die Preisprüfung später – das spart pro Karte eine Suche.
    """
    sf = h.ctx.scryfall
    lang = (lang or "").strip().lower() or None
    out = [None] * len(wanted)
    found = {}
    if hasattr(sf, "collection_identifiers"):
        idents = []
        for w in wanted:
            if w.get("scryfall_id"):
                idents.append({"id": w["scryfall_id"]})
            elif w.get("set") and w.get("cn"):
                idents.append({"set": str(w["set"]).lower(), "collector_number": str(w["cn"])})
            elif w.get("set"):
                idents.append({"name": w["name"].split(" // ")[0], "set": str(w["set"]).lower()})
            else:
                idents.append({"name": w["name"].split(" // ")[0]})
        try:
            cards, _ = sf.collection_identifiers(idents)
        except ScryfallError:
            cards = []
        for c in cards:
            found[("id", c.get("id"))] = c
            found[("sc", (c.get("set") or "").lower(), str(c.get("collector_number")))] = c
            for n in [c.get("name") or ""] + (c.get("name") or "").split(" // ")[:1]:
                found.setdefault(("name", n.lower()), c)
                found.setdefault(("nameset", n.lower(), (c.get("set") or "").lower()), c)
    for i, w in enumerate(wanted):
        raw = None
        if w.get("scryfall_id"):
            raw = found.get(("id", w["scryfall_id"]))
        elif w.get("set") and w.get("cn"):
            raw = found.get(("sc", str(w["set"]).lower(), str(w["cn"]).lstrip("0") or "0")) or \
                found.get(("sc", str(w["set"]).lower(), str(w["cn"])))
        elif w.get("set"):
            raw = found.get(("nameset", w["name"].split(" // ")[0].lower(), str(w["set"]).lower()))
        else:
            raw = found.get(("name", w["name"].lower())) or found.get(("name", w["name"].split(" // ")[0].lower()))
        try:
            if raw is None:   # z.B. deutscher Name -> einzeln (Namenssuche in allen Sprachen)
                out[i] = (w, _resolve(h, dict(w, lang=lang)))
                continue
            any_print = bool(w.get("any_print")) and not w.get("scryfall_id") and not w.get("set")
            if lang and (raw.get("lang") or "en") != lang and hasattr(sf, "localize"):
                raw = sf.localize(raw, lang, keep_print=not any_print)
            raw = sf.with_prices(raw)
            out[i] = (w, (card_fields(raw), price_of(raw), None, any_print))
        except ScryfallError as e:
            out[i] = (w, e)
    return out


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------

def r_info(h, qs):
    h.send_json({"app": APP_NAME, "version": __version__, "kind": h.ctx.kind, "revision": h.ctx.store.revision(),
                 "mtg_local": h.ctx.mtg is not None})


def r_projects(h, qs):
    h.send_json({"projects": h.ctx.store.projects()})


def r_project_create(h, qs):
    data = h.read_json()
    p = h.ctx.store.create_project(data.get("name"), data.get("notes") or "", data.get("kind") or "list")
    if data.get("mtg_deck_id"):
        _mtg_import(h, p["id"], {"source": "deck", "deck_id": data["mtg_deck_id"], "missing_only": False,
                                 "lang": data.get("lang")})
    errors = []
    if (data.get("list") or "").strip():
        errors = _import_list(h, p["id"], data["list"], data.get("lang"))
    h.send_json({"project": h.ctx.store.project(p["id"]), "errors": errors}, 201)


def r_project_get(h, qs, pid):
    h.send_json(_project_or_404(h.ctx.store.project(_id(pid))))


def r_project_patch(h, qs, pid):
    h.send_json(_project_or_404(h.ctx.store.update_project(_id(pid), h.read_json())))


def r_project_delete(h, qs, pid):
    if not h.ctx.store.delete_project(_id(pid)):
        raise ApiError(404, "Druckliste nicht gefunden")
    h.send_json({"deleted": True})


def r_project_duplicate(h, qs, pid):
    data = h.read_json()
    h.send_json(_project_or_404(h.ctx.store.duplicate_project(_id(pid), data.get("name"))), 201)


def r_item_add(h, qs, pid):
    data = h.read_json()
    if not (data.get("name") or data.get("scryfall_id")):
        raise ApiError(400, "Name oder scryfall_id angeben")
    _project_or_404(h.ctx.store.project(_id(pid)))
    fields, price, pset, any_print = _resolve(h, data)
    item = h.ctx.store.add_item(_id(pid), fields, _qty(data.get("quantity")), any_print, price, pset,
                                _price_in(data.get("max_price_eur")), notes=data.get("notes") or "",
                                board=data.get("board") or "main")
    h.send_json(item, 201)


def r_custom_add(h, qs, pid):
    data = h.read_json()
    _project_or_404(h.ctx.store.project(_id(pid)))
    img = decode_jpeg(data.get("image"))
    name = (data.get("name") or "").strip() or "Eigene Karte"
    item = h.ctx.store.add_item(_id(pid), {"name": name}, _qty(data.get("quantity")), kind="custom",
                                custom_image=img, notes=data.get("notes") or "", merge=False)
    h.send_json(item, 201)


def _import_list(h, pid, text, lang=None):
    entries = parse_decklist(text or "")
    if not entries:
        raise ApiError(400, "Keine Karten in der Liste erkannt")
    is_deck = (h.ctx.store.project(pid) or {}).get("kind") == "deck"
    errors = []
    wanted = [{"name": e["name"], "set": e.get("set"), "cn": e.get("cn"), "any_print": not e.get("set")} for e in entries]
    for (w, res), e in zip(_resolve_many(h, wanted, lang), entries):
        if isinstance(res, ScryfallError):
            errors.append(f"{e['name']}: {res}")
            continue
        fields, price, pset, any_print = res
        h.ctx.store.add_item(pid, fields, e["quantity"], any_print, price, pset,
                             board=e.get("board", "main") if is_deck else "main")
    return errors


def r_import_list(h, qs, pid):
    data = h.read_json()
    _project_or_404(h.ctx.store.project(_id(pid)))
    errors = _import_list(h, _id(pid), data.get("list"), data.get("lang"))
    h.send_json({"project": h.ctx.store.project(_id(pid)), "errors": errors})


# -- Karten einer Druckliste ------------------------------------------------------

def r_item_patch(h, qs, iid):
    data = h.read_json()
    it = _item_or_404(h, iid)
    if "scryfall_id" in data or data.get("any_print"):
        sid = data.pop("scryfall_id", None)
        data.pop("any_print", None)
        if it["kind"] != "scryfall":
            raise ApiError(400, "Eigene Karten haben keinen Scryfall-Druck")
        if sid:
            raw = h.ctx.scryfall.with_prices(h.ctx.scryfall.lookup(scryfall_id=sid))
            if it.get("oracle_id") and raw.get("oracle_id") and raw["oracle_id"] != it["oracle_id"]:
                raise ApiError(400, "Dieser Druck gehört zu einer anderen Karte")
            h.ctx.store.set_print(it["id"], card_fields(raw), price_of(raw))
        else:
            best = None
            try:
                best = _cheapest(h, it["name"])
            except ScryfallError:
                pass
            h.ctx.store.set_print(it["id"], None, *(best or (None, None)))
    if "max_price_eur" in data:
        data["max_price_eur"] = _price_in(data["max_price_eur"])
    if "quantity" in data:
        try:
            data["quantity"] = int(data["quantity"])
        except (TypeError, ValueError):
            raise ApiError(400, "Ungültige Anzahl") from None
    res = h.ctx.store.update_item(it["id"], data) if data else h.ctx.store.item(it["id"])
    h.send_json(res)


def r_item_delete(h, qs, iid):
    if not h.ctx.store.delete_item(_id(iid)):
        raise ApiError(404, "Karte nicht gefunden")
    h.send_json({"deleted": True})


def r_item_base(h, qs, iid):
    """Ausgangsbild für den Editor (PNG in bester Qualität) – über den Server, damit der Canvas es lesen darf."""
    it = _item_or_404(h, iid)
    back = _first(qs, "side") == "back"
    if it["kind"] == "custom":
        img = h.ctx.store.blob(it["id"], "custom_image")
        return h.send_bytes(img, "image/jpeg", cache=True)
    for url in ((it["png_url_back"], it["image_url_back"]) if back else (it["png_url"], it["image_url"])):
        data = h.ctx.any_fetcher(url, h.ctx.cache_dir) if url else None
        if data:
            return h.send_bytes(data, "image/png" if data[:4] == b"\x89PNG" else "image/jpeg", cache=True)
    raise ApiError(404, "Kein Kartenbild verfügbar")


def r_item_blob_get(h, qs, iid, column):
    col = {"art": "art", "rendered": "rendered", "custom": "custom_image"}[column]
    if col == "rendered" and _first(qs, "side") == "back":
        col = "rendered_back"
    data = h.ctx.store.blob(_id(iid), col)
    if data is None:
        raise ApiError(404, "Kein Bild")
    h.send_bytes(data, "image/jpeg", cache=True)


def r_item_art_put(h, qs, iid):
    it = _item_or_404(h, iid)
    h.ctx.store.set_blob(it["id"], "art", decode_jpeg(h.read_json().get("image")))
    h.send_json(h.ctx.store.item(it["id"]))


def r_item_art_delete(h, qs, iid):
    it = _item_or_404(h, iid)
    h.ctx.store.set_blob(it["id"], "art", None)
    h.send_json(h.ctx.store.item(it["id"]))


def r_item_rendered_put(h, qs, iid):
    """Fertig bearbeitetes Bild aus dem Editor speichern (+ Einstellungen)."""
    it = _item_or_404(h, iid)
    data = h.read_json()
    if data.get("front"):
        h.ctx.store.set_blob(it["id"], "rendered", decode_jpeg(data["front"]))
    if data.get("back"):
        h.ctx.store.set_blob(it["id"], "rendered_back", decode_jpeg(data["back"]))
    if "settings" in data:
        h.ctx.store.update_item(it["id"], {"settings": data["settings"]})
    h.send_json(h.ctx.store.item(it["id"]))


def r_item_rendered_delete(h, qs, iid):
    """Bearbeitung zurücksetzen (Original von Scryfall drucken)."""
    it = _item_or_404(h, iid)
    h.ctx.store.set_blob(it["id"], "rendered", None)
    h.ctx.store.set_blob(it["id"], "rendered_back", None)
    if _first(qs, "settings") == "1":
        h.ctx.store.update_item(it["id"], {"settings": {}})
        h.ctx.store.set_blob(it["id"], "art", None)
    h.send_json(h.ctx.store.item(it["id"]))


# -- Preise ---------------------------------------------------------------------

def refresh_prices(ctx, pid=None):
    rows = ctx.store.print_rows(pid) if pid else [r for r in ctx.store.items_with_prices()]
    updated = 0
    for r in rows:
        if r.get("kind") != "scryfall":
            continue
        try:
            if r.get("scryfall_id"):
                raw = ctx.scryfall.with_prices(ctx.scryfall.lookup(scryfall_id=r["scryfall_id"]))
                price, pset = price_of(raw), None
            else:
                best = None
                for raw in ctx.scryfall.prints(r["name"]):
                    p = price_of(raw)
                    if p is not None and not raw.get("digital") and (best is None or p < best[0]):
                        best = (p, (raw.get("set") or "").upper())
                price, pset = best or (None, None)
        except ScryfallError:
            continue
        if price is not None:
            ctx.store.set_price(r["id"], price, pset)
            updated += 1
    return {"updated": updated}


def r_refresh_prices(h, qs, pid):
    _project_or_404(h.ctx.store.project(_id(pid)))
    h.send_json(refresh_prices(h.ctx, _id(pid)))


# -- Druck ----------------------------------------------------------------------

def _print_args(h, qs, pid):
    project = _project_or_404(h.ctx.store.project(_id(pid)))
    ids = {int(x) for x in _first(qs, "ids").split(",") if x.strip().isdigit()}
    rows = h.ctx.store.print_rows(project["id"], ids)
    # Decks: Bereiche (z.B. ohne Sideboard) und Standardländer weglassen
    boards = {b for b in _first(qs, "boards").split(",") if b}
    if boards:
        rows = [r for r in rows if (r.get("board") or "main") in boards]
    if _first(qs, "skip_basic") == "1":
        rows = [r for r in rows if "Basic Land" not in (r.get("type_line") or "")]
    if not rows:
        raise ApiError(400, "Keine Karten ausgewählt")
    back = h.ctx.store.back_image(project["back_id"]) if project.get("back_id") else None
    return project, rows, back


def r_print_pdf(h, qs, pid):
    project, rows, back = _print_args(h, qs, pid)
    try:
        gap = float(_first(qs, "gap", "0").replace(",", "."))
    except ValueError:
        gap = 0.0
    pdf = make_pdf(h.ctx.scryfall, project, rows, h.ctx.cache_dir, h.ctx.image_fetcher,
                   paper=_first(qs, "paper", "a4"), cut=_first(qs, "cut", "1") != "0", gap=gap,
                   sharpen=_first(qs, "hq", "1") != "0", duplex=_first(qs, "duplex") == "1", card_back=back,
                   one=_first(qs, "copies") == "one")
    if pdf is None:
        raise ApiError(400, "Keine Karten ausgewählt")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", project["name"]).strip("-") or "proxies"
    h.send_bytes(pdf, "application/pdf", filename=f"proxies-{safe}.pdf")


def r_print_zip(h, qs, pid):
    project, rows, back = _print_args(h, qs, pid)
    data = make_zip(h.ctx.scryfall, rows, h.ctx.cache_dir, h.ctx.image_fetcher,
                    sharpen=_first(qs, "hq", "1") != "0", card_back=back)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", project["name"]).strip("-") or "proxies"
    h.send_bytes(data, "application/zip", filename=f"proxies-{safe}.zip")


def r_decklist(h, qs, pid):
    """Deckliste als Text (Moxfield/Arena-Format) – zum Weitergeben oder Sichern."""
    p = _project_or_404(h.ctx.store.project(_id(pid)))
    lines = []
    for board, title in (("commander", "Commander"), ("companion", "Companion"), ("main", "Deck"),
                         ("side", "Sideboard"), ("maybe", "Maybeboard")):
        cards = [i for i in p["items"] if (i.get("board") or "main") == board]
        if not cards:
            continue
        lines.append(title)
        lines += [f"{i['quantity']} {i['name']}" + (f" ({i['set_code']}) {i['collector_number']}"
                                                    if i.get("scryfall_id") and i.get("set_code") else "") for i in cards]
        lines.append("")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", p["name"]).strip("-") or "deck"
    h.send_bytes(("\n".join(lines).strip() + "\n").encode("utf-8"), "text/plain; charset=utf-8",
                 filename=f"{safe}.txt")


# -- Scryfall -----------------------------------------------------------------------

def r_autocomplete(h, qs):
    q = _first(qs, "q").strip()
    h.send_json({"data": h.ctx.scryfall.autocomplete(q) if q else []})


def r_prints(h, qs):
    name = _first(qs, "name").strip()
    if not name:
        raise ApiError(400, "name angeben")
    lang = _first(qs, "lang").strip().lower()
    raws = h.ctx.scryfall.prints(name, lang or None)
    if not raws:
        try:
            found = h.ctx.scryfall.lookup_any(name=name, lang=lang or None)
            raws = h.ctx.scryfall.prints(found.get("name") or name, lang or found.get("lang"))
        except ScryfallError:
            raws = []
    out = []
    for raw in raws:
        f = card_fields(raw)
        out.append(dict(f, set_name=raw.get("set_name"), released_at=raw.get("released_at"),
                        artist=raw.get("artist"), price_eur=(raw.get("prices") or {}).get("eur"),
                        price_usd=(raw.get("prices") or {}).get("usd"), digital=raw.get("digital"),
                        illustration_id=raw.get("illustration_id")))
    h.send_json({"data": [o for o in out if not o.get("digital")]})


# -- Rückseiten & Vorlagen ---------------------------------------------------------------

def r_backs(h, qs):
    h.send_json({"backs": h.ctx.store.backs()})


def r_back_add(h, qs):
    data = h.read_json()
    h.send_json(h.ctx.store.add_back(data.get("name"), data.get("image")), 201)


def r_back_image(h, qs, bid):
    data = h.ctx.store.back_image(_id(bid))
    if data is None:
        raise ApiError(404, "Rückseite nicht gefunden")
    h.send_bytes(data, "image/jpeg", cache=True)


def r_back_delete(h, qs, bid):
    if not h.ctx.store.delete_back(_id(bid)):
        raise ApiError(404, "Rückseite nicht gefunden")
    h.send_json({"deleted": True})


def r_presets(h, qs):
    h.send_json({"presets": h.ctx.store.presets()})


def r_preset_save(h, qs):
    data = h.read_json()
    h.send_json({"presets": h.ctx.store.save_preset(data.get("name"), data.get("settings"))})


def r_preset_delete(h, qs, prid):
    h.ctx.store.delete_preset(_id(prid))
    h.send_json({"presets": h.ctx.store.presets()})


# -- Import aus MTG Cards ------------------------------------------------------------------

def _mtg_cfg(h):
    return {"url": h.ctx.store.get_meta("mtg_url", ""), "token": h.ctx.store.get_meta("mtg_token", ""),
            "fingerprint": h.ctx.store.get_meta("mtg_fingerprint", "")}


def _mtg_local(h, path):
    """Wunschliste/Decks direkt aus MTG Cards (gleicher Server)."""
    m = h.ctx.mtg
    if path == "/api/info":
        return {"version": __version__}
    if path == "/api/wishlist":
        return m.wishlist.list()
    if path == "/api/decks":
        return {"decks": m.decks.list()}
    mt = re.fullmatch(r"/api/decks/(\d+)", path)
    if mt:
        deck = m.decks.get(int(mt.group(1)))
        if deck is None:
            raise ApiError(404, "Deck nicht gefunden")
        return deck
    raise ApiError(404, "Unbekannt")


def _mtg_get(h, path):
    if h.ctx.mtg is not None:
        return _mtg_local(h, path)
    cfg = _mtg_cfg(h)
    if not cfg["url"]:
        raise ApiError(400, "MTG-Cards-Server ist nicht eingerichtet (Einstellungen)")
    base = cfg["url"].rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    req = Request(base + path, headers={"Authorization": f"Bearer {cfg['token']}", "Accept": "application/json"})
    try:
        with tls.urlopen(req, timeout=30, fingerprint=cfg["fingerprint"] or None) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        raise ApiError(502, "MTG Cards: Token abgelehnt" if e.code == 401 else f"MTG Cards: Fehler {e.code}") from None
    except (URLError, OSError, ValueError) as e:
        raise ApiError(502, f"MTG Cards nicht erreichbar: {e}") from None


def r_mtg_settings_get(h, qs):
    cfg = _mtg_cfg(h)
    h.send_json({"url": cfg["url"] or ("local" if h.ctx.mtg is not None else ""), "local": h.ctx.mtg is not None,
                 "token_set": bool(cfg["token"]), "fingerprint": cfg["fingerprint"]})


def r_mtg_settings_set(h, qs):
    data = h.read_json()
    for k in ("url", "token", "fingerprint"):
        if k in data and (k != "token" or data[k]):
            h.ctx.store.set_meta(f"mtg_{k}", (data[k] or "").strip())
    info = _mtg_get(h, "/api/info")
    h.send_json({"ok": True, "version": info.get("version"), **{k: v for k, v in _mtg_cfg(h).items() if k != "token"}})


def r_mtg_decks(h, qs):
    decks = _mtg_get(h, "/api/decks").get("decks", [])
    h.send_json({"decks": [{"id": d["id"], "name": d["name"], "status": d.get("status"),
                            "missing": (d.get("stats") or {}).get("missing", 0),
                            "cards": (d.get("stats") or {}).get("cards", 0)} for d in decks]})


def r_mtg_import(h, qs, pid):
    """Karten aus MTG Cards übernehmen: Wunschliste (mit gewähltem Druck) oder Deck (fehlende/alle Karten)."""
    res = _mtg_import(h, _id(pid), h.read_json())
    h.send_json(dict(res, project=h.ctx.store.project(_id(pid))))


def _mtg_import(h, pid, data):
    project = _project_or_404(h.ctx.store.project(pid))
    is_deck = project.get("kind") == "deck"
    wanted = []
    if data.get("source") == "wishlist":
        only = {int(x) for x in data.get("ids") or [] if str(x).isdigit()}   # leer = ganze Wunschliste
        for w in _mtg_get(h, "/api/wishlist").get("items", []):
            if only and w.get("id") not in only:
                continue
            wanted.append({"name": w["name"], "scryfall_id": w.get("scryfall_id"), "quantity": w.get("quantity") or 1,
                           "max_price_eur": w.get("max_price_eur"), "any_print": not w.get("scryfall_id")})
    elif data.get("source") == "deck":
        deck = _mtg_get(h, f"/api/decks/{_id(data.get('deck_id'))}")
        only_missing = data.get("missing_only", True)
        boards = ("commander", "companion", "main", "side") if is_deck and not only_missing else \
            ("commander", "companion", "main")
        for c in deck.get("cards", []):
            if c.get("board") not in boards:
                continue
            n = c.get("missing", 0) if only_missing else c.get("quantity", 1)
            if c.get("basic") and only_missing:
                continue
            if n > 0:
                wanted.append({"name": c["name"], "quantity": n, "any_print": True,
                               "board": c.get("board") if is_deck else "main"})
    else:
        raise ApiError(400, "source muss 'wishlist' oder 'deck' sein")
    errors, added = [], 0
    for w, res in _resolve_many(h, wanted, data.get("lang")):
        try:
            if isinstance(res, ScryfallError):
                raise res
            fields, price, pset, any_print = res
            h.ctx.store.add_item(pid, fields, _qty(w["quantity"]), any_print, price, pset,
                                 _price_in(w.get("max_price_eur")), board=w.get("board") or "main")
            added += w["quantity"]
        except (ScryfallError, ApiError) as e:
            errors.append(f"{w['name']}: {e}")
    return {"added": added, "errors": errors}


# -- Sicherung -------------------------------------------------------------------------------

def r_export(h, qs):
    body = json.dumps(h.ctx.store.export_all(), ensure_ascii=False).encode("utf-8")
    h.send_bytes(body, "application/json; charset=utf-8", filename="proxie-maker-sicherung.json")


def r_import(h, qs):
    data = h.read_json()
    h.send_json(h.ctx.store.import_all(data, replace=_first(qs, "mode") == "replace"))


ROUTES = [
    ("GET", r"/api/info", r_info),
    ("GET", r"/api/projects", r_projects),
    ("POST", r"/api/projects", r_project_create),
    ("GET", r"/api/projects/(\d+)", r_project_get),
    ("PATCH", r"/api/projects/(\d+)", r_project_patch),
    ("DELETE", r"/api/projects/(\d+)", r_project_delete),
    ("POST", r"/api/projects/(\d+)/duplicate", r_project_duplicate),
    ("POST", r"/api/projects/(\d+)/items", r_item_add),
    ("POST", r"/api/projects/(\d+)/custom", r_custom_add),
    ("POST", r"/api/projects/(\d+)/import", r_import_list),
    ("POST", r"/api/projects/(\d+)/import-mtg", r_mtg_import),
    ("POST", r"/api/projects/(\d+)/refresh-prices", r_refresh_prices),
    ("GET", r"/api/projects/(\d+)/print\.pdf", r_print_pdf),
    ("GET", r"/api/projects/(\d+)/images\.zip", r_print_zip),
    ("GET", r"/api/projects/(\d+)/decklist\.txt", r_decklist),
    ("PATCH", r"/api/items/(\d+)", r_item_patch),
    ("DELETE", r"/api/items/(\d+)", r_item_delete),
    ("GET", r"/api/items/(\d+)/base", r_item_base),
    ("GET", r"/api/items/(\d+)/(art|rendered|custom)", r_item_blob_get),
    ("PATCH", r"/api/items/(\d+)/art", r_item_art_put),
    ("DELETE", r"/api/items/(\d+)/art", r_item_art_delete),
    ("PATCH", r"/api/items/(\d+)/rendered", r_item_rendered_put),
    ("DELETE", r"/api/items/(\d+)/rendered", r_item_rendered_delete),
    ("GET", r"/api/autocomplete", r_autocomplete),
    ("GET", r"/api/prints", r_prints),
    ("GET", r"/api/backs", r_backs),
    ("POST", r"/api/backs", r_back_add),
    ("GET", r"/api/backs/(\d+)/image", r_back_image),
    ("DELETE", r"/api/backs/(\d+)", r_back_delete),
    ("GET", r"/api/presets", r_presets),
    ("POST", r"/api/presets", r_preset_save),
    ("DELETE", r"/api/presets/(\d+)", r_preset_delete),
    ("GET", r"/api/mtg/settings", r_mtg_settings_get),
    ("POST", r"/api/mtg/settings", r_mtg_settings_set),
    ("GET", r"/api/mtg/decks", r_mtg_decks),
    ("GET", r"/api/export", r_export),
    ("POST", r"/api/import", r_import),
]


