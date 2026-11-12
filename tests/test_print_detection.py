"""Erkennung des richtigen Drucks (Edition) beim Scannen."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtgcards.scryfall import Scryfall, set_code_variants  # noqa: E402
from mtgcards.server import Server  # noqa: E402


def card(set_code, cn, lang="en", printed=None):
    return {"id": f"{set_code}-{cn}-{lang}", "oracle_id": "bolt", "name": "Lightning Bolt", "lang": lang,
            "printed_name": printed, "set": set_code, "set_name": set_code.upper(), "collector_number": cn,
            "type_line": "Instant", "oracle_text": "Deal 3 damage.", "color_identity": ["R"], "colors": ["R"],
            "keywords": [], "rarity": "common", "prices": {"eur": "1.00"}}


PRINTS = {("mh3", "123"): card("mh3", "123"), ("mic", "5"): card("mic", "5"), ("pip", "1"): card("pip", "1")}
FDN_DE = card("fdn", "77", "de", "Blitzschlag")


class FakeApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = u.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "cards" and parts[1] != "named":
            c = PRINTS.get((parts[1], parts[2]))
            return self.send(c) if c else self.send({"details": "nicht gefunden"}, 404)
        if u.path == "/cards/named":
            if "bolt" not in q.get("fuzzy", "").lower():
                return self.send({"details": "nicht gefunden"}, 404)
            s = q.get("set")
            if not s:
                return self.send(PRINTS[("pip", "1")])        # Standard-Druck = neuester Nachdruck
            hit = [c for (cs, _), c in PRINTS.items() if cs == s]
            return self.send(hit[0]) if hit else self.send({"details": "nicht in Edition"}, 404)
        if u.path == "/cards/search":
            if "Blitzschlag" in q.get("q", "") and "e:fdn" in q.get("q", ""):
                return self.send({"data": [FDN_DE]})
            return self.send({"details": "keine"}, 404)
        return self.send({"details": "?"}, 404)


class TestPrintDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        cls.sf = Scryfall(base=f"http://127.0.0.1:{cls.api.server_address[1]}", min_interval=0)

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()

    def test_variants(self):
        self.assertEqual(set_code_variants("M1C")[:2], ["M1C", "MIC"])
        self.assertEqual(set_code_variants("MH3"), ["MH3"])
        self.assertEqual(set_code_variants("F0N"), ["F0N", "FON"])

    def test_exact_with_ocr_fix(self):
        c = self.sf.lookup(name="Lightning Bolt", set_code="M1C", collector_number="005")   # "I" als "1" gelesen
        self.assertEqual((c["set"], c["collector_number"], c["_match"]), ("mic", "5", "exact"))

    def test_set_without_number(self):
        c = self.sf.lookup(name="Lightning Bolt", set_code="MH3")
        self.assertEqual((c["set"], c["_match"]), ("mh3", "set"))

    def test_preferred_set(self):
        c = self.sf.lookup(name="Lightning Bolt", prefer_set="MH3")
        self.assertEqual((c["set"], c["_match"]), ("mh3", "preferred"))
        c = self.sf.lookup(name="Lightning Bolt", prefer_set="XXX")       # Karte nicht in dieser Edition
        self.assertEqual((c["set"], c["_match"]), ("pip", "name"))

    def test_name_only_and_german_with_set(self):
        self.assertEqual(self.sf.lookup(name="Lightning Bolt")["_match"], "name")
        c = self.sf.lookup(name="Blitzschlag", set_code="FDN")
        self.assertEqual((c["set"], c["lang"], c["_match"]), ("fdn", "de", "set"))

    def test_api_reports_match(self):
        srv = Server(os.path.join(tempfile.mkdtemp(), "p.db"), "T", bind="127.0.0.1", port=0,
                     discovery=False, scryfall=self.sf).start()
        try:
            def get(q):
                with urlopen(Request(f"http://127.0.0.1:{srv.port}/api/lookup?{q}",
                                     headers={"Authorization": "Bearer T"})) as r:
                    return json.loads(r.read())
            self.assertEqual(get("name=Lightning%20Bolt&set=MH3&cn=123")["match"], "exact")
            self.assertEqual(get("name=Lightning%20Bolt&prefer_set=MH3")["match"], "preferred")
            self.assertEqual(get("name=Lightning%20Bolt")["match"], "name")
            self.assertEqual(get("set=M1C&cn=005")["set_code"], "MIC")            # Code-Modus, ohne Namen
            req = Request(f"http://127.0.0.1:{srv.port}/api/cards", method="POST",
                          data=json.dumps({"set": "MH3", "cn": "123", "quantity": 2}).encode(),
                          headers={"Authorization": "Bearer T", "Content-Type": "application/json"})
            with urlopen(req) as r:
                row = json.loads(r.read())
            self.assertEqual((row["set_code"], row["collector_number"], row["quantity"]), ("MH3", "123", 2))
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
