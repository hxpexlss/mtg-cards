"""Minimaler Scryfall-API-Client (https://scryfall.com/docs/api).

- respektiert das Rate-Limit (mind. 100 ms zwischen Anfragen)
- cached Antworten im Speicher
- normalisiert Kartenobjekte in das Format der Datenbank
"""

import difflib
import json
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .tags import auto_tags

API_BASE = "https://api.scryfall.com"
COLOR_ORDER = "WUBRG"


class ScryfallError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def name_matches(query, card, threshold=0.75):
    """Prüft grob, ob ein (OCR-)Name zu einer Karte passt."""
    q = _norm(query)
    if not q:
        return True
    candidates = [card.get("name"), card.get("printed_name")]
    for face in card.get("card_faces") or []:
        candidates += [face.get("name"), face.get("printed_name")]
    for c in candidates:
        c = _norm(c)
        if not c:
            continue
        if q == c or q in c or c in q:
            return True
        if difflib.SequenceMatcher(None, q, c).ratio() >= threshold:
            return True
    return False


def sort_colors(colors):
    return "".join(c for c in COLOR_ORDER if c in (colors or []))


def normalize_card(raw):
    """Wandelt ein Scryfall-Kartenobjekt in ein flaches dict für die DB."""
    faces = raw.get("card_faces") or []

    def pick(key):
        if raw.get(key) not in (None, ""):
            return raw.get(key)
        vals = [f.get(key) for f in faces if f.get(key)]
        return vals

    oracle = raw.get("oracle_text")
    if oracle is None and faces:
        parts = []
        for f in faces:
            parts.append(f"{f.get('name', '')}\n{f.get('oracle_text', '')}".strip())
        oracle = "\n\n// \n\n".join(parts)

    mana_cost = raw.get("mana_cost")
    if not mana_cost and faces:
        mana_cost = " // ".join(f.get("mana_cost", "") for f in faces if f.get("mana_cost"))

    image = None
    if raw.get("image_uris"):
        image = raw["image_uris"].get("normal") or raw["image_uris"].get("large")
    elif faces and faces[0].get("image_uris"):
        image = faces[0]["image_uris"].get("normal")

    colors = raw.get("colors")
    if colors is None and faces:
        colors = sorted({c for f in faces for c in (f.get("colors") or [])})

    def first(val):
        if isinstance(val, list):
            return val[0] if val else None
        return val

    printed_name = raw.get("printed_name")
    if not printed_name and faces and faces[0].get("printed_name"):
        printed_name = " // ".join(f.get("printed_name", "") for f in faces)

    prices = raw.get("prices") or {}
    art = (raw.get("image_uris") or {}).get("art_crop") or (
        (faces[0].get("image_uris") or {}).get("art_crop") if faces else None)
    card = {
        "scryfall_id": raw.get("id"),
        "oracle_id": raw.get("oracle_id") or (faces[0].get("oracle_id") if faces else None),
        "name": raw.get("name"),
        "printed_name": printed_name,
        "lang": raw.get("lang") or "en",
        "set_code": (raw.get("set") or "").upper(),
        "set_name": raw.get("set_name"),
        "collector_number": raw.get("collector_number"),
        "rarity": raw.get("rarity"),
        "mana_cost": mana_cost or "",
        "cmc": raw.get("cmc"),
        "type_line": raw.get("type_line") or " // ".join(f.get("type_line", "") for f in faces),
        "layout": raw.get("layout"),
        "oracle_text": oracle or "",
        "power": first(pick("power")),
        "toughness": first(pick("toughness")),
        "loyalty": first(pick("loyalty")),
        "colors": sort_colors(colors),
        "color_identity": sort_colors(raw.get("color_identity")),
        "keywords": list(raw.get("keywords") or []),
        "image_url": image,
        "scryfall_uri": raw.get("scryfall_uri"),
        "price_eur": prices.get("eur"),
        "price_eur_foil": prices.get("eur_foil"),
        "price_usd": prices.get("usd"),
        "price_usd_foil": prices.get("usd_foil"),
    }
    # nur für Anzeige / Druck-Erkennung (nicht in der DB gespeichert)
    card["artist"] = raw.get("artist") or (faces[0].get("artist") if faces else None)
    card["released_at"] = raw.get("released_at")
    card["illustration_id"] = raw.get("illustration_id") or (faces[0].get("illustration_id") if faces else None)
    card["art_url"] = art
    card["auto_tags"] = auto_tags(card)
    card["match"] = raw.get("_match")      # wie sicher der Druck ist (nur für die Anzeige, nicht gespeichert)
    return card


