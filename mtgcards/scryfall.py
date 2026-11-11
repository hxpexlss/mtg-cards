"""Minimaler Scryfall-API-Client (https://scryfall.com/docs/api).

- respektiert das Rate-Limit (mind. 100 ms zwischen Anfragen)
- cached Antworten im Speicher
- normalisiert Kartenobjekte in das Format der Datenbank
"""

import difflib
import json
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
    card["auto_tags"] = auto_tags(card)
    return card


class Scryfall:
    def __init__(self, base=API_BASE, timeout=15, min_interval=0.1, cache_size=2000):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0
        self._cache = OrderedDict()
        self._cache_size = cache_size
        self._cache_lock = threading.Lock()

    # -- HTTP -------------------------------------------------------------
    def _get(self, path, params=None, cache=True):
        url = self.base + path
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})
        if cache:
            with self._cache_lock:
                if url in self._cache:
                    self._cache.move_to_end(url)
                    return self._cache[url]
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        req = Request(url, headers={
            "User-Agent": f"MTGCardsCollection/{__version__}",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            try:
                details = json.loads(e.read().decode("utf-8")).get("details")
            except Exception:  # noqa: BLE001
                details = None
            raise ScryfallError(details or f"Scryfall-Fehler {e.code}", e.code) from None
        except (URLError, TimeoutError, OSError) as e:
            raise ScryfallError(f"Scryfall nicht erreichbar: {e}", 503) from None
        if cache:
            with self._cache_lock:
                self._cache[url] = data
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return data

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

    def autocomplete(self, q):
        if len(q.strip()) < 2:
            return []
        return self._get("/cards/autocomplete", {"q": q}).get("data", [])

    def prints(self, name):
        """Alle Drucke einer Karte (exakter Name)."""
        safe = name.replace('"', "")
        try:
            data = self.search(f'!"{safe}"', unique="prints", order="released")
        except ScryfallError as e:
            if e.status == 404:
                return []
            raise
        return data.get("data", [])

    # -- High-Level-Lookup -----------------------------------------------
    def lookup(self, name=None, set_code=None, collector_number=None, lang=None, scryfall_id=None):
        """Findet eine Karte. Reihenfolge: ID -> Set+Nummer -> Name(+Set) -> fremdsprachiger Name."""
        if scryfall_id:
            return self.by_id(scryfall_id)

        set_code = (set_code or "").strip() or None
        collector_number = (str(collector_number).strip().lstrip("0") or "0") if collector_number else None

        if set_code and collector_number:
            for lg in ([lang, None] if lang and lang.lower() != "en" else [None]):
                try:
                    card = self.by_set_number(set_code, collector_number, lg)
                    if not name or name_matches(name, card):
                        return card
                except ScryfallError as e:
                    if e.status not in (400, 404):
                        raise

        if not name:
            raise ScryfallError("Kein Kartenname angegeben", 400)

        if set_code:
            try:
                return self.named(name, set_code)
            except ScryfallError as e:
                if e.status not in (400, 404):
                    raise
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
            for card in results:
                if name_matches(name, card, threshold=0.7):
                    return card
            if results:
                return results[0]
        except ScryfallError as e:
            if e.status not in (400, 404):
                raise
        raise ScryfallError(f'Keine Karte gefunden für "{name}"', 404) from last
