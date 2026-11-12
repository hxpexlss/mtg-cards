"""Sprache des Ergebnisses, Preise fremdsprachiger Drucke und Erkennung alter Karten."""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtgcards.scryfall import Scryfall  # noqa: E402


def bolt(set_code, cn, lang="en", printed=None, artist="Christopher Moeller", released="2009-07-17",
         ill="ill-b", prices=None):
    return {"id": f"{set_code}-{cn}-{lang}", "oracle_id": "bolt", "name": "Lightning Bolt", "lang": lang,
            "printed_name": printed, "set": set_code, "set_name": set_code.upper(), "collector_number": cn,
            "type_line": "Instant", "oracle_text": "Deal 3 damage.", "color_identity": ["R"], "colors": ["R"],
            "keywords": [], "rarity": "common", "artist": artist, "released_at": released,
            "illustration_id": ill,
            "prices": prices if prices is not None else ({"eur": "2.00", "usd": "2.50"} if lang == "en" else
                                                          {"eur": None, "eur_foil": None, "usd": None})}


LEA = bolt("lea", "161", artist="Christopher Rush", released="1993-08-05", ill="ill-a")
M10 = bolt("m10", "146")
M11 = bolt("m11", "149", released="2010-07-16")
FDN = bolt("fdn", "77", released="2024-11-15", ill="ill-c", prices={"eur": "0.30", "usd": "0.40"})
FDN_DE = bolt("fdn", "77", "de", "Blitzschlag", released="2024-11-15", ill="ill-c")
FDN_JA = bolt("fdn", "77", "ja", "稲妻", released="2024-11-15", ill="ill-c")
EMBLEM = {"id": "emb", "oracle_id": "emb-o", "name": "Chandra, Torch of Defiance Emblem", "lang": "en",
          "set": "tkld", "set_name": "Kaladesh Tokens", "collector_number": "10", "layout": "emblem",
          "type_line": "Emblem — Chandra", "oracle_text": "Whenever you cast a spell, this emblem deals 5 damage.",
          "color_identity": [], "colors": [], "keywords": [], "prices": {}}
CARDS = {(c["set"], c["collector_number"], c["lang"]): c for c in (LEA, M10, M11, FDN, FDN_DE, FDN_JA, EMBLEM)}
SETS = [{"code": "lea", "card_count": 295}, {"code": "m10", "card_count": 249, "printed_size": 249},
        {"code": "m11", "card_count": 249}, {"code": "fdn", "card_count": 730, "printed_size": 271}]


class FakeApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        found, missing = [], []
        for ident in body["identifiers"]:
            c = CARDS.get((ident.get("set"), ident.get("collector_number"), "en"))
            (found.append(c) if c else missing.append(ident))
        self.send({"data": found, "not_found": missing})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = u.path.strip("/").split("/")
        if u.path == "/cards/autocomplete":
            names = ["Lightning Bolt"] if "light" in q["q"].lower() else []
            if q.get("include_extras") and "chandra" in q["q"].lower():
                names = [EMBLEM["name"], "Chandra // Chandra"]
            return self.send({"data": names})
        if u.path == "/sets":
            return self.send({"data": SETS})
        if parts[0] == "cards" and len(parts) in (3, 4) and parts[1] not in ("named", "search"):
            c = CARDS.get((parts[1], parts[2], parts[3] if len(parts) == 4 else "en"))
            return self.send(c) if c else self.send({"details": "nicht gefunden"}, 404)
        if u.path == "/cards/named":
            if q.get("fuzzy", "").lower() != "lightning bolt":
                return self.send({"details": "nicht gefunden"}, 404)
            s = q.get("set")
            hit = [c for c in CARDS.values() if c["lang"] == "en" and c["name"] == "Lightning Bolt" and (not s or c["set"] == s)]
            return self.send(hit[-1]) if hit else self.send({"details": "nicht in Edition"}, 404)
        if u.path == "/cards/search":
            qq = q.get("q", "").replace(" include:extras", "")
            if qq == '!"Lightning Bolt"':
                return self.send({"data": [LEA, M10, M11, FDN]})
            if qq.startswith("t:emblem") and "chandra" in qq.lower():
                return self.send({"data": [EMBLEM]})
            if qq == '!"Chandra, Torch of Defiance Emblem"':
                return self.send({"data": [EMBLEM]})
            if qq == "Blitzsch lang:any":
                return self.send({"data": [FDN_JA, FDN_DE]})
            if qq == '!"Lightning Bolt" lang:de':
                return self.send({"data": [FDN_DE]})
            if "Blitzschlag" in qq and "lang:any" in qq:
                return self.send({"data": [FDN_JA, FDN_DE]})    # Japanisch kommt zuerst!
            return self.send({"details": "keine"}, 404)
        return self.send({"details": "?"}, 404)


