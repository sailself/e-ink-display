<#
.SYNOPSIS
  Installs the kiosk app on the USB-connected Boox and launches it.
.PARAMETER Urls
  Comma-separated dashboard URLs to try in order (default: the list baked into the APK).
.PARAMETER Apk
  Path to the APK (default: android\build\eink-dashboard.apk).
#>
param(
    [string]$Urls = "",
    [string]$Apk = ""
)

$root = Split-Path -Parent $PSScriptRoot
if (-not $Apk) { $Apk = Join-Path $root "android\build\eink-dashboard.apk" }
if (-not (Test-Path $Apk)) { throw "APK not found at $Apk - run: python android\build.py" }

$adb = (Get-Command adb.exe -ErrorAction SilentlyContinue).Source
if (-not $adb) {
    $adb = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Google.PlatformTools_*\platform-tools\adb.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $adb) { throw "adb not found; run: winget install Google.PlatformTools" }

$pkg = "dev.eink.dashboard"
$port = (Get-Content (Join-Path $root "config.json") | ConvertFrom-Json).port

& $adb start-server | Out-Null
$state = (& $adb get-state 2>&1)
if ($state -ne "device") { throw "No authorized device (adb get-state: $state). Plug in the Boox and accept the USB debugging prompt." }

$fresh = -not ((& $adb shell pm list packages $pkg) -match [regex]::Escape("package:$pkg"))
Write-Host "Installing $Apk ..."
& $adb install -r $Apk
# Boox "Freeze new apps" disables freshly installed packages; undo that and point the user at the per-app switch.
& $adb shell pm enable $pkg | Out-Null
if ($fresh) {
    Write-Host "New package: turn OFF the 'E-ink Dashboard' switch on the App Freeze screen that is opening now, then press Back."
    & $adb shell am start -a onyx.settings.action.APP_FREEZE_MANAGEMENT | Out-Null
    Start-Sleep -Seconds 8
}
# Let the boot receiver start an activity from the background (Android 10+ restriction).
& $adb shell appops set $pkg SYSTEM_ALERT_WINDOW allow
# Make http://localhost:$port on the device reach this PC over USB. The server re-issues this every 30 s too.
& $adb reverse "tcp:$port" "tcp:$port"
# Let adb also reach the device over Wi-Fi once the cable is out (cleared by a device reboot; re-run this then).
$wifi = (Get-Content (Join-Path $root "config.json") | ConvertFrom-Json).adb.device_wifi
if ($wifi) { & $adb tcpip 5555 | Out-Null; Start-Sleep -Seconds 3; & $adb connect $wifi }

if ($Urls) {
    & $adb shell am start -n "$pkg/.MainActivity" --es urls "`"$Urls`""
} else {
    & $adb shell am start -n "$pkg/.MainActivity"
}
Write-Host "Launched. Press Back on the device to leave the dashboard; tap its icon to return."
