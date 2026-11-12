import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, LURRUS, SOL_RING  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.decks import DeckStore  # noqa: E402
from mtgcards.scryfall import normalize_card  # noqa: E402
from mtgcards.wishlist import Wishlist  # noqa: E402

P = ["Proxies"]


class TestProxyTag(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def test_proxy_is_separate_entry(self):
        real, _ = self.db.add(normalize_card(ATRAXA))
        prox, created = self.db.add(normalize_card(ATRAXA), tags=P)
        self.assertTrue(created)
        self.assertNotEqual(real["id"], prox["id"])
        self.assertTrue(prox["proxy"])
        self.assertNotIn("Proxies", self.db.get(real["id"])["tags"])
        prox, created = self.db.add(normalize_card(ATRAXA), tags=P)   # zweiter Proxy -> Anzahl +1
        self.assertFalse(created)
        self.assertEqual(prox["quantity"], 2)
        self.assertEqual(self.db.find_owned(ATRAXA["id"], ATRAXA["oracle_id"])["this_print"], 1)

    def test_value_duplicates_sets_exclude_proxies(self):
        self.db.add(normalize_card(ATRAXA))                    # 12,50 €
        self.db.add(normalize_card(ATRAXA), quantity=3, tags=P)
        s = self.db.detailed_stats()
        self.assertEqual(s["value_eur"], 12.5)
        self.assertEqual(s["proxies"], 3)
        self.assertEqual(self.db.stats()["value_eur"], 12.5)
        self.assertEqual(self.db.search(dup_min=2)[1], 0)      # echte Atraxa nur 1x
        self.assertEqual(self.db.set_ownership("C16")["28"]["quantity"], 1)
        self.assertEqual(self.db.search(tag="Proxies")[1], 1)

    def test_toggle_proxy_tag_merges(self):
        a, _ = self.db.add(normalize_card(SOL_RING), quantity=2)
        b, _ = self.db.add(normalize_card(SOL_RING), tags=P)
        merged = self.db.update(b["id"], {"tags": []})          # Proxy-Tag entfernen -> mit echter zusammenführen
        self.assertEqual(merged["id"], a["id"])
        self.assertEqual(merged["quantity"], 3)
        c = self.db.update(a["id"], {"tags": ["Proxies"]})      # ganze Zeile zum Proxy machen
        self.assertTrue(c["proxy"])

    def test_deck_and_wishlist(self):
        store = DeckStore(self.db)
        wl = Wishlist(self.db)
        self.db.add(normalize_card(LURRUS), tags=P)
        deck = store.create("D")
        d = store.set_card(deck["id"], normalize_card(LURRUS), 1)
        card = d["cards"][0]
        self.assertEqual((card["owned"], card["proxies"], card["missing"]), (0, 1, 1))
        wl.add(normalize_card(SOL_RING))
        self.assertEqual(wl.list()["items"][0]["owned"], 0)

    def test_migration_of_old_database(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE cards (id INTEGER PRIMARY KEY AUTOINCREMENT, scryfall_id TEXT, oracle_id TEXT,
              name TEXT NOT NULL, printed_name TEXT, lang TEXT, set_code TEXT, set_name TEXT, collector_number TEXT,
              rarity TEXT, mana_cost TEXT, cmc REAL, type_line TEXT, oracle_text TEXT, power TEXT, toughness TEXT,
              loyalty TEXT, colors TEXT, color_identity TEXT, keywords TEXT, image_url TEXT, scryfall_uri TEXT,
              price_eur TEXT, price_eur_foil TEXT, price_usd TEXT, price_usd_foil TEXT, foil INTEGER NOT NULL DEFAULT 0,
              quantity INTEGER NOT NULL DEFAULT 1, tags TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '',
              added_at TEXT, updated_at TEXT);
            CREATE UNIQUE INDEX ux_cards_print_foil ON cards(scryfall_id, foil) WHERE scryfall_id IS NOT NULL;
        """)
        con.execute("INSERT INTO cards(scryfall_id, name, tags) VALUES('x', 'Alt', ?)", (json.dumps(["Proxies"]),))
        con.commit()
        con.close()
        db = Database(path)
        self.assertTrue(db.all()[0]["proxy"])
        db.add({"scryfall_id": "x", "name": "Alt", "type_line": "Artifact"})   # echte Karte daneben möglich
        self.assertEqual(len(db.all()), 2)


if __name__ == "__main__":
    unittest.main()