_OCR_CONFUSIONS = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8",
                   "2": "Z", "Z": "2", "6": "G", "G": "6"}


def set_code_variants(code, limit=6):
    """Set-Code wie gelesen, danach Varianten mit je einem typischen OCR-Lesefehler
    (0/O, 1/I, 5/S, 8/B, 2/Z, 6/G), z.B. "M1C" -> "MIC"."""
    code = (code or "").upper()
    out = [code] if code else []
    for i, ch in enumerate(code):
        alt = _OCR_CONFUSIONS.get(ch)
        if alt:
            v = code[:i] + alt + code[i + 1:]
            if v not in out:
                out.append(v)
        if len(out) >= limit:
            break
    return out


def _tag(card, how):
    """Kopie der Karte mit Info, wie der Druck gefunden wurde (Cache-Objekte nicht verändern)."""
    return dict(card, _match=how)


class DiskCache:
    """Persistenter Cache für Scryfall-Antworten (SQLite).

    Beschleunigt wiederholte Abfragen und erlaubt Nachschlagen ohne Internet
    (veraltete Einträge werden genutzt, wenn Scryfall nicht erreichbar ist).
    """

    def __init__(self, path, max_entries=50000):
        import sqlite3
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.max_entries = max_entries
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("CREATE TABLE IF NOT EXISTS http_cache (url TEXT PRIMARY KEY, data TEXT, ts REAL)")
            self.conn.commit()

    def get(self, url):
        with self.lock:
            row = self.conn.execute("SELECT data, ts FROM http_cache WHERE url=?", (url,)).fetchone()
        if not row:
            return None, None
        return json.loads(row[0]), row[1]

    def put(self, url, data):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO http_cache(url, data, ts) VALUES(?,?,?)",
                              (url, json.dumps(data), time.time()))
            if self.conn.total_changes % 500 == 0:
                self.conn.execute(
                    "DELETE FROM http_cache WHERE url IN (SELECT url FROM http_cache ORDER BY ts DESC LIMIT -1 OFFSET ?)",
                    (self.max_entries,))
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()


