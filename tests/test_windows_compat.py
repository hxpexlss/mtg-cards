"""Teile, die vor allem für Windows gebraucht werden (laufen aber auf jedem System)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import FakeScryfall  # noqa: E402

from mtgcards import config, desktop, tls  # noqa: E402
from mtgcards.server import Server  # noqa: E402

try:
    import cryptography  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


class TestWindowsCompat(unittest.TestCase):
    def test_desktop_finds_local_server(self):
        tmp = tempfile.mkdtemp()
        srv = Server(os.path.join(tmp, "s.db"), "SERV-ERTO-KENA-AAAA", bind="127.0.0.1", port=0,
                     discovery=False, scryfall=FakeScryfall()).start()
        cfg_path = os.path.join(tmp, "server.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"token": "SERV-ERTO-KENA-AAAA"}, f)
        try:
            with mock.patch.object(config, "SERVER_CONFIG_PATH", cfg_path):
                url, token = desktop._local_server_login(srv.port)
            self.assertEqual(url, f"http://127.0.0.1:{srv.port}")
            self.assertEqual(token, "SERV-ERTO-KENA-AAAA")
            self.assertIsNone(desktop._local_server_login(1))   # nichts erreichbar
        finally:
            srv.stop()

    def test_config_save_without_chown(self):
        path = os.path.join(tempfile.mkdtemp(), "c.json")
        config.save(path, {"a": 1})
        saved = getattr(os, "chown", None)
        if saved is not None:
            del os.chown                      # wie unter Windows: os.chown existiert nicht
        try:
            config.save(path, {"a": 2})
        finally:
            if saved is not None:
                os.chown = saved
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["a"], 2)

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography nicht installiert")
    def test_certificate_without_openssl(self):
        d = tempfile.mkdtemp()

        def no_openssl(*a, **k):
            raise FileNotFoundError("openssl")

        with mock.patch.object(subprocess, "run", no_openssl):
            self.assertTrue(tls.ensure_self_signed(os.path.join(d, "c.pem"), os.path.join(d, "k.pem"),
                                                   ["100.64.1.2", "pc.example.ts.net"]))
        tls.server_context(os.path.join(d, "c.pem"), os.path.join(d, "k.pem"))
        self.assertEqual(len(tls.normalize_fp(tls.fingerprint_file(os.path.join(d, "c.pem")))), 64)


if __name__ == "__main__":
    unittest.main()
