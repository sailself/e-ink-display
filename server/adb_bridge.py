"""adb-side helper for the Boox device.

1. Keeps `adb reverse` alive so the device can reach this server at http://localhost:PORT/.
   Loopback traffic is not filtered by Windows Firewall, so this works even when the Wi-Fi network is marked
   Public. The call is idempotent, so it is simply re-issued every maintenance tick.
2. Watches the kiosk app: Boox "auto-freezes" (pm disable-user) third-party apps around reboots and crashes,
   so if the package is found disabled it is re-enabled and relaunched; if the device booted recently and the
   app is not running, it is launched. A deliberate exit (Back button) is left alone otherwise.

The device is addressed explicitly (`adb -s`): USB is preferred; otherwise the Wi-Fi adb endpoint from
`adb.device_wifi` is tried (it only answers while the device is in `adb tcpip 5555` mode, which a device
reboot clears).
"""
import glob
import logging
import os
import shutil
import subprocess
import time


def find_adb(cfg_path=""):
    candidates = []
    if cfg_path:
        candidates.append(os.path.expanduser(cfg_path))
    which = shutil.which("adb")
    if which:
        candidates.append(which)
    local = os.environ.get("LOCALAPPDATA", "")
    candidates += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Google.PlatformTools_*",
                                         "platform-tools", "adb.exe"))
    candidates.append(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


class AdbBridge:
    def __init__(self, cfg, port):
        adb_cfg = cfg.get("adb") or {}
        self.cfg = cfg
        self.port = port
        self.adb = find_adb(adb_cfg.get("path", ""))
        self.enabled = bool(adb_cfg.get("reverse", True)) and self.adb is not None
        self.package = adb_cfg.get("app_package", "dev.eink.dashboard")
        self.watch_app = bool(adb_cfg.get("watch_app", True)) and bool(self.package)
        self.boot_window_s = int(adb_cfg.get("boot_window_seconds", 600))
        self.device_wifi = adb_cfg.get("device_wifi", "")  # "<device-ip>:5555", valid after `adb tcpip 5555`
        self.serial = None
        self.last_wifi_try = 0.0
        self.last_ok = None
        self.last_error = None
        self.last_attempt = 0.0
        self.last_app_check = 0.0
        self.app_state = None

    # -- low level -------------------------------------------------------------------------------------------
    def _run(self, *args, timeout=20):
        return subprocess.run([self.adb, *args], capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _dev(self, *args, timeout=20):
        return self._run("-s", self.serial, *args, timeout=timeout)

    def _shell(self, cmd, timeout=20):
        r = self._dev("shell", cmd, timeout=timeout)
        return (r.stdout or "").strip()

    def _pick_device(self):
        """Serial to talk to: a USB device first, else the Wi-Fi endpoint. None if nothing is attached."""
        serials = []
        for line in (self._run("devices").stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        usb = [s for s in serials if ":" not in s]
        return (usb or serials or [None])[0]

    def _try_wifi(self):
        if not self.device_wifi or time.time() - self.last_wifi_try < 120:
            return
        self.last_wifi_try = time.time()
        try:
            c = self._run("connect", self.device_wifi, timeout=15)
            if "connected to" in (c.stdout or ""):
                logging.info("adb reached %s over Wi-Fi", self.device_wifi)
        except Exception:  # noqa: BLE001 - unreachable endpoint, nothing to do
            pass

    # -- maintenance tick ------------------------------------------------------------------------------------
    def keepalive(self, cfg=None):
        if not self.enabled:
            return
        if cfg is not None:
            self.cfg = cfg
        self.last_attempt = time.time()
        try:
            serial = self._pick_device()
            if serial is None:
                self._try_wifi()
                serial = self._pick_device()
            if serial is None:
                self.serial = None
                self.last_error = "no device attached (USB or Wi-Fi adb)"
                return
            if serial != self.serial:
                logging.info("adb device: %s", serial)
                self.serial = serial
            r = self._dev("reverse", f"tcp:{self.port}", f"tcp:{self.port}")
            if r.returncode == 0:
                self.last_ok = time.time()
                self.last_error = None
                if self.watch_app:
                    self._watch_app()
            else:
                self.last_error = (r.stderr or r.stdout).strip() or f"adb exit {r.returncode}"
        except Exception as e:  # adb missing, timeout, ...
            self.last_error = str(e)

    def _watch_app(self):
        if time.time() - self.last_app_check < 60:
            return
        self.last_app_check = time.time()
        pkg = self.package
        try:
            self._ensure_auto_rotate()
            if f"package:{pkg}" in self._shell(f"pm list packages -d {pkg}").splitlines():
                logging.warning("%s is frozen/disabled on the device; re-enabling and relaunching", pkg)
                self._dev("shell", "pm", "enable", pkg)
                self._launch()
                self.app_state = "relaunched (was frozen)"
                return
            if not self._shell(f"pidof {pkg}"):
                uptime = float(self._shell("cat /proc/uptime").split()[0])
                if uptime < self.boot_window_s:
                    logging.info("device booted %.0fs ago and %s is not running; launching", uptime, pkg)
                    self._launch()
                    self.app_state = "launched after boot"
                else:
                    self.app_state = "not running (left alone)"
            else:
                self.app_state = "running"
        except Exception as e:  # noqa: BLE001
            self.app_state = f"check failed: {e}"

    def _ensure_auto_rotate(self):
        """Boox ignores an app's sensor-orientation request unless Android's own auto-rotate is on."""
        mode = ((self.cfg or {}).get("dashboard") or {}).get("orientation", "portrait")
        if mode not in ("auto", "sensor", "sensor-portrait", "sensor-landscape"):
            return
        if self._shell("settings get system accelerometer_rotation") != "1":
            self._dev("shell", "settings", "put", "system", "accelerometer_rotation", "1")
            logging.info("enabled Android auto-rotate on the device (orientation=%s)", mode)

    def _launch(self):
        self._dev("shell", "am", "start", "-n", f"{self.package}/.MainActivity")

    def status(self):
        return {
            "enabled": self.enabled,
            "adb": self.adb,
            "device": self.serial,
            "connected": self.enabled and self.last_error is None and self.last_ok is not None,
            "error": self.last_error,
            "app": self.app_state,
        }
