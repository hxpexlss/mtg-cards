"""SQLite-Datenbank für die Kartensammlung."""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from .tags import AUTO_TAGS, auto_tags, emblem_matches, is_emblem, merge_tags

CARD_FIELDS = [
    "scryfall_id", "oracle_id", "name", "printed_name", "lang", "set_code", "set_name",
    "collector_number", "rarity", "mana_cost", "cmc", "type_line", "oracle_text",
    "power", "toughness", "loyalty", "colors", "color_identity", "keywords",
    "image_url", "scryfall_uri", "price_eur", "price_eur_foil", "price_usd", "price_usd_foil",
]
USER_FIELDS = ["foil", "quantity", "tags", "notes"]
EXPORT_FIELDS = CARD_FIELDS + USER_FIELDS + ["added_at", "updated_at"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scryfall_id TEXT,
    oracle_id TEXT,
    name TEXT NOT NULL,
    printed_name TEXT,
    lang TEXT DEFAULT 'en',
    set_code TEXT,
    set_name TEXT,
    collector_number TEXT,
    rarity TEXT,
    mana_cost TEXT,
    cmc REAL,
    type_line TEXT,
    oracle_text TEXT,
    power TEXT,
    toughness TEXT,
    loyalty TEXT,
    colors TEXT DEFAULT '',
    color_identity TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    image_url TEXT,
    scryfall_uri TEXT,
    price_eur TEXT,
    price_eur_foil TEXT,
    price_usd TEXT,
    price_usd_foil TEXT,
    foil INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 1,
    tags TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    added_at TEXT,
    updated_at TEXT,
    proxy INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS value_history (
    day TEXT PRIMARY KEY,
    value_eur REAL NOT NULL,
    value_usd REAL NOT NULL,
    cards INTEGER NOT NULL
);
"""

INDEXES = """
DROP INDEX IF EXISTS ux_cards_print_foil;
CREATE UNIQUE INDEX IF NOT EXISTS ux_cards_print_foil_proxy ON cards(scryfall_id, foil, proxy)
    WHERE scryfall_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_cards_name ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_cards_oracle ON cards(oracle_id);
"""

PROXY_TAG = "Proxies"


def is_proxy_tags(tags):
    return any(str(t).lower() == PROXY_TAG.lower() for t in tags or [])


SORTS = {
    "name": "name COLLATE NOCASE ASC",
    "added": "added_at DESC, id DESC",
    "updated": "updated_at DESC, id DESC",
    "cmc": "cmc ASC, name COLLATE NOCASE",
    "set": "set_code ASC, CAST(collector_number AS INTEGER), collector_number",
    "quantity": "quantity DESC, name COLLATE NOCASE",
    "price": "CAST(COALESCE(price_eur, price_usd, '0') AS REAL) DESC",
}


def tags_json(tags):
    """Tags als JSON – Umlaute bleiben lesbar (nicht als \\uXXXX), damit Suche und Filter sie finden."""
    return json.dumps(list(tags), ensure_ascii=False)


def _like(term):
    """LIKE-Muster für einen Suchbegriff; %, _ und \\ werden wörtlich gesucht (ESCAPE '\\')."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                return list(json.loads(s))
            except ValueError:
                pass
        return [p.strip() for p in s.replace(",", ";").split(";") if p.strip()]
    return [v]


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "ja", "foil", "y", "x", "etched")
    return bool(v)


