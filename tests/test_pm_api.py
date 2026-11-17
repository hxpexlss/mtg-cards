"""Server-API: Drucklisten, Karten, Druck-Auswahl, Personalisierung, Druck, Sicherung, Import aus MTG Cards."""

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_fixtures import BOLT_DE, BOLT_M11, JPEG, FakeScryfall, fake_fetch, fake_fetch_any  # noqa: E402

from mtgcards.server import Server  # noqa: E402

B64 = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


class FakeMtgCards(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer MTG":
            self.send_response(401)
            self.end_headers()
            return
        data = {"/api/info": {"version": "2.1.1"},
                "/api/wishlist": {"items": [{"name": "Lightning Bolt", "scryfall_id": "bolt-m11", "quantity": 2,
                                             "max_price_eur": 1.5}]},
                "/api/decks": {"decks": [{"id": 3, "name": "Izzet", "stats": {"missing": 1, "cards": 2}}]},
                "/api/decks/3": {"cards": [{"name": "Sol Ring", "board": "main", "missing": 1, "quantity": 1},
                                           {"name": "Island", "board": "main", "missing": 0, "quantity": 5, "basic": True}]},
                }.get(self.path)
        body = json.dumps(data).encode()
        self.send_response(200 if data else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(os.path.join(tempfile.mkdtemp(), "p.db"), "ABCD-EFGH", bind="127.0.0.1", port=0,
                         discovery=False, scryfall=FakeScryfall()).start()
        cls.srv.ctx.pm.image_fetcher = fake_fetch
        cls.srv.ctx.pm.any_fetcher = fake_fetch_any
        cls.mtg = ThreadingHTTPServer(("127.0.0.1", 0), FakeMtgCards)
        threading.Thread(target=cls.mtg.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.mtg.shutdown()

    def call(self, method, path, body=None, raw=False, token="abcd efgh"):
        req = Request(f"http://127.0.0.1:{self.srv.port}{'/proxies' if path.startswith('/api/') else ''}{path}", method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen(req) as r:
            data = r.read()
            return data if raw else json.loads(data)

    def project(self, name="Test"):
        return self.call("POST", "/api/projects", {"name": name})["project"]

    def test_auth(self):
        with self.assertRaises(HTTPError) as ctx:
            self.call("GET", "/api/projects", token="falsch")
        self.assertEqual(ctx.exception.code, 401)

    def test_add_merge_print_choice_and_prices(self):
        p = self.project()
        a = self.call("POST", f"/api/projects/{p['id']}/items", {"name": "Lightning Bolt", "any_print": True,
                                                                 "max_price_eur": "1,00"})
        self.assertTrue(a["any_print"])
        self.call("POST", f"/api/projects/{p['id']}/items", {"name": "Lightning Bolt", "any_print": True})
        proj = self.call("GET", f"/api/projects/{p['id']}")
        self.assertEqual((len(proj["items"]), proj["items"][0]["quantity"]), (1, 2))   # zusammengeführt
        self.assertEqual(proj["items"][0]["price_eur"], 0.3)                              # günstigster Druck
        self.assertEqual(proj["alerts"], 1)                                               # unter Zielpreis
        it = self.call("PATCH", f"/api/items/{a['id']}", {"scryfall_id": BOLT_M11["id"]})
        self.assertEqual((it["set_code"], it["collector_number"], it["any_print"]), ("M11", "149", False))
        it = self.call("PATCH", f"/api/items/{a['id']}", {"scryfall_id": BOLT_DE["id"]})
        self.assertTrue(it["lowres"])
        with self.assertRaises(HTTPError) as ctx:
            self.call("PATCH", f"/api/items/{a['id']}", {"scryfall_id": "sol"})
        self.assertEqual(ctx.exception.code, 400)

    def test_personalize_and_print(self):
        p = self.project("Druck")
        dfc = self.call("POST", f"/api/projects/{p['id']}/items", {"name": "Delver of Secrets // Insectile Aberration"})
        sol = self.call("POST", f"/api/projects/{p['id']}/items", {"name": "Sol Ring", "quantity": 2})
        self.assertTrue(dfc["image_url_back"])
        # Editor: Basisbild über den Server, Artwork + fertiges Bild speichern
        self.assertTrue(self.call("GET", f"/api/items/{sol['id']}/base", raw=True).startswith(b"\x89PNG"))
        self.call("PUT", f"/api/items/{sol['id']}/art", {"image": B64})
        it = self.call("PUT", f"/api/items/{sol['id']}/rendered", {"front": B64, "settings": {"footer": {"mode": "remove"}}})
        self.assertTrue(it["has_rendered"] and it["has_art"])
        self.assertEqual(it["settings"]["footer"]["mode"], "remove")
        self.assertEqual(self.call("GET", f"/api/items/{sol['id']}/rendered", raw=True), JPEG)
        with self.assertRaises(HTTPError):
            self.call("PUT", f"/api/items/{sol['id']}/rendered", {"front": "bm9wZQ=="})
        # PDF: DFC ohne Duplex = 2 Karten + 2x Sol Ring
        pdf = self.call("GET", f"/api/projects/{p['id']}/print.pdf", raw=True)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(pdf.count(b"/Type /Page "), 1)
        # Duplex mit eigener Rückseite: Vorder- + Rückseitenseite
        back = self.call("POST", "/api/backs", {"name": "Meine Rückseite", "image": B64})
        self.call("PATCH", f"/api/projects/{p['id']}", {"back_id": back["id"]})
        pdf = self.call("GET", f"/api/projects/{p['id']}/print.pdf?duplex=1", raw=True)
        self.assertEqual(pdf.count(b"/Type /Page "), 2)
        z = zipfile.ZipFile(io.BytesIO(self.call("GET", f"/api/projects/{p['id']}/images.zip", raw=True)))
        names = z.namelist()
        self.assertIn("kartenrueckseite.jpg", names)
        self.assertTrue(any(n.endswith(("_rueckseite.png", "_rueckseite.jpg")) for n in names))
        self.assertTrue(any("Sol-Ring_x2" in n for n in names))
        # Zurücksetzen
        it = self.call("DELETE", f"/api/items/{sol['id']}/rendered?settings=1")
        self.assertFalse(it["has_rendered"] or it["has_art"])

    def test_custom_list_import_duplicate(self):
        p = self.project("Fun")
        c = self.call("POST", f"/api/projects/{p['id']}/custom", {"name": "Mein Drache", "image": B64, "quantity": 3})
        self.assertEqual((c["kind"], c["quantity"]), ("custom", 3))
        r = self.call("POST", f"/api/projects/{p['id']}/import", {"list": "2 Sol Ring\n1 Gibtsnicht"})
        self.assertEqual(len(r["errors"]), 1)
        d = self.call("POST", f"/api/projects/{p['id']}/duplicate", {})
        self.assertEqual(len(d["items"]), 2)
        self.assertTrue(any(i["has_custom"] for i in d["items"]))

    def test_presets_backup(self):
        self.call("POST", "/api/presets", {"name": "Gold", "settings": {"border": {"mode": "color", "color": "#c9a24a"}}})
        self.assertIn("Gold", [p["name"] for p in self.call("GET", "/api/presets")["presets"]])
        p = self.project("Sicherung")
        self.call("POST", f"/api/projects/{p['id']}/custom", {"name": "X", "image": B64})
        dump = json.loads(self.call("GET", "/api/export", raw=True))
        self.assertEqual(dump["format"], "proxie-maker")
        before = len(self.call("GET", "/api/projects")["projects"])
        res = self.call("POST", "/api/import?mode=add", dump)
        self.assertEqual(len(self.call("GET", "/api/projects")["projects"]), before + res["projects"])

    def test_import_from_mtg_cards_same_server(self):
        """MTG Cards läuft im selben Server: Wunschliste und Decks direkt, ohne Adresse/Token."""
        from mtgcards.scryfall import normalize_card
        from pm_fixtures import SOL
        mtg = self.srv.ctx
        mtg.wishlist.add(normalize_card(BOLT_M11), 2, 1.5, any_print=False)
        deck = mtg.decks.create("Izzet")
        mtg.decks.set_card(deck["id"], normalize_card(SOL), 1, "commander")
        self.assertTrue(self.call("GET", "/api/mtg/settings")["local"])
        self.assertIn("Izzet", [d["name"] for d in self.call("GET", "/api/mtg/decks")["decks"]])
        p = self.project("MTG")
        r = self.call("POST", f"/api/projects/{p['id']}/import-mtg", {"source": "wishlist"})
        self.assertEqual(r["added"], 2)
        self.assertEqual((r["project"]["items"][0]["set_code"], r["project"]["items"][0]["max_price_eur"]), ("M11", 1.5))
        # nur ausgewählte Wünsche
        sol_wish = mtg.wishlist.add(normalize_card(SOL), 1)
        p2 = self.project("Auswahl")
        r = self.call("POST", f"/api/projects/{p2['id']}/import-mtg", {"source": "wishlist", "ids": [sol_wish["id"]]})
        self.assertEqual([i["name"] for i in r["project"]["items"]], ["Sol Ring"])
        d = self.call("POST", "/api/projects", {"name": "Izzet", "kind": "deck", "mtg_deck_id": deck["id"]})["project"]
        self.assertEqual([(i["name"], i["board"]) for i in d["items"]], [("Sol Ring", "commander")])

    def test_web_ui_served(self):
        with urlopen(f"http://127.0.0.1:{self.srv.port}/proxies/") as r:
            self.assertIn(b"<title>Proxie Maker</title>", r.read())
        with urlopen(f"http://127.0.0.1:{self.srv.port}/proxies/editor.js") as r:
            self.assertIn(b"renderCard", r.read())
        with urlopen(f"http://127.0.0.1:{self.srv.port}/proxies") as r:     # Weiterleitung auf /proxies/
            self.assertTrue(r.url.endswith("/proxies/"))
        with urlopen(f"http://127.0.0.1:{self.srv.port}/start.html") as r:
            self.assertIn(b"Proxie Maker", r.read())
        with urlopen(f"http://127.0.0.1:{self.srv.port}/api/health") as r:
            self.assertEqual(json.loads(r.read())["app"], "mtg-cards")


if __name__ == "__main__":
    unittest.main()
