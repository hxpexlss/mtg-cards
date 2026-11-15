"""SQLite-Speicher: Drucklisten (Projekte), Karten mit Personalisierung, Kartenrückseiten, Stil-Vorlagen."""

import base64
import binascii
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from ..proxies import jpeg_info

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    back_id INTEGER,                 -- eigene Kartenrückseite für den beidseitigen Druck
    kind TEXT NOT NULL DEFAULT 'list',   -- 'list' = Druckliste, 'deck' = Deck (Reiter „Decks“)
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'scryfall',   -- 'scryfall' = Karte von Scryfall, 'custom' = komplett eigenes Bild
    name TEXT NOT NULL,
    oracle_id TEXT,
    scryfall_id TEXT,                -- leer = beliebiger (günstigster) Druck
    set_code TEXT,
    collector_number TEXT,
    lang TEXT,
    type_line TEXT,
    mana_cost TEXT,
    image_url TEXT,                  -- Vorderseite (JPEG "large") – Druck ohne Bearbeitung
    image_url_back TEXT,             -- Rückseite doppelseitiger Karten
    png_url TEXT,                    -- beste Qualität (PNG 745x1040) – Grundlage im Editor
    png_url_back TEXT,
    image_status TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    max_price_eur REAL,
    price_eur REAL,
    price_set TEXT,
    price_checked_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',     -- Personalisierung (siehe web/editor.js)
    art BLOB,                        -- eigenes Artwork (JPEG)
    custom_image BLOB,               -- kind='custom': komplette Karte (JPEG)
    rendered BLOB,                   -- fertig bearbeitete Vorderseite (JPEG, aus dem Editor)
    rendered_back BLOB,              -- fertig bearbeitete Rückseite (doppelseitige Karten)
    position INTEGER NOT NULL DEFAULT 0,
    board TEXT NOT NULL DEFAULT 'main',      -- Decks: commander | companion | main | side | maybe
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_project ON items(project_id);
CREATE TABLE IF NOT EXISTS backs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    image BLOB NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

ITEM_FIELDS = ("id", "project_id", "kind", "name", "oracle_id", "scryfall_id", "set_code", "collector_number", "lang",
               "type_line", "mana_cost", "image_url", "image_url_back", "png_url", "png_url_back", "image_status",
               "quantity", "max_price_eur", "price_eur", "price_set", "price_checked_at", "notes", "settings",
               "position", "board", "created_at", "updated_at")
CARD_KEYS = ("name", "oracle_id", "scryfall_id", "set_code", "collector_number", "lang", "type_line", "mana_cost",
             "image_url", "image_url_back", "png_url", "png_url_back", "image_status")
MAX_IMAGE = 12 * 1024 * 1024
BOARDS = ("commander", "companion", "main", "side", "maybe")
LOWRES = ("lowres", "placeholder", "missing")


