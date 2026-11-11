# MTG Cards

Magic: The Gathering Kartensammlung – **scannen mit dem Handy, verwalten am Linux-PC, zentral auf einem Server.**

| Paket | Wofür |
|---|---|
| `mtg-cards-scanner.apk` | Android-App: Karten mit der Kamera scannen, Sammlung durchsuchen |
| `mtg-cards-desktop_*.deb` | Linux-Anwendung: Karten per Name eintragen, suchen, Import/Export; eigene Datenbank **oder** Verbindung zum Server |
| `mtg-cards-server_*.deb` | Headless-Server für Ubuntu (systemd-Dienst) – Datenbank immer und überall erreichbar |

Alle Kartendaten (Regeltext/Fähigkeiten, Farbidentität, Manakosten, Typ, Edition, Bild, Preise) kommen automatisch von
[Scryfall](https://scryfall.com). Automatische Tags:

- **Commander** – legendäre Kreaturen (`Legendary Creature`, auch Artefakt-/Verzauberungskreaturen und Karten mit
  „can be your commander“)
- **Partner** – Partner, Partner with …, Friends forever
- **Companion** – Karten mit Companion

Eigene Tags (z.B. `Deck: Atraxa`, `Tauschen`) und Notizen können zusätzlich vergeben werden.

## Download

**Fertige Dateien: [GitHub-Releases](../../releases/latest)** (APK + beide .deb). Sie werden von GitHub Actions bei jedem Push automatisch gebaut und veröffentlicht; zusätzlich unter **Actions → Build → Artifacts**
(`android-apk` und `deb-pakete`). Für einen Release mit Download-Links einen Tag pushen: `git tag v1.0.0 && git push --tags`.

Lokal bauen:

```sh
./packaging/build-debs.sh                 # -> dist/*.deb
cd android && ./gradlew assembleRelease   # -> app/build/outputs/apk/release/app-release.apk (Android-SDK nötig)
```

## Installation

### Linux-Desktop (Ubuntu/Debian/Mint …)

```sh
sudo apt install ./mtg-cards-desktop_1.3.0_all.deb
```

Startet über das Anwendungsmenü („MTG Cards“) oder `mtg-cards`. Unter **⚙ Einstellungen** stehen die Adressen und der
Token, die man in der Handy-App einträgt.

- **Lokal auf diesem PC**: Datenbank liegt in `~/.local/share/mtg-cards/cards.db`. Das Handy verbindet sich mit dem PC
  (der PC muss dabei laufen).
- **Headless-Server**: Server-Adresse und Server-Token eintragen – alles wird dann auf dem Server gespeichert.

Weitere Optionen: `mtg-cards --help` (`--browser`, `--server-only`, `--remote URL --remote-token TOKEN`, `--show-token`).

### Ubuntu-Server (headless)

```sh
sudo apt install ./mtg-cards-server_1.3.0_all.deb
sudo mtg-cards-server --show-token        # Token für App und Desktop
```

- Läuft als Dienst `mtg-cards-server` auf Port **8765** (`systemctl status mtg-cards-server`)
- Datenbank: `/var/lib/mtg-cards/cards.db`, Konfiguration: `/etc/mtg-cards/server.json`
- Weboberfläche im Browser: `http://<server>:8765`
- Neuer Token: `sudo mtg-cards-server --new-token && sudo systemctl restart mtg-cards-server`
- Backup per Kommandozeile: `sudo -u mtgcards mtg-cards-server --export /tmp/backup.json`
  (Import: `--import datei.json`, mit `--replace` wird die Sammlung ersetzt)
- Firewall: `sudo ufw allow 8765/tcp` (und optional `47811/udp` für die automatische Suche im WLAN)

### Android

APK aufs Handy kopieren und installieren („Installation aus unbekannten Quellen“ erlauben).
Unter **Verbindung** → „Im WLAN suchen“ oder Adresse eintragen, Token eingeben, „Speichern & testen“.

## Verbindung: WLAN und Tailscale

- **WLAN**: Die App findet PC/Server automatisch per UDP-Broadcast (Port 47811). Alternativ die IP eintragen,
  z.B. `192.168.1.20` – Port 8765 wird automatisch ergänzt.
- **Tailscale**: Tailscale auf Handy und PC/Server installieren und die Tailscale-IP (`100.x.y.z`) oder den
  MagicDNS-Namen (`mein-server.tailxxxx.ts.net`) eintragen. Die Desktop-Einstellungen zeigen beides an.
  Damit ist die Datenbank von überall erreichbar, ohne Ports im Router zu öffnen.
- Alle API-Zugriffe sind mit einem Token geschützt (Format `XXXX-XXXX-XXXX-XXXX`).
  Standardmäßig HTTP – im Heimnetz und über Tailscale (WireGuard-verschlüsselt) ist das in Ordnung; optional
  HTTPS (siehe unten). **Den Port nicht direkt ins Internet freigeben**.

## Scannen

Karte in den Rahmen halten, sodass der Name im violetten Feld liegt. Die Texterkennung (Google ML Kit) läuft
offline auf dem Handy. Erkannt werden der Kartenname und – wenn lesbar – Set-Code und Sammlernummer unten links,
damit der richtige Druck gespeichert wird. Funktioniert auch mit deutschen (und anderen) Karten.

- **Auto**-Schalter: erkannte Karten sofort hinzufügen (für Stapel), sonst Vorschau mit Anzahl/Foil und „Hinzufügen“
- Erkennung über mehrere Bilder: kleine OCR-Fehler werden toleriert, ~3–4 Auswertungen pro Sekunde
- Vibration und Piepton bei Erfolg (Ton abschaltbar)
- **Verlauf** der Sitzung unten: Karte antippen → Rückgängig (−1), +1 Exemplar oder Details
- **Offline-Warteschlange**: Ist PC/Server nicht erreichbar, werden Scans gespeichert und automatisch nachgetragen,
  sobald die Verbindung wieder da ist (oder Hinweis antippen)
- Mehrere Namenskandidaten pro Scan: Liegt der Name nicht an der üblichen Stelle (Showcase-, randlose oder
  Sonderrahmen), probiert der Server automatisch die weiteren erkannten Zeilen
- **Querformat-Rahmen** (Drehen-Symbol) für quer gedruckte Karten wie Schlachten
- Bildschirm antippen = scharfstellen, zwei Finger = zoomen, Blitz-Symbol = Taschenlampe
- „Name manuell eingeben“, falls die Erkennung nicht klappt

## Import / Export

In der Desktop-/Weboberfläche unter **⇅ Import/Export**:

- **JSON** – vollständige Sicherung inkl. Tags und Notizen (zum Wiederherstellen empfohlen)
- **CSV** – für Tabellenkalkulation; Import versteht auch CSVs anderer Tools (Moxfield, ManaBox, Deckbox …) mit den
  Spalten `Name`, `Set`/`Edition`, `Collector Number`, `Quantity`/`Count`, `Foil`. Fehlende Daten werden über
  Scryfall ergänzt.
- Modus „hinzufügen“ (Anzahlen werden addiert) oder „ersetzen“.
- **Alle Karten aktualisieren**: lädt Regeltext und aktuelle Preise der ganzen Sammlung per Sammelabfrage neu.

Scryfall-Antworten werden in `scryfall-cache.db` neben der Datenbank zwischengespeichert: wiederholte Scans sind
sofort da, und bereits bekannte Karten lassen sich auch ohne Internet nachschlagen.

## Decks

Tab **Decks** in der Desktop-/Weboberfläche:

- **Neues Deck** → Name und optional eine Deckliste einfügen. Verstanden werden die üblichen Formate von Moxfield,
  Archidekt, MTG Arena und MTGO (`1 Sol Ring`, `1x Sol Ring`, `1 Sol Ring (C21) 263`, Abschnitte `Commander`,
  `Deck`, `Sideboard`, Markierung `*CMDR*`).
- Jede Karte zeigt **✓ vorhanden** oder **✗ fehlt** (Abgleich mit der Sammlung über alle Drucke). Standardländer
  zählen nie als fehlend.
- Mit Commander wird die **Farbidentität geprüft** – Karten außerhalb werden mit ⚠ markiert.
- **Fehlende kopieren** erzeugt eine Einkaufsliste; **Exportieren** speichert die Deckliste als Text.
- Karten einzeln hinzufügen (Name mit Vorschlägen), Anzahl ±, als Commander ★ oder ins Sideboard ⇄ verschieben.
- In den Kartendetails der Sammlung: **＋ Zu Deck**.
- In der App: Tab **Decks** mit Fortschritt, „Nur fehlende“ und **Fehlende teilen** (z.B. per Messenger).

- **Geteilte Karten ⇄**: Steckt eine Karte auch in anderen Decks und reicht dein Bestand nicht für alle
  gleichzeitig, wird sie orange mit ⇄ markiert („auch in: …“). Die Kachel zeigt, wie viele Karten fehlen, um alle
  Decks gleichzeitig zu bauen. In den Kartendetails der Sammlung steht, in welchen Decks die Karte steckt.
- Mini-Manakurve pro Deck.

Decks sind im JSON-Export enthalten und werden beim Import wiederhergestellt.

## Verschlüsselung (HTTPS)

Standardmäßig wird unverschlüsseltes HTTP genutzt (im Heimnetz und über Tailscale in Ordnung). Optional:

**Headless-Server**

```sh
sudo mtg-cards-server --enable-tls            # erzeugt ein eigenes Zertifikat
sudo systemctl restart mtg-cards-server
sudo mtg-cards-server --show-fingerprint      # Fingerabdruck zum Vergleichen
```

Mit echtem Zertifikat von Tailscale (dann ist keine Bestätigung nötig):

```sh
sudo tailscale cert mein-server.tailxxxx.ts.net
sudo mtg-cards-server --enable-tls --cert mein-server.tailxxxx.ts.net.crt --key mein-server.tailxxxx.ts.net.key
```

(Die Dateien müssen für den Dienst-Benutzer `mtgcards` lesbar sein, z.B. nach `/etc/mtg-cards/tls/` kopieren.)

**Desktop**: ⚙ Einstellungen → „HTTPS für Handy-Verbindung“, danach die Anwendung neu starten.

In der App und im Desktop-Server-Modus die Adresse mit `https://` eintragen. Beim ersten Verbinden wird der
Zertifikats-Fingerabdruck angezeigt – mit dem am PC/Server angezeigten vergleichen und bestätigen. Danach wird
er bei jeder Verbindung geprüft; ändert sich das Zertifikat, verweigert die App die Verbindung.

## Statistik

Tab **Statistik**: Wert der Sammlung (€ und $), Wertverlauf, Manakurve, Kartentypen, Farbidentitäten, Seltenheiten,
häufigste Editionen, hinzugefügte Karten pro Monat und die wertvollsten Karten. Alle Diagramme zeigen beim
Überfahren Details.

Preise werden **automatisch täglich** über Scryfall aktualisiert (Server und Desktop, solange sie laufen) und der
Sammlungswert pro Tag gespeichert – daraus entsteht der Wertverlauf. Intervall in der Konfiguration:
`"auto_refresh_hours": 24` (0 = aus).

## Suche

Volltextsuche über Name (auch deutscher Name), Typzeile, Regeltext, Tags und Notizen. Filter:

- **Farbidentität** mit drei Modi: *passt in Deck mit diesen Farben* (ideal für Commander-Decks), *genau*, *enthält*
- Tags (Commander/Partner/Companion/eigene), Kartentyp, Seltenheit, nur Foils
- Sortierung nach Name, zuletzt hinzugefügt, Manawert, Edition, Anzahl, Preis

## Architektur

```
 Android-App ──HTTP/JSON──┐
                          ├──► Desktop (eingebetteter Server, lokale SQLite-DB)
 Browser ─────────────────┤         │  Remote-Modus: leitet an Server weiter
                          └──► Headless-Server (SQLite-DB) ◄──┘
                                    │
                                    └──► api.scryfall.com
```

- `mtgcards/` – Python-Kern, nur Standardbibliothek (keine pip-Abhängigkeiten): `db.py`, `scryfall.py`, `tags.py`,
  `importexport.py`, `server.py` (REST-API + Weboberfläche in `web/`), `desktop.py`, `server_main.py`
- `android/` – Kotlin-App (CameraX, ML Kit Text Recognition, Material 3)
- `packaging/` – Skripte und Dateien für die `.deb`-Pakete
- Tests: `python3 -m unittest discover -s tests`

### REST-API (Auszug)

Header `Authorization: Bearer <TOKEN>`.

| Methode | Pfad | |
|---|---|---|
| GET | `/api/cards?q=&ci=WU&ci_mode=within&tag=Commander&type=&sort=` | Suche |
| POST | `/api/cards` `{name \| scryfall_id, set, cn, quantity, foil, tags}` | Hinzufügen (Anzahl wird bei gleichem Druck erhöht) |
| GET/PATCH/DELETE | `/api/cards/{id}` | Einzelne Karte |
| GET | `/api/lookup?name=&set=&cn=` | Karte bei Scryfall nachschlagen (inkl. Bestand) |
| GET | `/api/autocomplete?q=`, `/api/prints?name=` | Namensvorschläge, Drucke |
| GET | `/api/export?format=json\|csv` | Export |
| GET/POST | `/api/decks` | Decks auflisten / anlegen (`{name, list}`) |
| GET/PATCH/DELETE | `/api/decks/{id}` | Deck inkl. Abgleich mit der Sammlung |
| POST | `/api/decks/{id}/import`, `/api/decks/{id}/cards` | Deckliste einfügen, Karte hinzufügen |
| GET | `/api/decks/{id}/export?missing=1` | Deckliste / fehlende Karten als Text |
| POST | `/api/import?mode=add\|replace` | Import (JSON/CSV im Body) |

Hinweis zur App-Signatur: Die APK wird mit einem im Repository liegenden, nicht geheimen Schlüssel
(`android/app/mtgcards-debug.keystore`) signiert, damit Updates aus jedem Build ohne Neuinstallation funktionieren.
