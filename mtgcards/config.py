"""Konfiguration (JSON-Datei) für Desktop und Server."""

import json
import os
import secrets

from . import DEFAULT_PORT

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O/1/I – gut abtippbar


def generate_token():
    """Token im Format XXXX-XXXX-XXXX-XXXX (80 Bit), leicht am Handy einzutippen."""
    chars = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return "-".join(chars[i:i + 4] for i in range(0, 16, 4))


def _xdg(var, fallback):
    return os.environ.get(var) or os.path.expanduser(fallback)


DESKTOP_CONFIG_PATH = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "mtg-cards", "config.json")
DESKTOP_DATA_DIR = os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), "mtg-cards")
SERVER_CONFIG_PATH = "/etc/mtg-cards/server.json"

DESKTOP_DEFAULTS = {
    "mode": "local",            # "local" = eigene Datenbank, "remote" = mit Server verbinden
    "bind": "0.0.0.0",          # 0.0.0.0, damit das Handy (WLAN/Tailscale) verbinden kann
    "port": DEFAULT_PORT,
    "token": None,
    "db_path": os.path.join(DESKTOP_DATA_DIR, "cards.db"),
    "remote_url": "",
    "remote_token": "",
    "remote_fingerprint": "",
    "discovery": True,
    "tls": False,
    "tls_cert": os.path.join(os.path.dirname(DESKTOP_CONFIG_PATH), "tls", "cert.pem"),
    "tls_key": os.path.join(os.path.dirname(DESKTOP_CONFIG_PATH), "tls", "key.pem"),
}

SERVER_DEFAULTS = {
    "bind": "0.0.0.0",
    "port": DEFAULT_PORT,
    "token": None,
    "db_path": "/var/lib/mtg-cards/cards.db",
    "discovery": True,
    "tls": False,
    "tls_cert": "/etc/mtg-cards/tls/cert.pem",
    "tls_key": "/etc/mtg-cards/tls/key.pem",
}


def load(path, defaults, create=True):
    cfg = dict(defaults)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    changed = False
    if not cfg.get("token"):
        cfg["token"] = generate_token()
        changed = True
    if create and (changed or not os.path.exists(path)):
        try:
            save(path, cfg)
        except OSError:
            pass
    return cfg


def save(path, cfg):
    """Speichert atomar; Besitzer und Rechte einer vorhandenen Datei bleiben erhalten."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = os.stat(path) if os.path.exists(path) else None
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if old:
        try:
            os.chmod(tmp, old.st_mode & 0o777)
            os.chown(tmp, old.st_uid, old.st_gid)
        except OSError:
            pass
    os.replace(tmp, path)
