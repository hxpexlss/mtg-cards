"""Wunschliste: Karten mit Wunsch-Anzahl und Zielpreis; Hinweis, sobald der Preis darunter fällt."""

from .db import now_iso
from .scryfall import ScryfallError, normalize_card

WISH_SCHEMA = """
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    oracle_id TEXT,
    scryfall_id TEXT,              -- gesetzt = bestimmter Druck, leer = beliebiger (günstigster) Druck
    set_code TEXT,
    collector_number TEXT,
    type_line TEXT,
    mana_cost TEXT,
    color_identity TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    foil INTEGER NOT NULL DEFAULT 0,
    max_price_eur REAL,            -- Zielpreis pro Stück (NULL = kein Zielpreis)
    price_eur REAL,                -- aktueller (günstigster) Preis
    price_set TEXT,                -- Edition des günstigsten Drucks
    price_checked_at TEXT,
    target_reached_at TEXT,        -- wann der Zielpreis (zuletzt) erreicht wurde
    notes TEXT NOT NULL DEFAULT '',
    added_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_wishlist_oracle ON wishlist(oracle_id);
"""


def _price(card, foil):
    vals = [card.get("price_eur_foil"), card.get("price_eur")] if foil else [card.get("price_eur"), card.get("price_eur_foil")]
    for v in vals:
        try:
            if v:
                return float(v)
        except (TypeError, ValueError):
            pass
    return None


