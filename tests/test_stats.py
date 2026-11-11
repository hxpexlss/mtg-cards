import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, DFC, KRAUM, LURRUS, SOL_RING, FakeScryfall  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.decks import DeckStore  # noqa: E402
from mtgcards.scryfall import normalize_card  # noqa: E402
from mtgcards.server import Server, refresh_all  # noqa: E402


class TestStats(unittest.TestCase):
    def test_detailed_stats(self):
        db = Database(":memory:")
        db.add(normalize_card(ATRAXA), quantity=2)            # 12.50 €
        db.add(normalize_card(SOL_RING), quantity=3)          # 1.50 €
        db.add(normalize_card(SOL_RING), foil=True)           # kein Foil-Preis -> Fallback 1.50
        db.add(normalize_card(KRAUM))                         # kein Preis
        db.add(normalize_card(DFC))                           # Land, kein Preis
        s = db.detailed_stats()
        self.assertEqual(s["cards"], 8)
        self.assertEqual(s["foils"], 1)
        self.assertEqual(s["value_eur"], 31.0)
        self.assertEqual(s["without_price"], 2)
        self.assertEqual(s["top_cards"][0]["name"], "Atraxa, Praetors' Voice")
        self.assertEqual(s["top_cards"][0]["total_eur"], 25.0)
        curve = {b["cmc"]: b["cards"] for b in s["mana_curve"]}
        self.assertEqual(curve[1], 4)          # Sol Ring
        self.assertEqual(curve[0], 0)          # Land zählt nicht
        self.assertEqual({b["key"] for b in s["by_rarity"]}, {"mythic", "uncommon", "rare"})
        types = {b["key"]: b["cards"] for b in s["by_type"]}
        self.assertEqual(types["Land"], 1)
        db.snapshot_value("2026-01-01")
        db.snapshot_value()
        self.assertEqual(len(db.value_history()), 2)
        self.assertEqual(db.value_history()[0]["value_eur"], 31.0)

    def test_refresh_all_records_history(self):
        tmp = tempfile.mkdtemp()
        srv = Server(os.path.join(tmp, "x.db"), "T", bind="127.0.0.1", port=0, discovery=False,
                     scryfall=FakeScryfall()).start()
        try:
            srv.db.add(normalize_card(SOL_RING), quantity=2)
            res = refresh_all(srv.ctx)
            self.assertEqual(res["updated"], 1)
            self.assertEqual(srv.db.value_history()[-1]["value_eur"], 198.0)   # Fake-Preis 99 €
            self.assertIsNotNone(srv.db.get_meta("last_price_refresh"))
        finally:
            srv.stop()


class TestDeckReservation(unittest.TestCase):
    def test_shared_between_decks(self):
        db = Database(":memory:")
        store = DeckStore(db)
        db.add(normalize_card(SOL_RING), quantity=1)
        a = store.create("Deck A")
        b = store.create("Deck B")
        store.set_card(a["id"], normalize_card(SOL_RING), 1)
        store.set_card(a["id"], normalize_card(LURRUS), 1)
        d = store.set_card(b["id"], normalize_card(SOL_RING), 1)
        sol = d["cards"][0]
        self.assertEqual(sol["missing"], 0)                 # 1 besessen
        self.assertTrue(sol["shared"])                      # ... steckt aber auch in Deck A
        self.assertEqual(sol["other_decks"], [{"deck_id": a["id"], "deck": "Deck A", "quantity": 1}])
        self.assertEqual(sol["available"], 0)
        self.assertEqual(d["stats"]["missing_reserved"], 1)
        db.add(normalize_card(SOL_RING), quantity=1)        # zweiter Sol Ring -> reicht für beide
        sol = store.get(b["id"])["cards"][0]
        self.assertFalse(sol["shared"])
        usage = store.usage_for(sol["oracle_id"], "Sol Ring")
        self.assertEqual(sorted(u["deck"] for u in usage), ["Deck A", "Deck B"])


if __name__ == "__main__":
    unittest.main()