class StoreError(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def decode_jpeg(value):
    """JPEG aus Bytes, Base64 oder Data-URL. Andere Formate wandeln Weboberfläche und App vorher um."""
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        s = str(value or "").strip()
        if s.startswith("data:"):
            s = s.split(",", 1)[-1]
        try:
            data = base64.b64decode(s)
        except (binascii.Error, ValueError):
            raise StoreError("Bild konnte nicht gelesen werden") from None
    if not data:
        raise StoreError("Kein Bild angegeben")
    if len(data) > MAX_IMAGE:
        raise StoreError("Bild ist zu groß (höchstens 12 MB)")
    if not jpeg_info(data):
        raise StoreError("Bitte ein JPEG-Bild senden")
    return data


def card_fields(raw):
    """Felder einer Scryfall-Karte für einen Eintrag (Bilder: large für den Druck, png für den Editor)."""
    faces = raw.get("card_faces") or []
    uris = raw.get("image_uris") or {}
    front = uris or (faces[0].get("image_uris") if faces else {}) or {}
    back = (faces[1].get("image_uris") or {}) if (not uris and len(faces) > 1) else {}
    mana = raw.get("mana_cost") or " // ".join(f.get("mana_cost", "") for f in faces if f.get("mana_cost"))
    return {
        "name": raw.get("name"),
        "oracle_id": raw.get("oracle_id") or (faces[0].get("oracle_id") if faces else None),
        "scryfall_id": raw.get("id"),
        "set_code": (raw.get("set") or "").upper(),
        "collector_number": raw.get("collector_number"),
        "lang": raw.get("lang") or "en",
        "type_line": raw.get("type_line") or " // ".join(f.get("type_line", "") for f in faces),
        "mana_cost": mana or "",
        "image_url": front.get("large") or front.get("normal"),
        "image_url_back": back.get("large") or back.get("normal"),
        "png_url": front.get("png") or front.get("large"),
        "png_url_back": back.get("png") or back.get("large"),
        "image_status": raw.get("image_status"),
    }


def price_of(raw, foil=False):
    p = raw.get("prices") or {}
    for k in (("eur_foil", "eur") if foil else ("eur", "eur_foil")):
        try:
            if p.get(k):
                return float(p[k])
        except (TypeError, ValueError):
            pass
    return None


class Store:
    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()

    def _migrate(self):
        """Ältere Datenbanken: Spalten für Decks ergänzen."""
        pcols = {r[1] for r in self.conn.execute("PRAGMA table_info(projects)")}
        if "kind" not in pcols:
            self.conn.execute("ALTER TABLE projects ADD COLUMN kind TEXT NOT NULL DEFAULT 'list'")
        icols = {r[1] for r in self.conn.execute("PRAGMA table_info(items)")}
        if "board" not in icols:
            self.conn.execute("ALTER TABLE items ADD COLUMN board TEXT NOT NULL DEFAULT 'main'")

    def close(self):
        with self.lock:
            self.conn.close()

    # -- Meta / Revision -----------------------------------------------------
    def get_meta(self, key, default=None):
        with self.lock:
            r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value)))
            self.conn.commit()

    def _bump(self):
        r = self.conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('revision', ?)", (str(int(r[0]) + 1 if r else 1),))

    def revision(self):
        return int(self.get_meta("revision", 0) or 0)

    # -- Projekte --------------------------------------------------------------
    def projects(self):
        with self.lock:
            rows = self.conn.execute(
                """SELECT p.*, COUNT(i.id) AS cards, COALESCE(SUM(i.quantity), 0) AS copies,
                          COALESCE(SUM(COALESCE(i.price_eur, 0) * i.quantity), 0) AS value_eur,
                          SUM(i.rendered IS NOT NULL) AS edited
                   FROM projects p LEFT JOIN items i ON i.project_id = p.id
                   GROUP BY p.id ORDER BY p.name COLLATE NOCASE""").fetchall()
        return [dict(r, value_eur=round(r["value_eur"], 2), edited=r["edited"] or 0) for r in rows]

    def project(self, pid):
        with self.lock:
            p = self.conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not p:
                return None
            items = [self._item(r) for r in self.conn.execute(
                f"SELECT {', '.join(ITEM_FIELDS)}, art IS NOT NULL AS has_art, rendered IS NOT NULL AS has_rendered, "
                f"rendered_back IS NOT NULL AS has_rendered_back, custom_image IS NOT NULL AS has_custom, "
                f"length(rendered) AS rendered_len FROM items WHERE project_id=? ORDER BY position, id", (pid,))]
        d = dict(p)
        d["items"] = items
        d["copies"] = sum(i["quantity"] for i in items)
        d["value_eur"] = round(sum((i["price_eur"] or 0) * i["quantity"] for i in items), 2)
        d["alerts"] = sum(1 for i in items if i["target_reached"])
        return d

    def create_project(self, name, notes="", kind="list"):
        name = (name or "").strip()
        if not name:
            raise StoreError("Name fehlt")
        ts = now_iso()
        with self.lock:
            cur = self.conn.execute("INSERT INTO projects(name, notes, kind, created_at, updated_at) VALUES(?,?,?,?,?)",
                                    (name, notes or "", "deck" if kind == "deck" else "list", ts, ts))
            self._bump()
            self.conn.commit()
        return self.project(cur.lastrowid)

    def update_project(self, pid, changes):
        sets, vals = [], []
        for k in ("name", "notes", "back_id"):
            if k in changes:
                v = changes[k]
                if k == "name":
                    v = str(v or "").strip()
                    if not v:
                        raise StoreError("Name fehlt")
                if k == "back_id":
                    v = int(v) if v not in (None, "", 0, "0") else None
                sets.append(f"{k}=?")
                vals.append(v)
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
                return None
            if sets:
                self.conn.execute(f"UPDATE projects SET {', '.join(sets)}, updated_at=? WHERE id=?",
                                  vals + [now_iso(), pid])
                self._bump()
                self.conn.commit()
        return self.project(pid)

    def delete_project(self, pid):
        with self.lock:
            self.conn.execute("DELETE FROM items WHERE project_id=?", (pid,))
            cur = self.conn.execute("DELETE FROM projects WHERE id=?", (pid,))
            self._bump()
            self.conn.commit()
            return cur.rowcount > 0

    def duplicate_project(self, pid, name=None):
        src = self.project(pid)
        if not src:
            return None
        new = self.create_project(name or f"{src['name']} (Kopie)", src["notes"], src.get("kind") or "list")
        with self.lock:
            cols = [c for c in ITEM_FIELDS if c not in ("id", "project_id")] + ["art", "custom_image", "rendered",
                                                                                 "rendered_back"]
            self.conn.execute(
                f"INSERT INTO items(project_id, {', '.join(cols)}) SELECT ?, {', '.join(cols)} FROM items "
                f"WHERE project_id=? ORDER BY position, id", (new["id"], pid))
            self.conn.execute("UPDATE projects SET back_id=? WHERE id=?", (src["back_id"], new["id"]))
            self._bump()
            self.conn.commit()
        return self.project(new["id"])

    # -- Karten ------------------------------------------------------------------
    def _item(self, r):
        d = dict(r)
        try:
            d["settings"] = json.loads(d.get("settings") or "{}")
        except ValueError:
            d["settings"] = {}
        for k in ("has_art", "has_rendered", "has_rendered_back", "has_custom"):
            if k in d:
                d[k] = bool(d[k])
        d["any_print"] = d["kind"] == "scryfall" and not d["scryfall_id"]
        d["lowres"] = d.get("image_status") in LOWRES
        d["target_reached"] = (d["max_price_eur"] is not None and d["price_eur"] is not None
                               and d["price_eur"] <= d["max_price_eur"])
        # Versionskennung der Bilder (für Browser-Cache)
        d["version"] = (d.get("updated_at") or "").replace(":", "").replace("-", "")
        return d

    def item(self, iid):
        with self.lock:
            r = self.conn.execute(
                f"SELECT {', '.join(ITEM_FIELDS)}, art IS NOT NULL AS has_art, rendered IS NOT NULL AS has_rendered, "
                f"rendered_back IS NOT NULL AS has_rendered_back, custom_image IS NOT NULL AS has_custom "
                f"FROM items WHERE id=?", (iid,)).fetchone()
        return self._item(r) if r else None

    def add_item(self, pid, fields, quantity=1, any_print=False, price=None, price_set=None, max_price=None,
                 kind="scryfall", custom_image=None, notes="", merge=True, board="main"):
        """Karte hinzufügen. Gleiche Karte (gleicher Druck bzw. beide "beliebig") ohne Bearbeitung -> Anzahl erhöhen."""
        ts = now_iso()
        f = {k: fields.get(k) for k in CARD_KEYS}
        if any_print:
            f["scryfall_id"] = None
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
                return None
            if merge and kind == "scryfall":
                ex = self.conn.execute(
                    "SELECT id FROM items WHERE project_id=? AND kind='scryfall' AND name=? AND "
                    "COALESCE(scryfall_id,'')=? AND rendered IS NULL AND art IS NULL AND board=?",
                    (pid, f["name"], f["scryfall_id"] or "", board or "main")).fetchone()
                if ex:
                    self.conn.execute("UPDATE items SET quantity=quantity+?, updated_at=? WHERE id=?",
                                      (int(quantity), ts, ex[0]))
                    self._bump()
                    self.conn.commit()
                    return self.item(ex[0])
            pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM items WHERE project_id=?",
                                    (pid,)).fetchone()[0]
            cur = self.conn.execute(
                f"""INSERT INTO items(project_id, kind, {', '.join(CARD_KEYS)}, quantity, price_eur, price_set,
                    price_checked_at, max_price_eur, notes, custom_image, position, board, created_at, updated_at)
                    VALUES(?, ?, {', '.join('?' * len(CARD_KEYS))}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [pid, kind] + [f[k] for k in CARD_KEYS] + [
                    max(1, int(quantity)), price, price_set or f.get("set_code"), ts if price is not None else None,
                    max_price, notes or "", custom_image, pos, board if board in BOARDS else "main", ts, ts])
            self.conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (ts, pid))
            self._bump()
            self.conn.commit()
        return self.item(cur.lastrowid)

    def update_item(self, iid, changes):
        sets, vals = [], []
        if "board" in changes and changes["board"] not in BOARDS:
            raise StoreError("Ungültiger Bereich")
        for k in ("quantity", "max_price_eur", "notes", "name", "position", "board"):
            if k not in changes:
                continue
            v = changes[k]
            if k == "quantity":
                v = int(v)
            elif k == "position":
                v = int(v)
            elif k == "max_price_eur":
                v = None if v in (None, "") else float(str(v).replace(",", ".").replace("€", "").strip())
            elif k == "name":
                v = str(v or "").strip()
                if not v:
                    raise StoreError("Name fehlt")
            sets.append(f"{k}=?")
            vals.append(v)
        if "settings" in changes:
            sets.append("settings=?")
            vals.append(json.dumps(changes["settings"] or {}, ensure_ascii=False))
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
                return None
            if "quantity" in changes and int(changes["quantity"]) <= 0:
                self.conn.execute("DELETE FROM items WHERE id=?", (iid,))
                self._bump()
                self.conn.commit()
                return {"id": iid, "deleted": True}
            if sets:
                self.conn.execute(f"UPDATE items SET {', '.join(sets)}, updated_at=? WHERE id=?",
                                  vals + [now_iso(), iid])
                self._bump()
                self.conn.commit()
        return self.item(iid)

    def set_print(self, iid, fields=None, price=None, price_set=None):
        """Druck wechseln (fields aus card_fields) oder mit fields=None "beliebig". Bearbeitung bleibt als Einstellung
        erhalten, das fertige Bild wird verworfen (es passt nicht mehr zum neuen Druck)."""
        ts = now_iso()
        with self.lock:
            if not self.conn.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
                return None
            if fields:
                self.conn.execute(
                    f"UPDATE items SET {', '.join(f'{k}=?' for k in CARD_KEYS)}, price_eur=?, price_set=?, "
                    f"price_checked_at=?, rendered=NULL, rendered_back=NULL, updated_at=? WHERE id=?",
                    [fields.get(k) for k in CARD_KEYS] + [price, price_set or fields.get("set_code"),
                                                         ts if price is not None else None, ts, iid])
            else:
                self.conn.execute(
                    "UPDATE items SET scryfall_id=NULL, price_eur=COALESCE(?, price_eur), price_set=COALESCE(?, price_set),"
                    " updated_at=? WHERE id=?", (price, price_set, ts, iid))
            self._bump()
            self.conn.commit()
        return self.item(iid)

    def set_price(self, iid, price, price_set=None):
        with self.lock:
            self.conn.execute("UPDATE items SET price_eur=?, price_set=COALESCE(?, price_set), price_checked_at=? "
                              "WHERE id=?", (price, price_set, now_iso(), iid))
            self.conn.commit()

    def delete_item(self, iid):
        with self.lock:
            cur = self.conn.execute("DELETE FROM items WHERE id=?", (iid,))
            self._bump()
            self.conn.commit()
            return cur.rowcount > 0

    def set_blob(self, iid, column, data):
        """column: art | rendered | rendered_back | custom_image. data=None löscht."""
        if column not in ("art", "rendered", "rendered_back", "custom_image"):
            raise StoreError("Unbekanntes Bild")
        with self.lock:
            cur = self.conn.execute(f"UPDATE items SET {column}=?, updated_at=? WHERE id=?", (data, now_iso(), iid))
            self._bump()
            self.conn.commit()
            return cur.rowcount > 0

    def blob(self, iid, column):
        if column not in ("art", "rendered", "rendered_back", "custom_image"):
            return None
        with self.lock:
            r = self.conn.execute(f"SELECT {column} FROM items WHERE id=?", (iid,)).fetchone()
        return bytes(r[0]) if r and r[0] is not None else None

    def print_rows(self, pid, ids=None):
        """Alles, was für den Druck gebraucht wird (inkl. Bilder)."""
        wanted = set(ids or [])
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM items WHERE project_id=? ORDER BY position, id", (pid,))]
        return [r for r in rows if not wanted or r["id"] in wanted]

    def items_with_prices(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT id, name, scryfall_id, kind FROM items WHERE kind='scryfall'")]

    # -- Rückseiten ----------------------------------------------------------------
    def backs(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT id, name, created_at FROM backs ORDER BY name")]

    def add_back(self, name, image):
        data = decode_jpeg(image)
        with self.lock:
            cur = self.conn.execute("INSERT INTO backs(name, image, created_at) VALUES(?,?,?)",
                                    ((name or "Rückseite").strip() or "Rückseite", data, now_iso()))
            self._bump()
            self.conn.commit()
        return {"id": cur.lastrowid, "name": name}

    def back_image(self, bid):
        with self.lock:
            r = self.conn.execute("SELECT image FROM backs WHERE id=?", (bid,)).fetchone()
        return bytes(r[0]) if r else None

    def delete_back(self, bid):
        with self.lock:
            self.conn.execute("UPDATE projects SET back_id=NULL WHERE back_id=?", (bid,))
            cur = self.conn.execute("DELETE FROM backs WHERE id=?", (bid,))
            self._bump()
            self.conn.commit()
            return cur.rowcount > 0

    # -- Stil-Vorlagen ----------------------------------------------------------------
    def presets(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM presets ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r, settings=json.loads(r["settings"] or "{}")) for r in rows]

    def save_preset(self, name, settings):
        name = (name or "").strip()
        if not name:
            raise StoreError("Name fehlt")
        with self.lock:
            self.conn.execute("INSERT INTO presets(name, settings, created_at) VALUES(?,?,?) "
                              "ON CONFLICT(name) DO UPDATE SET settings=excluded.settings",
                              (name, json.dumps(settings or {}, ensure_ascii=False), now_iso()))
            self._bump()
            self.conn.commit()
        return self.presets()

    def delete_preset(self, prid):
        with self.lock:
            cur = self.conn.execute("DELETE FROM presets WHERE id=?", (prid,))
            self.conn.commit()
            return cur.rowcount > 0

    # -- Sicherung -----------------------------------------------------------------
    def export_all(self):
        b64 = lambda v: base64.b64encode(bytes(v)).decode("ascii") if v is not None else None  # noqa: E731
        with self.lock:
            projects = [dict(r) for r in self.conn.execute("SELECT * FROM projects ORDER BY id")]
            for p in projects:
                p["items"] = []
                for r in self.conn.execute("SELECT * FROM items WHERE project_id=? ORDER BY position, id", (p["id"],)):
                    d = dict(r)
                    for k in ("art", "custom_image", "rendered", "rendered_back"):
                        d[k] = b64(d[k])
                    p["items"].append(d)
            backs = [dict(r, image=b64(r["image"])) for r in self.conn.execute("SELECT * FROM backs ORDER BY id")]
            presets = [dict(r) for r in self.conn.execute("SELECT name, settings FROM presets ORDER BY id")]
        return {"format": "proxie-maker", "version": 1, "exported_at": now_iso(), "projects": projects,
                "backs": backs, "presets": presets}

    def import_all(self, data, replace=False):
        if not isinstance(data, dict) or data.get("format") != "proxie-maker":
            raise StoreError("Keine Proxie-Maker-Sicherung")
        unb64 = lambda v: base64.b64decode(v) if v else None  # noqa: E731
        res = {"projects": 0, "items": 0, "backs": 0, "presets": 0}
        with self.lock:
            try:
                if replace:
                    for t in ("items", "projects", "backs", "presets"):
                        self.conn.execute(f"DELETE FROM {t}")
                back_map = {}
                for b in data.get("backs") or []:
                    cur = self.conn.execute("INSERT INTO backs(name, image, created_at) VALUES(?,?,?)",
                                            (b.get("name") or "Rückseite", unb64(b.get("image")), b.get("created_at")))
                    back_map[b.get("id")] = cur.lastrowid
                    res["backs"] += 1
                for pr in data.get("presets") or []:
                    self.conn.execute("INSERT OR IGNORE INTO presets(name, settings, created_at) VALUES(?,?,?)",
                                      (pr.get("name"), pr.get("settings") or "{}", now_iso()))
                    res["presets"] += 1
                cols = [c for c in ITEM_FIELDS if c not in ("id", "project_id")]
                for p in data.get("projects") or []:
                    cur = self.conn.execute(
                        "INSERT INTO projects(name, notes, back_id, kind, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                        (p.get("name") or "Import", p.get("notes") or "", back_map.get(p.get("back_id")),
                         p.get("kind") or "list", p.get("created_at"), p.get("updated_at")))
                    res["projects"] += 1
                    for it in p.get("items") or []:
                        vals = [it.get(c) for c in cols]
                        vals[cols.index("settings")] = it.get("settings") or "{}"
                        vals[cols.index("board")] = it.get("board") or "main"
                        vals[cols.index("position")] = it.get("position") or 0
                        vals[cols.index("kind")] = it.get("kind") or "scryfall"
                        vals[cols.index("quantity")] = it.get("quantity") or 1
                        self.conn.execute(
                            f"INSERT INTO items(project_id, {', '.join(cols)}, art, custom_image, rendered, rendered_back)"
                            f" VALUES(?, {', '.join('?' * len(cols))}, ?, ?, ?, ?)",
                            [cur.lastrowid] + vals + [unb64(it.get(k)) for k in ("art", "custom_image", "rendered",
                                                                                 "rendered_back")])
                        res["items"] += 1
                self._bump()
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return res
