"""Scryfall-ähnliche Testdaten und ein Fake-Client ohne Netzwerk."""

from mtgcards.scryfall import ScryfallError, name_matches

ATRAXA = {
    "id": "d0d33d52-3d28-4635-b985-51e126289259", "oracle_id": "7d3a2c6b-0000-0000-0000-000000000001",
    "name": "Atraxa, Praetors' Voice", "lang": "en", "set": "c16", "set_name": "Commander 2016",
    "collector_number": "28", "rarity": "mythic", "mana_cost": "{G}{W}{U}{B}", "cmc": 4.0,
    "type_line": "Legendary Creature — Phyrexian Angel Horror",
    "oracle_text": "Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, proliferate.",
    "power": "4", "toughness": "4", "colors": ["B", "G", "U", "W"], "color_identity": ["B", "G", "U", "W"],
    "keywords": ["Flying", "Vigilance", "Deathtouch", "Lifelink", "Proliferate"],
    "image_uris": {"normal": "https://cards.scryfall.io/normal/front/atraxa.jpg"},
    "scryfall_uri": "https://scryfall.com/card/c16/28", "prices": {"eur": "12.50", "usd": "14.00"},
}

KRAUM = {
    "id": "kraum-id", "oracle_id": "kraum-oracle", "name": "Kraum, Ludevic's Opus", "lang": "en",
    "set": "c16", "set_name": "Commander 2016", "collector_number": "36", "rarity": "mythic",
    "mana_cost": "{3}{U}{R}", "cmc": 5.0, "type_line": "Legendary Creature — Zombie Horror",
    "oracle_text": "Flying, haste\nWhenever an opponent casts their second spell each turn, draw a card.\n"
                   "Partner (You can have two commanders if both have partner.)",
    "colors": ["U", "R"], "color_identity": ["U", "R"], "keywords": ["Flying", "Haste", "Partner"],
    "image_uris": {"normal": "https://cards.scryfall.io/normal/front/kraum.jpg"}, "prices": {},
}

LURRUS = {
    "id": "lurrus-id", "oracle_id": "lurrus-oracle", "name": "Lurrus of the Dream-Den", "lang": "en",
    "set": "iko", "set_name": "Ikoria", "collector_number": "226", "rarity": "rare",
    "mana_cost": "{1}{W/B}{W/B}", "cmc": 3.0, "type_line": "Legendary Creature — Cat Nightmare",
    "oracle_text": "Companion — Each permanent card in your starting deck has mana value 2 or less.\nLifelink",
    "colors": ["W", "B"], "color_identity": ["W", "B"], "keywords": ["Lifelink", "Companion"],
    "image_uris": {"normal": "x"}, "prices": {"eur": "3.00"},
}

SOL_RING = {
    "id": "solring-id", "oracle_id": "solring-oracle", "name": "Sol Ring", "lang": "en", "set": "c21",
    "set_name": "Commander 2021", "collector_number": "263", "rarity": "uncommon", "mana_cost": "{1}",
    "cmc": 1.0, "type_line": "Artifact", "oracle_text": "{T}: Add {C}{C}.", "colors": [],
    "color_identity": [], "keywords": [], "image_uris": {"normal": "y"}, "prices": {"eur": "1.50"},
}

# Doppelseitig, Vorderseite legendäre Kreatur
DFC = {
    "id": "dfc-id", "oracle_id": "dfc-oracle", "name": "Westvale Abbey // Ormendahl, Profane Prince",
    "lang": "en", "set": "soi", "set_name": "Shadows over Innistrad", "collector_number": "281",
    "rarity": "rare", "cmc": 0.0, "type_line": "Land // Legendary Creature — Demon",
    "color_identity": [], "keywords": [], "prices": {},
    "card_faces": [
        {"name": "Westvale Abbey", "type_line": "Land", "oracle_text": "{T}: Add {C}.", "mana_cost": "",
         "image_uris": {"normal": "front.jpg"}},
        {"name": "Ormendahl, Profane Prince", "type_line": "Legendary Creature — Demon",
         "oracle_text": "Flying, lifelink, indestructible, haste", "power": "9", "toughness": "7",
         "mana_cost": "", "colors": ["B"]},
    ],
}

# Deutsche Karte (printed_name)
ATRAXA_DE = dict(ATRAXA, id="atraxa-de-id", lang="de", printed_name="Atraxa, Stimme der Prätoren")

ALL = [ATRAXA, KRAUM, LURRUS, SOL_RING, DFC, ATRAXA_DE]


class FakeScryfall:
    def __init__(self):
        self.calls = 0

    def lookup(self, name=None, set_code=None, collector_number=None, lang=None, scryfall_id=None, prefer_set=None,
               **_hints):
        self.calls += 1
        if scryfall_id:
            for c in ALL:
                if c["id"] == scryfall_id:
                    return c
            raise ScryfallError("not found", 404)
        if set_code and collector_number:
            for c in ALL:
                if c["set"] == set_code.lower() and c["collector_number"] == str(collector_number) \
                        and (not name or name_matches(name, c)):
                    return c
        for c in ALL:
            if name and name_matches(name, c, threshold=0.8):
                return c
        raise ScryfallError(f'Keine Karte gefunden für "{name}"', 404)

    def lookup_any(self, name=None, alternatives=(), **kw):
        try:
            return self.lookup(name=name, **kw)
        except ScryfallError:
            for alt in alternatives:
                try:
                    return self.lookup(name=alt)
                except ScryfallError:
                    pass
            raise

    def collection_identifiers(self, identifiers):
        found, missing = [], []
        for ident in identifiers:
            match = [c for c in ALL if c["lang"] == "en" and c["name"].lower() == ident.get("name", "").lower()]
            (found.append(match[0]) if match else missing.append(ident))
        return found, missing

    def with_prices(self, raw):
        return raw

    def collection(self, ids):
        self.calls += 1
        return {c["id"]: dict(c, prices={"eur": "99.00"}) for c in ALL if c["id"] in ids}

    def autocomplete(self, q):
        return [c["name"] for c in ALL if q.lower() in c["name"].lower() and c["lang"] == "en"]

    def prints(self, name, lang=None, max_age=None):
        return [c for c in ALL if c["name"].lower() == name.lower()]
