"""Eigene Proxies: hochgeladene Kartenbilder (z.B. Fun-Karten, Alters, selbst gestaltete Karten).

Die Bilder werden als JPEG in der Datenbank gespeichert (eine Datei = komplette Sicherung) und lassen sich
wie Scryfall-Karten als Proxy-PDF drucken (9 pro Seite). Andere Formate (PNG, WebP, HEIC …) wandeln
Weboberfläche und App vor dem Hochladen in JPEG um – der Server braucht dafür keine Bildbibliothek.
"""

import base64
import binascii
import hashlib

from .db import now_iso
from .proxies import jpeg_info

SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    image BLOB NOT NULL,
    image_hash TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    created_at TEXT,
    updated_at TEXT
);
"""

MAX_IMAGE = 10 * 1024 * 1024
_FIELDS = "id, name, notes, quantity, image_hash, width, height, created_at, updated_at"


class CustomProxyError(ValueError):
    pass


def decode_image(value):
    """Bild aus Bytes, Base64 oder Data-URL ("data:image/jpeg;base64,…"). Nur JPEG."""
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        s = str(value or "").strip()
        if s.startswith("data:"):
            s = s.split(",", 1)[-1]
        try:
            data = base64.b64decode(s, validate=False)
        except (binascii.Error, ValueError):
            raise CustomProxyError("Bild konnte nicht gelesen werden") from None
    if not data:
        raise CustomProxyError("Kein Bild angegeben")
    if len(data) > MAX_IMAGE:
        raise CustomProxyError("Bild ist zu groß (höchstens 10 MB)")
    info = jpeg_info(data)
    if not info:
        raise CustomProxyError("Bitte ein JPEG-Bild hochladen (Weboberfläche und App wandeln andere Formate um)")
    return data, info


def _quantity(v, default=1):
    try:
        return max(1, min(999, int(v)))
    except (TypeError, ValueError):
        return default


class CustomProxies:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def _row(self, r):
        d = dict(r)
        d["image_version"] = (d.get("image_hash") or "")[:12]
        return d

    def list(self):
        with self.db._lock:
            rows = self.db.conn.execute(
                f"SELECT {_FIELDS} FROM custom_proxies ORDER BY name COLLATE NOCASE, id").fetchall()
        items = [self._row(r) for r in rows]
        return {"items": items, "copies": sum(i["quantity"] for i in items)}

    def get(self, pid):
        with self.db._lock:
            r = self.db.conn.execute(f"SELECT {_FIELDS} FROM custom_proxies WHERE id=?", (pid,)).fetchone()
        return self._row(r) if r else None

    def image(self, pid):
        with self.db._lock:
            r = self.db.conn.execute("SELECT image FROM custom_proxies WHERE id=?", (pid,)).fetchone()
        return bytes(r[0]) if r else None

    def add(self, name, image, quantity=1, notes=""):
        name = (name or "").strip()
        if not name:
            raise CustomProxyError("Name fehlt")
        data, (w, h, _) = decode_image(image)
        ts = now_iso()
        with self.db._lock:
            cur = self.db.conn.execute(
                "INSERT INTO custom_proxies(name, notes, quantity, image, image_hash, width, height, created_at,"
                " updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (name, notes or "", _quantity(quantity), data, hashlib.sha1(data).hexdigest(), w, h, ts, ts))
            self.db._bump()
            self.db.conn.commit()
        return self.get(cur.lastrowid)

    def update(self, pid, changes):
        sets, vals = [], []
        if "name" in changes:
            name = str(changes["name"] or "").strip()
            if not name:
                raise CustomProxyError("Name fehlt")
            sets.append("name=?")
            vals.append(name)
        if "notes" in changes:
            sets.append("notes=?")
            vals.append(str(changes["notes"] or ""))
        if "quantity" in changes:
            sets.append("quantity=?")
            vals.append(_quantity(changes["quantity"]))
        if changes.get("image"):
            data, (w, h, _) = decode_image(changes["image"])
            sets += ["image=?", "image_hash=?", "width=?", "height=?"]
            vals += [data, hashlib.sha1(data).hexdigest(), w, h]
        with self.db._lock:
            if not self.db.conn.execute("SELECT 1 FROM custom_proxies WHERE id=?", (pid,)).fetchone():
                return None
            if sets:
                sets.append("updated_at=?")
                vals.append(now_iso())
                self.db.conn.execute(f"UPDATE custom_proxies SET {', '.join(sets)} WHERE id=?", vals + [pid])
                self.db._bump()
                self.db.conn.commit()
        return self.get(pid)

    def delete(self, pid):
        with self.db._lock:
            cur = self.db.conn.execute("DELETE FROM custom_proxies WHERE id=?", (pid,))
            self.db._bump()
            self.db.conn.commit()
            return cur.rowcount > 0

    def entries(self, ids=None, one=False):
        """Druckbare Einträge für proxies.build_pdf (pro Exemplar ein Eintrag)."""
        wanted = set(ids or [])
        out = []
        with self.db._lock:
            rows = self.db.conn.execute(
                "SELECT id, name, quantity, image FROM custom_proxies ORDER BY name COLLATE NOCASE, id").fetchall()
        for pid, name, qty, img in rows:
            if wanted and pid not in wanted:
                continue
            for _ in range(1 if one else qty):
                out.append({"image": bytes(img), "name": name})
        return out


def export_custom_proxies(db):
    CustomProxies(db)
    with db._lock:
        rows = db.conn.execute(
            "SELECT name, notes, quantity, image, created_at FROM custom_proxies ORDER BY id").fetchall()
    return [{"name": r[0], "notes": r[1], "quantity": r[2], "created_at": r[4],
             "image": base64.b64encode(bytes(r[3])).decode("ascii")} for r in rows]


def import_custom_proxies(db, items, replace=False, _in_tx=False):
    """Aus einem JSON-Export. Gleiches Bild mit gleichem Namen wird beim Ergänzen nicht doppelt angelegt."""
    if not _in_tx:
        CustomProxies(db)
    count = 0
    with db._lock:
        if replace:
            db.conn.execute("DELETE FROM custom_proxies")
        existing = {(r[0].lower(), r[1]) for r in db.conn.execute("SELECT name, image_hash FROM custom_proxies")}
        for it in items or []:
            if not isinstance(it, dict) or not it.get("name") or not it.get("image"):
                continue
            try:
                data, (w, h, _) = decode_image(it["image"])
            except CustomProxyError:
                continue
            key = (it["name"].lower(), hashlib.sha1(data).hexdigest())
            if key in existing:
                continue
            ts = now_iso()
            db.conn.execute(
                "INSERT INTO custom_proxies(name, notes, quantity, image, image_hash, width, height, created_at,"
                " updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (it["name"], it.get("notes") or "", _quantity(it.get("quantity")), data, key[1], w, h,
                 it.get("created_at") or ts, ts))
            existing.add(key)
            count += 1
        db._bump()
        if not _in_tx:
            db.conn.commit()
    return count
