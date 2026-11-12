## MTG Cards für Windows (Vorschau)

Windows-Version von **Desktop-Anwendung** und **Server** – gleiche Funktionen und gleiche Schnittstelle wie unter
Linux. Alle Kombinationen funktionieren: Handy-App ↔ Windows-PC/-Server, Windows-Desktop ↔ Linux-Server,
Linux-Desktop ↔ Windows-Server.

### Neu in 2.0.0

Enthält alle Korrekturen aus Version 2.0.0 (sicherer Import, kein doppeltes Speichern von Scans, aktuelle Preise,
Tags mit Umlauten, Enter in den Dialogen …) – siehe [CHANGELOG](https://github.com/hxpexlss/mtg-cards/blob/claude/windows-build/CHANGELOG.md).

Zusätzlich für Windows behoben:

- **Desktop + Server auf demselben PC:** Windows ließ beide Programme denselben Port 8765 gleichzeitig belegen –
  die Desktop-Anwendung hat den laufenden Server deshalb nicht erkannt. Der Port wird jetzt exklusiv belegt, die
  Desktop-Anwendung verbindet sich wie vorgesehen automatisch mit dem Server (auch wenn dieser HTTPS verwendet).
- **Server wieder entfernt:** Die Desktop-Anwendung blieb auf „Server auf diesem PC“ eingestellt und leitete Anfragen
  endlos an sich selbst weiter. Sie wechselt jetzt zurück zur eigenen Datenbank.
- **Update:** Der Installer beendet Server und Desktop-Anwendung, bevor er Dateien ersetzt (vorher waren sie
  gesperrt und Windows verlangte einen Neustart).
- Kein kurz aufblitzendes schwarzes Fenster mehr, wenn die Desktop-Anwendung Tailscale abfragt.
- Umlaute im Installationsprogramm werden richtig dargestellt; verständliche Meldung, wenn der Port belegt ist.

### Installation

1. `MTG-Cards-Setup-<version>.exe` herunterladen und ausführen (Administratorrechte nötig).
   Windows SmartScreen warnt evtl. („Unbekannter Herausgeber“) → „Weitere Informationen“ → „Trotzdem ausführen“.
2. Auswählen:
   - **Desktop-Anwendung** – eigenes Fenster (über Microsoft Edge im App-Modus), eigene Sammlung oder Verbindung
     zu einem Server.
   - **Server** – läuft im Hintergrund und startet mit Windows (geplante Aufgabe „MTG Cards Server“, Port 8765).
   - oder beides – die Desktop-Anwendung verbindet sich dann automatisch mit dem Server auf diesem PC.
3. Server-Token: Startmenü → **MTG Cards → Server-Token anzeigen**.

Die Firewall-Freigaben (TCP 8765, UDP 47811 für die WLAN-Suche) richtet der Installer ein.

### Speicherorte

| | |
|---|---|
| Server-Datenbank, Token, Log | `C:\ProgramData\mtg-cards\` |
| Desktop-Datenbank | `%LOCALAPPDATA%\mtg-cards\` |
| Desktop-Einstellungen | `%APPDATA%\mtg-cards\config.json` |

Beim Deinstallieren und bei Updates bleiben die Daten erhalten. Update: einfach das neue Setup ausführen.

### Portable Version

`MTG-Cards-Windows-portable-<version>.zip` enthält beide Programme ohne Installation
(`mtg-cards-desktop\mtg-cards-desktop.exe`, `mtg-cards-server\mtg-cards-server.exe`). Der Server läuft dann nur,
solange das Fenster offen ist.

> Vorschau-Version: auf GitHub unter Windows automatisch getestet (Tests, Server- und Desktop-Start),
> aber noch nicht auf einem echten PC ausprobiert. Rückmeldungen willkommen.
