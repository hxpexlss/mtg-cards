import json
import os
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import FakeScryfall  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.importexport import export_json, import_cards  # noqa: E402
from mtgcards.server import Server  # noqa: E402

TOK = "WISH-AAAA-BBBB-CCCC"


class TestWishlistApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(os.path.join(tempfile.mkdtemp(), "w.db"), TOK, bind="127.0.0.1", port=0,
                         discovery=False, scryfall=FakeScryfall()).start()
        cls.base = f"http://127.0.0.1:{cls.srv.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def call(self, path, method="GET", data=None):
        req = Request(self.base + path, method=method, data=None if data is None else json.dumps(data).encode(),
                      headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
        try:
            with urlopen(req) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_flow(self):
        st, w = self.call("/api/wishlist", "POST", {"name": "Sol Ring", "quantity": 2, "max_price_eur": "2,00"})
        self.assertEqual(st, 201)
        self.assertEqual(w["price_eur"], 1.5)
        self.assertTrue(w["target_reached"])
        self.assertTrue(w["any_print"])
        st, w2 = self.call("/api/wishlist", "POST", {"name": "Atraxa", "max_price_eur": 5})
        self.assertFalse(w2["target_reached"])                      # 12,50 € > 5 €
        lst = self.call("/api/wishlist")[1]
        self.assertEqual((len(lst["items"]), lst["alerts"]), (2, 1))

        st, w2 = self.call(f"/api/wishlist/{w2['id']}", "PATCH", {"max_price_eur": 15})
        self.assertTrue(w2["target_reached"])

        # Karte gekauft und eingescannt -> Wunsch wird reduziert
        st, row = self.call("/api/cards", "POST", {"name": "Sol Ring"})
        self.assertEqual(row["wish_fulfilled"][0]["remaining"], 1)
        # Stapel: zweiter Sol Ring erfüllt den Rest, unbekannte Karte erzeugt Fehler, Rest wird gespeichert
        st, res = self.call("/api/cards/batch", "POST", {"cards": [
            {"name": "Sol Ring"}, {"name": "Unbekannt xyz"}, {"name": "Kraum", "quantity": 2, "foil": True}]})
        self.assertEqual(res["added"], 3)
        self.assertEqual(len(res["errors"]), 1)
        self.assertEqual(res["wish_fulfilled"][0]["remaining"], 0)
        names = [i["name"] for i in self.call("/api/wishlist")[1]["items"]]
        self.assertEqual(names, ["Atraxa, Praetors' Voice"])

        # Fehlende Deck-Karten -> Wunschliste
        st, d = self.call("/api/decks", "POST", {"name": "D", "list": "1 Lurrus of the Dream-Den\n1 Sol Ring"})
        st, r = self.call(f"/api/decks/{d['deck']['id']}/to-wishlist", "POST", {})
        self.assertEqual(r["added"], ["Lurrus of the Dream-Den"])
        self.assertEqual(self.call(f"/api/wishlist/{w2['id']}", "DELETE")[0], 200)
        st, r = self.call("/api/wishlist/refresh", "POST", {})
        self.assertEqual(r["total"], 1)

    def test_z_export_contains_wishlist(self):
        db = self.srv.db
        self.call("/api/wishlist", "POST", {"name": "Kraum", "max_price_eur": 1})
        data = export_json(db)
        self.assertTrue(json.loads(data)["wishlist"])
        other = Database(":memory:")
        res = import_cards(other, FakeScryfall(), data)
        self.assertGreaterEqual(res["wishlist"], 1)


if __name__ == "__main__":
    unittest.main()