class Wishlist:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(WISH_SCHEMA)
            db.conn.commit()

    # -- Lesen ---------------------------------------------------------------
    def _owned(self):
        out = {}
        for oid, name, qty in self.db.conn.execute("SELECT oracle_id, name, quantity FROM cards WHERE proxy=0"):
            out[oid or name.lower()] = out.get(oid or name.lower(), 0) + qty
        return out

    def _row(self, r, owned):
        d = dict(r)
        d["foil"] = bool(d["foil"])
        d["any_print"] = not d["scryfall_id"]
        d["owned"] = owned.get(d["oracle_id"] or d["name"].lower(), 0)
        d["target_reached"] = (d["max_price_eur"] is not None and d["price_eur"] is not None
                               and d["price_eur"] <= d["max_price_eur"])
        return d

    def list(self):
        with self.db._lock:
            owned = self._owned()
            rows = self.db.conn.execute("SELECT * FROM wishlist ORDER BY name COLLATE NOCASE").fetchall()
            items = [self._row(r, owned) for r in rows]
        alerts = [i for i in items if i["target_reached"]]
        total = sum((i["price_eur"] or 0) * i["quantity"] for i in items)
        return {"items": items, "alerts": len(alerts), "total_eur": round(total, 2)}

    def get(self, wid):
        with self.db._lock:
            r = self.db.conn.execute("SELECT * FROM wishlist WHERE id=?", (wid,)).fetchone()
            return self._row(r, self._owned()) if r else None

    # -- Schreiben -------------------------------------------------------------
    def add(self, card, quantity=1, max_price=None, any_print=True, foil=False, notes="", price=None, price_set=None):
        """card: normalisierte Scryfall-Karte. Existiert der Wunsch schon, wird die Anzahl erhöht."""
        ts = now_iso()
        price = price if price is not None else _price(card, foil)
        with self.db._lock:
            ex = self.db.conn.execute(
                "SELECT id FROM wishlist WHERE (oracle_id=? OR name=?) AND COALESCE(scryfall_id,'')=? AND foil=?",
                (card.get("oracle_id"), card["name"], "" if any_print else card.get("scryfall_id") or "",
                 1 if foil else 0)).fetchone()
            if ex:
                self.db.conn.execute("UPDATE wishlist SET quantity=quantity+?, updated_at=? WHERE id=?",
                                     (int(quantity), ts, ex[0]))
                wid = ex[0]
            else:
                cur = self.db.conn.execute(
                    """INSERT INTO wishlist(name, oracle_id, scryfall_id, set_code, collector_number, type_line,
                       mana_cost, color_identity, image_url, quantity, foil, max_price_eur, price_eur, price_set,
                       price_checked_at, notes, added_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (card["name"], card.get("oracle_id"), None if any_print else card.get("scryfall_id"),
                     card.get("set_code"), card.get("collector_number"), card.get("type_line"), card.get("mana_cost"),
                     card.get("color_identity") or "", card.get("image_url"), int(quantity), 1 if foil else 0,
                     max_price, price, price_set or card.get("set_code"), ts if price is not None else None,
                     notes or "", ts, ts))
                wid = cur.lastrowid
            self._update_target_flag(wid)
            self.db._bump()
            self.db.conn.commit()
        return self.get(wid)

    def update(self, wid, changes):
        sets, vals = [], []
        for k in ("quantity", "max_price_eur", "notes", "foil"):
            if k in changes:
                v = changes[k]
                if k == "max_price_eur":
                    v = None if v in (None, "") else float(str(v).replace(",", "."))
                elif k == "quantity":
                    v = int(v)
                elif k == "foil":
                    v = 1 if v else 0
                sets.append(f"{k}=?")
                vals.append(v)
        with self.db._lock:
            if not self.db.conn.execute("SELECT 1 FROM wishlist WHERE id=?", (wid,)).fetchone():
                return None
            if "quantity" in changes and int(changes["quantity"]) <= 0:
                self.db.conn.execute("DELETE FROM wishlist WHERE id=?", (wid,))
                self.db._bump()
                self.db.conn.commit()
                return {"id": wid, "deleted": True}
            if sets:
                sets.append("updated_at=?")
                vals.append(now_iso())
                self.db.conn.execute(f"UPDATE wishlist SET {', '.join(sets)} WHERE id=?", vals + [wid])
                self._update_target_flag(wid)
                self.db._bump()
                self.db.conn.commit()
        return self.get(wid)

    def delete(self, wid):
        with self.db._lock:
            cur = self.db.conn.execute("DELETE FROM wishlist WHERE id=?", (wid,))
            self.db._bump()
            self.db.conn.commit()
            return cur.rowcount > 0

    def _update_target_flag(self, wid):
        r = self.db.conn.execute("SELECT price_eur, max_price_eur, target_reached_at FROM wishlist WHERE id=?",
                                 (wid,)).fetchone()
        if not r:
            return
        reached = r[0] is not None and r[1] is not None and r[0] <= r[1]
        if reached and not r[2]:
            self.db.conn.execute("UPDATE wishlist SET target_reached_at=? WHERE id=?", (now_iso(), wid))
        elif not reached and r[2]:
            self.db.conn.execute("UPDATE wishlist SET target_reached_at=NULL WHERE id=?", (wid,))

    def fulfill(self, card, quantity):
        """Karte wurde zur Sammlung hinzugefügt -> passenden Wunsch reduzieren. Gibt erfüllte Wünsche zurück."""
        done = []
        remaining = int(quantity)
        with self.db._lock:
            rows = self.db.conn.execute(
                "SELECT id, name, quantity, scryfall_id FROM wishlist WHERE oracle_id=? OR (oracle_id IS NULL AND name=?)"
                " ORDER BY scryfall_id IS NULL",   # bestimmter Druck zuerst
                (card.get("oracle_id"), card.get("name"))).fetchall()
            for wid, name, qty, sid in rows:
                if remaining <= 0:
                    break
                if sid and sid != card.get("scryfall_id"):
                    continue
                take = min(qty, remaining)
                remaining -= take
                if take >= qty:
                    self.db.conn.execute("DELETE FROM wishlist WHERE id=?", (wid,))
                else:
                    self.db.conn.execute("UPDATE wishlist SET quantity=quantity-?, updated_at=? WHERE id=?",
                                         (take, now_iso(), wid))
                done.append({"id": wid, "name": name, "fulfilled": take, "remaining": qty - take})
            if done:
                self.db._bump()
                self.db.conn.commit()
        return done

    # -- Preise ------------------------------------------------------------------
    def refresh_prices(self, scryfall):
        """Aktualisiert die Preise aller Wünsche. Bei 'beliebiger Druck' zählt der günstigste Druck."""
        with self.db._lock:
            rows = [dict(r) for r in self.db.conn.execute("SELECT * FROM wishlist")]
        specific = [r["scryfall_id"] for r in rows if r["scryfall_id"]]
        fetched = scryfall.collection(specific) if specific else {}
        updated = 0
        for r in rows:
            price, pset = None, r["price_set"]
            try:
                if r["scryfall_id"]:
                    raw = fetched.get(r["scryfall_id"])
                    if raw:
                        price = _price(normalize_card(raw), r["foil"])
                else:
                    best = None
                    for raw in scryfall.prints(r["name"]):
                        c = normalize_card(raw)
                        p = _price(c, r["foil"])
                        if p is not None and (best is None or p < best[0]):
                            best = (p, c["set_code"])
                    if best:
                        price, pset = best
            except ScryfallError:
                continue
            if price is None:
                continue
            with self.db._lock:
                self.db.conn.execute(
                    "UPDATE wishlist SET price_eur=?, price_set=?, price_checked_at=? WHERE id=?",
                    (price, pset, now_iso(), r["id"]))
                self._update_target_flag(r["id"])
                self.db.conn.commit()
            updated += 1
        with self.db._lock:
            self.db._bump()
            self.db.conn.commit()
        return {"updated": updated, "total": len(rows)}

    def cheapest_print(self, scryfall, name, foil=False):
        best = None
        for raw in scryfall.prints(name):
            c = normalize_card(raw)
            p = _price(c, foil)
            if p is not None and (best is None or p < best[0]):
                best = (p, c["set_code"])
        return best


_EXPORT = ("name", "oracle_id", "scryfall_id", "set_code", "collector_number", "type_line", "mana_cost",
           "color_identity", "image_url", "quantity", "foil", "max_price_eur", "price_eur", "price_set", "notes",
           "added_at")


def export_wishlist(db):
    Wishlist(db)
    with db._lock:
        return [{k: r[k] for k in _EXPORT} for r in db.conn.execute("SELECT * FROM wishlist ORDER BY id")]


def import_wishlist(db, items, replace=False):
    Wishlist(db)
    count = 0
    with db._lock:
        if replace:
            db.conn.execute("DELETE FROM wishlist")
        existing = {(r[0] or "").lower() for r in db.conn.execute("SELECT name FROM wishlist")}
        for it in items or []:
            if not isinstance(it, dict) or not it.get("name") or it["name"].lower() in existing:
                continue
            vals = [it.get(k) for k in _EXPORT]
            db.conn.execute(f"INSERT INTO wishlist({', '.join(_EXPORT)}, updated_at) VALUES({', '.join('?' * len(_EXPORT))}, ?)",
                            vals + [now_iso()])
            count += 1
        db._bump()
        db.conn.commit()
    return count
