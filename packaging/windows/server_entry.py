"""Startpunkt des Windows-Servers (PyInstaller, Konsolenprogramm)."""

import sys

# Für HTTPS-Zertifikate ohne openssl (wird sonst nur bei Bedarf importiert und von PyInstaller übersehen)
try:
    import cryptography.hazmat.primitives.asymmetric.ec  # noqa: F401
    import cryptography.hazmat.primitives.serialization  # noqa: F401
    import cryptography.x509  # noqa: F401
except ImportError:
    pass

from mtgcards.server_main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
