# Änderungen

Neueste Version oben. Aus diesen Einträgen werden automatisch die Release-Notes auf GitHub erzeugt
(`.github/scripts/release_notes.py`). Für eine neue Version einfach oben einen Abschnitt
`## [x.y.z] – JJJJ-MM-TT` ergänzen.

## [1.11.0] – 2026-11-12

### Neu
- **Code-Modus beim Scannen:** nur den unteren Kartenrand scannen (z.B. `0077` und `FDN • DE`) – Set-Code und
  Sammlernummer bestimmen den Druck eindeutig, inklusive Sprache. Im Seitenmenü einschaltbar.
- **„Druck ändern“** im Scan-Ergebnis und in der Stapel-Zusammenfassung (Liste aller Drucke mit Edition und Preis).
- Anzeige, wie sicher der Druck ist: ✓ erkannt · ≈ Edition übernommen · ⚠ geraten.
- **Edition festlegen** im Seitenmenü (z.B. `FDN`); ohne Festlegung wird die zuletzt sicher erkannte Edition
  bevorzugt, wenn unten nichts lesbar ist – praktisch für Stapel aus einer Edition.

### Verbessert
- Texterkennung in Full-HD und exakte Umrechnung des Rahmens auf das Kamerabild – die kleine Zeile mit Set-Code
  und Nummer wird deutlich häufiger gelesen.
- Set-Code und Nummer werden über mehrere Bilder gesammelt (Mehrheitsentscheid); bei Bedarf wird kurz weitergelesen.
- Server korrigiert typische Lesefehler im Set-Code (0/O, 1/I, 5/S, 8/B …).
- Deutsche (fremdsprachige) Karten: ein gelesener Set-Code wird jetzt berücksichtigt (vorher immer neuester Druck).
- Gewählter Druck + Sprache: es wird derselbe Druck in dieser Sprache gespeichert (auch am PC).

## [1.10.0] – 2026-11-12

### Neu
- **Commander, Partner und Companion im Deck festlegen:** Karte als Commander markieren (★, zwei Commander für
  Partner/Background möglich) oder als **Companion** (🅲, eigener Bereich). Am PC über die Knöpfe an der Karte bzw.
  beim Hinzufügen, in der App per Antippen einer Karte im Deck.
- Deck-Kopf zeigt „Commander (Partner): … · Companion: …“.
- **Hinweise ⚠** bei Rollen, die nicht passen: Commander ist kein legendäres Wesen, zwei Commander ohne
  Partner-Fähigkeit, Companion ohne Companion-Fähigkeit.
- Companion wird gegen die Farbidentität geprüft und zählt bei Bestand/Fehlenden mit; Abschnitt „Companion“ in
  Decklisten wird erkannt und exportiert.
- **Tag „Token“** für Spielsteine (automatisch, auch für bereits vorhandene Karten) mit Filter in Sammlung und App.

## [1.9.0] – 2026-11-12

### Neu
- **Seitenmenü in der Scan-Ansicht** (Knopf oben rechts) mit allen Einstellungen: Ziel-Deck, Kartensprache,
  automatisch hinzufügen, Stapel-Modus, Proxy, Foil, Querformat-Rahmen und Ton.
- **Ziel-Deck beim Scannen:** Gescannte Karten kommen in die Sammlung **und zusätzlich direkt ins gewählte Deck** –
  auch im Stapel-Modus und bei Offline-Scans.
- Zeile unter dem Status zeigt die aktiven Einstellungen (z.B. `🅿 Proxy · Stapel · → Atraxa · DE`).

### Geändert
- Aufgeräumte Scan-Ansicht: oben nur Status, Licht und Menü; unten „Name eingeben“ und „Stapel abschließen“.
- Server: `POST /api/cards` und `/api/cards/batch` akzeptieren `deck_id`.

> Die Ziel-Deck-Funktion benötigt Server **und** App in Version 1.9.0.

## [1.8.0] – 2026-11-12

### Neu
- **Deck-Status „Besitz“ / „Bau“:** Decks, die du gebaut hast, und Decks, die du zusammenstellen willst.
  Beim Anlegen wählbar und jederzeit umschaltbar.
- Filter Alle / Besitz / Bau in der Deck-Liste (PC und App), Status-Knopf in der Deck-Ansicht der App.
- Status ist im JSON-Export enthalten.

### Hinweis
- Bestehende Decks stehen nach dem Update auf „Bau“.

## [1.7.0] – 2026-11-12

### Neu
- **Tag „Proxies“** und **Proxy-Schalter beim Scannen**: alle gescannten Karten bekommen den Tag
  (auch im Stapel-Modus und offline). Am PC: Checkbox „Proxy“ beim Hinzufügen.
- Proxies werden als **eigener Eintrag** gespeichert – getrennt von echten Karten desselben Drucks.
- Proxies zählen nicht zum Sammlungswert, Set-Fortschritt und zu den Doppelten und erfüllen keine Wünsche;
  im Deck wird „🅿 vorhanden“ angezeigt.
- Filter „Proxies“ in der Suche, Kennzeichnung „PROXY“ / 🅿.
- **Verbindungsprotokoll** in der App unter „Verbindung“.

### Verbessert
- **Stabilere Verbindung der App:** automatische Wiederholung bei Netzwerkfehlern, längere Timeouts (Tailscale),
  keine Wiederverwendung abgerissener Verbindungen; Offline-Scans werden alle 30 Sekunden nachgetragen.

