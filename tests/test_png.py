"""Verlustfreie PNG-Verarbeitung für die Proxy-PDF (ohne Bildbibliothek)."""

import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtgcards import pngimg  # noqa: E402
from mtgcards.proxies import build_pdf  # noqa: E402


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def make_png(w, h, pixels, ctype=6, palette=None):
    """Kleiner PNG-Encoder für Tests: jede Zeile mit einem anderen Filter (0–4)."""
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * bpp
    raw = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        line = pixels[y * stride:(y + 1) * stride]
        ft = y % 5
        out = bytearray(stride)
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = [0, a, b, (a + b) >> 1, _paeth(a, b, c)][ft]
            out[i] = (line[i] - pred) & 255
        raw += bytes([ft]) + out
        prev = bytearray(line)

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xffffffff)
    data = pngimg.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
    if palette:
        data += chunk(b"PLTE", palette)
    return data + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


class TestPng(unittest.TestCase):
    def test_rgb_all_filters_exact(self):
        w, h = 7, 10
        px = bytes((x * 37 + y * 11 + c * 59) % 256 for y in range(h) for x in range(w) for c in range(3))
        png = make_png(w, h, px, ctype=2)
        self.assertEqual(pngimg.png_info(png), (w, h))
        self.assertEqual(pngimg.decode_rgb(png), (w, h, px))          # bitgenau = verlustfrei

    def test_rgba_corners_get_border_color(self):
        w, h = 6, 5
        px = bytearray()
        for y in range(h):
            for x in range(w):
                corner = (x, y) in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))
                px += bytes([200, 10, 10, 0]) if corner else bytes([20, 30, 40, 255])
        _, _, rgb = pngimg.decode_rgb(make_png(w, h, bytes(px), ctype=6))
        self.assertEqual(rgb[0:3], bytes([20, 30, 40]))               # transparente Ecke -> Randfarbe
        self.assertEqual(rgb[3:6], bytes([20, 30, 40]))

    def test_gray_and_palette(self):
        _, _, rgb = pngimg.decode_rgb(make_png(2, 2, bytes([0, 128, 255, 7]), ctype=0))
        self.assertEqual(rgb, bytes([0, 0, 0, 128, 128, 128, 255, 255, 255, 7, 7, 7]))
        pal = bytes([255, 0, 0, 0, 255, 0])
        _, _, rgb = pngimg.decode_rgb(make_png(2, 1, bytes([1, 0]), ctype=3, palette=pal))
        self.assertEqual(rgb, bytes([0, 255, 0, 255, 0, 0]))

    def test_pdf_embeds_flate_and_caches(self):
        w, h = 8, 8
        png = make_png(w, h, bytes((i * 3) % 256 for i in range(w * h * 4)), ctype=6)
        cache = tempfile.mkdtemp()
        pdf = build_pdf([{"image": png, "name": "X"}], image_cache=cache)
        self.assertIn(b"/Filter /FlateDecode", pdf)
        self.assertNotIn(b"/DCTDecode", pdf)
        self.assertEqual(len(os.listdir(cache)), 1)
        self.assertEqual(pngimg.pdf_stream(png, cache)[:2], (w, h))   # aus dem Cache

    def test_rejects_fake_png(self):
        self.assertIsNone(pngimg.png_info(b"\x89PNG\r\n\x1a\n...."))


if __name__ == "__main__":
    unittest.main()