class Scryfall:
    def __init__(self, base=API_BASE, timeout=15, min_interval=0.1, cache_size=2000,
                 cache_path=None, cache_ttl=3 * 86400):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0
        self._cache = OrderedDict()
        self._cache_size = cache_size
        self._cache_lock = threading.Lock()
        self.cache_ttl = cache_ttl
        self.disk = DiskCache(cache_path) if cache_path else None

    # -- HTTP -------------------------------------------------------------
    def _remember(self, url, data, disk=True):
        with self._cache_lock:
            self._cache[url] = (data, time.time())
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        if disk and self.disk:
            try:
                self.disk.put(url, data)
            except Exception:  # noqa: BLE001 – Cache-Fehler nie nach außen geben
                pass

    def _request(self, url, body=None):
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        headers = {"User-Agent": f"MTGCardsCollection/{__version__}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            try:
                details = json.loads(e.read().decode("utf-8")).get("details")
            except Exception:  # noqa: BLE001
                details = None
            raise ScryfallError(details or f"Scryfall-Fehler {e.code}", e.code) from None
        except (URLError, TimeoutError, OSError) as e:
            raise ScryfallError(f"Scryfall nicht erreichbar: {e}", 503) from None

    def _get(self, path, params=None, cache=True):
        url = path if path.startswith("http") else self.base + path
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})
        now = time.time()
        stale = None
        if cache:
            with self._cache_lock:
                hit = self._cache.get(url)
                if hit and now - hit[1] < self.cache_ttl:
                    self._cache.move_to_end(url)
                    return hit[0]
            if self.disk:
                try:
                    data, ts = self.disk.get(url)
                except Exception:  # noqa: BLE001
                    data, ts = None, None
                if data is not None:
                    if now - ts < self.cache_ttl:
                        with self._cache_lock:
                            self._cache[url] = (data, ts)
                        return data
                    stale = data
        try:
            data = self._request(url)
        except ScryfallError as e:
            if e.status == 503 and stale is not None:
                return stale  # offline: veraltete Daten sind besser als keine
            raise
        if cache:
            self._remember(url, data)
        return data

    def collection(self, scryfall_ids):
        """Viele Karten auf einmal laden (max. 75 pro Anfrage). Gibt {id: karte} zurück."""
        out = {}
        ids = [i for i in scryfall_ids if i]
        for i in range(0, len(ids), 75):
            chunk = ids[i:i + 75]
            data = self._request(self.base + "/cards/collection",
                                 body={"identifiers": [{"id": x} for x in chunk]})
            for card in data.get("data", []):
                out[card["id"]] = card
                self._remember(self.base + f"/cards/{quote(card['id'])}", card)
        return out

    # -- Endpunkte --------------------------------------------------------
    def by_id(self, scryfall_id):
        return self._get(f"/cards/{quote(scryfall_id)}")

    def named(self, name, set_code=None):
        return self._get("/cards/named", {"fuzzy": name, "set": (set_code or "").lower() or None})

    def by_set_number(self, set_code, number, lang=None):
        path = f"/cards/{quote(set_code.lower())}/{quote(str(number))}"
        if lang and lang.lower() != "en":
            path += f"/{quote(lang.lower())}"
        return self._get(path)

    def search(self, q, unique="cards", order="name", page=1):
        return self._get("/cards/search", {"q": q, "unique": unique, "order": order, "page": page})

    # -- Editionen ----------------------------------------------------------
    def sets(self):
        """Alle Editionen (Code, Name, Kartenanzahl, Symbol, Erscheinungsdatum)."""
        return self._get("/sets").get("data", [])

    def set_info(self, code):
        return self._get(f"/sets/{quote(code.lower())}")

    def set_cards(self, code):
        """Alle Karten einer Edition inkl. Varianten (Showcase, randlos …), seitenweise geladen."""
        params = {"q": f"e:{code.lower()}", "unique": "prints", "order": "set",
                  "include_extras": "true", "include_variations": "true"}
        try:
            page = self._get("/cards/search", params)
        except ScryfallError as e:
            if e.status == 404:
                return []
            raise
        cards = list(page.get("data", []))
        while page.get("has_more") and page.get("next_page"):
            page = self._get(page["next_page"])
            cards += page.get("data", [])
        return cards

    # -- Sprache -------------------------------------------------------------
    def localize(self, raw, lang, keep_print=False):
        """Gleiche Karte in einer anderen Sprache (z.B. "de"). Fällt auf das Original zurück.

        keep_print=True: Gibt es den Druck (Set + Nummer) nicht in der Sprache, bleibt der Druck erhalten
        (richtige Edition ist wichtiger als die Sprache). Sonst der neueste Druck in dieser Sprache.
        """
        lang = (lang or "").lower()
        if not lang or lang in ("auto", "any") or (raw.get("lang") or "en") == lang:
            return raw
        try:
            return self.by_set_number(raw["set"], raw["collector_number"], lang)
        except (ScryfallError, KeyError):
            pass
        if keep_print:
            return raw
        safe = (raw.get("name") or "").split(" // ")[0].replace('"', "")
        try:
            data = self._get("/cards/search", {"q": f'!"{safe}" lang:{lang}', "unique": "prints",
                                               "order": "released", "dir": "desc"})
            if data.get("data"):
                return data["data"][0]
        except ScryfallError:
            pass
        return raw

    # -- Preise --------------------------------------------------------------
    @staticmethod
    def _has_price(raw):
        prices = raw.get("prices") or {}
        return any(prices.get(k) for k in ("eur", "eur_foil", "usd", "usd_foil"))

    def with_prices(self, raw):
        """Scryfall führt Preise nur beim englischen Druck. Fremdsprachige Karten bekommen die Preise
        des englischen Drucks mit gleichem Set + Sammlernummer."""
        if self._has_price(raw) or (raw.get("lang") or "en") == "en" or not raw.get("set"):
            return raw
        try:
            en = self.by_set_number(raw["set"], raw["collector_number"])
        except (ScryfallError, KeyError):
            return raw
        return dict(raw, prices=en.get("prices") or {})

    def fill_prices(self, raws):
        """Wie with_prices für viele Karten auf einmal (Sammelabfrage). raws: {schlüssel: karte} – wird ergänzt."""
        need = {k: r for k, r in raws.items()
                if not self._has_price(r) and (r.get("lang") or "en") != "en" and r.get("set")}
        if not need:
            return raws
        idents = list({(r["set"], r["collector_number"]) for r in need.values()})
        try:
            found, _ = self.collection_identifiers([{"set": s, "collector_number": n} for s, n in idents])
        except ScryfallError:
            return raws
        prices = {(c.get("set"), c.get("collector_number")): c.get("prices") or {} for c in found}
        for k, r in need.items():
            p = prices.get((r["set"], r["collector_number"]))
            if p:
                raws[k] = dict(r, prices=p)
        return raws

    def autocomplete(self, q):
        if len(q.strip()) < 2:
            return []
        return self._get("/cards/autocomplete", {"q": q}).get("data", [])

    def prints(self, name, lang=None):
        """Alle Drucke einer Karte (exakter Name), optional in einer Sprache (z.B. "de")."""
        safe = name.replace('"', "")
        q = f'!"{safe}"'
        lang = (lang or "").lower()
        if lang and lang not in ("en", "auto"):
            q += " lang:any" if lang == "any" else f" lang:{lang}"
        try:
            data = self.search(q, unique="prints", order="released")
        except ScryfallError as e:
            if e.status == 404:
                return []
            raise
        return data.get("data", [])

    def collection_identifiers(self, identifiers):
        """Sammelabfrage mit beliebigen Identifiern (z.B. {"name": ...}).

        Gibt (gefundene_karten, nicht_gefundene_identifier) zurück.
        """
        found, missing = [], []
        for i in range(0, len(identifiers), 75):
            data = self._request(self.base + "/cards/collection", body={"identifiers": identifiers[i:i + 75]})
            for card in data.get("data", []):
                found.append(card)
                self._remember(self.base + f"/cards/{quote(card['id'])}", card)
            missing += data.get("not_found", [])
        return found, missing

    # -- High-Level-Lookup -----------------------------------------------
    def lookup_any(self, name=None, alternatives=(), **kw):
        """Wie lookup(), probiert bei "nicht gefunden" aber weitere Namenskandidaten (vom Scanner).

        Sprache des Ergebnisses (nie ein zufälliger Treffer):
        1. lang (Scan-Sprache), falls angegeben
        2. die Sprache, in der der gelesene Name wirklich gedruckt ist (deutscher Name -> deutscher Druck)
        3. Englisch
        Fremdsprachige Drucke bekommen die Preise des englischen Drucks.
        """
        found = self._lookup_any(name, alternatives, **kw)
        target = target_lang(found, kw.get("lang"))
        out = found
        if (found.get("lang") or "en") != target:
            out = self.localize(found, target, keep_print=found.get("_match") in ("exact", "set", "id", "likely", "preferred"))
        out = self.with_prices(out)
        return dict(out, _match=found.get("_match"))

    def _lookup_any(self, name=None, alternatives=(), **kw):
        try:
            return self.lookup(name=name, **kw)
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
            first = e
        for alt in alternatives or ():
            alt = (alt or "").strip()
            if len(alt) < 3 or alt == name:
                continue
            try:
                return self.lookup(name=alt, prefer_set=kw.get("prefer_set"))
            except ScryfallError as e:
                if e.status not in (400, 404):
                    raise
        raise first

    def lookup(self, name=None, set_code=None, collector_number=None, lang=None, scryfall_id=None,
               prefer_set=None, total=None, artist=None, year=None):
        """Findet eine Karte und merkt sich, wie sicher der Druck ist (Feld "_match"):

        "exact"     – Set-Code + Sammlernummer vom Kartenrand passen (bei alten Karten: Nummer + Set-Größe)
        "set"       – Name + gelesener Set-Code
        "likely"    – alte Karte: Künstler / Jahr / Nummer passen zu genau einem Druck
        "preferred" – Name + bevorzugte Edition (zuletzt gescannt / im Scanner festgelegt)
        "name"      – nur der Name: Scryfalls Standard-Druck (meist der neueste)

        Wurde der Name in einer anderen Sprache gelesen, steht diese in "_name_lang".
        """
        if scryfall_id:
            return _tag(self.by_id(scryfall_id), "id")

        set_code = (set_code or "").strip().upper() or None
        prefer_set = (prefer_set or "").strip().upper() or None
        collector_number = (str(collector_number).strip().lstrip("0") or "0") if collector_number else None

        # 1) Set-Code + Sammlernummer (mit typischen OCR-Verwechslungen im Set-Code: 0/O, 1/I, 5/S …)
        if set_code and collector_number:
            for code in set_code_variants(set_code):
                for lg in ([lang, None] if lang and lang.lower() not in ("en", "auto") else [None]):
                    try:
                        card = self.by_set_number(code, collector_number, lg)
                    except ScryfallError as e:
                        if e.status not in (400, 404):
                            raise
                        continue
                    if not name or name_matches(name, card):
                        return _tag(card, "exact")
                    # Name in anderer Sprache gelesen? -> gleicher Druck, Name passt zum gedruckten Namen
                    local = self._named_in_set(name, code, collector_number)
                    if local and local.get("collector_number", "").lstrip("0") == collector_number:
                        return dict(_tag(local, "exact"), _name_lang=_printed_lang(name, local))

        if not name:
            raise ScryfallError("Kein Kartenname angegeben", 400)

        # 2) Name + gelesener Set-Code
        for code in set_code_variants(set_code) if set_code else []:
            card = self._named_in_set(name, code, collector_number)
            if card:
                return dict(_tag(card, "set"), _name_lang=_printed_lang(name, card))

        # 3) Karte über den Namen finden (Standard-Druck)
        base = self._by_name(name)
        name_lang = _printed_lang(name, base)

        # 4) Alte Karten: Nummer "123/249", Künstler, Jahr
        if collector_number or total or artist or year:
            old = self._old_print(base, collector_number, total, artist, year, prefer_set)
            if old:
                return dict(old, _name_lang=name_lang)

        # 5) Bevorzugte Edition
        if prefer_set and prefer_set != set_code:
            card = self._named_in_set(base.get("name") or name, prefer_set)
            if card:
                return dict(_tag(card, "preferred"), _name_lang=name_lang)

        return dict(_tag(base, "name"), _name_lang=name_lang)

    def _by_name(self, name):
        """Standard-Druck zu einem (OCR-)Namen – englisch oder fremdsprachig."""
        try:
            return self.named(name)
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
            last = e
        # Fremdsprachige Namen (z.B. deutsche Karten) über die Volltextsuche
        safe = name.replace('"', "")
        try:
            data = self.search(f'"{safe}" lang:any', unique="prints", order="released")
            results = data.get("data") or []
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
            results = []
        matches = [c for c in results if name_matches(name, c, threshold=0.7)]
        if matches:
            # Bester Treffer: gedruckter Name am ähnlichsten, bei Gleichstand lateinische Sprachen zuerst
            return max(matches, key=lambda c: (_similarity(name, c), (c.get("lang") or "en") not in NON_LATIN_LANGS))
        raise ScryfallError(f'Keine Karte gefunden für "{name}"', 404) from last

    def _named_in_set(self, name, code, collector_number=None):
        """Karte per Name in einer bestimmten Edition – englischer oder fremdsprachiger Name.
        Mit collector_number wird bei mehreren Drucken im Set (Showcase …) dieser bevorzugt."""
        card = None
        try:
            card = self.named(name, code)
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
        if card and (not collector_number or card.get("collector_number", "").lstrip("0") == collector_number):
            return card
        safe = name.replace('"', "")
        try:
            data = self.search(f'"{safe}" lang:any e:{code.lower()}', unique="prints", order="released")
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
            return card
        hits = [c for c in data.get("data") or [] if name_matches(name, c, threshold=0.7)]
        if collector_number:
            same = [c for c in hits if c.get("collector_number", "").lstrip("0") == collector_number]
            if same:
                hits = same
        if hits:
            return max(hits, key=lambda c: (_similarity(name, c), (c.get("lang") or "en") not in NON_LATIN_LANGS))
        return card

    def _set_sizes(self):
        try:
            return {s["code"]: {s.get("printed_size"), s.get("card_count")} for s in self.sets()}
        except ScryfallError:
            return {}

    def _old_print(self, base, collector_number=None, total=None, artist=None, year=None, prefer_set=None):
        """Druck alter Karten ohne Set-Code anhand der Hinweise am Kartenrand bestimmen.

        - "123/249": Nummer + Kartenanzahl der Edition (2003–2014)
        - "Illus. Name": Künstler (Neudrucke haben oft ein anderes Artwork)
        - "© 1995": Erscheinungsjahr
        """
        prints = [p for p in self.prints(base.get("name") or "") if not p.get("digital")]
        if not prints:
            return None
        sizes = self._set_sizes() if total else {}
        try:
            total = int(total) if total else None
            year = int(year) if year else None
        except (TypeError, ValueError):
            total = year = None
        scored = []
        for i, p in enumerate(prints):
            score, strong = 0, False
            cn_ok = bool(collector_number) and (p.get("collector_number") or "").lstrip("0") == collector_number
            size_ok = bool(total) and total in sizes.get(p.get("set"), ())
            if cn_ok:
                score += 3
            if size_ok:
                score += 3
            strong = cn_ok and size_ok
            if artist and _artist_matches(artist, p.get("artist")):
                score += 2
            released = (p.get("released_at") or "")[:4]
            if year and released.isdigit() and 0 <= int(released) - year <= 1:
                score += 1
            if prefer_set and (p.get("set") or "").upper() == prefer_set:
                score += 1
            scored.append((score, strong, -i, p))
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        best = scored[0]
        if best[0] < 2:
            return None
        if len(scored) > 1 and scored[1][0] == best[0] and not best[1]:
            # Gleichstand: nur übernehmen, wenn es dasselbe Artwork ist (Bild ist dann ohnehin gleich)
            if scored[1][3].get("illustration_id") != best[3].get("illustration_id"):
                return None
        return _tag(best[3], "exact" if best[1] else "likely")