### Hinweis
- Die Datenbank wird beim ersten Start automatisch erweitert (neue Spalte), vorhandene Daten bleiben erhalten.

## [1.6.3] – 2026-11-12

### Neu
- **Wunschliste: Kartenansicht** mit großem Bild, Regeltext, aktuellem Preis, Zielpreis und Bestand –
  in der App per Antippen, am PC per Klick auf Bild oder Name (plus Bild-Vorschau beim Überfahren).

## [1.6.2] – 2026-11-12

### Behoben
- App: **Tag-Filter** (Commander, Partner, Companion) in der Suche hatten keine Wirkung.
- App: Die Chip-Reihe mit Tags und „Doppelte“ ließ sich nicht wischen.

### Verbessert
- Aktive Filter-Chips sind deutlich erkennbar (Häkchen, farbiger Hintergrund).

## [1.6.1] – 2026-11-12

### Behoben
- **„Nicht autorisiert“** trotz richtigem Token, wenn die Handy-Tastatur ein Leerzeichen eingefügt hatte
  (z.B. `ABCD-EFGH- JKLM-NPQR`). Leerzeichen und Bindestriche im Token werden jetzt ignoriert.
- Token-Feld in der App ohne Autokorrektur.

## [1.6.0] – 2026-11-11

### Neu
- **Set-Sammelfortschritt:** Tab „Sets“ mit Fortschritt je Edition (Grundset / inkl. Varianten), Set-Ansicht mit
  vorhandenen und fehlenden Karten, Filter nach Seltenheit, Wert der fehlenden Karten, „Fehlende → Wunschliste“.
  In der App unter Suche → „Editionen & Sammelfortschritt“.
- **Scan-Sprache:** wählbar oder automatisch vom Kartenrand gelesen (z.B. `DMU • DE`); gespeichert wird der Druck
  in dieser Sprache. Auch im PC-Dialog „Karte hinzufügen“.
- **Doppelte Karten ab 2 Exemplaren:** Filter in Sammlung und App, über alle Drucke zusammengezählt, mit
  überzähligen Exemplaren und deren Wert.

## [1.5.0] – 2026-11-11

### Neu
- **Proxy-PDF zum Drucken** aus der Wunschliste (alle oder ausgewählte Karten) und aus Decks (fehlende Karten):
  9 Karten pro Seite in Originalgröße 63,5 × 88,9 mm, A4 oder US Letter, Schnittmarken, optional Abstand.
  Doppelseitige Karten mit beiden Seiten, Text-Proxy wenn kein Bild verfügbar.
- App: Proxy-PDF öffnen, drucken oder teilen.

## [1.4.0] – 2026-11-11

### Neu
- **Wunschliste** mit Zielpreis (bestimmter oder günstigster Druck), täglicher Preisprüfung und
  **Benachrichtigung in der App**, sobald der Zielpreis erreicht ist.
- Eingescannte Karten erfüllen Wünsche automatisch; „Fehlende → Wunschliste“ im Deck.
- **Stapel-Scan:** Karten erst sammeln, dann in einer Zusammenfassung mit Gesamtwert prüfen, korrigieren und
  auf einmal speichern.

## [1.3.0] – 2026-11-11

### Neu
- **Statistik:** Sammlungswert, Wertverlauf, Manakurve, Kartentypen, Farbidentität, Seltenheit, Editionen,
  wertvollste Karten.
- Preise werden **täglich automatisch aktualisiert** und der Sammlungswert gespeichert.
- **Deck-Reservierung:** Karten, die auch in anderen Decks stecken (⇄), und Bedarf für alle Decks gleichzeitig;
  Kartendetails zeigen, in welchen Decks eine Karte steckt. Mini-Manakurve pro Deck.

## [1.2.0] – 2026-11-11

### Neu
- **Decks:** Decklisten einfügen (Moxfield, Arena, MTGO, Archidekt), Abgleich mit der Sammlung (✓/✗),
  Commander-Farbidentität prüfen, fehlende Karten exportieren. Deck-Tab auch in der App.
- **HTTPS (optional):** eigenes Zertifikat oder `tailscale cert`, Zertifikats-Pinning in App und Desktop.

### Verbessert
- Scannen: mehrere Namenskandidaten (Showcase/randlose Karten), Querformat-Rahmen für Schlachten.

## [1.1.0] – 2026-11-11

### Verbessert
- Scannen: schnellere, fehlertolerante Erkennung, Vibration/Ton, Scan-Verlauf mit Rückgängig,
  **Offline-Warteschlange**, Tippen zum Fokussieren, Zwei-Finger-Zoom.
- Server: Scryfall-Cache auf der Festplatte (schneller, offline nutzbar), „Alle Karten aktualisieren“.

## [1.0.0] – 2026-11-11

### Erste Version
- **Android-App:** Karten mit der Kamera scannen (Texterkennung auf dem Gerät), Sammlung durchsuchen.
- **Linux-Desktop (.deb):** Karten per Name eintragen, suchen, Import/Export (JSON/CSV), lokale Datenbank oder
  Verbindung zum Server.
- **Headless-Server (.deb)** für Ubuntu als systemd-Dienst mit Token-Schutz.
- Kartendaten von Scryfall (Fähigkeiten, Farbidentität, Preise), automatische Tags Commander, Partner, Companion.
- Verbindung über WLAN (automatische Suche) oder Tailscale.
