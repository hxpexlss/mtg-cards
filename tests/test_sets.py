import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, ATRAXA_DE, KRAUM, SOL_RING  # noqa: E402

from mtgcards.scryfall import Scryfall, normalize_card  # noqa: E402
from mtgcards.server import Server  # noqa: E402

TOK = "SETS-AAAA-BBBB-CCCC"
# Edition C16 mit 3 Karten im Grundset (Nr. 1, 2, 3) + 1 Variante (Nr. 300)
C16_CARDS = [
    dict(ATRAXA, collector_number="1"),
    dict(KRAUM, collector_number="2"),
    {**SOL_RING, "id": "c16-solring", "set": "c16", "set_name": "Commander 2016", "collector_number": "3",
     "rarity": "uncommon", "prices": {"eur": "2.00"}},
    {**ATRAXA, "id": "c16-atraxa-showcase", "collector_number": "300", "prices": {"eur": "40.00"}},
]


class FakeScryfallApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        if u.path == "/sets":
            return self.send({"data": [{"code": "c16", "name": "Commander 2016", "card_count": 4,
                                        "printed_size": 3, "icon_svg_uri": "x.svg", "released_at": "2016-11-11"}]})
        if u.path == "/sets/c16":
            return self.send({"code": "c16", "name": "Commander 2016", "card_count": 4, "printed_size": 3})
        if u.path == "/cards/search" and q.get("q") == "e:c16":
            if q.get("page") == "2":
                return self.send({"data": C16_CARDS[2:], "has_more": False})
            return self.send({"data": C16_CARDS[:2], "has_more": True,
                              "next_page": base + "/cards/search?q=e%3Ac16&unique=prints&page=2"})
        if u.path == "/cards/c16/1/de":
            return self.send(ATRAXA_DE)
        if u.path == "/cards/named":
            for c in (ATRAXA, KRAUM, SOL_RING):
                if q.get("fuzzy", "").lower() in c["name"].lower():
                    return self.send(c)
        if u.path.startswith("/cards/") and u.path.endswith("/de"):
            return self.send({"details": "nicht gefunden"}, 404)
        if u.path == "/cards/search" and "lang:de" in q.get("q", ""):
            return self.send({"details": "keine"}, 404)
        return self.send({"details": "nicht gefunden"}, 404)


class TestSetsAndLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), FakeScryfallApi)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        sf = Scryfall(base=f"http://127.0.0.1:{cls.api.server_address[1]}", min_interval=0)
        cls.srv = Server(os.path.join(tempfile.mkdtemp(), "s.db"), TOK, bind="127.0.0.1", port=0,
                         discovery=False, scryfall=sf).start()
        cls.base = f"http://127.0.0.1:{cls.srv.port}"
        db = cls.srv.db
        db.add(normalize_card(C16_CARDS[0]), quantity=1)               # Atraxa C16 #28
        db.add(normalize_card(C16_CARDS[0]), quantity=1, foil=True)    # + Foil -> zusammen 2
        db.add(normalize_card(C16_CARDS[3]), quantity=1)               # Showcase-Atraxa -> zusammen 3
        db.add(normalize_card(SOL_RING), quantity=1)                   # C21, einzeln

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.api.shutdown()

    def get(self, path):
        with urlopen(Request(self.base + path, headers={"Authorization": "Bearer " + TOK})) as r:
            return json.loads(r.read())

    def test_set_list_and_detail(self):
        sets = {s["code"]: s for s in self.get("/api/sets")["sets"]}
        c16 = sets["C16"]
        self.assertEqual((c16["main_owned"], c16["main_size"], c16["percent"]), (1, 3, 33.3))
        d = self.get("/api/sets/c16")
        self.assertEqual(len(d["cards"]), 4)                          # Seitenwechsel funktioniert
        self.assertEqual(d["stats"]["main"]["_all"], {"total": 3, "owned": 1, "missing_value": 2.0,
                                                       "percent": 33.3})
        self.assertEqual(d["stats"]["all"]["_all"]["owned"], 2)       # inkl. Showcase-Variante
        atraxa = next(c for c in d["cards"] if c["collector_number"] == "1")
        self.assertEqual((atraxa["owned"], atraxa["owned_foil"]), (2, 1))
        self.assertFalse(next(c for c in d["cards"] if c["collector_number"] == "300")["main"])

    def test_duplicates(self):
        res = self.get("/api/cards?dup_min=2")
        self.assertEqual({c["name"] for c in res["cards"]}, {"Atraxa, Praetors' Voice"})
        self.assertEqual(len(res["cards"]), 3)                       # alle Einträge der Karte
        self.assertEqual(res["duplicates"]["cards"], 1)
        self.assertEqual(res["duplicates"]["extra_copies"], 2)
        self.assertEqual(res["duplicates"]["extra_value_eur"], 25.0)  # 2× 12,50 (Showcase 40 € wird behalten)
        self.assertEqual(self.get("/api/cards?dup_min=4")["total"], 0)

    def test_lookup_language(self):
        de = self.get("/api/lookup?name=Atraxa&set=C16&cn=1&lang=de")
        self.assertEqual(de["lang"], "de")
        self.assertEqual(de["printed_name"], "Atraxa, Stimme der Prätoren")
        # Sprache nicht verfügbar -> Original
        self.assertEqual(self.get("/api/lookup?name=Kraum&lang=de")["lang"], "en")
        self.assertEqual(self.get("/api/lookup?name=Kraum&lang=auto")["lang"], "en")


if __name__ == "__main__":
    unittest.main()
