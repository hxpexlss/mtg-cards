"""Druckbare Proxy-PDFs: 9 Karten pro Seite (3×3) in Originalgröße, mit Schnittmarken.

Reines Python (Standardbibliothek): Die Kartenbilder von Scryfall sind JPEGs und werden direkt
(DCTDecode) in die PDF eingebettet – keine Bildbibliothek nötig.
"""

import hashlib
import os
import textwrap
from urllib.request import Request, urlopen

from . import __version__
from .scryfall import ScryfallError

MM = 72 / 25.4
CARD_W, CARD_H = 63.5, 88.9          # mm – Standardgröße (2,5 × 3,5 Zoll), passt in normale Sleeves
PAPERS = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}


# ---------------------------------------------------------------------------
# Bilder
# ---------------------------------------------------------------------------

def jpeg_info(data):
    """(Breite, Höhe, Farbkomponenten) aus einem JPEG lesen; None wenn kein gültiges JPEG."""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h, data[i + 9]
        i += 2 + length
    return None


def card_images(raw):
    """Bild-URLs (groß) einer Scryfall-Karte; doppelseitige Karten liefern Vorder- und Rückseite."""
    if raw.get("image_uris"):
        return [raw["image_uris"].get("large") or raw["image_uris"].get("normal")]
    out = []
    for face in raw.get("card_faces") or []:
        uris = face.get("image_uris") or {}
        if uris:
            out.append(uris.get("large") or uris.get("normal"))
    return [u for u in out if u]


def fetch_image(url, cache_dir=None, timeout=20):
    """Lädt ein Bild (mit Datei-Cache). Gibt Bytes oder None zurück."""
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".jpg")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    try:
        req = Request(url, headers={"User-Agent": f"MTGCardsCollection/{__version__}", "Accept": "image/*"})
        with urlopen(req, timeout=timeout) as r:
            data = r.read()
    except OSError:
        return None
    if not jpeg_info(data):
        return None
    if path:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return data


def collect_entries(scryfall, items, cache_dir=None, fetch=fetch_image):
    """items: [{"name", "scryfall_id"(opt), "copies"}] -> Liste druckbarer Karten (pro Exemplar/Seite ein Eintrag)."""
    entries, errors = [], []
    for it in items:
        copies = max(0, int(it.get("copies") or 1))
        if not copies:
            continue
        raw = None
        try:
            raw = scryfall.lookup(scryfall_id=it["scryfall_id"]) if it.get("scryfall_id") \
                else scryfall.lookup(name=it["name"])
        except ScryfallError as e:
            errors.append(f"{it['name']}: {e}")
        faces = []
        if raw:
            for url in card_images(raw):
                img = fetch(url, cache_dir)
                faces.append({"image": img, "url": url})
            if not faces or any(f["image"] is None for f in faces):
                # Bild nicht verfügbar -> Text-Proxy
                faces = [{"image": None, "text": _text_card(raw)}]
        else:
            faces = [{"image": None, "text": {"name": it["name"], "mana": "", "type": "", "text": "", "pt": ""}}]
        for _ in range(copies):
            for f in faces:
                entries.append(dict(f, name=it["name"]))
    return entries, errors


def _text_card(raw):
    faces = raw.get("card_faces") or [raw]
    f = faces[0]
    pt = f"{f.get('power')}/{f.get('toughness')}" if f.get("power") is not None else (f.get("loyalty") or "")
    return {"name": raw.get("name", ""), "mana": f.get("mana_cost") or raw.get("mana_cost") or "",
            "type": f.get("type_line") or raw.get("type_line") or "",
            "text": f.get("oracle_text") or raw.get("oracle_text") or "", "pt": pt}


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

class _Pdf:
    def __init__(self):
        self.objs = []

    def reserve(self):
        self.objs.append(None)
        return len(self.objs)

    def set(self, num, data):
        self.objs[num - 1] = data if isinstance(data, bytes) else data.encode("latin-1")

    def add(self, data):
        num = self.reserve()
        self.set(num, data)
        return num

    def stream(self, header, data):
        return self.add(b"<< " + header.encode("latin-1") + b" /Length %d >>\nstream\n" % len(data) + data
                        + b"\nendstream")

    def build(self, root):
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, obj in enumerate(self.objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(self.objs) + 1, root, len(self.objs), xref)
        return bytes(out)


def _pdf_text(s):
    s = (s or "").replace("—", "-").replace("−", "-").replace("’", "'").replace("•", "*")
    s = s.encode("cp1252", "replace").decode("cp1252")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252", "replace").decode("latin-1")


def _text_ops(x, y, size, text, font="F1"):
    return f"BT /{font} {size:.1f} Tf {x:.2f} {y:.2f} Td ({_pdf_text(text)}) Tj ET\n"


