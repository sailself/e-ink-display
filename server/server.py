"""E-ink dashboard server.

Serves `dashboard/index.html` at `/` and a JSON feed at `/api/data` that merges every data source
(Claude quota, Codex quota, weather, calendar). Each source is refreshed in a background thread on its
own TTL; failures keep the last good payload and flag it as stale, so the display never goes blank.

Run:  python server/server.py            (config in ../config.json)
"""
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from providers import claude_usage, codex_usage, weather, calendar_ics  # noqa: E402
from adb_bridge import AdbBridge  # noqa: E402
from http_util import RateLimited  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config.json")
DASHBOARD_PATH = os.path.join(ROOT, "dashboard", "index.html")
LOG_PATH = os.path.join(ROOT, "logs", "server.log")
RETRY_AFTER_ERROR = 90  # seconds
RETRY_AFTER_429 = 900  # seconds: usage endpoints rate-limit aggressive polling


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds") if ts else None


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


class Section:
    """One cached data source with its own refresh interval and stale-on-error behaviour."""

    def __init__(self, name, ttl, fetch):
        self.name, self.ttl, self.fetch = name, ttl, fetch
        self.data = None
        self.fetched_at = 0.0
        self.error = None
        self.error_at = 0.0
        self.retry_after = RETRY_AFTER_ERROR
        self.lock = threading.Lock()

    def due(self):
        last = max(self.fetched_at, self.error_at)
        wait = self.ttl if self.error is None else max(min(self.ttl, RETRY_AFTER_ERROR), self.retry_after)
        return time.time() - last >= wait

    def refresh(self, cfg):
        with self.lock:
            try:
                self.data = self.fetch(cfg)
                self.fetched_at = time.time()
                if self.error:
                    logging.info("%s: recovered", self.name)
                self.error = None
            except Exception as e:  # noqa: BLE001 - any provider failure is reported, never fatal
                self.error = str(e)
                self.error_at = time.time()
                self.retry_after = RETRY_AFTER_429 if isinstance(e, RateLimited) else RETRY_AFTER_ERROR
                logging.warning("%s: %s (retry in %ds)", self.name, e, self.retry_after)

    def snapshot(self):
        return {
            "ok": self.error is None and self.data is not None,
            "stale": self.error is not None and self.data is not None,
            "error": self.error,
            "fetched_at": iso(self.fetched_at),
            "data": self.data,
        }


class Hub:
    def __init__(self):
        self.cfg = load_config()
        self.cfg_mtime = os.path.getmtime(CONFIG_PATH)
        self.port = int(self.cfg.get("port", 8787))
        self.sections = self._build_sections()
        self.adb = AdbBridge(self.cfg, self.port)
        self.started = time.time()

    def _build_sections(self):
        c = self.cfg
        return {
            "claude": Section("claude", c["claude"].get("ttl_seconds", 60), claude_usage.fetch),
            "codex": Section("codex", c["codex"].get("ttl_seconds", 60), codex_usage.fetch),
            "weather": Section("weather", c["weather"].get("ttl_seconds", 600), weather.fetch),
            "calendar": Section("calendar", c["calendar"].get("ttl_seconds", 300), calendar_ics.fetch),
        }

    def maybe_reload_config(self):
        try:
            m = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return
        if m != self.cfg_mtime:
            try:
                self.cfg = load_config()
                self.cfg_mtime = m
                for s in self.sections.values():
                    s.fetched_at = 0.0  # force refresh with new settings
                logging.info("config.json reloaded")
            except Exception as e:  # noqa: BLE001
                logging.warning("config.json reload failed: %s", e)

    def maintain(self):
        """Background loop: refresh due sections, keep adb reverse alive."""
        last_adb = 0.0
        while True:
            try:
                self.maybe_reload_config()
                for s in self.sections.values():
                    if s.due():
                        s.refresh(self.cfg)
                if time.time() - last_adb >= 30:
                    self.adb.keepalive()
                    last_adb = time.time()
            except Exception as e:  # noqa: BLE001
                logging.error("maintain loop: %s", e)
            time.sleep(5)

    def payload(self):
        d = self.cfg.get("dashboard") or {}
        return {
            "generated_at": iso(time.time()),
            "meta": {
                "refresh_seconds": d.get("refresh_seconds", 120),
                "flash_clear_minutes": d.get("flash_clear_minutes", 30),
                "full_reload_hours": d.get("full_reload_hours", 6),
                "timezone": self.cfg["location"]["timezone"],
                "location": self.cfg["location"].get("name"),
                "server_uptime_s": int(time.time() - self.started),
                "adb": self.adb.status(),
            },
            "sections": {name: s.snapshot() for name, s in self.sections.items()},
        }


HUB = None
CLIENTS = {}  # ip -> {"last_seen": iso, "path": str, "hits": n}; shown at /api/health to check the device link


class Handler(BaseHTTPRequestHandler):
    server_version = "EinkDashboard/0.1"

    def log_message(self, fmt, *args):
        ip = self.client_address[0]
        path = urlparse(self.path).path
        c = CLIENTS.setdefault(ip, {"hits": 0})
        c.update(last_seen=iso(time.time()), path=path, hits=c["hits"] + 1)
        if ip not in ("127.0.0.1", "::1"):  # the device; local curl/tests stay quiet
            logging.info("client %s GET %s", ip, path)

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(DASHBOARD_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError as e:
                self._send(500, str(e).encode(), "text/plain")
        elif path == "/api/data":
            self._send(200, json.dumps(HUB.payload()).encode("utf-8"), "application/json; charset=utf-8")
        elif path == "/api/health":
            body = {"ok": True, "uptime_s": int(time.time() - HUB.started), "adb": HUB.adb.status(), "clients": CLIENTS}
            self._send(200, json.dumps(body).encode("utf-8"), "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    global HUB
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    HUB = Hub()
    threading.Thread(target=HUB.maintain, name="maintain", daemon=True).start()
    bind = HUB.cfg.get("bind", "0.0.0.0")
    srv = ThreadingHTTPServer((bind, HUB.port), Handler)
    srv.daemon_threads = True
    logging.info("serving on http://%s:%d/ (adb: %s)", bind, HUB.port, HUB.adb.adb or "not found")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
