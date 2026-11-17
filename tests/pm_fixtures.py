"""Testdaten: nachgebautes Scryfall ohne Netzwerk und kleine Testbilder."""

import base64

from mtgcards.scryfall import ScryfallError, name_matches

# Kleinstes gültiges JPEG (1×1 Pixel)
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////"
    "////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def card(cid, name, set_code, cn, lang="en", eur="1.00", faces=None, status="highres_scan", oracle=None):
    c = {"id": cid, "oracle_id": oracle or name.lower(), "name": name, "lang": lang, "set": set_code,
         "set_name": set_code.upper(), "collector_number": cn, "type_line": "Instant", "mana_cost": "{R}",
         "image_status": status, "released_at": "2020-01-01", "artist": "Künstler",
         "prices": {"eur": eur, "usd": None}}
    if faces:
        c["card_faces"] = faces
    else:
        c["image_uris"] = {"large": f"https://cards.scryfall.io/large/{cid}.jpg",
                           "png": f"https://cards.scryfall.io/png/{cid}.png"}
    return c


BOLT_M11 = card("bolt-m11", "Lightning Bolt", "m11", "149", eur="2.00")
BOLT_FDN = card("bolt-fdn", "Lightning Bolt", "fdn", "77", eur="0.30")
BOLT_DE = card("bolt-de", "Lightning Bolt", "fdn", "77", lang="de", eur=None, status="lowres")
SOL = card("sol", "Sol Ring", "c21", "263", eur="1.50")
DFC = card("dfc", "Delver of Secrets // Insectile Aberration", "isd", "51", eur="0.50", faces=[
    {"name": "Delver of Secrets", "image_uris": {"large": "https://cards.scryfall.io/large/dfc-a.jpg",
                                                  "png": "https://cards.scryfall.io/png/dfc-a.png"}},
    {"name": "Insectile Aberration", "image_uris": {"large": "https://cards.scryfall.io/large/dfc-b.jpg",
                                                     "png": "https://cards.scryfall.io/png/dfc-b.png"}}])
ALL = [BOLT_FDN, BOLT_M11, BOLT_DE, SOL, DFC]


class FakeScryfall:
    def lookup(self, name=None, scryfall_id=None, set_code=None, collector_number=None, lang=None, **_):
        if scryfall_id:
            for c in ALL:
                if c["id"] == scryfall_id:
                    return c
            raise ScryfallError("nicht gefunden", 404)
        cands = [c for c in ALL if name and name_matches(name, c, 0.8)]
        if set_code:
            cands = [c for c in cands if c["set"] == set_code.lower()] or cands
        if lang:
            cands = [c for c in cands if c["lang"] == lang] or cands
        else:
            cands = [c for c in cands if c["lang"] == "en"] or cands
        if not cands:
            raise ScryfallError(f'Keine Karte gefunden für "{name}"', 404)
        return cands[0]

    def lookup_any(self, name=None, alternatives=(), **kw):
        return self.lookup(name=name, **kw)

    def with_prices(self, raw):
        return raw

    def prints(self, name, lang=None, **_):
        return [c for c in ALL if c["name"] == name and (c["lang"] == (lang or "en"))]

    def autocomplete(self, q):
        return sorted({c["name"] for c in ALL if q.lower() in c["name"].lower()})

    def by_set_number(self, set_code, cn, lang=None):
        for c in ALL:
            if c["set"] == set_code and c["collector_number"] == cn and c["lang"] == (lang or "en"):
                return c
        raise ScryfallError("nicht gefunden", 404)


def fake_fetch(url, cache_dir=None):
    if not url:
        return None
    return JPEG if url.endswith(".jpg") else (PNG if url.endswith(".png") else None)


def fake_fetch_any(url, cache_dir=None):
    if not url:
        return None
    return PNG if url.endswith(".png") else JPEG
