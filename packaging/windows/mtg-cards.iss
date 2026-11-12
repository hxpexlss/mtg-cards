; Inno-Setup-Skript für MTG Cards (Windows)
; Bauen: iscc /DAppVersion=1.9.0 packaging\windows\mtg-cards.iss
; Erwartet die PyInstaller-Ausgabe in dist\windows\mtg-cards-desktop und dist\windows\mtg-cards-server

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C6F3A52-0B6B-4F0E-9E59-3C1E5D2B7A11}
AppName=MTG Cards
AppVersion={#AppVersion}
AppVerName=MTG Cards {#AppVersion}
AppPublisher=MTG Cards
AppPublisherURL=https://github.com/hxpexlss/mtg-cards
DefaultDirName={autopf}\MTG Cards
DefaultGroupName=MTG Cards
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=MTG-Cards-Setup-{#AppVersion}
SetupIconFile=mtg-cards.ico
UninstallDisplayIcon={app}\mtg-cards.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ShowLanguageDialog=no
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Types]
Name: "desktop"; Description: "Desktop-Anwendung (eigene Sammlung oder mit Server verbinden)"
Name: "full"; Description: "Desktop-Anwendung + Server auf diesem PC"
Name: "server"; Description: "Nur Server (läuft im Hintergrund, startet mit Windows)"
Name: "custom"; Description: "Benutzerdefiniert"; Flags: iscustom

[Components]
Name: "desktop"; Description: "Desktop-Anwendung"; Types: desktop full custom
Name: "server"; Description: "Server (Hintergrunddienst für App und andere PCs)"; Types: server full

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; Components: desktop

[Files]
Source: "mtg-cards.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\windows\mtg-cards-desktop\*"; DestDir: "{app}\desktop"; Components: desktop; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\dist\windows\mtg-cards-server\*"; DestDir: "{app}\server"; Components: server; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "install-server.ps1"; DestDir: "{app}\server"; Components: server; Flags: ignoreversion
Source: "uninstall-server.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MTG Cards"; Filename: "{app}\desktop\mtg-cards-desktop.exe"; Components: desktop
Name: "{autodesktop}\MTG Cards"; Filename: "{app}\desktop\mtg-cards-desktop.exe"; Tasks: desktopicon
Name: "{group}\Server-Token anzeigen"; Filename: "{cmd}"; Parameters: "/k ""title MTG Cards Server-Token & ""{app}\server\mtg-cards-server.exe"" --show-token"""; Components: server
Name: "{group}\Server-Weboberfläche"; Filename: "http://127.0.0.1:8765"; Components: server
Name: "{group}\MTG Cards deinstallieren"; Filename: "{uninstallexe}"

[Run]
; Server: Dienst (geplante Aufgabe) + Firewall einrichten und starten
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\server\install-server.ps1"" -Exe ""{app}\server\mtg-cards-server.exe"""; StatusMsg: "Richte den Server-Dienst ein …"; Flags: runhidden waituntilterminated; Components: server
; Desktop: Firewall-Freigabe, damit die Handy-App den PC erreicht (sonst fragt Windows beim ersten Start)
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Remove-NetFirewallRule -DisplayName 'MTG Cards Desktop' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'MTG Cards Desktop' -Direction Inbound -Action Allow -Program '{app}\desktop\mtg-cards-desktop.exe' -Profile Any | Out-Null"""; StatusMsg: "Firewall-Freigabe …"; Flags: runhidden waituntilterminated; Components: desktop
; Nach der Installation
Filename: "{cmd}"; Parameters: "/k ""title MTG Cards Server-Token & ""{app}\server\mtg-cards-server.exe"" --show-token"""; Description: "Server-Token anzeigen (für App und andere PCs)"; Flags: postinstall skipifsilent unchecked; Components: server
Filename: "{app}\desktop\mtg-cards-desktop.exe"; Description: "MTG Cards starten"; Flags: postinstall nowait skipifsilent; Components: desktop

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-server.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveServer"

[Messages]
german.FinishedLabel=MTG Cards wurde installiert.%n%nDie Datenbanken (Server: C:\ProgramData\mtg-cards, Desktop: AppData\Local\mtg-cards) bleiben bei Updates und beim Deinstallieren erhalten.