NON_LATIN_LANGS = {"ja", "zhs", "zht", "ko", "ru", "ph", "he", "ar", "sa", "grc"}


def _similarity(query, card):
    q = _norm(query)
    best = 0.0
    for c in [card.get("name"), card.get("printed_name")] + [
            f.get(k) for f in card.get("card_faces") or [] for k in ("name", "printed_name")]:
        c = _norm(c)
        if c:
            best = max(best, 1.0 if q == c else difflib.SequenceMatcher(None, q, c).ratio())
    return best


def _printed_lang(name, card):
    """Sprache, in der der gelesene Name gedruckt ist: die Kartensprache, wenn der Name zum gedruckten
    (übersetzten) Namen besser passt als zum englischen – sonst Englisch."""
    lang = (card.get("lang") or "en").lower()
    if not name or lang == "en" or lang in NON_LATIN_LANGS:
        return "en"
    q = _norm(name)

    def ratio(vals):
        return max([difflib.SequenceMatcher(None, q, _norm(v)).ratio() for v in vals if v] or [0.0])

    faces = card.get("card_faces") or []
    printed = ratio([card.get("printed_name")] + [f.get("printed_name") for f in faces])
    english = ratio([card.get("name")] + [f.get("name") for f in faces])
    return lang if printed >= 0.7 and printed > english else "en"


def target_lang(card, lang=None):
    """Sprache, in der eine gefundene Karte gespeichert wird (siehe Scryfall.lookup_any)."""
    lang = (lang or "").lower()
    if lang and lang not in ("auto", "any"):
        return lang
    return card.get("_name_lang") or "en"


def _artist_matches(read, artist):
    a, b = _norm(read), _norm(artist)
    if not a or not b:
        return False
    if len(a) >= 5 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75
