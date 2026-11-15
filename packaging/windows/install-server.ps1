# MTG Cards Server als Hintergrunddienst einrichten (wird vom Installer mit Admin-Rechten ausgeführt).
# - Geplante Aufgabe "MTG Cards Server": startet mit Windows als SYSTEM, startet bei Absturz neu
# - Firewall-Freigaben: TCP 8765 (App/Desktop/Browser), UDP 47811 (Suche im WLAN)
param(
    [Parameter(Mandatory = $true)][string]$Exe
)
$ErrorActionPreference = "Stop"
$dataDir = Join-Path $env:ProgramData "mtg-cards"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$log = Join-Path $dataDir "server.log"
$taskName = "MTG Cards Server"

# Konfiguration + Token anlegen (falls noch nicht vorhanden)
& $Exe --show-token | Out-Null

# Laufende Instanz beenden (Update)
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Get-Process -Name "mtg-cards-server" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $Exe -Argument "--log `"$log`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description "MTG Cards Headless-Server (Port 8765)" -Force | Out-Null

# Firewall
foreach ($name in @("MTG Cards Server (TCP)", "MTG Cards Suche (UDP)")) {
    Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
}
New-NetFirewallRule -DisplayName "MTG Cards Server (TCP)" -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort 8765 -Program $Exe -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "MTG Cards Suche (UDP)" -Direction Inbound -Action Allow -Protocol UDP `
    -LocalPort 47811 -Program $Exe -Profile Any | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Output "MTG Cards Server eingerichtet."
