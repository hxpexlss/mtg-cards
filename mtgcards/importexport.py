"""Export und Import der Sammlung (JSON und CSV)."""

import csv
import io
import json

from . import __version__
from .db import CARD_FIELDS, EXPORT_FIELDS, _as_list, _bool, now_iso
from .decks import export_decks, import_decks
from .wishlist import export_wishlist, import_wishlist
from .scryfall import ScryfallError, normalize_card

# Spaltennamen anderer Tools (Moxfield, Deckbox, ManaBox, ...) auf unsere abbilden
CSV_ALIASES = {
    "name": "name", "card name": "name", "card": "name",
    "set": "set_code", "set code": "set_code", "edition": "set_code", "set_code": "set_code",
    "collector number": "collector_number", "collector_number": "collector_number",
    "card number": "collector_number", "number": "collector_number", "cn": "collector_number",
    "quantity": "quantity", "count": "quantity", "qty": "quantity", "anzahl": "quantity",
    "foil": "foil", "language": "lang", "lang": "lang",
    "scryfall id": "scryfall_id", "scryfall_id": "scryfall_id",
    "tags": "tags", "notes": "notes",
}


def export_json(db):
    cards = []
    for c in db.all():
        cards.append({f: c.get(f) for f in EXPORT_FIELDS})
    return json.dumps({
        "format": "mtg-cards",
        "version": 1,
        "app_version": __version__,
        "exported_at": now_iso(),
        "cards": cards,
        "decks": export_decks(db),
        "wishlist": export_wishlist(db),
    }, ensure_ascii=False, indent=2)


def export_csv(db):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    w.writeheader()
    for c in db.all():
        row = dict(c)
        row["tags"] = ";".join(c["tags"])
        row["keywords"] = ";".join(c["keywords"])
        row["foil"] = "1" if c["foil"] else "0"
        w.writerow(row)
    return buf.getvalue()


def parse_import(text):
    """Erkennt JSON oder CSV und liefert eine Liste von dicts."""
    return _parse_import(text)[0]


def _parse_import(text):
    """Wie parse_import, liefert zusätzlich enthaltene Decks (nur JSON-Export)."""
    text = text.lstrip("﻿")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        decks = None
        if isinstance(data, dict):
            decks = {"decks": data.get("decks"), "wishlist": data.get("wishlist")}
            data = data.get("cards", [])
        if not isinstance(data, list):
            raise ValueError("Unbekanntes JSON-Format")
        return [d for d in data if isinstance(d, dict)], decks
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for raw in reader:
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = k.strip()
            mapped = CSV_ALIASES.get(key.lower(), key if key in EXPORT_FIELDS else None)
            if mapped and mapped not in row:
                row[mapped] = (v or "").strip()
        if row.get("name") or row.get("scryfall_id"):
            rows.append(row)
    return rows, None


def import_cards(db, scryfall, text, mode="add"):
    """Importiert Karten.

    mode: "add"     -> Anzahlen werden zu vorhandenen Einträgen addiert
          "replace" -> Datenbank wird vorher geleert
    Karten ohne vollständige Daten werden über Scryfall nachgeschlagen.
    """
    rows, decks = _parse_import(text)
    with db._lock:  # gesamter Import in einer Transaktion
        result = _import_rows(db, scryfall, rows, mode)
        if decks is not None:
            if decks.get("decks") is not None:
                result["decks"] = import_decks(db, decks["decks"], replace=(mode == "replace"))
            if decks.get("wishlist") is not None:
                result["wishlist"] = import_wishlist(db, decks["wishlist"], replace=(mode == "replace"))
        return result


def _import_rows(db, scryfall, rows, mode):
    result = {"imported": 0, "created": 0, "merged": 0, "looked_up": 0, "errors": []}
    if mode == "replace":
        db.clear(_commit=False)
    try:
        for i, row in enumerate(rows, 1):
            try:
                qty = int(float(row.get("quantity") or 1))
            except ValueError:
                qty = 1
            if qty <= 0:
                continue
            complete = bool(row.get("type_line")) and bool(row.get("name"))
            if complete:
                card = {f: row.get(f) for f in CARD_FIELDS}
                card["keywords"] = _as_list(row.get("keywords"))
                for f in ("scryfall_id", "oracle_id"):
                    card[f] = card[f] or None
                if card.get("cmc") in ("", None):
                    card["cmc"] = None
                else:
                    try:
                        card["cmc"] = float(card["cmc"])
                    except (TypeError, ValueError):
                        card["cmc"] = None
            else:
                try:
                    raw = scryfall.lookup(
                        name=row.get("name"), set_code=row.get("set_code"),
                        collector_number=row.get("collector_number"), lang=row.get("lang"),
                        scryfall_id=row.get("scryfall_id") or None,
                    )
                except ScryfallError as e:
                    result["errors"].append(f"Zeile {i} ({row.get('name')}): {e}")
                    continue
                card = normalize_card(raw)
                result["looked_up"] += 1
            ts = {}
            if row.get("added_at"):
                ts["added_at"] = row["added_at"]
            if row.get("updated_at"):
                ts["updated_at"] = row["updated_at"]
            _, created = db.add(card, foil=_bool(row.get("foil")), quantity=qty,
                                tags=_as_list(row.get("tags")), notes=row.get("notes") or "",
                                _commit=False, **ts)
            result["imported"] += qty
            result["created" if created else "merged"] += 1
        db.commit()
    except Exception:
        db.conn.rollback()
        raise
    return result