class TestLanguageAndPrices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        cls.sf = Scryfall(base=f"http://127.0.0.1:{cls.api.server_address[1]}", min_interval=0)

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()

    def test_german_name_gives_german_print_not_japanese(self):
        c = self.sf.lookup_any(name="Blitzschlag")
        self.assertEqual(c["lang"], "de")
        self.assertEqual(c["prices"]["eur"], "0.30")            # Preis vom englischen Druck übernommen

    def test_english_name_stays_english(self):
        c = self.sf.lookup_any(name="Lightning Bolt")
        self.assertEqual(c["lang"], "en")

    def test_scan_language_wins(self):
        c = self.sf.lookup_any(name="Lightning Bolt", set_code="FDN", collector_number="77", lang="de")
        self.assertEqual((c["lang"], c["_match"], c["prices"]["eur"]), ("de", "exact", "0.30"))

    def test_scan_language_keeps_detected_print(self):
        # Edition sicher erkannt, gibt es aber nicht auf Deutsch -> Edition bleibt (englisch)
        c = self.sf.lookup_any(name="Lightning Bolt", set_code="M11", collector_number="149", lang="de")
        self.assertEqual((c["set"], c["lang"]), ("m11", "en"))

    def test_old_card_number_and_set_size(self):
        c = self.sf.lookup(name="Lightning Bolt", collector_number="149", total="249")
        self.assertEqual((c["set"], c["_match"]), ("m11", "exact"))

    def test_old_card_artist_and_year(self):
        c = self.sf.lookup(name="Lightning Bolt", artist="Christopher Rush")
        self.assertEqual((c["set"], c["_match"]), ("lea", "likely"))
        c = self.sf.lookup(name="Lightning Bolt", artist="Chris Moeller", year="2010")
        self.assertEqual(c["set"], "m11")

    def test_old_card_without_hints_is_guess(self):
        self.assertEqual(self.sf.lookup(name="Lightning Bolt")["_match"], "name")

    def test_fill_prices(self):
        out = self.sf.fill_prices({"a": FDN_DE, "b": M10})
        self.assertEqual(out["a"]["prices"]["eur"], "0.30")
        self.assertEqual(out["b"]["prices"]["eur"], "2.00")

    def test_emblem_by_type_line_and_token_set(self):
        c = self.sf.lookup_any(name="Emblem — Chandra")
        self.assertEqual((c["name"], c["_match"]), (EMBLEM["name"], "name"))
        c = self.sf.lookup_any(name="Emblem Chandra", set_code="KLD")
        self.assertEqual((c["set"], c["_match"]), ("tkld", "set"))
        c = self.sf.lookup_any(name="Emblem", set_code="KLD", collector_number="10")
        self.assertEqual((c["set"], c["_match"]), ("tkld", "exact"))

    def test_emblem_by_full_name(self):
        self.assertEqual(self.sf.lookup_any(name="Chandra, Torch of Defiance Emblem")["id"], "emb")

    def test_autocomplete_extras_and_german(self):
        self.assertEqual(self.sf.autocomplete("chandra"), [EMBLEM["name"]])
        self.assertIn("Blitzschlag", self.sf.autocomplete("Blitzsch"))

    def test_prints_in_language(self):
        self.assertEqual([p["lang"] for p in self.sf.prints("Lightning Bolt", "de")], ["de"])


if __name__ == "__main__":
    unittest.main()
