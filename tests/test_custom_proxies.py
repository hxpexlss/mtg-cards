"""Eigene Proxies (Upload, Druck, Export) und Druck-Auswahl in der Wunschliste."""

import base64
import json
import os
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, ATRAXA_DE, FakeScryfall  # noqa: E402

from mtgcards.customproxies import CustomProxies, CustomProxyError  # noqa: E402
from mtgcards.db import Database  # noqa: E402
from mtgcards.importexport import export_json, import_cards  # noqa: E402
from mtgcards.server import Server  # noqa: E402

# Kleinstes gültiges JPEG (1x1 Pixel, grau)
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////"
    "////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")


class TestCustomProxyStore(unittest.TestCase):
    def test_add_list_update_delete(self):
        db = Database(":memory:")
        store = CustomProxies(db)
        p = store.add("Mein Fun-Drache", "data:image/jpeg;base64," + base64.b64encode(JPEG).decode(), 2, "Alter")
        self.assertEqual((p["name"], p["quantity"], p["width"], p["height"]), ("Mein Fun-Drache", 2, 1, 1))
        self.assertEqual(store.image(p["id"]), JPEG)
        self.assertEqual(store.list()["copies"], 2)
        self.assertEqual(store.update(p["id"], {"quantity": 3, "name": "Drache"})["quantity"], 3)
        self.assertEqual(len(store.entries()), 3)
        self.assertEqual(len(store.entries(one=True)), 1)
        self.assertTrue(store.delete(p["id"]))
        self.assertEqual(store.list()["items"], [])

    def test_rejects_non_jpeg(self):
        store = CustomProxies(Database(":memory:"))
        with self.assertRaises(CustomProxyError):
            store.add("PNG", base64.b64encode(b"\x89PNG\r\n\x1a\n....").decode())
        with self.assertRaises(CustomProxyError):
            store.add("", base64.b64encode(JPEG).decode())

    def test_export_import_roundtrip(self):
        db = Database(":memory:")
        CustomProxies(db).add("Fun", JPEG, 4)
        data = export_json(db)
        other = Database(":memory:")
        res = import_cards(other, FakeScryfall(), data, mode="add")
        self.assertEqual(res["custom_proxies"], 1)
        items = CustomProxies(other).list()["items"]
        self.assertEqual((items[0]["name"], items[0]["quantity"]), ("Fun", 4))
        # erneut ergänzen -> nicht doppelt
        self.assertEqual(import_cards(other, FakeScryfall(), data, mode="add")["custom_proxies"], 0)


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(os.path.join(tempfile.mkdtemp(), "c.db"), "T", bind="127.0.0.1", port=0,
                         discovery=False, scryfall=FakeScryfall()).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def call(self, method, path, body=None, raw=False):
        req = Request(f"http://127.0.0.1:{self.srv.port}{path}", method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer T", "Content-Type": "application/json"})
        with urlopen(req) as r:
            data = r.read()
            return data if raw else json.loads(data)

    def test_custom_proxy_api_and_pdf(self):
        p = self.call("POST", "/api/custom-proxies", {"name": "Fun", "image": base64.b64encode(JPEG).decode(),
                                                      "quantity": 2})
        self.assertEqual(self.call("GET", f"/api/custom-proxies/{p['id']}/image", raw=True), JPEG)
        pdf = self.call("GET", f"/api/custom-proxies/proxies.pdf?ids={p['id']}", raw=True)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(pdf.count(b"/Subtype /Image"), 1)          # gleiches Bild nur einmal eingebettet
        self.assertEqual(self.call("PATCH", f"/api/custom-proxies/{p['id']}", {"quantity": 5})["quantity"], 5)
        with self.assertRaises(HTTPError) as ctx:
            self.call("POST", "/api/custom-proxies", {"name": "x", "image": "bm9wZQ=="})
        self.assertEqual(ctx.exception.code, 400)
        self.call("DELETE", f"/api/custom-proxies/{p['id']}")

    def test_wishlist_choose_print_and_back(self):
        w = self.call("POST", "/api/wishlist", {"name": "Atraxa, Praetors' Voice"})
        self.assertTrue(w["any_print"])
        w = self.call("PATCH", f"/api/wishlist/{w['id']}", {"scryfall_id": ATRAXA_DE["id"]})
        self.assertEqual((w["any_print"], w["scryfall_id"], w["set_code"], w["collector_number"]),
                         (False, ATRAXA_DE["id"], "C16", "28"))
        self.assertEqual(w["price_eur"], 12.5)
        w = self.call("PATCH", f"/api/wishlist/{w['id']}", {"any_print": True})
        self.assertTrue(w["any_print"])
        with self.assertRaises(HTTPError) as ctx:          # Druck einer anderen Karte
            self.call("PATCH", f"/api/wishlist/{w['id']}", {"scryfall_id": "solring-id"})
        self.assertEqual(ctx.exception.code, 400)
        self.call("DELETE", f"/api/wishlist/{w['id']}")


if __name__ == "__main__":
    unittest.main()
