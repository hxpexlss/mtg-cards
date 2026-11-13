"""Proxy-PDF: unscharfe Scryfall-Bilder durch einen scharfen Scan mit gleichem Artwork ersetzen."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtgcards.proxies import collect_entries, sharper_print  # noqa: E402
from mtgcards.scryfall import ScryfallError  # noqa: E402


def card(set_code, lang, status, ill="ill-a", cn="1"):
    return {"id": f"{set_code}-{lang}", "name": "Bolt", "set": set_code, "collector_number": cn, "lang": lang,
            "image_status": status, "illustration_id": ill,
            "image_uris": {"large": f"https://img/{set_code}-{lang}.jpg"}}


class Fake:
    def __init__(self, en=None, prints=()):
        self.en, self._prints = en, list(prints)

    def by_set_number(self, s, n, lang=None):
        if self.en:
            return self.en
        raise ScryfallError("nope", 404)

    def prints(self, name):
        return self._prints

    def lookup(self, scryfall_id=None, name=None):
        return card("xx", "de", "lowres")


class TestSharperPrint(unittest.TestCase):
    def test_highres_stays(self):
        c = card("m10", "de", "highres_scan")
        self.assertIs(sharper_print(Fake(), c), c)

    def test_english_same_print(self):
        en = card("m10", "en", "highres_scan")
        self.assertIs(sharper_print(Fake(en=en), card("m10", "de", "lowres")), en)

    def test_same_artwork_other_print(self):
        other_art = card("lea", "en", "highres_scan", ill="ill-b")
        same_art = card("m11", "en", "highres_scan")
        got = sharper_print(Fake(prints=[same_art, other_art]), card("m10", "de", "lowres"))
        self.assertIs(got, same_art)

    def test_nothing_better(self):
        c = card("m10", "de", "lowres")
        self.assertIs(sharper_print(Fake(), c), c)

    def test_collect_uses_sharp_image_and_can_be_disabled(self):
        fake = Fake(en=card("xx", "en", "highres_scan"))
        urls = []

        def fetch(url, cache_dir=None):
            urls.append(url)
            return b"\xff\xd8" + b"\x00" * 10
        collect_entries(fake, [{"name": "Bolt", "scryfall_id": "x", "copies": 1}], fetch=fetch)
        collect_entries(fake, [{"name": "Bolt", "scryfall_id": "x", "copies": 1}], fetch=fetch, sharpen=False)
        self.assertEqual(urls, ["https://img/xx-en.jpg", "https://img/xx-de.jpg"])


if __name__ == "__main__":
    unittest.main()
