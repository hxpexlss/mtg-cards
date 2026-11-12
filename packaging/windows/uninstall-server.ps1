# MTG Cards Server-Dienst und Firewall-Regeln entfernen. Datenbank und Token in %ProgramData%\mtg-cards bleiben erhalten.
$taskName = "MTG Cards Server"
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Get-Process -Name "mtg-cards-server" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
foreach ($name in @("MTG Cards Server (TCP)", "MTG Cards Suche (UDP)", "MTG Cards Desktop")) {
    Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
}