class Database:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.executescript(INDEXES)
            self.conn.commit()

    def _tag_tokens_once(self):
        """Einmalig: vorhandene Token-Karten bekommen den automatischen Tag "Token"."""
        done = self.conn.execute("SELECT value FROM meta WHERE key='token_tag_v1'").fetchone()
        if done:
            return
        for cid, tags in self.conn.execute(
                "SELECT id, tags FROM cards WHERE type_line LIKE 'Token%'").fetchall():
            tag_list = _as_list(tags)
            if "Token" not in tag_list:
                self.conn.execute("UPDATE cards SET tags=? WHERE id=?", (tags_json(tag_list + ["Token"]), cid))
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('token_tag_v1', '1')")

    def _tag_emblems_once(self):
        """Einmalig: vorhandene Embleme bekommen den automatischen Tag "Emblem"."""
        if self.conn.execute("SELECT value FROM meta WHERE key='emblem_tag_v1'").fetchone():
            return
        for cid, tags in self.conn.execute(
                "SELECT id, tags FROM cards WHERE type_line LIKE 'Emblem%'").fetchall():
            tag_list = _as_list(tags)
            if "Emblem" not in tag_list:
                self.conn.execute("UPDATE cards SET tags=? WHERE id=?", (tags_json(tag_list + ["Emblem"]), cid))
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('emblem_tag_v1', '1')")

    def _tags_utf8_once(self):
        """Einmalig: Tags mit Umlauten lagen als \\uXXXX in der Datenbank und waren nicht filterbar."""
        if self.conn.execute("SELECT value FROM meta WHERE key='tags_utf8_v1'").fetchone():
            return
        for cid, tags in self.conn.execute("SELECT id, tags FROM cards WHERE tags LIKE '%\\u%'").fetchall():
            self.conn.execute("UPDATE cards SET tags=? WHERE id=?", (tags_json(_as_list(tags)), cid))
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('tags_utf8_v1', '1')")

    def _migrate(self):
        """Ältere Datenbanken: Spalte 'proxy' ergänzen (Proxies sind eigene Einträge)."""
        self._tag_tokens_once()
        self._tag_emblems_once()
        self._tags_utf8_once()
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(cards)")}
        if "proxy" not in cols:
            self.conn.execute("ALTER TABLE cards ADD COLUMN proxy INTEGER NOT NULL DEFAULT 0")
            self.conn.execute("UPDATE cards SET proxy=1 WHERE tags LIKE ?", (f'%"{PROXY_TAG}"%',))

    # -- Hilfsfunktionen --------------------------------------------------
    def _row(self, row):
        if row is None:
            return None
        d = dict(row)
        d["foil"] = bool(d["foil"])
        d["proxy"] = bool(d.get("proxy"))
        d["tags"] = _as_list(d.get("tags"))
        d["keywords"] = _as_list(d.get("keywords"))
        return d

    def _bump(self):
        cur = self.conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
        rev = int(cur[0]) + 1 if cur else 1
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('revision', ?)", (str(rev),))
        return rev

    def revision(self):
        with self._lock:
            cur = self.conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
            return int(cur[0]) if cur else 0

    def close(self):
        with self._lock:
            self.conn.close()

    # -- CRUD -------------------------------------------------------------
    def get(self, card_id):
        with self._lock:
            return self._row(self.conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone())

    def find_owned(self, scryfall_id=None, oracle_id=None):
        """Bestand einer Karte: exakter Druck und alle Drucke derselben Karte."""
        with self._lock:
            exact = 0
            total = 0
            if scryfall_id:
                exact = self.conn.execute(
                    "SELECT COALESCE(SUM(quantity),0) FROM cards WHERE scryfall_id=? AND proxy=0", (scryfall_id,)
                ).fetchone()[0]
            if oracle_id:
                total = self.conn.execute(
                    "SELECT COALESCE(SUM(quantity),0) FROM cards WHERE oracle_id=? AND proxy=0", (oracle_id,)
                ).fetchone()[0]
            return {"this_print": exact, "all_prints": max(total, exact)}

    def _insert(self, card, foil, quantity, tags, notes, added_at=None, updated_at=None):
        ts = now_iso()
        values = {f: card.get(f) for f in CARD_FIELDS}
        values["keywords"] = json.dumps(_as_list(values.get("keywords")))
        values["colors"] = values.get("colors") or ""
        values["color_identity"] = values.get("color_identity") or ""
        values.update({
            "foil": 1 if foil else 0,
            "quantity": int(quantity),
            "tags": tags_json(tags),
            "proxy": 1 if is_proxy_tags(tags) else 0,
            "notes": notes or "",
            "added_at": added_at or ts,
            "updated_at": updated_at or ts,
        })
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = self.conn.execute(f"INSERT INTO cards ({cols}) VALUES ({marks})", list(values.values()))
        return cur.lastrowid

    def add(self, card, foil=False, quantity=1, tags=None, notes="", _commit=True, **ts):
        """Fügt eine Karte hinzu; existiert der Druck (gleiche Foil-Art, Proxy/echt) schon, wird die Anzahl erhöht.

        Gibt (karte, neu_angelegt) zurück.
        """
        quantity = max(1, int(quantity or 1))
        tags = merge_tags(card.get("auto_tags") or auto_tags(card), tags)
        proxy = 1 if is_proxy_tags(tags) else 0
        with self._lock:
            existing = None
            if card.get("scryfall_id"):
                existing = self.conn.execute(
                    "SELECT * FROM cards WHERE scryfall_id=? AND foil=? AND proxy=?",
                    (card["scryfall_id"], 1 if foil else 0, proxy),
                ).fetchone()
            if existing:
                ex = self._row(existing)
                new_tags = merge_tags(ex["tags"], tags)
                new_notes = ex["notes"] or notes or ""
                self.conn.execute(
                    "UPDATE cards SET quantity=quantity+?, tags=?, notes=?, updated_at=? WHERE id=?",
                    (quantity, tags_json(new_tags), new_notes, now_iso(), ex["id"]),
                )
                card_id, created = ex["id"], False
            else:
                card_id = self._insert(card, foil, quantity, tags, notes, **ts)
                created = True
            self._bump()
            if _commit:
                self.conn.commit()
            return self.get(card_id), created

    def update(self, card_id, changes):
        allowed = {"quantity", "foil", "tags", "notes"}
        sets, vals = [], []
        for k, v in changes.items():
            if k not in allowed:
                continue
            if k == "tags":
                tag_list = merge_tags(_as_list(v))
                v = tags_json(tag_list)
                sets.append("proxy=?")
                vals.append(1 if is_proxy_tags(tag_list) else 0)
            elif k == "foil":
                v = 1 if _bool(v) else 0
            elif k == "quantity":
                v = int(v)
            sets.append(f"{k}=?")
            vals.append(v)
        with self._lock:
            if self.get(card_id) is None:
                return None
            if "quantity" in changes and int(changes["quantity"]) <= 0:
                self.conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
                self._bump()
                self.conn.commit()
                return {"id": card_id, "deleted": True}
            if sets:
                sets.append("updated_at=?")
                vals.append(now_iso())
                try:
                    self.conn.execute(f"UPDATE cards SET {', '.join(sets)} WHERE id=?", vals + [card_id])
                except sqlite3.IntegrityError:
                    # Foil-/Proxy-Umschaltung kollidiert mit vorhandenem Eintrag -> zusammenführen
                    self.conn.rollback()
                    return self._merge_into_existing(card_id, changes)
                self._bump()
                self.conn.commit()
            return self.get(card_id)

    def _merge_into_existing(self, card_id, changes):
        src = self.get(card_id)
        foil = (1 if _bool(changes["foil"]) else 0) if "foil" in changes else (1 if src["foil"] else 0)
        tags_new = _as_list(changes["tags"]) if "tags" in changes else src["tags"]
        proxy = 1 if is_proxy_tags(tags_new) else 0
        dst = self._row(self.conn.execute(
            "SELECT * FROM cards WHERE scryfall_id=? AND foil=? AND proxy=? AND id!=?",
            (src["scryfall_id"], foil, proxy, card_id)).fetchone())
        qty = int(changes.get("quantity", src["quantity"]))
        tags = merge_tags(dst["tags"], _as_list(changes.get("tags", src["tags"])))
        self.conn.execute("UPDATE cards SET quantity=quantity+?, tags=?, updated_at=? WHERE id=?",
                          (qty, tags_json(tags), now_iso(), dst["id"]))
        self.conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        self._bump()
        self.conn.commit()
        return self.get(dst["id"])

    def refresh_card_data(self, card_id, card):
        """Aktualisiert Scryfall-Daten einer vorhandenen Karte, behält Benutzerdaten."""
        with self._lock:
            ex = self.get(card_id)
            if ex is None:
                return None
            manual = [t for t in ex["tags"] if t not in AUTO_TAGS]
            tags = merge_tags(card.get("auto_tags") or auto_tags(card), manual)
            sets = [f"{f}=?" for f in CARD_FIELDS]
            vals = [json.dumps(card.get(f) or []) if f == "keywords" else card.get(f) for f in CARD_FIELDS]
            sets += ["tags=?", "updated_at=?"]
            vals += [tags_json(tags), now_iso()]
            self.conn.execute(f"UPDATE cards SET {', '.join(sets)} WHERE id=?", vals + [card_id])
            self._bump()
            self.conn.commit()
            return self.get(card_id)

    def change_print(self, card_id, card):
        """Anderen Druck (Edition/Sprache) für einen Eintrag übernehmen. Gibt es den Druck schon
        (gleiche Foil-Art, Proxy/echt), werden die Einträge zusammengeführt."""
        with self._lock:
            ex = self.get(card_id)
            if ex is None:
                return None
            dup = self.conn.execute(
                "SELECT id FROM cards WHERE scryfall_id=? AND foil=? AND proxy=? AND id!=?",
                (card.get("scryfall_id"), 1 if ex["foil"] else 0, 1 if ex["proxy"] else 0, card_id)).fetchone()
            if dup:
                tags = merge_tags(self.get(dup[0])["tags"], ex["tags"])
                self.conn.execute("UPDATE cards SET quantity=quantity+?, tags=?, updated_at=? WHERE id=?",
                                  (ex["quantity"], tags_json(tags), now_iso(), dup[0]))
                self.conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
                self.conn.commit()
                card_id = dup[0]
            return self.refresh_card_data(card_id, card)

    def related(self, card):
        """Verknüpfungen Emblem <-> Planeswalker. Wird bei jeder Abfrage neu berechnet,
        deshalb ist die Reihenfolge des Hinzufügens egal."""
        if not card:
            return []
        tl = card.get("type_line") or ""
        cols = "id, name, printed_name, set_code, collector_number, image_url, quantity, type_line, proxy"
        with self._lock:
            if is_emblem(card):
                rows = [dict(r) for r in self.conn.execute(
                    f"SELECT {cols} FROM cards WHERE type_line LIKE '%Planeswalker%'")]
                hits = [r for r in rows if emblem_matches(card, r)]
                kind = "planeswalker"
            elif "Planeswalker" in tl.split("//")[0] or "Planeswalker" in tl:
                rows = [dict(r) for r in self.conn.execute(
                    f"SELECT {cols} FROM cards WHERE type_line LIKE 'Emblem%'")]
                hits = [r for r in rows if emblem_matches(r, card)]
                kind = "emblem"
            else:
                return []
        for h in hits:
            h["kind"] = kind
            h["proxy"] = bool(h["proxy"])
        return sorted(hits, key=lambda h: (h["name"].lower(), h["set_code"] or ""))

    def delete(self, card_id):
        with self._lock:
            cur = self.conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
            if cur.rowcount:
                self._bump()
            self.conn.commit()
            return cur.rowcount > 0

    def clear(self, _commit=True):
        with self._lock:
            self.conn.execute("DELETE FROM cards")
            self._bump()
            if _commit:
                self.conn.commit()

    def commit(self):
        with self._lock:
            self.conn.commit()

    # -- Suche ------------------------------------------------------------
    def search(self, q="", ci="", ci_mode="within", tag="", type_="", rarity="", set_code="",
               foil=None, sort="name", limit=500, offset=0, dup_min=0):
        where, vals = [], []
        dup_min = int(dup_min or 0)
        if dup_min > 1:
            # Doppelte: alle Drucke einer Karte (normal + Foil, alle Editionen/Sprachen) zusammengezählt
            where.append("proxy = 0 AND COALESCE(oracle_id, name) IN (SELECT COALESCE(oracle_id, name) FROM cards "
                         "WHERE proxy = 0 GROUP BY COALESCE(oracle_id, name) HAVING SUM(quantity) >= ?)")
            vals.append(dup_min)
        for term in (q or "").split():
            like = _like(term)
            where.append("(name LIKE ? ESCAPE '\\' OR printed_name LIKE ? ESCAPE '\\' OR type_line LIKE ? ESCAPE '\\'"
                         " OR oracle_text LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')")
            vals += [like] * 6
        if type_:
            where.append("type_line LIKE ? ESCAPE '\\'")
            vals.append(_like(type_))
        if rarity:
            where.append("rarity = ?")
            vals.append(rarity.lower())
        if set_code:
            where.append("set_code = ?")
            vals.append(set_code.upper())
        if foil is not None:
            where.append("foil = ?")
            vals.append(1 if foil else 0)
        sql = "SELECT * FROM cards"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + SORTS.get(sort, SORTS["name"])
        with self._lock:
            rows = [self._row(r) for r in self.conn.execute(sql, vals).fetchall()]

        if tag:
            # exakter Tag (ohne Groß-/Kleinschreibung) – auch mit Umlauten oder Sonderzeichen
            wanted_tag = str(tag).strip().lower()
            rows = [r for r in rows if any(str(t).lower() == wanted_tag for t in r["tags"])]

        ci = (ci or "").upper()
        if ci:
            wanted = set(c for c in ci if c in "WUBRG")
            colorless = "C" in ci

            def ok(card):
                have = set(card["color_identity"] or "")
                if ci_mode == "exact":
                    return have == wanted
                if ci_mode == "includes":
                    return wanted <= have and (not colorless or not have)
                # within: Karte passt in ein Deck mit dieser Farbidentität
                return have <= wanted if wanted else (not have)

            rows = [r for r in rows if ok(r)]
        total = len(rows)
        limit = max(1, min(int(limit or 500), 5000))
        offset = max(0, int(offset or 0))
        return rows[offset:offset + limit], total

    def duplicate_summary(self, dup_min=2):
        """Zusammenfassung doppelter Karten: Anzahl Karten, überzählige Exemplare, deren Wert."""
        dup_min = max(2, int(dup_min or 2))
        groups = {}
        for c in self.all():
            if c["proxy"]:
                continue
            g = groups.setdefault(c["oracle_id"] or c["name"], {"qty": 0, "prices": []})
            g["qty"] += c["quantity"]
            g["prices"] += [self.card_price(c)] * c["quantity"]
        dups = [g for g in groups.values() if g["qty"] >= dup_min]
        extra = 0
        extra_value = 0.0
        for g in dups:
            # behalten: 1 Exemplar (das wertvollste), Rest = überzählig
            prices = sorted(g["prices"], reverse=True)
            extra += g["qty"] - 1
            extra_value += sum(prices[1:])
        return {"min": dup_min, "cards": len(dups), "copies": sum(g["qty"] for g in dups),
                "extra_copies": extra, "extra_value_eur": round(extra_value, 2)}

    def set_ownership(self, set_code):
        """Besitz pro Sammlernummer einer Edition: {cn: {"quantity", "foil", "ids"}}"""
        out = {}
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, collector_number, quantity, foil FROM cards WHERE set_code=? AND proxy=0", (set_code.upper(),))
            for cid, cn, qty, foil in rows:
                o = out.setdefault(cn or "", {"quantity": 0, "foil": 0, "ids": []})
                o["quantity"] += qty
                o["foil"] += qty if foil else 0
                o["ids"].append(cid)
        return out

    def owned_sets(self):
        with self._lock:
            return [dict(zip(("set_code", "set_name", "prints", "cards"), r)) for r in self.conn.execute(
                "SELECT set_code, MAX(set_name), COUNT(DISTINCT collector_number), SUM(quantity) FROM cards "
                "WHERE set_code IS NOT NULL AND set_code != '' AND proxy=0 GROUP BY set_code")]

    def all(self):
        with self._lock:
            return [self._row(r) for r in self.conn.execute("SELECT * FROM cards ORDER BY name").fetchall()]

    def tag_counts(self):
        counts = {}
        for card in self.all():
            for t in card["tags"]:
                counts[t] = counts.get(t, 0) + card["quantity"]
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())))

    @staticmethod
    def card_price(c, currency="eur"):
        """Preis einer Karte (Foil-Preis für Foils, sonst normal; Fallback auf den jeweils anderen).

        Proxies haben keinen Sammlungswert (0).
        """
        if c.get("proxy"):
            return 0.0
        normal, foil = c.get(f"price_{currency}"), c.get(f"price_{currency}_foil")
        price = (foil or normal) if c.get("foil") else (normal or foil)
        try:
            return float(price) if price else 0.0
        except (TypeError, ValueError):
            return 0.0

    def get_meta(self, key, default=None):
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key, value):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value)))
            self.conn.commit()

    def snapshot_value(self, day=None):
        """Speichert den heutigen Sammlungswert (für den Wertverlauf)."""
        cards = self.all()
        eur = sum(self.card_price(c, "eur") * c["quantity"] for c in cards)
        usd = sum(self.card_price(c, "usd") * c["quantity"] for c in cards)
        day = day or now_iso()[:10]
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO value_history(day, value_eur, value_usd, cards) VALUES(?,?,?,?)",
                              (day, round(eur, 2), round(usd, 2), sum(c["quantity"] for c in cards)))
            self.conn.commit()

    def value_history(self, days=365):
        with self._lock:
            rows = self.conn.execute(
                "SELECT day, value_eur, value_usd, cards FROM value_history ORDER BY day DESC LIMIT ?", (days,))
            return [dict(zip(("day", "value_eur", "value_usd", "cards"), r)) for r in rows][::-1]

    def detailed_stats(self):
        """Auswertungen für die Statistik-Ansicht."""
        cards = self.all()
        total_cards = sum(c["quantity"] for c in cards)

        def bucket(keyfn):
            out = {}
            for c in cards:
                k = keyfn(c)
                b = out.setdefault(k, {"key": k, "cards": 0, "value_eur": 0.0})
                b["cards"] += c["quantity"]
                b["value_eur"] += self.card_price(c) * c["quantity"]
            for b in out.values():
                b["value_eur"] = round(b["value_eur"], 2)
            return sorted(out.values(), key=lambda b: -b["cards"])

        types = ("Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land")
        front = lambda c: (c["type_line"] or "").split("//")[0]  # noqa: E731
        rarity_order = ["common", "uncommon", "rare", "mythic", "special", "bonus"]
        curve = {}
        for c in cards:
            if "Land" in front(c) or c["cmc"] is None:
                continue
            k = min(int(c["cmc"]), 7)
            curve[k] = curve.get(k, 0) + c["quantity"]
        months = {}
        for c in cards:
            m = (c["added_at"] or "")[:7]
            if m:
                months[m] = months.get(m, 0) + c["quantity"]
        top = sorted(cards, key=lambda c: -self.card_price(c))[:25]
        sets = bucket(lambda c: f"{c['set_code']}|{c['set_name'] or ''}")
        return {
            "cards": total_cards,
            "entries": len(cards),
            "unique_names": len({c["name"] for c in cards}),
            "foils": sum(c["quantity"] for c in cards if c["foil"]),
            "value_eur": round(sum(self.card_price(c) * c["quantity"] for c in cards), 2),
            "value_usd": round(sum(self.card_price(c, "usd") * c["quantity"] for c in cards), 2),
            "without_price": sum(c["quantity"] for c in cards if not c["proxy"] and not self.card_price(c)),
            "proxies": sum(c["quantity"] for c in cards if c["proxy"]),
            "by_color_identity": bucket(lambda c: c["color_identity"] or "C"),
            "by_rarity": sorted(bucket(lambda c: c["rarity"] or "?"),
                                key=lambda b: rarity_order.index(b["key"]) if b["key"] in rarity_order else 99),
            "by_type": [b for b in bucket(lambda c: next((t for t in types if t in front(c)), "Sonstige"))],
            "by_set": [dict(b, key=b["key"].split("|")[0], name=b["key"].split("|", 1)[1]) for b in sets[:15]],
            "set_count": len(sets),
            "mana_curve": [{"cmc": k, "cards": curve.get(k, 0)} for k in range(0, 8)],
            "added_per_month": [{"month": k, "cards": months[k]} for k in sorted(months)[-12:]],
            "top_cards": [{"id": c["id"], "name": c["name"], "set_code": c["set_code"], "foil": c["foil"],
                           "quantity": c["quantity"], "price_eur": round(self.card_price(c), 2),
                           "total_eur": round(self.card_price(c) * c["quantity"], 2), "image_url": c["image_url"]}
                          for c in top if self.card_price(c) > 0],
            "value_history": self.value_history(),
            "last_price_refresh": self.get_meta("last_price_refresh"),
        }

    def stats(self):
        cards = self.all()
        by_color = {}
        value_eur = 0.0
        for c in cards:
            key = c["color_identity"] or "C"
            by_color[key] = by_color.get(key, 0) + c["quantity"]
            value_eur += self.card_price(c) * c["quantity"]
        return {
            "entries": len(cards),
            "cards": sum(c["quantity"] for c in cards),
            "unique_names": len({c["name"] for c in cards}),
            "by_color_identity": by_color,
            "tags": self.tag_counts(),
            "value_eur": round(value_eur, 2),
            "revision": self.revision(),
        }
