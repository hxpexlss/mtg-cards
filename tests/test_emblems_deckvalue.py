"""Embleme (Tag + Verknüpfung zum Planeswalker), Deckwert und Druck ändern."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, ATRAXA_DE, LURRUS, SOL_RING  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.decks import DeckStore  # noqa: E402
from mtgcards.scryfall import normalize_card  # noqa: E402

ELSPETH = {"id": "elspeth-id", "oracle_id": "elspeth-o", "name": "Elspeth, Knight-Errant", "lang": "en",
           "set": "sta", "collector_number": "1", "type_line": "Legendary Planeswalker — Elspeth",
           "oracle_text": "+1: ...", "color_identity": ["W"], "keywords": [], "prices": {"eur": "20.00"}}
EMBLEM = {"id": "emblem-id", "oracle_id": "emblem-o", "name": "Elspeth, Knight-Errant Emblem", "lang": "en",
          "set": "tmma", "collector_number": "22", "type_line": "Emblem — Elspeth", "layout": "emblem",
          "oracle_text": "Artifacts, creatures, enchantments, and lands you control have indestructible.",
          "color_identity": [], "keywords": [], "prices": {}}
OTHER_ELSPETH = dict(ELSPETH, id="e2", oracle_id="e2o", name="Elspeth, Sun's Champion")


class TestEmblems(unittest.TestCase):
    def test_tag(self):
        self.assertIn("Emblem", normalize_card(EMBLEM)["auto_tags"])
        self.assertNotIn("Emblem", normalize_card(ELSPETH)["auto_tags"])
        self.assertNotIn("Commander", normalize_card(EMBLEM)["auto_tags"])

    def test_link_independent_of_order(self):
        db = Database(":memory:")
        emblem, _ = db.add(normalize_card(EMBLEM))          # Emblem zuerst …
        self.assertEqual(db.related(emblem), [])
        walker, _ = db.add(normalize_card(ELSPETH))         # … Planeswalker später
        db.add(normalize_card(OTHER_ELSPETH))               # anderes Elspeth-Emblem gehört nicht dazu
        rel = db.related(db.get(emblem["id"]))
        self.assertEqual([r["name"] for r in rel], ["Elspeth, Knight-Errant"])
        self.assertEqual(rel[0]["kind"], "planeswalker")
        back = db.related(db.get(walker["id"]))
        self.assertEqual([(r["name"], r["kind"]) for r in back], [("Elspeth, Knight-Errant Emblem", "emblem")])

    def test_link_by_subtype_without_name(self):
        db = Database(":memory:")
        walker, _ = db.add(normalize_card(ELSPETH))
        emblem, _ = db.add(normalize_card(dict(EMBLEM, name="Emblem")))
        self.assertEqual(len(db.related(db.get(emblem["id"]))), 1)

    def test_migration_tags_existing(self):
        db = Database(":memory:")
        row, _ = db.add(normalize_card(EMBLEM))
        db.conn.execute("UPDATE cards SET tags='[]'")
        db.conn.execute("DELETE FROM meta WHERE key='emblem_tag_v1'")
        db._migrate()
        self.assertIn("Emblem", db.get(row["id"])["tags"])


class TestDeckValue(unittest.TestCase):
    def test_value_and_missing_cost(self):
        db = Database(":memory:")
        store = DeckStore(db)
        db.add(normalize_card(ATRAXA))                                   # 12,50 € in der Sammlung
        db.add(normalize_card(SOL_RING), tags=["Proxies"])               # Proxy zählt nicht
        deck = store.create("Test")
        store.set_card(deck["id"], normalize_card(ATRAXA), 1, "commander")
        store.set_card(deck["id"], normalize_card(SOL_RING), 1)          # Marktpreis 1,50 €
        store.set_card(deck["id"], normalize_card(LURRUS), 2)            # 2 x 3,00 €, fehlt
        st = store.get(deck["id"])["stats"]
        self.assertEqual(st["value_eur"], 12.5)
        self.assertEqual(st["missing_value_eur"], 7.5)
        self.assertEqual(st["total_value_eur"], 20.0)
        self.assertEqual(store.list()[0]["stats"]["value_eur"], 12.5)


class TestUmlautSearch(unittest.TestCase):
    def test_umlauts_and_case(self):
        db = Database(":memory:")
        db.add(normalize_card(dict(ATRAXA_DE, printed_name="Über die Straße")))
        for q in ("über", "ÜBER", "uber", "strasse", "Straße", "atraxa"):
            self.assertEqual(len(db.search(q=q)[0]), 1, q)


class TestChangePrint(unittest.TestCase):
    def test_change_language_and_merge(self):
        db = Database(":memory:")
        de, _ = db.add(normalize_card(ATRAXA_DE), quantity=2, tags=["Deck A"])
        changed = db.change_print(de["id"], normalize_card(ATRAXA))
        self.assertEqual((changed["lang"], changed["quantity"], changed["tags"][-1]), ("en", 2, "Deck A"))
        other, _ = db.add(normalize_card(ATRAXA_DE))
        merged = db.change_print(other["id"], normalize_card(ATRAXA))
        self.assertEqual((merged["id"], merged["quantity"]), (changed["id"], 3))
        self.assertIsNone(db.get(other["id"]))


if __name__ == "__main__":
    unittest.main()
