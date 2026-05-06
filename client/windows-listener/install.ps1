# Install Windows listener for memory-mcp webhooks.
# Must be run elevated (Run as Administrator).

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Run this script as Administrator."
    exit 1
}

# --- CONFIGURE THESE ---
$here     = "C:\Users\<USERNAME>\.claude\windows-listener"  # path to this folder
$python   = "C:\Users\<USERNAME>\AppData\Local\Programs\Python\Python312\pythonw.exe"
$user     = "<USERNAME>"                                      # Windows login name
$lanCidr  = "192.168.0.0/16"                                  # restrict inbound to LAN; tighten if needed
# -----------------------

$script   = Join-Path $here "listener.py"
$taskName = "memory-mcp-listener"
$port     = 8787

Write-Host "==> Installing BurntToast (PowerShell module)"
if (-not (Get-Module -ListAvailable -Name BurntToast)) {
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Install-Module -Name BurntToast -Scope AllUsers -Force -AllowClobber
} else {
    Write-Host "   BurntToast already installed"
}

Write-Host "==> Firewall rule: allow TCP $port inbound from $lanCidr"
$ruleName = "memory-mcp listener ($port)"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName $ruleName
}
New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $port `
    -RemoteAddress $lanCidr `
    -Action Allow `
    -Profile Any | Out-Null

Write-Host "==> Scheduled Task: $taskName (At log on, $user)"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action    = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $here
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 3 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null

Write-Host "==> Starting the task now"
Start-ScheduledTask -TaskName $taskName

Start-Sleep -Seconds 3
Write-Host "==> Health check"
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "   HTTP $($r.StatusCode): $($r.Content.Trim())"
} catch {
    Write-Warning "   health check failed: $_"
    $log = Join-Path $here "listener.log"
    if (Test-Path $log) { Get-Content $log -Tail 20 }
}

Write-Host "DONE. Set webhook URL in memory-mcp config.yaml: http://<THIS_PC_IP>:$port/notify"
