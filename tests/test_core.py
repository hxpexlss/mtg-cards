import json
import os
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import ATRAXA, ATRAXA_DE, DFC, KRAUM, LURRUS, SOL_RING, FakeScryfall  # noqa: E402

from mtgcards.db import Database  # noqa: E402
from mtgcards.importexport import export_csv, export_json, import_cards  # noqa: E402
from mtgcards.scryfall import normalize_card  # noqa: E402
from mtgcards.server import Server  # noqa: E402


class TestNormalizeAndTags(unittest.TestCase):
    def test_commander(self):
        c = normalize_card(ATRAXA)
        self.assertEqual(c["color_identity"], "WUBG")
        self.assertEqual(c["auto_tags"], ["Commander"])
        self.assertIn("proliferate", c["oracle_text"])
        self.assertEqual(c["set_code"], "C16")

    def test_partner(self):
        self.assertEqual(normalize_card(KRAUM)["auto_tags"], ["Commander", "Partner"])

    def test_companion(self):
        self.assertEqual(normalize_card(LURRUS)["auto_tags"], ["Commander", "Companion"])

    def test_no_tags(self):
        c = normalize_card(SOL_RING)
        self.assertEqual(c["auto_tags"], [])
        self.assertEqual(c["color_identity"], "")

    def test_dfc_back_face_not_commander(self):
        c = normalize_card(DFC)
        self.assertEqual(c["auto_tags"], [])  # Vorderseite ist ein Land
        self.assertIn("Ormendahl", c["oracle_text"])
        self.assertEqual(c["image_url"], "front.jpg")
        self.assertEqual(c["power"], "9")

    def test_german_printed_name(self):
        self.assertEqual(normalize_card(ATRAXA_DE)["printed_name"], "Atraxa, Stimme der Prätoren")

    def test_text_only_partner_with(self):
        from mtgcards.tags import auto_tags
        card = {"type_line": "Legendary Creature — Human", "keywords": [],
                "oracle_text": "Partner with Pir, Imaginative Rascal (When this ...)"}
        self.assertEqual(auto_tags(card), ["Commander", "Partner"])
        card = {"type_line": "Legendary Planeswalker — Teferi", "keywords": [],
                "oracle_text": "Teferi can be your commander."}
        self.assertEqual(auto_tags(card), ["Commander"])


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def test_add_merges_quantity(self):
        c = normalize_card(ATRAXA)
        row, created = self.db.add(c, quantity=1)
        self.assertTrue(created)
        row, created = self.db.add(c, quantity=2, tags=["Deck A"])
        self.assertFalse(created)
        self.assertEqual(row["quantity"], 3)
        self.assertEqual(row["tags"], ["Commander", "Deck A"])
        row2, created = self.db.add(c, foil=True)
        self.assertTrue(created)
        self.assertEqual(self.db.find_owned(c["scryfall_id"], c["oracle_id"])["this_print"], 4)

    def test_search_filters(self):
        for raw in (ATRAXA, KRAUM, LURRUS, SOL_RING):
            self.db.add(normalize_card(raw))
        names = lambda res: sorted(c["name"] for c in res[0])  # noqa: E731
        self.assertEqual(names(self.db.search(tag="Partner")), ["Kraum, Ludevic's Opus"])
        self.assertEqual(names(self.db.search(q="proliferate")), ["Atraxa, Praetors' Voice"])
        # passt in Esper/Weiß-Schwarz Deck: Lurrus + Sol Ring
        self.assertEqual(names(self.db.search(ci="WB")), ["Lurrus of the Dream-Den", "Sol Ring"])
        self.assertEqual(names(self.db.search(ci="UR", ci_mode="exact")), ["Kraum, Ludevic's Opus"])
        self.assertEqual(names(self.db.search(ci="C", ci_mode="within")), ["Sol Ring"])
        self.assertEqual(len(self.db.search(type_="Legendary")[0]), 3)

    def test_update_and_foil_merge(self):
        c = normalize_card(SOL_RING)
        a, _ = self.db.add(c, quantity=2)
        b, _ = self.db.add(c, foil=True, quantity=1)
        merged = self.db.update(b["id"], {"foil": False})
        self.assertEqual(merged["id"], a["id"])
        self.assertEqual(merged["quantity"], 3)
        self.assertTrue(self.db.update(a["id"], {"quantity": 0})["deleted"])
        self.assertEqual(self.db.all(), [])

    def test_export_import_roundtrip(self):
        for raw in (ATRAXA, KRAUM, DFC):
            self.db.add(normalize_card(raw), quantity=2, tags=["Mein Tag"], notes="x")
        data = export_json(self.db)
        other = Database(":memory:")
        fake = FakeScryfall()
        res = import_cards(other, fake, data)
        self.assertEqual(res["imported"], 6)
        self.assertEqual(fake.calls, 0)  # vollständige Daten -> kein Scryfall nötig
        self.assertEqual([c["name"] for c in other.all()], [c["name"] for c in self.db.all()])
        self.assertEqual(other.all()[0]["tags"], self.db.all()[0]["tags"])
        # CSV-Roundtrip mit replace
        csv_data = export_csv(self.db)
        res = import_cards(other, fake, csv_data, mode="replace")
        self.assertEqual(sum(c["quantity"] for c in other.all()), 6)
        self.assertEqual(fake.calls, 0)

    def test_import_foreign_csv(self):
        csv_data = "Count,Name,Edition,Card Number,Foil\n2,Sol Ring,C21,263,\n1,Kraum,,,foil\n1,Gibtsnicht,,,\n"
        res = import_cards(self.db, FakeScryfall(), csv_data)
        self.assertEqual(res["imported"], 3)
        self.assertEqual(len(res["errors"]), 1)
        kraum = self.db.search(q="Kraum")[0][0]
        self.assertTrue(kraum["foil"])
        self.assertIn("Partner", kraum["tags"])


class TestHttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.srv = Server(os.path.join(cls.tmp, "t.db"), "ABCD-EFGH-JKLM-NPQR", bind="127.0.0.1",
                         port=0, discovery=False, scryfall=FakeScryfall()).start()
        cls.base = f"http://127.0.0.1:{cls.srv.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def call(self, path, method="GET", data=None, token="abcd-efgh-jklm-nprq".upper(), raw=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        if raw is not None:
            body = raw.encode()
        req = Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urlopen(req) as r:
                txt = r.read().decode()
                return r.status, (json.loads(txt) if "json" in r.headers.get("Content-Type", "") else txt)
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_flow(self):
        tok = "ABCD-EFGH-JKLM-NPQR"
        self.assertEqual(self.call("/api/health", token=None)[1]["app"], "mtg-cards")
        self.assertEqual(self.call("/api/cards", token=None)[0], 401)
        self.assertEqual(self.call("/api/cards", token="falsch")[0], 401)
        self.assertEqual(self.call("/api/cards", token=tok.lower())[0], 200)  # Groß/klein egal

        st, card = self.call("/api/lookup?name=atraxa%20praetors%20voice", token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(card["owned"]["this_print"], 0)
        self.assertEqual(card["auto_tags"], ["Commander"])

        st, row = self.call("/api/cards", "POST", {"name": "Atraxa", "quantity": 2}, token=tok)
        self.assertEqual(st, 201)
        st, row = self.call("/api/cards", "POST", {"scryfall_id": ATRAXA["id"]}, token=tok)
        self.assertEqual((st, row["quantity"]), (200, 3))
        # Scan mit Set + Nummer, aber falsch erkanntem Namen -> Fallback greift trotzdem
        st, row = self.call("/api/cards", "POST", {"name": "Kraum Ludevics Opus", "set": "C16", "cn": "036"},
                            token=tok)
        self.assertEqual(row["name"], "Kraum, Ludevic's Opus")
        self.assertEqual(self.call("/api/cards", "POST", {"name": "xyzxyz"}, token=tok)[0], 404)

        st, lst = self.call("/api/cards?tag=Commander&sort=name", token=tok)
        self.assertEqual(lst["total"], 2)
        st, lst = self.call("/api/cards?q=haste", token=tok)
        self.assertEqual([c["name"] for c in lst["cards"]], ["Kraum, Ludevic's Opus"])

        cid = lst["cards"][0]["id"]
        st, upd = self.call(f"/api/cards/{cid}", "PATCH", {"tags": ["Partner", "Commander", "Trade"]}, token=tok)
        self.assertEqual(upd["tags"], ["Partner", "Commander", "Trade"])
        self.assertEqual(self.call("/api/tags", token=tok)[1]["tags"]["Commander"], 4)

        st, exp = self.call("/api/export?format=json&token=" + tok, token=None)
        self.assertEqual(st, 200)
        self.assertEqual(len(exp["cards"]), 2)
        st, res = self.call("/api/import?mode=replace", "POST", raw=json.dumps(exp), token=tok)
        self.assertEqual(res["imported"], 4)

        rev = self.call("/api/revision", token=tok)[1]["revision"]
        self.assertEqual(self.call(f"/api/cards/{cid}", "DELETE", token=tok)[0], 404)  # nach replace neue IDs
        st, lst = self.call("/api/cards", token=tok)
        self.assertEqual(self.call(f"/api/cards/{lst['cards'][0]['id']}", "DELETE", token=tok)[0], 200)
        self.assertGreater(self.call("/api/revision", token=tok)[1]["revision"], rev)

        st, res = self.call("/api/refresh-all", "POST", token=tok)
        self.assertEqual(res["missing"], 0)
        self.assertEqual(self.call("/api/cards", token=tok)[1]["cards"][0]["price_eur"], "99.00")

        st, res = self.call("/api/decks", "POST", {"name": "Kraum", "list": "Commander\n1 Kraum, Ludevic's Opus\n1 Sol Ring"}, token=tok)
        self.assertEqual(st, 201)
        did = res["deck"]["id"]
        st, deck = self.call(f"/api/decks/{did}/cards", "POST", {"name": "Atraxa", "board": "main"}, token=tok)
        self.assertEqual(deck["stats"]["outside_identity"], 1)
        st, txt = self.call(f"/api/decks/{did}/export?missing=1", token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(len(self.call("/api/decks", token=tok)[1]["decks"]), 1)
        dc = deck["cards"][0]["id"]
        self.assertEqual(self.call(f"/api/deck-cards/{dc}", "DELETE", token=tok)[0], 200)
        self.assertEqual(self.call(f"/api/decks/{did}", "DELETE", token=tok)[0], 200)

        st, html = self.call("/", token=None)
        self.assertIn("MTG Cards", html)
        st, ac = self.call("/api/autocomplete?q=sol", token=tok)
        self.assertEqual(ac["data"], ["Sol Ring"])


class TestDesktopProxy(unittest.TestCase):
    def test_remote_mode_proxies(self):
        from mtgcards.desktop import DesktopSettings
        tmp = tempfile.mkdtemp()
        remote = Server(os.path.join(tmp, "r.db"), "REMO-TETO-KENA-AAAA", bind="127.0.0.1", port=0,
                        discovery=False, scryfall=FakeScryfall()).start()
        cfg = {"mode": "local", "token": "LOCA-LTOK-ENAA-AAAA", "port": 0, "db_path": os.path.join(tmp, "l.db"),
               "remote_url": "", "remote_token": ""}
        settings = DesktopSettings(os.path.join(tmp, "cfg.json"), cfg)
        local = Server(cfg["db_path"], cfg["token"], bind="127.0.0.1", port=0, kind="desktop",
                       discovery=False, desktop=settings, scryfall=FakeScryfall()).start()
        settings.server = local
        try:
            res = settings.update({"mode": "remote", "remote_url": f"127.0.0.1:{remote.port}",
                                   "remote_token": "falsch"})
            self.assertFalse(res["ok"])
            res = settings.update({"mode": "remote", "remote_url": f"127.0.0.1:{remote.port}",
                                   "remote_token": "REMO-TETO-KENA-AAAA"})
            self.assertTrue(res["ok"], res)
            req = Request(f"http://127.0.0.1:{local.port}/api/cards", method="POST",
                          data=json.dumps({"name": "Sol Ring"}).encode(),
                          headers={"Authorization": "Bearer LOCA-LTOK-ENAA-AAAA",
                                   "Content-Type": "application/json"})
            with urlopen(req) as r:
                self.assertEqual(r.status, 201)
            self.assertEqual(len(remote.db.all()), 1)   # landet auf dem Server
            self.assertEqual(len(local.db.all()), 0)
            settings.update({"mode": "local"})
            self.assertIsNone(local.ctx.remote())
        finally:
            local.stop()
            remote.stop()


if __name__ == "__main__":
    unittest.main()
