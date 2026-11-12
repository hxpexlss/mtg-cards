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
                url, token, fp = desktop._local_server_login(srv.port)
            self.assertEqual(url, f"http://127.0.0.1:{srv.port}")
            self.assertEqual(token, "SERV-ERTO-KENA-AAAA")
            self.assertEqual(fp, "")
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

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography nicht installiert")
    def test_desktop_finds_local_https_server(self):
        tmp = tempfile.mkdtemp()
        cert, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")

        def no_openssl(*a, **k):
            raise FileNotFoundError("openssl")

        with mock.patch.object(subprocess, "run", no_openssl):
            tls.ensure_self_signed(cert, key)
        srv = Server(os.path.join(tmp, "s.db"), "SERV-ERTO-KENA-AAAA", bind="127.0.0.1", port=0,
                     discovery=False, scryfall=FakeScryfall(), tls_cert=cert, tls_key=key).start()
        cfg_path = os.path.join(tmp, "server.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"token": "SERV-ERTO-KENA-AAAA", "tls": True, "tls_cert": cert}, f)
        try:
            with mock.patch.object(config, "SERVER_CONFIG_PATH", cfg_path):
                url, token, fp = desktop._local_server_login(srv.port)
            self.assertEqual(url, f"https://127.0.0.1:{srv.port}")
            self.assertEqual(fp, tls.fingerprint_file(cert))
        finally:
            srv.stop()

    def test_points_to_self(self):
        self.assertTrue(desktop._points_to_self("http://127.0.0.1:8765", 8765))
        self.assertTrue(desktop._points_to_self("localhost:8765/", 8765))
        self.assertFalse(desktop._points_to_self("http://127.0.0.1:8765", 50123))
        self.assertFalse(desktop._points_to_self("http://192.168.1.5:8765", 8765))
        self.assertFalse(desktop._points_to_self("", 8765))

    def test_proxy_loop_is_stopped(self):
        """Server-Modus mit einer Adresse, die auf die Anwendung selbst zeigt: Fehler statt Endlosschleife."""
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        tmp = tempfile.mkdtemp()
        settings = desktop.DesktopSettings(os.path.join(tmp, "config.json"),
                                           {"token": "TOK", "port": 0, "db_path": os.path.join(tmp, "d.db")})
        srv = Server(os.path.join(tmp, "d.db"), "TOK", bind="127.0.0.1", port=0, kind="desktop", discovery=False,
                     desktop=settings, scryfall=FakeScryfall())
        settings.server = srv
        settings.cfg.update(mode="remote", remote_url=f"http://127.0.0.1:{srv.port}", remote_token="TOK")
        srv.start()
        try:
            req = Request(f"http://127.0.0.1:{srv.port}/api/stats", headers={"Authorization": "Bearer TOK"})
            with self.assertRaises(HTTPError) as cm:
                urlopen(req, timeout=20)
            self.assertEqual(cm.exception.code, 508)
            self.assertIn("Server-Adresse", json.loads(cm.exception.read().decode())["error"])
        finally:
            srv.stop()

    def test_port_cannot_be_taken_twice(self):
        """Auch unter Windows darf kein zweites Programm denselben Port belegen (SO_EXCLUSIVEADDRUSE)."""
        tmp = tempfile.mkdtemp()
        first = Server(os.path.join(tmp, "a.db"), "TOK", bind="0.0.0.0", port=0, discovery=False,
                       scryfall=FakeScryfall()).start()
        try:
            for bind in ("0.0.0.0", "127.0.0.1"):
                with self.assertRaises(OSError):
                    Server(os.path.join(tmp, "b.db"), "TOK", bind=bind, port=first.port, discovery=False,
                           scryfall=FakeScryfall())
        finally:
            first.stop()

    def test_no_console_window_flags(self):
        from mtgcards import netinfo
        if os.name == "nt":
            self.assertEqual(netinfo.NO_WINDOW, {"creationflags": subprocess.CREATE_NO_WINDOW})
        else:
            self.assertEqual(netinfo.NO_WINDOW, {})
        self.assertIsInstance(netinfo.local_addresses(), list)


if __name__ == "__main__":
    unittest.main()
