import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixtures import FakeScryfall  # noqa: E402

from mtgcards import proxies  # noqa: E402
from mtgcards.server import Server  # noqa: E402

# kleines echtes JPEG (32x44) als Kartenbild-Ersatz
JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAsACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDCUafaaRZT3Gn/AGiS48zLecyY2tjtUX27Sf8AoC/+TT0X/wDyAdJ/7bf+hCsutqVJTTlJvd9X3fmayk07Ly6Lsan27Sf+gL/5NPUrDT7vSL2e30/7PJb+XhvOZ87mx3rGrUsP+QDq3/bH/wBCNFWkoJSi3uur7rzCMm3Z+fRdgv8A/kA6T/22/wDQhWXWpf8A/IB0n/tt/wChCsutMP8AA/WX5smpv8l+QVqWH/IB1b/tj/6Eay61LD/kA6t/2x/9CNGI+BesfzQU9/k/yC//AOQDpP8A22/9CFZdX7bWdQtLdYLe42RpnC7FOMnPcVL/AMJDq3/P3/5DT/CogqsE0knq+r6u/YbcHrf8P+CZdalh/wAgHVv+2P8A6EaP+Eh1b/n7/wDIaf4VFc6zqF3btBcXG+N8ZXYozg57CiaqzSTSWq6vo79gTgtb/h/wT//Z")
TOK = "PROX-AAAA-BBBB-CCCC"


def fake_fetch(url, cache_dir=None):
    return JPEG


class TestProxyPdf(unittest.TestCase):
    def test_jpeg_info(self):
        self.assertEqual(proxies.jpeg_info(JPEG), (32, 44, 3))
        self.assertIsNone(proxies.jpeg_info(b"nope"))

    def test_layout_nine_per_page(self):
        entries = [{"name": f"Karte {i}", "image": JPEG} for i in range(11)]
        entries.append({"name": "Text", "image": None,
                        "text": {"name": "Sol Ring", "mana": "{1}", "type": "Artifact", "text": "{T}: Add {C}{C}.",
                                 "pt": ""}})
        pdf = proxies.build_pdf(entries, paper="a4")
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Count 2", pdf)                 # 12 Karten -> 2 Seiten
        self.assertEqual(pdf.count(b"/Subtype /Image"), 1)   # gleiches Bild nur einmal eingebettet
        self.assertEqual(pdf.count(b" Do Q"), 11)
        if shutil.which("pdfinfo"):
            out = subprocess.run(["pdfinfo", "-"], input=pdf, capture_output=True, text=False).stdout.decode()
            self.assertRegex(out, r"Pages:\s+2\n")
            self.assertIn("595.28 x 841.89", out)       # A4

    def test_card_size_is_real(self):
        # Kartenbreite 63,5 mm = 180,0 pt
        pdf = proxies.build_pdf([{"name": "x", "image": JPEG}], paper="letter", gap_mm=2)
        self.assertIn(b"q 180.000 0 0 252.000", pdf)
        self.assertIn(b"612.00 792.00", pdf)             # Letter

    def test_dfc_has_two_faces(self):
        raw = {"name": "A // B", "card_faces": [{"image_uris": {"large": "u1"}}, {"image_uris": {"large": "u2"}}]}
        self.assertEqual(proxies.card_images(raw), ["u1", "u2"])


class TestProxyApi(unittest.TestCase):
    def test_wishlist_and_deck_pdf(self):
        srv = Server(os.path.join(tempfile.mkdtemp(), "p.db"), TOK, bind="127.0.0.1", port=0, discovery=False,
                     scryfall=FakeScryfall()).start()
        srv.ctx.image_fetcher = fake_fetch
        try:
            from mtgcards.scryfall import normalize_card
            from fixtures import KRAUM, SOL_RING
            srv.ctx.wishlist.add(normalize_card(SOL_RING), quantity=4)
            srv.ctx.wishlist.add(normalize_card(KRAUM), quantity=7)
            base = f"http://127.0.0.1:{srv.port}"

            def get(path):
                with urlopen(Request(base + path, headers={"Authorization": "Bearer " + TOK})) as r:
                    return r.headers.get("Content-Type"), r.read()

            ctype, pdf = get("/api/wishlist/proxies.pdf")
            self.assertEqual(ctype, "application/pdf")
            self.assertIn(b"/Count 2", pdf)               # 11 Karten -> 2 Seiten
            self.assertEqual(pdf.count(b" Do Q"), 11)
            ctype, pdf = get("/api/wishlist/proxies.pdf?copies=one&paper=letter")
            self.assertEqual(pdf.count(b" Do Q"), 2)
            deck = srv.ctx.decks.create("D")
            srv.ctx.decks.import_list(deck["id"], srv.ctx.scryfall, "3 Sol Ring\n1 Kraum")
            ctype, pdf = get(f"/api/decks/{deck['id']}/proxies.pdf")
            self.assertEqual(pdf.count(b" Do Q"), 4)
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
