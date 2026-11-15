"""Druck: Einträge einer Druckliste -> PDF (9 pro Seite, optional beidseitig) oder ZIP mit Einzelbildern."""

import hashlib
import io
import os
import re
import zipfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .. import __version__
from ..proxies import build_pdf, card_images, fetch_image, sharper_print
from ..scryfall import ScryfallError

ALLOWED_IMAGE_HOSTS = ("cards.scryfall.io", "c1.scryfall.com", "c2.scryfall.com", "svgs.scryfall.io")


def fetch_any(url, cache_dir=None, timeout=20):
    """Bild (JPEG oder PNG) von Scryfall laden, mit Datei-Cache. Nur Scryfall-Hosts (kein offener Proxy)."""
    host = urlparse(url or "").hostname or ""
    if not url or host not in ALLOWED_IMAGE_HOSTS:
        return None
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".img")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    data = None
    for _ in range(3):
        try:
            req = Request(url, headers={"User-Agent": f"ProxieMaker/{__version__}", "Accept": "image/*"})
            with urlopen(req, timeout=timeout) as r:
                data = r.read()
            break
        except OSError:
            data = None
    if not data or not (data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    if path:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return data


def _text(row):
    return {"name": row.get("name") or "", "mana": row.get("mana_cost") or "", "type": row.get("type_line") or "",
            "text": "", "pt": ""}


def _scryfall_images(scryfall, row, cache_dir, fetch, sharpen):
    """(Vorderseite, Rückseite) als JPEG für einen unbearbeiteten Scryfall-Eintrag."""
    front_url, back_url = row.get("image_url"), row.get("image_url_back")
    if sharpen and row.get("image_status") in ("lowres", "placeholder", "missing") and row.get("scryfall_id"):
        try:
            better = sharper_print(scryfall, scryfall.lookup(scryfall_id=row["scryfall_id"]))
            urls = card_images(better)
            if urls:
                front_url = urls[0]
                back_url = urls[1] if len(urls) > 1 else back_url
        except ScryfallError:
            pass
    front = fetch(front_url, cache_dir) if front_url else None
    back = fetch(back_url, cache_dir) if back_url else None
    return front, back


def collect(scryfall, rows, cache_dir=None, fetch=fetch_image, sharpen=True, duplex=False, card_back=None, one=False):
    """Druck-Einträge. Ohne duplex werden Rückseiten doppelseitiger Karten als eigene Karte gedruckt."""
    entries = []
    for row in rows:
        copies = 1 if one else max(0, int(row.get("quantity") or 1))
        if not copies:
            continue
        front = row.get("rendered") or (row.get("custom_image") if row.get("kind") == "custom" else None)
        back = row.get("rendered_back")
        if front is None or (back is None and row.get("image_url_back")):
            f2, b2 = (None, None)
            if row.get("kind") == "scryfall":
                f2, b2 = _scryfall_images(scryfall, row, cache_dir, fetch, sharpen)
            front = front if front is not None else f2
            back = back if back is not None else b2
        front, back = (bytes(front) if front else None), (bytes(back) if back else None)
        for _ in range(copies):
            if duplex:
                entries.append({"image": front, "text": None if front else _text(row), "name": row["name"],
                                "back": back or card_back})
            else:
                entries.append({"image": front, "text": None if front else _text(row), "name": row["name"]})
                if back:
                    entries.append({"image": back, "name": row["name"]})
    return entries


def make_pdf(scryfall, project, rows, cache_dir=None, fetch=fetch_image, paper="a4", cut=True, gap=0.0,
             sharpen=True, duplex=False, card_back=None, one=False):
    entries = collect(scryfall, rows, cache_dir, fetch, sharpen, duplex, card_back, one)
    if not entries:
        return None
    return build_pdf(entries, paper=paper, cut_marks=cut, gap_mm=gap, title=f"Proxie Maker - {project['name']}",
                     duplex=duplex)


def make_zip(scryfall, rows, cache_dir=None, fetch=fetch_image, sharpen=True, card_back=None):
    """Einzelbilder (je Karte einmal, Anzahl im Dateinamen) – z.B. für Druckdienste."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        n = 0
        for row in rows:
            front = row.get("rendered") or (row.get("custom_image") if row.get("kind") == "custom" else None)
            back = row.get("rendered_back")
            if front is None or (back is None and row.get("image_url_back")):
                f2, b2 = (None, None)
                if row.get("kind") == "scryfall":
                    f2, b2 = _scryfall_images(scryfall, row, cache_dir, fetch, sharpen)
                front = front if front is not None else f2
                back = back if back is not None else b2
            if front is None:
                continue
            n += 1
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", row["name"]).strip("-")[:60] or "karte"
            q = max(1, int(row.get("quantity") or 1))
            z.writestr(f"{n:03d}_{safe}_x{q}.jpg", bytes(front))
            if back:
                z.writestr(f"{n:03d}_{safe}_x{q}_rueckseite.jpg", bytes(back))
        if card_back:
            z.writestr("kartenrueckseite.jpg", bytes(card_back))
    return buf.getvalue()
