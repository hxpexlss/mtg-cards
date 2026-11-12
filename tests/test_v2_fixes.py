"""Tests für die Fehlerkorrekturen in Version 2.0.0."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, KRAUM, LURRUS, SOL_RING, FakeScryfall  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.decks import DeckStore  # noqa: E402
from mtgcards.importexport import ImportAborted, export_json, import_cards  # noqa: E402
from mtgcards.scryfall import Scryfall, ScryfallError, normalize_card  # noqa: E402
from mtgcards.server import Server  # noqa: E402
from mtgcards.wishlist import Wishlist  # noqa: E402


class OfflineScryfall(FakeScryfall):
    def lookup(self, **kw):
        raise ScryfallError("Scryfall nicht erreichbar", 503)


class TestImportReplaceIsSafe(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.add(normalize_card(ATRAXA))
        self.db.add(normalize_card(SOL_RING), quantity=2)

    def tearDown(self):
        self.db.close()

    def test_unusable_file_does_not_wipe_collection(self):
        with self.assertRaises(ImportAborted):
            import_cards(self.db, FakeScryfall(), "Foo;Bar\n1;2\n", mode="replace")
        with self.assertRaises(ImportAborted):
            import_cards(self.db, FakeScryfall(), "{}", mode="replace")
        self.assertEqual(len(self.db.all()), 2)

    def test_offline_does_not_wipe_collection(self):
        with self.assertRaises(ImportAborted) as cm:
            import_cards(self.db, OfflineScryfall(), "Name,Count\nSol Ring,1\n", mode="replace")
        self.assertIn("NICHT verändert", str(cm.exception))
        self.assertEqual(sum(c["quantity"] for c in self.db.all()), 3)

    def test_unknown_card_aborts_replace_but_not_add(self):
        text = "Name,Count\nSol Ring,1\nGibtsnicht Karte,1\n"
        with self.assertRaises(ImportAborted):
            import_cards(self.db, FakeScryfall(), text, mode="replace")
        self.assertEqual(len(self.db.all()), 2)
        res = import_cards(self.db, FakeScryfall(), text, mode="add")
        self.assertEqual((res["imported"], len(res["errors"])), (1, 1))

    def test_replace_works_and_is_one_transaction(self):
        DeckStore(self.db).create("Altes Deck")
        other = Database(":memory:")
        other.add(normalize_card(KRAUM), quantity=3, tags=["Tauschbörse"])
        store = DeckStore(other)
        deck = store.create("Neues Deck")
        store.set_card(deck["id"], normalize_card(KRAUM), 1, "commander")
        Wishlist(other).add(normalize_card(LURRUS), 2, 1.5)
        dump = export_json(other)
        res = import_cards(self.db, FakeScryfall(), dump, mode="replace")
        self.assertEqual((res["imported"], res["decks"], res["wishlist"]), (3, 1, 1))
        self.assertEqual([c["name"] for c in self.db.all()], ["Kraum, Ludevic's Opus"])
        self.assertEqual([d["name"] for d in DeckStore(self.db).list()], ["Neues Deck"])
        # kaputte Wunschliste -> alles wird zurückgerollt, auch Karten und Decks
        broken = json.loads(dump)
        broken["cards"][0]["name"] = "Andere Karte"
        broken["wishlist"] = [{"name": "X", "max_price_eur": {"kaputt": 1}}]
        with self.assertRaises(Exception):
            import_cards(self.db, FakeScryfall(), json.dumps(broken), mode="replace")
        self.assertEqual([c["name"] for c in self.db.all()], ["Kraum, Ludevic's Opus"])
        self.assertEqual([d["name"] for d in DeckStore(self.db).list()], ["Neues Deck"])


class TestTags(unittest.TestCase):
    def test_umlaut_tags_are_searchable(self):
        db = Database(":memory:")
        db.add(normalize_card(ATRAXA), tags=["Tauschbörse"])
        db.add(normalize_card(SOL_RING), tags=["100%", "Deck: Atraxa"])
        self.assertEqual(db.search(tag="Tauschbörse")[1], 1)
        self.assertEqual(db.search(tag="tauschbörse")[1], 1)
        self.assertEqual(db.search(q="Tauschbörse")[1], 1)
        self.assertEqual(db.search(tag="Tausch")[1], 0)           # exakter Tag, kein Teiltreffer
        self.assertEqual(db.search(tag="%")[1], 0)                # Platzhalter werden wörtlich genommen
        self.assertEqual(db.search(tag="100%")[1], 1)
        self.assertEqual(db.search(q="100%")[1], 1)
        self.assertEqual(db.search(q="_ommander")[1], 0)
        db.close()

    def test_old_databases_are_migrated(self):
        path = os.path.join(tempfile.mkdtemp(), "cards.db")
        db = Database(path)
        row, _ = db.add(normalize_card(ATRAXA))
        db.conn.execute("UPDATE cards SET tags=? WHERE id=?", (json.dumps(["Commander", "Tauschbörse"]), row["id"]))
        db.conn.execute("DELETE FROM meta WHERE key='tags_utf8_v1'")
        db.conn.commit()
        self.assertEqual(db.search(q="Tauschbörse")[1], 0)        # so sah der Fehler aus
        db.close()
        db = Database(path)
        self.assertEqual(db.search(tag="Tauschbörse")[1], 1)
        self.assertEqual(db.search(q="Tauschbörse")[1], 1)
        self.assertEqual(db.get(row["id"])["tags"], ["Commander", "Tauschbörse"])
        db.close()


class CountingScryfall(Scryfall):
    """Scryfall-Client ohne Netz: zählt Anfragen, Preis lässt sich ändern."""

    def __init__(self):
        super().__init__(min_interval=0)
        self.price = "1.00"
        self.requests = []
        self.pages = 1

    def _request(self, url, body=None):
        self.requests.append(url)
        card = dict(SOL_RING, prices={"eur": self.price})
        if "/cards/search" in url or "page=" in url:
            page = int(url.split("page=")[1].split("&")[0]) if "page=" in url else 1
            more = page < self.pages
            return {"data": [dict(card, id=f"p{page}", set=f"s{page}")], "has_more": more,
                    "next_page": f"{self.base}/cards/search?next=1&page={page + 1}" if more else None}
        return card


class TestFreshPrices(unittest.TestCase):
    def test_single_refresh_bypasses_cache(self):
        s = CountingScryfall()
        self.assertEqual(s.lookup(scryfall_id="solring-id")["prices"]["eur"], "1.00")
        s.price = "5.00"
        self.assertEqual(s.lookup(scryfall_id="solring-id")["prices"]["eur"], "1.00")   # normal: Cache
        self.assertEqual(s.fresh_card("solring-id")["prices"]["eur"], "5.00")            # Aktualisieren: neu
        self.assertEqual(s.lookup(scryfall_id="solring-id")["prices"]["eur"], "5.00")   # Cache ist jetzt aktuell

    def test_offline_falls_back_to_cached_card(self):
        s = CountingScryfall()
        s.lookup(scryfall_id="solring-id")

        def offline(url, body=None):
            raise ScryfallError("offline", 503)
        s._request = offline
        self.assertEqual(s.fresh_card("solring-id")["prices"]["eur"], "1.00")

    def test_wishlist_prices_use_max_age_and_all_pages(self):
        s = CountingScryfall()
        s.pages = 3
        self.assertEqual([p["id"] for p in s.prints("Sol Ring")], ["p1", "p2", "p3"])
        n = len(s.requests)
        s.prints("Sol Ring")
        self.assertEqual(len(s.requests), n)                       # aus dem Cache
        s.prints("Sol Ring", max_age=0)
        self.assertEqual(len(s.requests), n + 3)                   # für Preise neu geladen

        db = Database(":memory:")
        wl = Wishlist(db)
        wl.add(normalize_card(SOL_RING), 1, 2.0, price=9.0)
        s.price = "1.50"
        import mtgcards.wishlist as wmod
        old, wmod.PRICE_MAX_AGE = wmod.PRICE_MAX_AGE, 0
        try:
            wl.refresh_prices(s)
        finally:
            wmod.PRICE_MAX_AGE = old
        item = wl.list()["items"][0]
        self.assertEqual(item["price_eur"], 1.5)
        self.assertTrue(item["target_reached"])
        db.close()


class TestServerFixes(unittest.TestCase):
    def setUp(self):
        self.sf = FakeScryfall()
        self.sf.sets = lambda: []
        self.srv = Server(":memory:", "TOK", bind="127.0.0.1", port=0, discovery=False, scryfall=self.sf).start()

    def tearDown(self):
        self.srv.stop()

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = Request(f"http://127.0.0.1:{self.srv.port}{path}", method=method, data=data,
                      headers={"Authorization": "Bearer TOK", "Content-Type": "application/json"})
        try:
            with urlopen(req) as r:
                text = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(text) if text.startswith(("{", "[")) else text)
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_bad_input_is_400_not_500(self):
        self.assertEqual(self.call("POST", "/api/cards", {"name": "Sol Ring"})[0], 201)
        for method, path, body in [
            ("GET", "/api/cards?limit=abc", None),
            ("GET", "/api/cards?dup_min=x", None),
            ("PATCH", "/api/cards/1", {"quantity": "x"}),
            ("POST", "/api/cards", {"name": "Sol Ring", "quantity": "viele"}),
            ("POST", "/api/cards", {"name": "Sol Ring", "tags": 5}),
            ("POST", "/api/cards", ["Sol Ring"]),
            ("POST", "/api/cards/batch", {"cards": "Sol Ring"}),
            ("POST", "/api/wishlist", {"name": "Sol Ring", "quantity": "x"}),
            ("POST", "/api/wishlist/bulk", {"scryfall_ids": "abc"}),
        ]:
            status, res = self.call(method, path, body)
            self.assertEqual(status, 400, (method, path, res))
        # einzelne kaputte Einträge im Stapel brechen den Rest nicht ab
        status, res = self.call("POST", "/api/cards/batch", {"cards": ["Sol Ring", {"name": "Sol Ring", "quantity": 2}]})
        self.assertEqual((status, res["added"], len(res["errors"])), (200, 2, 1))

    def test_negative_quantity_is_clamped(self):
        status, res = self.call("POST", "/api/cards", {"name": "Sol Ring", "quantity": -5})
        self.assertEqual((status, res["quantity"]), (201, 1))

    def test_sets_with_missing_collector_number(self):
        self.srv.db.conn.execute("INSERT INTO cards(name, set_code, quantity, tags) VALUES('X', 'ABC', 1, '[]')")
        self.srv.db.conn.commit()
        status, res = self.call("GET", "/api/sets")
        self.assertEqual(status, 200)
        self.assertEqual(res["sets"][0]["code"], "ABC")

    def test_deck_with_unreadable_list_is_not_created(self):
        status, res = self.call("POST", "/api/decks", {"name": "X", "list": "// nur ein Kommentar"})
        self.assertEqual(status, 400)
        self.assertIn("nicht angelegt", res["error"])
        self.assertEqual(self.call("GET", "/api/decks")[1]["decks"], [])
        status, res = self.call("POST", "/api/decks", {"name": "Y", "list": "1 Sol Ring\n1 Gibtsnicht Karte"})
        self.assertEqual((status, len(res["errors"])), (201, 1))

    def test_deck_is_removed_when_scryfall_fails(self):
        def boom(identifiers):
            raise ScryfallError("Scryfall nicht erreichbar", 503)
        self.sf.collection_identifiers = boom
        status, _ = self.call("POST", "/api/decks", {"name": "X", "list": "1 Sol Ring"})
        self.assertEqual(status, 503)
        self.assertEqual(self.call("GET", "/api/decks")[1]["decks"], [])

    def test_companion_counts_for_wishlist_and_proxies(self):
        _, res = self.call("POST", "/api/decks", {"name": "D", "list": "Companion\n1 Lurrus of the Dream-Den\n\nDeck\n1 Sol Ring"})
        did = res["deck"]["id"]
        self.assertEqual(res["deck"]["stats"]["missing"], 2)
        _, res = self.call("POST", f"/api/decks/{did}/to-wishlist")
        self.assertEqual(sorted(res["added"]), ["Lurrus of the Dream-Den", "Sol Ring"])
        seen = []
        self.srv.ctx.image_fetcher = lambda url, cache_dir=None: seen.append(url)
        self.call("GET", f"/api/decks/{did}/proxies.pdf")
        self.assertEqual(len(seen), 2)

    def test_request_id_prevents_double_add(self):
        body = {"name": "Sol Ring", "quantity": 2, "request_id": "scan-1"}
        status, first = self.call("POST", "/api/cards", body)
        self.assertEqual((status, first["quantity"]), (201, 2))
        status, again = self.call("POST", "/api/cards", body)            # App wiederholt nach Timeout
        self.assertEqual((status, again["quantity"], again["repeated"]), (200, 2, True))
        self.assertEqual(self.srv.db.get(first["id"])["quantity"], 2)
        status, other = self.call("POST", "/api/cards", dict(body, request_id="scan-2"))
        self.assertEqual(other["quantity"], 4)
        batch = {"cards": [{"name": "Atraxa", "quantity": 1}], "request_id": "stapel-1"}
        self.call("POST", "/api/cards/batch", batch)
        _, res = self.call("POST", "/api/cards/batch", batch)
        self.assertTrue(res["repeated"])
        self.assertEqual(self.call("GET", "/api/cards?q=Atraxa")[1]["cards"][0]["quantity"], 1)

    def test_import_replace_error_reaches_client(self):
        self.call("POST", "/api/cards", {"name": "Sol Ring"})
        status, res = self.call("POST", "/api/import?mode=replace", raw=b"Foo;Bar\n1;2\n")
        self.assertEqual(status, 400)
        self.assertIn("NICHT verändert", res["error"])
        self.assertEqual(self.call("GET", "/api/cards")[1]["total"], 1)

    def test_refresh_uses_fresh_prices(self):
        _, card = self.call("POST", "/api/cards", {"name": "Sol Ring"})
        self.sf.fresh_card = lambda sid: dict(SOL_RING, prices={"eur": "7.77"})
        _, res = self.call("POST", f"/api/cards/{card['id']}/refresh")
        self.assertEqual(res["price_eur"], "7.77")


class TestTlsMessage(unittest.TestCase):
    def test_fingerprint_in_error_is_the_real_one(self):
        import inspect
        from mtgcards import tls
        src = inspect.getsource(tls._PinnedHTTPSConnection.connect)
        self.assertNotIn("bytes.fromhex", src)      # früher: Fingerabdruck wurde ein zweites Mal gehasht
        self.assertEqual(tls.normalize_fp("aa:bb cc"), "AABBCC")


if __name__ == "__main__":
    unittest.main()
