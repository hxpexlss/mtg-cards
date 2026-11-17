"""PNG für die Proxy-PDF – verlustfrei, nur mit der Standardbibliothek.

PDF kann PNG-Dateien nicht direkt einbetten: Die Bilddaten werden entpackt, die PNG-Filter rückgängig gemacht,
Transparenz (abgerundete Ecken der Scryfall-Bilder) auf die Randfarbe gelegt und das Ergebnis als RGB mit
FlateDecode (zlib, verlustfrei) in die PDF geschrieben. Das Ergebnis wird je Bild zwischengespeichert.
"""

import hashlib
import os
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PngError(ValueError):
    pass


def is_png(data):
    return bool(data) and data[:8] == SIGNATURE


def png_info(data):
    """(Breite, Höhe) oder None."""
    if not is_png(data) or len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _chunks(data):
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        yield typ, data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if typ == b"IEND":
            break


def _unfilter(raw, w, h, bpp):
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            line = bytearray(map(lambda a, b: (a + b) & 255, line, prev))
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        elif ft != 0:
            raise PngError("Unbekannter PNG-Filter")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def decode_rgb(data):
    """PNG -> (Breite, Höhe, RGB-Bytes). Transparenz wird auf die Randfarbe gelegt (für gerade Schnittkanten)."""
    if not is_png(data):
        raise PngError("Kein PNG")
    w = h = depth = ctype = None
    palette, trns, idat = b"", b"", []
    for typ, body in _chunks(data):
        if typ == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body[:13])
            if interlace:
                raise PngError("Interlaced PNG wird nicht unterstützt")
            if depth != 8:
                raise PngError("Nur PNG mit 8 Bit pro Kanal")
        elif typ == b"PLTE":
            palette = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat.append(body)
    if w is None:
        raise PngError("Ungültiges PNG")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if bpp is None:
        raise PngError("Unbekannter PNG-Farbtyp")
    px = _unfilter(zlib.decompress(b"".join(idat)), w, h, bpp)

    # in RGBA bzw. RGB umwandeln
    if ctype == 2:
        return w, h, bytes(px)
    if ctype == 0:
        rgb = bytearray(w * h * 3)
        rgb[0::3] = px
        rgb[1::3] = px
        rgb[2::3] = px
        return w, h, bytes(rgb)
    if ctype == 3:
        alpha = list(trns) + [255] * (256 - len(trns))
        rgba = bytearray(w * h * 4)
        for i, idx in enumerate(px):
            rgba[i * 4:i * 4 + 3] = palette[idx * 3:idx * 3 + 3]
            rgba[i * 4 + 3] = alpha[idx]
        px, ctype = rgba, 6
    elif ctype == 4:
        rgba = bytearray(w * h * 4)
        rgba[0::4] = px[0::2]
        rgba[1::4] = px[0::2]
        rgba[2::4] = px[0::2]
        rgba[3::4] = px[1::2]
        px, ctype = rgba, 6

    # RGBA -> RGB: deckende Zeilen schnell (Slicing), nur Zeilen mit Transparenz pixelweise
    stride = w * 4
    mid = (w // 2) * 4
    bg = px[stride + mid:stride + mid + 3] if h > 1 else b"\x00\x00\x00"   # Randfarbe oben in der Mitte
    if len(bg) < 3:
        bg = b"\x00\x00\x00"
    rgb = bytearray(w * h * 3)
    full = b"\xff" * w
    for y in range(h):
        row = px[y * stride:(y + 1) * stride]
        out = bytearray(w * 3)
        out[0::3] = row[0::4]
        out[1::3] = row[1::4]
        out[2::3] = row[2::4]
        alpha = row[3::4]
        if alpha != full:
            for x, a in enumerate(alpha):
                if a != 255:
                    for c in range(3):
                        out[x * 3 + c] = (out[x * 3 + c] * a + bg[c] * (255 - a)) // 255
        rgb[y * w * 3:(y + 1) * w * 3] = out
    return w, h, bytes(rgb)


def pdf_stream(data, cache_dir=None):
    """(Breite, Höhe, zlib-komprimierte RGB-Daten) für ein PDF-Bild mit /FlateDecode – mit Datei-Cache."""
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, hashlib.sha1(data).hexdigest() + ".rgbz")
        if os.path.exists(path):
            with open(path, "rb") as f:
                blob = f.read()
            w, h = struct.unpack(">II", blob[:8])
            return w, h, blob[8:]
    w, h, rgb = decode_rgb(data)
    flate = zlib.compress(rgb, 6)
    if path:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(struct.pack(">II", w, h) + flate)
        except OSError:
            pass
    return w, h, flate
