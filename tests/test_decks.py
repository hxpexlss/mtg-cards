import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, LURRUS, SOL_RING, FakeScryfall  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.decks import DeckStore, parse_decklist  # noqa: E402
from mtgcards.importexport import export_json, import_cards  # noqa: E402
from mtgcards.scryfall import normalize_card  # noqa: E402

LIST = """Commander
1 Atraxa, Praetors' Voice (C16) 28

Deck
1x Sol Ring
1 Lurrus of the Dream-Den (IKO) 226 *F*
2 Kraum, Ludevic's Opus
1 Gibtsnicht Karte

Sideboard
1 Sol Ring
"""


class TestDecklistParser(unittest.TestCase):
    def test_formats(self):
        e = parse_decklist(LIST)
        self.assertEqual(e[0], {"quantity": 1, "name": "Atraxa, Praetors' Voice", "set": "C16", "cn": "28",
                                "board": "commander"})
        self.assertEqual(e[1]["name"], "Sol Ring")
        self.assertEqual(e[2]["name"], "Lurrus of the Dream-Den")
        self.assertEqual(e[3]["quantity"], 2)
        self.assertEqual(e[-1]["board"], "side")
        self.assertEqual(parse_decklist("1 Fire // Ice\nIsland")[0]["name"], "Fire // Ice")
        self.assertEqual(parse_decklist("1 Krenko *CMDR*")[0]["board"], "commander")


class TestDeckStore(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.store = DeckStore(self.db)
        self.db.add(normalize_card(SOL_RING), quantity=1)
        self.db.add(normalize_card(ATRAXA), quantity=1)

    def test_import_and_ownership(self):
        deck = self.store.create("Atraxa Superfriends")
        res = self.store.import_list(deck["id"], FakeScryfall(), LIST)
        self.assertEqual(len(res["errors"]), 1)            # "Gibtsnicht Karte"
        d = res["deck"]
        self.assertEqual(d["commanders"], ["Atraxa, Praetors' Voice"])
        self.assertEqual(d["color_identity"], "WUBG")
        cards = {(c["name"], c["board"]): c for c in d["cards"]}
        self.assertEqual(cards[("Sol Ring", "main")]["missing"], 0)
        self.assertEqual(cards[("Lurrus of the Dream-Den", "main")]["missing"], 1)
        self.assertTrue(cards[("Kraum, Ludevic's Opus", "main")]["outside_identity"])  # rot
        self.assertEqual(d["stats"]["missing"], 3)          # Lurrus 1 + Kraum 2
        self.assertEqual(d["stats"]["outside_identity"], 1)
        missing = self.store.export_text(d["id"], only_missing=True)
        self.assertIn("2 Kraum, Ludevic's Opus", missing)
        self.assertNotIn("Sol Ring", missing)
        # Export/Import der ganzen Datenbank inkl. Deck
        data = export_json(self.db)
        other = Database(":memory:")
        res = import_cards(other, FakeScryfall(), data)
        self.assertEqual(res["decks"], 1)
        d2 = DeckStore(other).list()[0]
        self.assertEqual(d2["stats"]["cards"], d["stats"]["cards"])
        res = import_cards(other, FakeScryfall(), data)   # erneut: Deck nicht doppelt
        self.assertEqual(len(DeckStore(other).list()), 1)
        self.assertEqual(json.loads(data)["decks"][0]["name"], "Atraxa Superfriends")

    def test_card_ops(self):
        deck = self.store.create("Test")
        d = self.store.set_card(deck["id"], normalize_card(LURRUS), 1, "main")
        cid = d["cards"][0]["id"]
        d = self.store.set_card(deck["id"], normalize_card(LURRUS), 1, "main", add=True)
        self.assertEqual(d["cards"][0]["quantity"], 2)
        d = self.store.update_card(cid, {"board": "commander"})
        self.assertEqual(d["commanders"], ["Lurrus of the Dream-Den"])
        d = self.store.update_card(cid, {"quantity": 0})
        self.assertEqual(d["cards"], [])
        self.assertTrue(self.store.delete(deck["id"]))
        self.assertEqual(self.store.list(), [])


if __name__ == "__main__":
    unittest.main()
