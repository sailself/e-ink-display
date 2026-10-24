# E-ink dashboard for a Boox Palma 2

Turns a retired Boox Palma 2 (Android 13, 824x1648 e-ink) into an always-on status display:
big clock, today's weather, AI subscription quota (Claude + Codex), and today's calendar events.

```
PC (Windows)                                USB / Wi-Fi                Boox Palma 2
┌──────────────────────────────┐                             ┌──────────────────────┐
│ server/server.py  :8787      │  <── adb reverse (USB) ───  │ dev.eink.dashboard   │
│  ├ Claude usage (OAuth file) │  <── http://PC-IP:8787 ───  │  fullscreen WebView  │
│  ├ Codex usage (auth.json)   │       (needs firewall rule) │  keeps screen on     │
│  ├ Open-Meteo weather        │                             │  restarts on boot    │
│  └ ICS calendars             │                             │  retries forever     │
└──────────────────────────────┘                             └──────────────────────┘
```

## Layout

| Path | What |
|---|---|
| `config.json` | Location, units, refresh timing, calendar feeds, credential file paths. Hot-reloaded. Not committed; start from `config.example.json`. |
| `server/server.py` | HTTP server: `/` dashboard page, `/api/data` merged JSON, `/api/health`. |
| `server/providers/*.py` | One module per data source. Each is cached on its own TTL; failures keep the last good data and flag it `stale`. |
| `server/adb_bridge.py` | Re-issues `adb reverse tcp:8787 tcp:8787` every 30 s so the USB-tethered device reaches the PC at `localhost`. |
| `dashboard/index.html` | The page. Pure black/white, vw-sized, no animation. Periodic black flash clears e-ink ghosting. |
| `android/` | Kiosk app source + `build.py` (aapt2/javac/d8/apksigner, no Gradle). Output: `android/build/eink-dashboard.apk`. |
| `scripts/` | `install-startup-task.ps1` (server at logon), `setup-device.ps1` (install + launch app), `setup-firewall.ps1` (optional Wi-Fi). |
| `logs/server.log` | Server log. |

## Fresh setup

1. `winget install Google.PlatformTools` (adb) and enable USB debugging on the Boox; accept its prompt.
2. `pip install --user -r requirements.txt` (Python 3.11+).
3. Copy `config.example.json` to `config.json`; set your location and put your PC's LAN address in
   `dashboard_urls`. Leave `adb.device_wifi` empty unless you want Wi-Fi adb.
4. `scripts\install-startup-task.ps1` starts the server now and at every logon.
5. Build tools: unzip Google's `build-tools_r34-windows.zip` and `platform-35_r02.zip` into
   `%LOCALAPPDATA%\Android\Sdk\build-tools\34.0.0` and `...\platforms\android-35`, have a JDK on `PATH`, then
   `python android\build.py`. It bakes `dashboard_urls` from `config.json` into the app, so put your PC's
   LAN address there first.
6. `scripts\setup-device.ps1` installs and launches the app and opens Boox's App Freeze screen: switch the
   app's freeze toggle OFF there.
7. Optional: `scripts\setup-firewall.ps1` from an elevated shell to run the display over Wi-Fi only.

## Data sources

