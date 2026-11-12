"""Startpunkt der Windows-Desktop-Anwendung (PyInstaller, ohne Konsole)."""

import os
import sys

# Ohne Konsole gibt es kein stdout/stderr -> in eine Logdatei schreiben (hilft bei der Fehlersuche).
if sys.stdout is None or sys.stderr is None:
    _dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mtg-cards")
    os.makedirs(_dir, exist_ok=True)
    _log = open(os.path.join(_dir, "desktop.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

# Für HTTPS-Zertifikate ohne openssl (wird sonst nur bei Bedarf importiert und von PyInstaller übersehen)
try:
    import cryptography.hazmat.primitives.asymmetric.ec  # noqa: F401
    import cryptography.hazmat.primitives.serialization  # noqa: F401
    import cryptography.x509  # noqa: F401
except ImportError:
    pass

from mtgcards.desktop import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
