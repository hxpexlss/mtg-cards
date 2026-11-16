"""Scryfall-Limits: gesammeltes Nachschlagen von Decklisten und Pause nach „429 Too Many Requests“."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pm_fixtures import ALL, FakeScryfall, fake_fetch, fake_fetch_any  # noqa: E402

from mtgcards.scryfall import Scryfall, ScryfallError  # noqa: E402
from mtgcards.server import Server  # noqa: E402


class CountingScryfall(FakeScryfall):
    """Wie FakeScryfall, zählt aber Einzel-Suchen und kann Sammelabfragen."""

    def __init__(self):
        self.single = 0
        self.batches = 0

    def lookup(self, *a, **kw):
        self.single += 1
        return super().lookup(*a, **kw)

    def collection_identifiers(self, idents):
        self.batches += 1
        found, missing = [], []
        for i in idents:
            hit = [c for c in ALL if c["lang"] == "en" and (
                (i.get("name") and c["name"].split(" // ")[0].lower() == i["name"].lower()) or
                (i.get("collector_number") and c["set"] == i.get("set") and c["collector_number"] == i["collector_number"]))]
            (found.append(hit[0]) if hit else missing.append(i))
        return found, missing


class TestBatchImport(unittest.TestCase):
    def test_decklist_uses_collection(self):
        sf = CountingScryfall()
        srv = Server(os.path.join(tempfile.mkdtemp(), "r.db"), "T", bind="127.0.0.1", port=0, discovery=False,
                     scryfall=sf).start()
        srv.ctx.pm.image_fetcher, srv.ctx.pm.any_fetcher = fake_fetch, fake_fetch_any
        try:
            body = json.dumps({"name": "Deck", "kind": "deck",
                               "list": "4 Lightning Bolt\n1 Sol Ring (C21) 263\n1 Delver of Secrets\n1 Gibtsnicht"}).encode()
            req = Request(f"http://127.0.0.1:{srv.port}/proxies/api/projects", data=body, method="POST",
                          headers={"Authorization": "Bearer T", "Content-Type": "application/json"})
            with urlopen(req) as r:
                res = json.loads(r.read())
            names = sorted(i["name"] for i in res["project"]["items"])
            self.assertEqual(names, ["Delver of Secrets // Insectile Aberration", "Lightning Bolt", "Sol Ring"])
            self.assertEqual(len(res["errors"]), 1)          # nur „Gibtsnicht“
            self.assertEqual(sf.batches, 1)                  # eine Sammelabfrage für alles
            self.assertEqual(sf.single, 1)                   # nur der unbekannte Name einzeln
        finally:
            srv.stop()


class TooMany(BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        TooMany.hits += 1
        body = json.dumps({"details": "You are being rate-limited"}).encode()
        self.send_response(429)
        self.send_header("Retry-After", "30")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestCooldown(unittest.TestCase):
    def test_pause_after_429(self):
        api = ThreadingHTTPServer(("127.0.0.1", 0), TooMany)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            sf = Scryfall(base=f"http://127.0.0.1:{api.server_address[1]}", min_interval=0)
            with self.assertRaises(ScryfallError) as ctx:
                sf.named("Sol Ring")
            self.assertEqual(ctx.exception.status, 429)
            self.assertIn("Pause", str(ctx.exception))
            with self.assertRaises(ScryfallError):
                sf.named("Lightning Bolt")
            self.assertEqual(TooMany.hits, 1)                # während der Pause keine weiteren Anfragen
        finally:
            api.shutdown()


if __name__ == "__main__":
    unittest.main()