- **Claude** reads the access token from `~/.claude/.credentials.json` (Claude Code's login) and calls the same
  usage endpoint as Claude Code's `/usage`. Tokens are never refreshed by the dashboard. When the token expires
  (about 8 h after Claude Code last refreshed it) the card shows the last values marked `stale` until you open
  Claude Code again.
- **Codex** does the same with `~/.codex/auth.json` and the ChatGPT usage endpoint.
- **Weather** is Open-Meteo for the `location` in `config.json` (no key). Set `"units": "imperial"` for °F/mph.
- **Calendar** accepts any ICS URL (Google Calendar "secret address in iCal format", Outlook "publish calendar",
  iCloud public share). Recurring events are expanded. Example:

  ```json
  "calendar": { "ics_urls": [ { "name": "Work", "url": "https://calendar.google.com/calendar/ical/.../basic.ics" } ] }
  ```

## Orientation

`dashboard.orientation` in `config.json` drives the screen: `portrait`, `landscape`, `reverse-portrait`,
`reverse-landscape` (USB port on the other side), `sensor-portrait`, `sensor-landscape`, or `auto` (follows
the accelerometer, so the layout changes when you rotate the device). The page relays the value to the app
after each poll, so a config edit takes effect within one refresh. Portrait is one column; landscape is three
(clock + weather, quota, events). `auto` needs Android's own auto-rotate switch on (`settings put system
accelerometer_rotation 1`): Boox ships with it off and ignores the app's sensor request while it is off.
`setup-device.ps1` sets it, and the server re-asserts it over adb whenever the config says `auto`.
One-off test without touching config:
`adb shell am start -n dev.eink.dashboard/.MainActivity --es orientation landscape`.

## Day-to-day

- Server runs as the per-user Scheduled Task `EinkDashboardServer` (starts at logon, restarts on failure).
  Re-register or remove it with `scripts\install-startup-task.ps1 [-Uninstall]`. Run in the foreground with
  `scripts\start-server.ps1`.
- Edit `config.json` and the server picks it up within seconds; the page refreshes every `refresh_seconds`.
- Edit `dashboard/index.html` and the page updates on its next full reload (or press Back on the device and
  reopen the app). Preview on the PC at <http://localhost:8787/> with a 440x880 viewport.
- Device: Back exits the dashboard; the launcher icon "E-ink Dashboard" reopens it. The app starts itself after
  a reboot.

## Rebuilding / reinstalling the app

```powershell
python android\build.py          # needs build-tools + a platform under %LOCALAPPDATA%\Android\Sdk and a JDK
scripts\setup-device.ps1         # adb install, grant boot-start app-op, adb reverse, launch
scripts\setup-device.ps1 -Urls "http://<PC-LAN-IP>:8787/"     # override the URL list (persisted on device)
```

## Wi-Fi instead of USB

`scripts\setup-firewall.ps1` (run once from an elevated PowerShell) opens inbound TCP 8787 on every profile, so
the Palma can run from any charger and use `http://<PC-LAN-IP>:8787/`, the second entry of `dashboard_urls`
in `config.json` (baked into the APK at build time). The app tries its URLs in order, remembers the one that
last worked, and the page asks it to move on after three failed polls in a row (for example when the cable is
pulled and `localhost` dies). Give the PC a DHCP reservation so that address stays valid, or change
`dashboard_urls` and rebuild.

The server can also keep its adb watchdog over Wi-Fi: `setup-device.ps1` puts the device in `adb tcpip 5555`
mode and the server connects to `adb.device_wifi` from `config.json` whenever no USB device is attached. A
device reboot clears tcpip mode; plug the cable in once and re-run the script (or `adb tcpip 5555`) to restore
it. Without it the app still recovers on its own after a boot through its boot receiver.

## Boox gotchas

- Boox "App Freeze" disables third-party apps (`pm disable-user`) around reboots, crashes and backgrounding.
  The per-app switch for *E-ink Dashboard* has been turned OFF in Settings → Apps → App Freeze (also reachable
  with `adb shell am start -a onyx.settings.action.APP_FREEZE_MANAGEMENT`). "Freeze new apps" is still ON, so
  a fresh install under a new package name would need the switch flipped again. As a safety net the server's
  USB watchdog re-enables and relaunches the app if it ever finds it frozen, and launches it within 10 minutes
  of a device boot if it is not running (`adb.watch_app` in `config.json`). Manual fix:
  `adb shell pm enable dev.eink.dashboard`.
- Android 13 only lets the boot receiver start an activity because `setup-device.ps1` grants the
  `SYSTEM_ALERT_WINDOW` app-op. Re-run that step if you reinstall from scratch.
- `android/eink-debug.keystore` signs the APK; keep it so updates install over the existing app.
