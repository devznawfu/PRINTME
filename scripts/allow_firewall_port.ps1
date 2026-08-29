# One-time: opens Windows Firewall for inbound TCP 5000, so customer
# phones on the shop's LAN can actually reach the server. Windows blocks
# inbound connections by default for most apps - without this, everything
# else (the always-on service, the dedicated router, the QR code) can be
# perfectly configured and phones still won't be able to load the page.
#
# Run this ONCE, from an ELEVATED (Run as Administrator) PowerShell prompt -
# New-NetFirewallRule requires admin rights, unlike the other setup scripts:
#
#   cd C:\PRINTME
#   .\scripts\allow_firewall_port.ps1
#
# Safe to re-run - removes any existing rule with the same name first.

$ErrorActionPreference = "Stop"
$RuleName = "PRINTME!"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This needs to run as Administrator - right-click PowerShell and choose 'Run as administrator', then run this script again."
    exit 1
}

Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow | Out-Null

Write-Host "Done: inbound TCP port 5000 is now allowed through Windows Firewall."
Write-Host "Customer phones on the same network as this PC should now be able to reach it."
