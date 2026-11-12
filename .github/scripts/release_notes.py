#!/usr/bin/env python3
"""Release-Notes aus CHANGELOG.md erzeugen.

  release_notes.py --version 1.9.0 --out notes.md   # Notes für eine Version in eine Datei schreiben
  release_notes.py --sync                           # Notes aller vorhandenen GitHub-Releases aktualisieren (gh CLI)
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_URL = "https://github.com/hxpexlss/mtg-cards"
HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\](.*)$", re.M)


def parse_changelog(path=os.path.join(ROOT, "CHANGELOG.md")):
    """{version: text} in der Reihenfolge der Datei."""
    text = open(path, encoding="utf-8").read()
    matches = list(HEADING.finditer(text))
    out = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1)] = text[m.end():end].strip()
    return out


def footer(version):
    base = f"{REPO_URL}/releases/download/v{version}"
    return f"""
---

### Downloads & Installation

| Datei | Für |
|---|---|
| `mtg-cards-scanner.apk` | Android-App – über die alte App installieren (nicht vorher deinstallieren) |
| `mtg-cards-desktop_{version}_all.deb` | Linux-Desktop |
| `mtg-cards-server_{version}_all.deb` | Ubuntu-Server (Headless) |

**Server aktualisieren** (Datenbank und Token bleiben erhalten):

```bash
wget {base}/mtg-cards-server_{version}_all.deb
sudo cp -a /var/lib/mtg-cards ~/mtg-cards-backup-$(date +%F)
sudo apt install ./mtg-cards-server_{version}_all.deb
```

**Desktop:**

```bash
wget {base}/mtg-cards-desktop_{version}_all.deb
sudo apt install ./mtg-cards-desktop_{version}_all.deb
```

Alle Änderungen: [CHANGELOG.md]({REPO_URL}/blob/HEAD/CHANGELOG.md) · Anleitung: [README]({REPO_URL}#readme)
"""


def notes_for(version, entries):
    body = entries.get(version)
    if body is None:
        body = "_Keine Release-Notes im CHANGELOG eingetragen._"
    return body + "\n" + footer(version)


def sync(entries):
    """Aktualisiert die Notes aller Releases, die es auf GitHub gibt."""
    failed = 0
    for version in entries:
        tag = f"v{version}"
        exists = subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode == 0
        if not exists:
            print(f"{tag}: kein Release vorhanden – übersprungen")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(notes_for(version, entries))
            path = f.name
        res = subprocess.run(["gh", "release", "edit", tag, "--title", f"MTG Cards {version}", "--notes-file", path],
                             capture_output=True, text=True)
        os.unlink(path)
        if res.returncode == 0:
            print(f"{tag}: Release-Notes aktualisiert")
        else:
            failed += 1
            print(f"{tag}: Fehler – {res.stderr.strip()}", file=sys.stderr)
    return 1 if failed else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version")
    p.add_argument("--out")
    p.add_argument("--sync", action="store_true")
    args = p.parse_args()
    entries = parse_changelog()
    if args.sync:
        return sync(entries)
    if not args.version:
        p.error("--version oder --sync angeben")
    text = notes_for(args.version, entries)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
