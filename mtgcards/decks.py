"""Deck-Verwaltung: Decklisten importieren und mit der Sammlung abgleichen."""

import json
import re

from .db import now_iso
from .scryfall import ScryfallError, normalize_card

BOARDS = ("commander", "companion", "main", "side", "maybe")
DECK_BOARDS = ("commander", "companion", "main")    # zählen zum Deck (Bestand, Fehlende, Reservierung)
_PARTNER_KW = {"partner", "partner with", "friends forever", "choose a background", "doctor's companion"}
STATUSES = ("owned", "build")   # Besitz = Deck ist gebaut/vorhanden, Bau = Deck wird zusammengestellt


def _status(v):
    return v if v in STATUSES else "build"

DECK_SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'commander',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS deck_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    oracle_id TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    board TEXT NOT NULL DEFAULT 'main',
    type_line TEXT,
    mana_cost TEXT,
    cmc REAL,
    color_identity TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    keywords TEXT NOT NULL DEFAULT '[]',
    UNIQUE(deck_id, name, board)
);
CREATE INDEX IF NOT EXISTS ix_deck_cards_deck ON deck_cards(deck_id);
"""

_HEADERS = {
    "commander": "commander", "commanders": "commander", "kommandeur": "commander",
    "companion": "companion", "begleiter": "companion", "deck": "main", "main": "main", "mainboard": "main", "maindeck": "main",
    "sideboard": "side", "side": "side", "maybeboard": "maybe", "maybe": "maybe", "considering": "maybe",
}
_LINE = re.compile(
    r"^(?:(?P<qty>\d+)\s*x?\s+)?(?P<name>.+?)"
    r"(?:\s+[\(\[](?P<set>[A-Za-z0-9]{2,6})[\)\]](?:\s+(?P<cn>[\w\-★]+))?)?"
    r"(?P<flags>(?:\s+\*[A-Za-z]+\*)*)\s*$"
)
_TYPE_ORDER = ["Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"]


def parse_decklist(text):
    """Liest gängige Decklisten-Formate (Moxfield, Arena, MTGO, Archidekt-Text).

    Gibt Liste von dicts {quantity, name, set, cn, board} zurück.
    """
    out = []
    board = "main"
    for raw in text.splitlines():
        line = raw.strip().replace("’", "'")
        if not line:
            continue
        header = line.strip("/#: ").lower()
        if header in _HEADERS:
            board = _HEADERS[header]
            continue
        if line.startswith(("#", "//")):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        flags = (m.group("flags") or "").upper()
        line_board = "commander" if "*CMDR*" in flags else board
        out.append({
            "quantity": int(m.group("qty") or 1),
            "name": name,
            "set": m.group("set"),
            "cn": m.group("cn"),
            "board": line_board,
        })
    return out


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _kw(card):
    return {str(k).lower() for k in card.get("keywords") or []}


def _role_warning(card, commanders):
    """Hinweis, wenn eine Karte ihre Rolle (Commander/Partner/Companion) eigentlich nicht erfüllen kann."""
    front = (card.get("type_line") or "").split("//")[0]
    if card["board"] == "commander":
        legendary = "Legendary" in front and ("Creature" in front or "Planeswalker" in front)
        background = "Background" in front
        if not (legendary or background):
            return "Kein legendäres Wesen – darf normalerweise nicht Commander sein"
        if len(commanders) > 2:
            return "Mehr als zwei Commander"
        if len(commanders) == 2:
            others = [o for o in commanders if o is not card]
            pair_ok = bool(_kw(card) & _PARTNER_KW) or background or any(
                "Background" in (o.get("type_line") or "") for o in others)
            if not pair_ok:
                return "Zwei Commander, aber diese Karte hat keine Partner-Fähigkeit"
    if card["board"] == "companion" and "companion" not in _kw(card):
        return "Karte hat keine Companion-Fähigkeit"
    return None


class DeckStore:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.execute("PRAGMA foreign_keys=ON")
            db.conn.executescript(DECK_SCHEMA)
            cols = {r[1] for r in db.conn.execute("PRAGMA table_info(decks)")}
            if "status" not in cols:
                db.conn.execute("ALTER TABLE decks ADD COLUMN status TEXT NOT NULL DEFAULT 'build'")
            card_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(deck_cards)")}
            for col in ("price_eur", "price_usd"):
                if col not in card_cols:
                    db.conn.execute(f"ALTER TABLE deck_cards ADD COLUMN {col} REAL")
            db.conn.commit()

    # -- Hilfen ---------------------------------------------------------------
    def _owned_maps(self, proxy=0):
        """Bestand nach oracle_id und Name; proxy=0 echte Karten, proxy=1 nur Proxies."""
        by_oracle, by_name = {}, {}
        for oid, name, qty in self.db.conn.execute(
                "SELECT oracle_id, name, quantity FROM cards WHERE proxy=?", (proxy,)):
            if oid:
                by_oracle[oid] = by_oracle.get(oid, 0) + qty
            key = (name or "").lower()
            by_name[key] = by_name.get(key, 0) + qty
        return by_oracle, by_name

    def _price_map(self):
        """Durchschnittlicher Stückpreis (EUR) der echten Karten in der Sammlung nach oracle_id und Name."""
        sums_o, sums_n = {}, {}
        for row in self.db.conn.execute(
                "SELECT oracle_id, name, quantity, foil, price_eur, price_eur_foil FROM cards WHERE proxy=0"):
            c = dict(row)
            p = self.db.card_price(c)
            if p <= 0:
                continue
            for key, sums in ((c["oracle_id"], sums_o), ((c["name"] or "").lower(), sums_n)):
                if key:
                    s = sums.setdefault(key, [0.0, 0])
                    s[0] += p * c["quantity"]
                    s[1] += c["quantity"]
        avg = lambda d: {k: v[0] / v[1] for k, v in d.items() if v[1]}  # noqa: E731
        return avg(sums_o), avg(sums_n)

    def refresh_prices(self, scryfall):
        """Marktpreise (Standard-Druck) für alle Deckkarten aktualisieren – Basis für fehlende Karten."""
        with self.db._lock:
            names = sorted({r[0] for r in self.db.conn.execute("SELECT name FROM deck_cards")})
        if not names:
            return 0
        found, _ = scryfall.collection_identifiers([{"name": n.split(" // ")[0]} for n in names])
        prices = {}
        for raw in found:
            p = raw.get("prices") or {}
            val = (_num(p.get("eur")) or _num(p.get("eur_foil")), _num(p.get("usd")) or _num(p.get("usd_foil")))
            prices[raw["name"].lower()] = val
            prices[raw["name"].split(" // ")[0].lower()] = val
        n = 0
        with self.db._lock:
            for name in names:
                val = prices.get(name.lower()) or prices.get(name.split(" // ")[0].lower())
                if val:
                    self.db.conn.execute("UPDATE deck_cards SET price_eur=?, price_usd=? WHERE name=?",
                                         (val[0], val[1], name))
                    n += 1
            self.db.conn.commit()
        return n

    def usage_maps(self):
        """Wo wird welche Karte verwendet? -> (nach oracle_id, nach Name): [{deck_id, deck, quantity}]"""
        by_oracle, by_name = {}, {}
        rows = self.db.conn.execute(
            """SELECT dc.deck_id, d.name, dc.oracle_id, dc.name, SUM(dc.quantity)
               FROM deck_cards dc JOIN decks d ON d.id = dc.deck_id
               WHERE dc.board IN ('commander', 'companion', 'main')
               GROUP BY dc.deck_id, dc.oracle_id, dc.name""")
        for deck_id, deck_name, oid, name, qty in rows:
            entry = {"deck_id": deck_id, "deck": deck_name, "quantity": qty}
            if oid:
                by_oracle.setdefault(oid, []).append(entry)
            by_name.setdefault(name.lower(), []).append(entry)
        return by_oracle, by_name

    def usage_for(self, oracle_id, name):
        """Decks, in denen eine Karte steckt (für die Kartendetails)."""
        with self.db._lock:
            by_oracle, by_name = self.usage_maps()
        return (by_oracle.get(oracle_id) if oracle_id else None) or by_name.get((name or "").lower(), [])

    def _card_row(self, row):
        d = dict(row)
        d["keywords"] = json.loads(d.get("keywords") or "[]")
        return d

    # -- Decks ---------------------------------------------------------------
    def create(self, name, fmt="commander", notes="", status="build"):
        name = (name or "").strip()
        if not name:
            raise ValueError("Name fehlt")
        ts = now_iso()
        with self.db._lock:
            cur = self.db.conn.execute(
                "INSERT INTO decks(name, format, notes, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (name, fmt or "commander", notes or "", _status(status), ts, ts))
            self.db._bump()
            self.db.conn.commit()
            return self.get(cur.lastrowid)

    def update(self, deck_id, changes):
        sets, vals = [], []
        for k in ("name", "format", "notes", "status"):
            if k in changes:
                sets.append(f"{k}=?")
                vals.append(_status(changes[k]) if k == "status" else str(changes[k]))
        with self.db._lock:
            if not self.db.conn.execute("SELECT 1 FROM decks WHERE id=?", (deck_id,)).fetchone():
                return None
            if sets:
                sets.append("updated_at=?")
                vals.append(now_iso())
                self.db.conn.execute(f"UPDATE decks SET {', '.join(sets)} WHERE id=?", vals + [deck_id])
                self.db._bump()
                self.db.conn.commit()
            return self.get(deck_id)

    def delete(self, deck_id):
        with self.db._lock:
            self.db.conn.execute("DELETE FROM deck_cards WHERE deck_id=?", (deck_id,))
            cur = self.db.conn.execute("DELETE FROM decks WHERE id=?", (deck_id,))
            self.db._bump()
            self.db.conn.commit()
            return cur.rowcount > 0

    def list(self):
        with self.db._lock:
            decks = [dict(r) for r in self.db.conn.execute("SELECT * FROM decks ORDER BY name COLLATE NOCASE")]
            ids = [d["id"] for d in decks]
        return [self._summary(self.get(i)) for i in ids]

    @staticmethod
    def _summary(deck):
        keys = ("id", "name", "format", "notes", "status", "created_at", "updated_at", "commanders", "color_identity",
                "stats")
        return {k: deck[k] for k in keys}

    def get(self, deck_id):
        """Deck mit allen Karten und Abgleich zur Sammlung."""
        with self.db._lock:
            row = self.db.conn.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
            if not row:
                return None
            deck = dict(row)
            cards = [self._card_row(r) for r in self.db.conn.execute(
                "SELECT * FROM deck_cards WHERE deck_id=? ORDER BY name COLLATE NOCASE", (deck_id,))]
            by_oracle, by_name = self._owned_maps()
            px_oracle, px_name = self._owned_maps(proxy=1)
            price_oracle, price_name = self._price_map()
            use_oracle, use_name = self.usage_maps()

        commanders = [c for c in cards if c["board"] == "commander"]
        identity = set("".join(c["color_identity"] or "" for c in commanders))
        stats = {"cards": 0, "owned": 0, "missing": 0, "basic_lands": 0, "outside_identity": 0, "shared": 0,
                 "missing_reserved": 0, "value_eur": 0.0, "total_value_eur": 0.0, "missing_value_eur": 0.0,
                 "without_price": 0}
        for c in cards:
            owned = by_oracle.get(c["oracle_id"]) if c["oracle_id"] else None
            if owned is None:
                owned = by_name.get(c["name"].lower(), 0)
            c["owned"] = owned
            px = px_oracle.get(c["oracle_id"]) if c["oracle_id"] else None
            c["proxies"] = px if px is not None else px_name.get(c["name"].lower(), 0)
            c["basic"] = "Basic Land" in (c["type_line"] or "")
            c["missing"] = 0 if c["basic"] else max(0, c["quantity"] - owned)
            uses = (use_oracle.get(c["oracle_id"]) if c["oracle_id"] else None) or use_name.get(c["name"].lower(), [])
            c["other_decks"] = [u for u in uses if u["deck_id"] != deck_id]
            used_elsewhere = sum(u["quantity"] for u in c["other_decks"])
            c["available"] = max(0, owned - used_elsewhere)   # frei, wenn alle anderen Decks bestückt sind
            # Reicht der Bestand nur, wenn die Karte aus einem anderen Deck genommen wird?
            c["shared"] = (not c["basic"] and c["missing"] == 0 and c["board"] in DECK_BOARDS
                           and owned < c["quantity"] + used_elsewhere)
            c["missing_reserved"] = 0 if c["basic"] else max(0, c["quantity"] - c["available"])
            c["outside_identity"] = bool(commanders) and c["board"] != "commander" and \
                not set(c["color_identity"] or "") <= identity
            c["group"] = {"commander": "Commander", "companion": "Companion"}.get(c["board"]) or next(
                (t for t in _TYPE_ORDER if t in (c["type_line"] or "")), "Sonstige")
            c["warning"] = _role_warning(c, commanders)
            # Preis: eigene (echte) Karten aus der Sammlung, sonst Marktpreis des Standard-Drucks
            own_price = (price_oracle.get(c["oracle_id"]) if c["oracle_id"] else None) or \
                price_name.get(c["name"].lower())
            market = c.get("price_eur") or 0.0
            unit = own_price or market
            c["unit_price_eur"] = round(unit, 2) if unit else None
            c["value_eur"] = round(unit * c["quantity"], 2) if unit else None
            if c["board"] in DECK_BOARDS:
                have = c["quantity"] - c["missing"]
                stats["value_eur"] += (own_price or market) * have
                stats["total_value_eur"] += unit * c["quantity"]
                stats["missing_value_eur"] += (market or unit) * c["missing"]
                stats["without_price"] += 0 if unit or c["basic"] else 1
                stats["cards"] += c["quantity"]
                stats["missing"] += c["missing"]
                stats["owned"] += c["quantity"] - c["missing"]
                stats["basic_lands"] += c["quantity"] if c["basic"] else 0
                stats["outside_identity"] += 1 if c["outside_identity"] else 0
                stats["shared"] += 1 if c["shared"] else 0
                stats["missing_reserved"] += c["missing_reserved"]
        deck["cards"] = cards
        deck["commanders"] = [c["name"] for c in commanders]
        deck["companions"] = [c["name"] for c in cards if c["board"] == "companion"]
        stats["role_warnings"] = sum(1 for c in cards if c["warning"])
        for k in ("value_eur", "total_value_eur", "missing_value_eur"):
            stats[k] = round(stats[k], 2)
        deck["color_identity"] = "".join(x for x in "WUBRG" if x in identity)
        deck["stats"] = stats
        return deck

    # -- Karten ----------------------------------------------------------------
    def set_card(self, deck_id, card, quantity=1, board="main", add=False):
        """Setzt (oder erhöht mit add=True) die Anzahl einer Karte. card: normalisierte Scryfall-Karte."""
        board = board if board in BOARDS else "main"
        with self.db._lock:
            if not self.db.conn.execute("SELECT 1 FROM decks WHERE id=?", (deck_id,)).fetchone():
                return None
            ex = self.db.conn.execute("SELECT quantity FROM deck_cards WHERE deck_id=? AND name=? AND board=?",
                                      (deck_id, card["name"], board)).fetchone()
            qty = int(quantity) + (ex[0] if ex and add else 0)
            if qty <= 0:
                self.db.conn.execute("DELETE FROM deck_cards WHERE deck_id=? AND name=? AND board=?",
                                     (deck_id, card["name"], board))
            else:
                self.db.conn.execute(
                    """INSERT INTO deck_cards(deck_id, name, oracle_id, quantity, board, type_line, mana_cost, cmc,
                                              color_identity, image_url, keywords, price_eur, price_usd)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(deck_id, name, board) DO UPDATE SET quantity=excluded.quantity,
                         oracle_id=excluded.oracle_id, type_line=excluded.type_line, mana_cost=excluded.mana_cost,
                         cmc=excluded.cmc, color_identity=excluded.color_identity, image_url=excluded.image_url,
                         keywords=excluded.keywords,
                         price_eur=COALESCE(excluded.price_eur, price_eur),
                         price_usd=COALESCE(excluded.price_usd, price_usd)""",
                    (deck_id, card["name"], card.get("oracle_id"), qty, board, card.get("type_line"),
                     card.get("mana_cost"), card.get("cmc"), card.get("color_identity") or "",
                     card.get("image_url"), json.dumps(card.get("keywords") or []),
                     _num(card.get("price_eur")) or _num(card.get("price_eur_foil")),
                     _num(card.get("price_usd")) or _num(card.get("price_usd_foil"))))
            self.db.conn.execute("UPDATE decks SET updated_at=? WHERE id=?", (now_iso(), deck_id))
            self.db._bump()
            self.db.conn.commit()
        return self.get(deck_id)

    def remove_card(self, deck_card_id):
        with self.db._lock:
            row = self.db.conn.execute("SELECT deck_id FROM deck_cards WHERE id=?", (deck_card_id,)).fetchone()
            if not row:
                return None
            self.db.conn.execute("DELETE FROM deck_cards WHERE id=?", (deck_card_id,))
            self.db._bump()
            self.db.conn.commit()
            return self.get(row[0])

    def update_card(self, deck_card_id, changes):
        with self.db._lock:
            row = self.db.conn.execute("SELECT * FROM deck_cards WHERE id=?", (deck_card_id,)).fetchone()
            if not row:
                return None
            row = dict(row)
            qty = int(changes.get("quantity", row["quantity"]))
            board = changes.get("board", row["board"])
            board = board if board in BOARDS else row["board"]
            if qty <= 0:
                self.db.conn.execute("DELETE FROM deck_cards WHERE id=?", (deck_card_id,))
            else:
                try:
                    self.db.conn.execute("UPDATE deck_cards SET quantity=?, board=? WHERE id=?",
                                         (qty, board, deck_card_id))
                except Exception:  # noqa: BLE001 – gleiche Karte existiert im Ziel-Board
                    self.db.conn.execute(
                        "UPDATE deck_cards SET quantity=quantity+? WHERE deck_id=? AND name=? AND board=?",
                        (qty, row["deck_id"], row["name"], board))
                    self.db.conn.execute("DELETE FROM deck_cards WHERE id=?", (deck_card_id,))
            self.db._bump()
            self.db.conn.commit()
            return self.get(row["deck_id"])

    def import_list(self, deck_id, scryfall, text, replace=False):
        """Importiert eine Deckliste. Namen werden per Scryfall-Sammelabfrage aufgelöst."""
        entries = parse_decklist(text)
        if not entries:
            raise ValueError("Keine Karten in der Liste erkannt")
        with self.db._lock:
            if not self.db.conn.execute("SELECT 1 FROM decks WHERE id=?", (deck_id,)).fetchone():
                return None
        # Doppelseitige Karten: "A // B" -> Scryfall kennt den vollen Namen; Sammelabfrage mit Vorderseite klappt auch
        idents = [{"name": e["name"].split(" // ")[0]} for e in entries]
        found, _ = scryfall.collection_identifiers(idents)
        by_name = {}
        for raw in found:
            card = normalize_card(raw)
            by_name[card["name"].lower()] = card
            by_name[card["name"].split(" // ")[0].lower()] = card
        errors = []
        resolved = []
        for e in entries:
            card = by_name.get(e["name"].lower()) or by_name.get(e["name"].split(" // ")[0].lower())
            if card is None:
                try:
                    card = normalize_card(scryfall.lookup(name=e["name"]))
                except ScryfallError as err:
                    errors.append(f"{e['name']}: {err}")
                    continue
            resolved.append((e, card))
        with self.db._lock:
            if replace:
                self.db.conn.execute("DELETE FROM deck_cards WHERE deck_id=?", (deck_id,))
                self.db.conn.commit()
            for e, card in resolved:
                self.set_card(deck_id, card, e["quantity"], e["board"], add=True)
        return {"imported": sum(e["quantity"] for e, _ in resolved), "errors": errors, "deck": self.get(deck_id)}

    def export_text(self, deck_id, only_missing=False):
        deck = self.get(deck_id)
        if deck is None:
            return None
        lines = []
        for board, title in (("commander", "Commander"), ("companion", "Companion"), ("main", "Deck"),
                             ("side", "Sideboard"),
                             ("maybe", "Maybeboard")):
            cards = [c for c in deck["cards"] if c["board"] == board]
            if only_missing:
                cards = [dict(c, quantity=c["missing"]) for c in cards if c["missing"] > 0]
            if not cards:
                continue
            if not only_missing:
                lines.append(title)
            lines += [f"{c['quantity']} {c['name']}" for c in cards]
            lines.append("")
        return "\n".join(lines).strip() + "\n"


_DECK_CARD_FIELDS = ("name", "oracle_id", "quantity", "board", "type_line", "mana_cost", "cmc",
                     "color_identity", "image_url", "keywords")


def export_decks(db):
    """Alle Decks für den JSON-Export."""
    store = DeckStore(db)
    out = []
    with db._lock:
        decks = [dict(r) for r in db.conn.execute("SELECT * FROM decks ORDER BY id")]
        for d in decks:
            cards = [store._card_row(r) for r in db.conn.execute(
                "SELECT * FROM deck_cards WHERE deck_id=? ORDER BY id", (d["id"],))]
            out.append({
                "name": d["name"], "format": d["format"], "notes": d["notes"], "status": d.get("status") or "build",
                "created_at": d["created_at"], "updated_at": d["updated_at"],
                "cards": [{k: c[k] for k in _DECK_CARD_FIELDS} for c in cards],
            })
    return out


def import_decks(db, decks, replace=False, _in_tx=False):
    """Decks aus einem JSON-Export wiederherstellen (ohne Scryfall-Abfragen).

    _in_tx=True: Teil einer laufenden Transaktion (kein eigenes Commit, Tabellen existieren bereits).
    """
    if not _in_tx:
        DeckStore(db)
    count = 0
    with db._lock:
        if replace:
            db.conn.execute("DELETE FROM deck_cards")
            db.conn.execute("DELETE FROM decks")
        existing = {r[0].lower() for r in db.conn.execute("SELECT name FROM decks")}
        for d in decks or []:
            if not isinstance(d, dict) or not d.get("name"):
                continue
            if d["name"].lower() in existing:
                continue  # beim Ergänzen nicht doppelt anlegen
            cur = db.conn.execute(
                "INSERT INTO decks(name, format, notes, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (d["name"], d.get("format") or "commander", d.get("notes") or "", _status(d.get("status")),
                 d.get("created_at") or now_iso(), d.get("updated_at") or now_iso()))
            existing.add(d["name"].lower())
            for c in d.get("cards") or []:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                try:
                    qty = max(1, int(c.get("quantity") or 1))
                except (TypeError, ValueError):
                    qty = 1
                db.conn.execute(
                    """INSERT OR REPLACE INTO deck_cards(deck_id, name, oracle_id, quantity, board, type_line,
                       mana_cost, cmc, color_identity, image_url, keywords) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (cur.lastrowid, c["name"], c.get("oracle_id"), qty,
                     c.get("board") if c.get("board") in BOARDS else "main", c.get("type_line"),
                     c.get("mana_cost"), c.get("cmc"), c.get("color_identity") or "", c.get("image_url"),
                     json.dumps(c.get("keywords") or [])))
            count += 1
        db._bump()
        if not _in_tx:
            db.conn.commit()
    return count
