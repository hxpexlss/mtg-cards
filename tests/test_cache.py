import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import KRAUM, SOL_RING  # noqa: E402

from mtgcards.scryfall import Scryfall, ScryfallError  # noqa: E402


class FakeApi(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeApi.hits.append(self.path)
        if self.path.startswith("/cards/named"):
            self._send(SOL_RING)
        else:
            self._send({"details": "nope"}, 404)

    def do_POST(self):
        FakeApi.hits.append(self.path)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ids = [i["id"] for i in body["identifiers"]]
        self._send({"data": [c for c in (SOL_RING, KRAUM) if c["id"] in ids]})


class TestScryfallCache(unittest.TestCase):
    def setUp(self):
        FakeApi.hits = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.cache = os.path.join(tempfile.mkdtemp(), "c.db")

    def tearDown(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except OSError:
            pass

    def test_disk_cache_and_offline_fallback(self):
        s1 = Scryfall(base=self.base, min_interval=0, cache_path=self.cache)
        self.assertEqual(s1.named("sol ring")["name"], "Sol Ring")
        self.assertEqual(s1.named("sol ring")["name"], "Sol Ring")
        self.assertEqual(len(FakeApi.hits), 1)                 # Speicher-Cache
        s2 = Scryfall(base=self.base, min_interval=0, cache_path=self.cache)
        s2.named("sol ring")
        self.assertEqual(len(FakeApi.hits), 1)                 # Festplatten-Cache
        self.httpd.shutdown()
        self.httpd.server_close()
        s3 = Scryfall(base=self.base, min_interval=0, cache_path=self.cache, cache_ttl=0, timeout=2)
        self.assertEqual(s3.named("sol ring")["name"], "Sol Ring")   # offline: veralteter Eintrag
        with self.assertRaises(ScryfallError):
            s3.named("unbekannt")

    def test_collection_batches(self):
        s = Scryfall(base=self.base, min_interval=0, cache_path=self.cache)
        ids = [SOL_RING["id"], KRAUM["id"]] + [f"x{i}" for i in range(100)]
        res = s.collection(ids)
        self.assertEqual(set(res), {SOL_RING["id"], KRAUM["id"]})
        self.assertEqual(FakeApi.hits, ["/cards/collection", "/cards/collection"])  # 102 IDs -> 2 Anfragen
        s.by_id(KRAUM["id"])                                    # aus Cache
        self.assertEqual(len(FakeApi.hits), 2)


if __name__ == "__main__":
    unittest.main()
