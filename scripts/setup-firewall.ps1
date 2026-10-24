<#
.SYNOPSIS
  (Optional, needs an elevated PowerShell) Opens the dashboard port so the Boox can reach it over Wi-Fi,
  which lets you unplug it from the PC and run it from any charger.
#>
$root = Split-Path -Parent $PSScriptRoot
$port = (Get-Content (Join-Path $root "config.json") | ConvertFrom-Json).port
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from an elevated (Administrator) PowerShell."
}
$name = "E-ink dashboard ($port)"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Any | Out-Null
Write-Host "Inbound TCP $port allowed on all profiles. The Boox can now use http://<this PC's LAN IP>:$port/"
