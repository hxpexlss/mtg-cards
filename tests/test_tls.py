import json
import os
import sys
import tempfile
import unittest
from urllib.request import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import FakeScryfall  # noqa: E402

from mtgcards import tls  # noqa: E402
from mtgcards.desktop import DesktopSettings  # noqa: E402
from mtgcards.server import Server, test_remote  # noqa: E402

TOKEN = "AAAA-BBBB-CCCC-DDDD"


class TestTls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cert = os.path.join(cls.tmp, "tls", "cert.pem")
        cls.key = os.path.join(cls.tmp, "tls", "key.pem")
        tls.ensure_self_signed(cls.cert, cls.key, ["100.64.1.2", "pc.example.ts.net"])
        cls.srv = Server(os.path.join(cls.tmp, "s.db"), TOKEN, bind="127.0.0.1", port=0, discovery=False,
                         scryfall=FakeScryfall(), tls_cert=cls.cert, tls_key=cls.key, local_http=True).start()
        cls.url = f"https://127.0.0.1:{cls.srv.port}"
        cls.fp = tls.fingerprint_file(cls.cert)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_fingerprint_and_pinning(self):
        self.assertEqual(len(tls.normalize_fp(self.fp)), 64)
        self.assertEqual(tls.fetch_fingerprint("127.0.0.1", self.srv.port), self.fp)
        with tls.urlopen(Request(self.url + "/api/health"), fingerprint=self.fp) as r:
            health = json.loads(r.read())
        self.assertTrue(health["tls"])
        with self.assertRaises(Exception):
            tls.urlopen(Request(self.url + "/api/health"), fingerprint="00" * 32).read()
        # unverschlüsselter Listener nur lokal (Desktop-Fenster)
        with tls.urlopen(f"http://127.0.0.1:{self.srv.local_port}/api/health") as r:
            self.assertEqual(json.loads(r.read())["app"], "mtg-cards")

    def test_trust_on_first_use(self):
        res = test_remote(self.url, TOKEN)
        self.assertTrue(res["needs_trust"])
        self.assertEqual(res["fingerprint"], self.fp)
        self.assertTrue(test_remote(self.url, TOKEN, self.fp)["ok"])
        self.assertIn("Token", test_remote(self.url, "falsch", self.fp)["error"])

    def test_desktop_proxy_over_tls(self):
        cfg = {"mode": "local", "token": "LOCA-LAAA-AAAA-AAAA", "db_path": os.path.join(self.tmp, "l.db"),
               "remote_url": "", "remote_token": "", "port": 0, "tls_cert": "", "tls_key": ""}
        settings = DesktopSettings(os.path.join(self.tmp, "cfg.json"), cfg)
        local = Server(cfg["db_path"], cfg["token"], bind="127.0.0.1", port=0, kind="desktop",
                       discovery=False, desktop=settings, scryfall=FakeScryfall()).start()
        settings.server = local
        try:
            res = settings.update({"mode": "remote", "remote_url": self.url, "remote_token": TOKEN})
            self.assertTrue(res.get("needs_trust"))
            res = settings.update({"mode": "remote", "remote_url": self.url, "remote_token": TOKEN,
                                   "remote_fingerprint": res["fingerprint"]})
            self.assertTrue(res["ok"], res)
            req = Request(f"http://127.0.0.1:{local.port}/api/cards", method="POST",
                          data=json.dumps({"name": "Sol Ring"}).encode(),
                          headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"})
            with tls.urlopen(req) as r:
                self.assertEqual(r.status, 201)
            self.assertEqual(self.srv.db.all()[0]["name"], "Sol Ring")
        finally:
            local.stop()


if __name__ == "__main__":
    unittest.main()
