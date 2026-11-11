#!/bin/sh
# Baut mtg-cards-desktop_<ver>_all.deb und mtg-cards-server_<ver>_all.deb nach dist/
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('$ROOT/mtgcards/__init__.py').read()).group(1))")
OUT="$ROOT/dist"
BUILD="$ROOT/build/deb"
rm -rf "$BUILD"
mkdir -p "$OUT" "$BUILD"
MAINT="MTG Cards <noreply@users.noreply.github.com>"

copy_pkg() {  # $1 = Zielverzeichnis der Python-Bibliothek
    mkdir -p "$1"
    (cd "$ROOT" && find mtgcards -type f ! -name '*.pyc' ! -path '*__pycache__*' -print) | while read -r f; do
        install -D -m 0644 "$ROOT/$f" "$1/$f"
    done
}

# ---------------------------------------------------------------- Desktop
D="$BUILD/mtg-cards-desktop"
copy_pkg "$D/usr/lib/mtg-cards-desktop"
install -d "$D/usr/bin" "$D/DEBIAN"
cat > "$D/usr/bin/mtg-cards" <<'SH'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/usr/lib/mtg-cards-desktop exec python3 -m mtgcards "$@"
SH
chmod 0755 "$D/usr/bin/mtg-cards"
install -D -m 0644 "$ROOT/packaging/desktop/mtg-cards.desktop" "$D/usr/share/applications/mtg-cards.desktop"
install -D -m 0644 "$ROOT/mtgcards/web/icon.svg" "$D/usr/share/icons/hicolor/scalable/apps/mtg-cards.svg"
install -m 0755 "$ROOT/packaging/desktop/postinst" "$D/DEBIAN/postinst"
cat > "$D/DEBIAN/control" <<CTRL
Package: mtg-cards-desktop
Version: $VERSION
Section: games
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0
Recommends: iproute2, openssl
Suggests: tailscale
Maintainer: $MAINT
Installed-Size: $(du -sk "$D/usr" | cut -f1)
Description: Magic: The Gathering Kartensammlung (Desktop)
 Verwaltet Magic-Karten in einer lokalen SQLite-Datenbank oder auf einem
 MTG-Cards-Server. Karten koennen per Name eingetragen oder mit der
 Android-App gescannt werden; Faehigkeiten, Farbidentitaet und Tags
 (Commander, Partner, Companion) kommen automatisch von Scryfall.
 Import/Export als JSON oder CSV.
CTRL

# ---------------------------------------------------------------- Server
S="$BUILD/mtg-cards-server"
copy_pkg "$S/usr/lib/mtg-cards-server"
install -d "$S/usr/bin" "$S/DEBIAN"
cat > "$S/usr/bin/mtg-cards-server" <<'SH'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/usr/lib/mtg-cards-server exec python3 -m mtgcards.server_main "$@"
SH
chmod 0755 "$S/usr/bin/mtg-cards-server"
install -D -m 0644 "$ROOT/packaging/server/mtg-cards-server.service" "$S/lib/systemd/system/mtg-cards-server.service"
for s in postinst prerm postrm; do install -m 0755 "$ROOT/packaging/server/$s" "$S/DEBIAN/$s"; done
cat > "$S/DEBIAN/control" <<CTRL
Package: mtg-cards-server
Version: $VERSION
Section: games
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), passwd
Recommends: iproute2, openssl
Suggests: tailscale
Maintainer: $MAINT
Installed-Size: $(du -sk "$S/usr" | cut -f1)
Description: Magic: The Gathering Kartensammlung (Headless-Server)
 Zentraler Server fuer MTG Cards. Die Android-App und die Desktop-Anwendung
 verbinden sich ueber WLAN oder Tailscale. Laeuft als systemd-Dienst
 (mtg-cards-server) auf Port 8765 und bietet zusaetzlich eine Weboberflaeche.
CTRL

dpkg-deb --build --root-owner-group "$D" "$OUT/mtg-cards-desktop_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$S" "$OUT/mtg-cards-server_${VERSION}_all.deb"
ls -l "$OUT"/*.deb
