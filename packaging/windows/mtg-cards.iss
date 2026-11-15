; Inno-Setup-Skript für MTG Cards (Windows)
; Bauen: iscc /DAppVersion=1.9.0 packaging\windows\mtg-cards.iss
; Erwartet die PyInstaller-Ausgabe in dist\windows\mtg-cards-desktop (ab Version 3: nur Desktop)

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

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"

[Files]
Source: "mtg-cards.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\windows\mtg-cards-desktop\*"; DestDir: "{app}\desktop"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "uninstall-server.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MTG Cards & Proxie Maker"; Filename: "{app}\desktop\mtg-cards-desktop.exe"
Name: "{autodesktop}\MTG Cards"; Filename: "{app}\desktop\mtg-cards-desktop.exe"; Tasks: desktopicon
Name: "{group}\MTG Cards deinstallieren"; Filename: "{uninstallexe}"

[Run]
; Server: Dienst (geplante Aufgabe) + Firewall einrichten und starten
; Desktop: Firewall-Freigabe, damit die Handy-App den PC erreicht (sonst fragt Windows beim ersten Start)
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Remove-NetFirewallRule -DisplayName 'MTG Cards Desktop' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'MTG Cards Desktop' -Direction Inbound -Action Allow -Program '{app}\desktop\mtg-cards-desktop.exe' -Profile Any | Out-Null"""; StatusMsg: "Firewall-Freigabe …"; Flags: runhidden waituntilterminated
; Nach der Installation
Filename: "{app}\desktop\mtg-cards-desktop.exe"; Description: "MTG Cards starten"; Flags: postinstall nowait skipifsilent

[Code]
// Vor dem Kopieren der Dateien: laufenden Server (geplante Aufgabe, läuft als SYSTEM) und die Desktop-Anwendung
// beenden. Sonst sind die .exe/.dll bei einem Update gesperrt und der Installer verlangt einen Neustart.
// Der Server wird danach von install-server.ps1 wieder gestartet.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "MTG Cards Server"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM mtg-cards-server.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM mtg-cards-desktop.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
  Result := '';
end;

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-server.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveServer"

[Messages]
german.FinishedLabel=MTG Cards (mit Proxie Maker) wurde installiert.%n%nBeim Start wählst du MTG Cards oder Proxie Maker. Die Datenbanken (AppData\Local\mtg-cards: cards.db und proxies.db) bleiben bei Updates und beim Deinstallieren erhalten.