def build_pdf(entries, paper="a4", cut_marks=True, gap_mm=0.0, title="MTG Cards Proxies"):
    """Erzeugt die PDF (Bytes). entries aus collect_entries()."""
    pw, ph = PAPERS.get(paper, PAPERS["a4"])
    cols, rows = 3, 3
    gap = max(0.0, min(float(gap_mm or 0), 5.0))
    grid_w = cols * CARD_W + (cols - 1) * gap
    grid_h = rows * CARD_H + (rows - 1) * gap
    left = (pw - grid_w) / 2
    bottom = (ph - grid_h) / 2
    per_page = cols * rows
    pages_n = max(1, (len(entries) + per_page - 1) // per_page)

    pdf = _Pdf()
    catalog = pdf.reserve()
    pages = pdf.reserve()
    font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_b = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    images = {}   # gleiche Bilder nur einmal einbetten
    for e in entries:
        img = e.get("image")
        if img is None:
            continue
        key = hashlib.sha1(img).hexdigest()
        if key in images:
            continue
        w, h, comps = jpeg_info(img)
        cs = {1: "/DeviceGray", 4: "/DeviceCMYK"}.get(comps, "/DeviceRGB")
        extra = " /Decode [1 0 1 0 1 0 1 0]" if comps == 4 else ""
        num = pdf.stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace {cs}"
                         f" /BitsPerComponent 8 /Filter /DCTDecode{extra}", img)
        images[key] = (f"Im{len(images) + 1}", num)

    xobjects = " ".join(f"/{name} {num} 0 R" for name, num in images.values())
    resources = f"<< /Font << /F1 {font} 0 R /F2 {font_b} 0 R >> /XObject << {xobjects} >> >>"

    page_nums = []
    for p in range(pages_n):
        ops = []
        chunk = entries[p * per_page:(p + 1) * per_page]
        for i, e in enumerate(chunk):
            c, r = i % cols, i // cols
            x = (left + c * (CARD_W + gap)) * MM
            y = (bottom + (rows - 1 - r) * (CARD_H + gap)) * MM
            w, h = CARD_W * MM, CARD_H * MM
            if e.get("image") is not None:
                name = images[hashlib.sha1(e["image"]).hexdigest()][0]
                ops.append(f"q {w:.3f} 0 0 {h:.3f} {x:.3f} {y:.3f} cm /{name} Do Q\n")
            else:
                ops.append(_text_card_ops(e.get("text") or {"name": e.get("name", "")}, x, y, w, h))
        if cut_marks:
            ops.append(_cut_marks(left, bottom, cols, rows, gap, pw, ph))
        footer = f"{title} - nur zum Testen, nicht zum Verkauf - Seite {p + 1}/{pages_n} - mit 100 % (tatsächliche Größe) drucken"
        ops.append("0.45 g\n" + _text_ops(left * MM, max(4, bottom - 9) * MM, 7, footer) + "0 g\n")
        content = pdf.stream("", "".join(ops).encode("latin-1"))
        page_nums.append(pdf.add(f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 {pw * MM:.2f} {ph * MM:.2f}]"
                                 f" /Resources {resources} /Contents {content} 0 R >>"))
    pdf.set(pages, f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_nums)}] /Count {len(page_nums)} >>")
    pdf.set(catalog, f"<< /Type /Catalog /Pages {pages} 0 R >>")
    pdf.add(f"<< /Title ({_pdf_text(title)}) /Producer (MTG Cards {__version__}) >>")
    return pdf.build(catalog)


def _cut_marks(left, bottom, cols, rows, gap, pw, ph):
    """Schnittmarken außerhalb des Kartenrasters (an jeder Kartenkante)."""
    xs, ys = [], []
    for c in range(cols):
        xs += [left + c * (CARD_W + gap), left + c * (CARD_W + gap) + CARD_W]
    for r in range(rows):
        ys += [bottom + r * (CARD_H + gap), bottom + r * (CARD_H + gap) + CARD_H]
    xs, ys = sorted(set(round(v, 3) for v in xs)), sorted(set(round(v, 3) for v in ys))
    top, right = ys[-1], xs[-1]
    length, off = 6.0, 1.5
    ops = ["0.25 w 0 G\n"]
    for x in xs:
        ops.append(f"{x * MM:.2f} {(top + off) * MM:.2f} m {x * MM:.2f} {(top + off + length) * MM:.2f} l S\n")
        ops.append(f"{x * MM:.2f} {(ys[0] - off) * MM:.2f} m {x * MM:.2f} {(ys[0] - off - length) * MM:.2f} l S\n")
    for y in ys:
        ops.append(f"{(xs[0] - off) * MM:.2f} {y * MM:.2f} m {(xs[0] - off - length) * MM:.2f} {y * MM:.2f} l S\n")
        ops.append(f"{(right + off) * MM:.2f} {y * MM:.2f} m {(right + off + length) * MM:.2f} {y * MM:.2f} l S\n")
    return "".join(ops)


def _text_card_ops(t, x, y, w, h):
    """Text-Proxy, falls kein Bild verfügbar ist."""
    pad = 3 * MM
    ops = [f"q 0.6 w 0 G {x + 1:.2f} {y + 1:.2f} {w - 2:.2f} {h - 2:.2f} re S Q\n"]
    cy = y + h - pad - 9
    ops.append(_text_ops(x + pad, cy, 9.5, t.get("name", ""), "F2"))
    if t.get("mana"):
        cy -= 11
        ops.append(_text_ops(x + pad, cy, 8, t["mana"]))
    cy -= 13
    ops.append(f"q 0.4 w {x + pad:.2f} {cy + 9:.2f} m {x + w - pad:.2f} {cy + 9:.2f} l S Q\n")
    ops.append(_text_ops(x + pad, cy, 7.5, t.get("type", ""), "F2"))
    cy -= 12
    for para in (t.get("text") or "").split("\n"):
        for line in textwrap.wrap(para, 44) or [""]:
            if cy < y + pad + 14:
                break
            ops.append(_text_ops(x + pad, cy, 7, line))
            cy -= 8.6
        cy -= 2
    if t.get("pt"):
        ops.append(_text_ops(x + w - pad - 22, y + pad, 10, t["pt"], "F2"))
    return "".join(ops)
