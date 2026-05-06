# Uninstall Windows listener. Must be run elevated.

$ErrorActionPreference = "Continue"

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "Run as Administrator."; exit 1 }

$taskName = "memory-mcp-listener"
$port     = 8787

Write-Host "==> Stopping and removing Scheduled Task"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Write-Host "==> Killing running listener processes"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match "windows-listener\\listener\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "==> Removing firewall rule"
if (Get-NetFirewallRule -DisplayName "memory-mcp listener ($port)" -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName "memory-mcp listener ($port)"
}

Write-Host "DONE. (BurntToast left installed — remove manually if needed: Uninstall-Module BurntToast)"
