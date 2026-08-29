# One-time setup for the admin PC: makes PRINTME! start itself, silently,
# every time this Windows account logs in - no terminal, no "did I run
# the server today," no remembering `flask db upgrade` (wsgi.py now does
# that itself on every launch - see wsgi.py).
#
# Run this ONCE, from a normal (not necessarily elevated) PowerShell
# prompt, after setup.ps1 has already created venv\ and installed
# requirements.txt:
#
#   cd C:\PRINTME
#   .\scripts\install_startup_task.ps1
#
# Safe to re-run - Register-ScheduledTask -Force replaces the existing
# task rather than erroring or duplicating it.
#
# Deliberate choice: the trigger is "at log on," not "run whether user is
# logged on or not." The latter needs this Windows account's password
# stored inside Task Scheduler, which is a real credential-security
# tradeoff for a shop counter PC - not worth it here. The real
# consequence: PRINTME! only starts once someone actually logs into
# Windows. If the counter PC should be ready before anyone touches it,
# configure Windows itself for auto-logon (Settings > Accounts > Sign-in
# options, or netplwiz) - that's a Windows setting, not something this
# script can or should do on its own.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonwPath = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
$WsgiPath = Join-Path $RepoRoot "wsgi.py"
$TaskName = "PRINTME! Print Queue"

if (-not (Test-Path $PythonwPath)) {
    Write-Error "venv\Scripts\pythonw.exe not found at $PythonwPath - run setup.ps1 first."
    exit 1
}
if (-not (Test-Path $WsgiPath)) {
    Write-Error "wsgi.py not found at $WsgiPath - is this script running from inside the PRINTME repo?"
    exit 1
}

Write-Host "Registering scheduled task '$TaskName'..."

$action = New-ScheduledTaskAction -Execute $PythonwPath -Argument '"wsgi.py"' -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Runs the PRINTME! print queue server (wsgi.py) at log on. Installed by scripts/install_startup_task.ps1." `
    -Force | Out-Null

Write-Host "Starting it now, so you don't have to log out and back in to see it work..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

# Desktop shortcut - the "just open it like Chrome" piece. A plain
# .url file is the simplest possible Windows internet shortcut; no
# custom icon resource needed for a first version.
#
# The address it points at follows SERVE_HOST from .env (see wsgi.py):
# once that's locked to the customer router's reserved IP, 127.0.0.1
# stops working (the server no longer binds the loopback interface at
# all), so the shortcut has to match whatever wsgi.py will actually
# bind to, not always assume localhost.
$DashboardHost = "127.0.0.1"
$EnvPath = Join-Path $RepoRoot ".env"
if (Test-Path $EnvPath) {
    $match = Select-String -Path $EnvPath -Pattern '^\s*SERVE_HOST\s*=\s*(\S+)' | Select-Object -First 1
    if ($match) {
        $DashboardHost = $match.Matches[0].Groups[1].Value
    }
}
$DashboardUrl = "http://${DashboardHost}:5000/admin/"

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "PRINTME Dashboard.url"
@"
[InternetShortcut]
URL=$DashboardUrl
"@ | Set-Content -Path $ShortcutPath -Encoding ASCII

Write-Host ""
Write-Host "Done:"
Write-Host " - PRINTME! now starts automatically every time this Windows account logs in."
Write-Host " - A 'PRINTME Dashboard' icon was added to the Desktop - open it like any other app."
Write-Host " - It should already be running right now: $DashboardUrl"
Write-Host ""
Write-Host "If the page doesn't load, check instance\printme.log for what went wrong."
