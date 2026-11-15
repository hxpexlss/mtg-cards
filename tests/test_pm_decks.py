"""Reiter „Decks“: Deckliste mit Bereichen, Druck mit/ohne Sideboard und Standardländer, Export, MTG-Cards-Deck."""

import json
import os
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_fixtures import ALL, FakeScryfall, card, fake_fetch, fake_fetch_any  # noqa: E402

from mtgcards.server import Server  # noqa: E402
from mtgcards.pm.store import Store  # noqa: E402

ISLAND = card("island", "Island", "fdn", "270", eur="0.10")
ISLAND["type_line"] = "Basic Land — Island"

LIST = """Commander
1 Sol Ring

Deck
4 Lightning Bolt (M11) 149
10 Island

Sideboard
2 Delver of Secrets // Insectile Aberration
"""


class TestDecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ALL.append(ISLAND)
        cls.srv = Server(os.path.join(tempfile.mkdtemp(), "d.db"), "T", bind="127.0.0.1", port=0,
                         discovery=False, scryfall=FakeScryfall()).start()
        cls.srv.ctx.pm.image_fetcher = fake_fetch
        cls.srv.ctx.pm.any_fetcher = fake_fetch_any

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        ALL.remove(ISLAND)

    def call(self, method, path, body=None, raw=False):
        req = Request(f"http://127.0.0.1:{self.srv.port}{'/proxies' if path.startswith('/api/') else ''}{path}", method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer T", "Content-Type": "application/json"})
        with urlopen(req) as r:
            data = r.read()
            return data if raw else json.loads(data)

    def test_deck_boards_print_and_export(self):
        r = self.call("POST", "/api/projects", {"name": "Izzet", "kind": "deck", "list": LIST})
        p = r["project"]
        self.assertEqual((p["kind"], r["errors"]), ("deck", []))
        boards = {i["name"]: (i["board"], i["quantity"]) for i in p["items"]}
        self.assertEqual(boards["Sol Ring"], ("commander", 1))
        self.assertEqual(boards["Lightning Bolt"], ("main", 4))
        self.assertEqual(boards["Delver of Secrets // Insectile Aberration"], ("side", 2))
        self.assertEqual(p["items"][1]["set_code"], "M11")
        lists = [x for x in self.call("GET", "/api/projects")["projects"] if x["id"] == p["id"]]
        self.assertEqual(lists[0]["kind"], "deck")
        # Druck: ohne Sideboard + ohne Standardländer = 1 + 4 Karten -> 1 Seite; mit allem: 1+4+10+2*2 = 19 -> 3 Seiten
        pdf = self.call("GET", f"/api/projects/{p['id']}/print.pdf?boards=commander,companion,main&skip_basic=1", raw=True)
        self.assertEqual(pdf.count(b"/Type /Page "), 1)
        pdf = self.call("GET", f"/api/projects/{p['id']}/print.pdf", raw=True)
        self.assertEqual(pdf.count(b"/Type /Page "), 3)
        txt = self.call("GET", f"/api/projects/{p['id']}/decklist.txt", raw=True).decode()
        self.assertIn("Commander\n1 Sol Ring", txt)
        self.assertIn("4 Lightning Bolt (M11) 149", txt)
        self.assertIn("Sideboard\n2 Delver", txt)
        # Bereich ändern, Karte direkt in einen Bereich hinzufügen
        bolt = next(i for i in p["items"] if i["name"] == "Lightning Bolt")
        self.assertEqual(self.call("PATCH", f"/api/items/{bolt['id']}", {"board": "side"})["board"], "side")
        it = self.call("POST", f"/api/projects/{p['id']}/items", {"name": "Sol Ring", "board": "side"})
        self.assertEqual(it["board"], "side")
        d = self.call("POST", f"/api/projects/{p['id']}/duplicate", {})
        self.assertEqual(d["kind"], "deck")

    def test_migration_old_database(self):
        path = os.path.join(tempfile.mkdtemp(), "alt.db")
        import sqlite3
        c = sqlite3.connect(path)
        c.executescript("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',"
                        " back_id INTEGER, created_at TEXT, updated_at TEXT);"
                        "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'scryfall',"
                        " name TEXT NOT NULL, oracle_id TEXT, scryfall_id TEXT, set_code TEXT, collector_number TEXT, lang TEXT,"
                        " type_line TEXT, mana_cost TEXT, image_url TEXT, image_url_back TEXT, png_url TEXT, png_url_back TEXT,"
                        " image_status TEXT, quantity INTEGER NOT NULL DEFAULT 1, max_price_eur REAL, price_eur REAL, price_set TEXT,"
                        " price_checked_at TEXT, notes TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}', art BLOB,"
                        " custom_image BLOB, rendered BLOB, rendered_back BLOB, position INTEGER NOT NULL DEFAULT 0,"
                        " created_at TEXT, updated_at TEXT);"
                        "INSERT INTO projects(id, name) VALUES(1, 'Alt'); INSERT INTO items(project_id, name) VALUES(1, 'X');")
        c.commit()
        c.close()
        s = Store(path)
        p = s.project(1)
        self.assertEqual((p["kind"], p["items"][0]["board"]), ("list", "main"))
        s.close()


if __name__ == "__main__":
    unittest.main()
