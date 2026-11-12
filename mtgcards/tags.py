"""Automatische Tags (Commander, Partner, Companion) aus Kartendaten ableiten."""

import re

AUTO_TAGS = ("Commander", "Partner", "Companion", "Token", "Emblem")

_PARTNER_KEYWORDS = {"partner", "partner with", "friends forever"}
_PARTNER_RE = re.compile(r"^(partner|partner with [^\n(]+|friends forever)\s*(\(|$)", re.I | re.M)
_COMPANION_RE = re.compile(r"^companion\s*[—-]", re.I | re.M)


def front_type_line(type_line):
    """Typzeile der Vorderseite (bei doppelseitigen Karten 'A // B')."""
    return (type_line or "").split("//")[0].strip()


def is_emblem(card):
    return (card.get("type_line") or "").startswith("Emblem") or card.get("layout") == "emblem"


def _subtype(type_line):
    """'Legendary Planeswalker — Elspeth' -> 'elspeth' (nur Vorderseite)."""
    front = front_type_line(type_line)
    return front.split("—", 1)[1].strip().lower() if "—" in front else ""


def emblem_owner_names(emblem):
    """Namen des Planeswalkers zu einem Emblem: 'Elspeth, Knight-Errant Emblem' -> 'elspeth, knight-errant'."""
    name = (emblem.get("name") or "").strip()
    return name[:-len(" Emblem")].strip().lower() if name.lower().endswith(" emblem") else ""


def emblem_matches(emblem, walker):
    """Gehört das Emblem zum Planeswalker? Exakt über den Namen, sonst über den Untertyp (z.B. 'Elspeth')."""
    owner = emblem_owner_names(emblem)
    names = [n.strip().lower() for n in (walker.get("name") or "").split("//")]
    if owner:
        return owner in names
    sub = _subtype(emblem.get("type_line"))
    return bool(sub) and sub in [_subtype(t) for t in (walker.get("type_line") or "").split("//")]


def auto_tags(card):
    """Liefert die automatisch vergebenen Tags für eine normalisierte Karte.

    card: dict mit type_line, oracle_text, keywords (Liste).
    """
    tags = []
    front = front_type_line(card.get("type_line")).lower()
    text = card.get("oracle_text") or ""
    keywords = {str(k).lower() for k in (card.get("keywords") or [])}

    is_token = (card.get("type_line") or "").startswith("Token") or card.get("layout") in ("token", "double_faced_token")
    is_legendary_creature = "legendary" in front and "creature" in front and not is_token
    if is_legendary_creature or "can be your commander" in text.lower():
        tags.append("Commander")

    if keywords & _PARTNER_KEYWORDS or _PARTNER_RE.search(text):
        tags.append("Partner")

    if "companion" in keywords or _COMPANION_RE.search(text):
        tags.append("Companion")

    # Spielsteine: Typzeile "Token Creature — Goblin", "Token Artifact — Treasure" …
    if is_token:
        tags.append("Token")

    # Embleme von Planeswalkern: Typzeile "Emblem — Elspeth"
    if is_emblem(card):
        tags.append("Emblem")

    return tags


def merge_tags(*lists):
    """Vereinigt Tag-Listen, behält Reihenfolge, ignoriert Groß/Kleinschreibung bei Duplikaten."""
    seen = set()
    out = []
    for lst in lists:
        for t in lst or []:
            t = str(t).strip()
            if not t:
                continue
            key = t.lower()
            if key not in seen:
                seen.add(key)
                out.append(t)
    return out
