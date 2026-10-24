"""OpenAI Codex (ChatGPT subscription) rate-limit windows.

Reads the ChatGPT access token from the Codex CLI auth file (read-only, never refreshed here).
"""
import base64
import json
import os
import time
from datetime import datetime, timezone

from http_util import get_json

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None


def _window_label(seconds):
    if not seconds:
        return "Window"
    if seconds < 2 * 86400:
        return f"{round(seconds / 3600)}-hour session"
    days = round(seconds / 86400)
    return "Weekly" if days == 7 else f"{days}-day"


def fetch(cfg):
    path = os.path.expanduser(cfg["codex"]["auth_file"])
    with open(path, encoding="utf-8") as f:
        auth = json.load(f)
    tokens = auth.get("tokens") or {}
    token = tokens.get("access_token")
    if not token:
        raise RuntimeError("No Codex ChatGPT login found (run codex login)")
    exp = _jwt_exp(token)
    if exp and exp < time.time():
        raise RuntimeError("Codex token expired; run codex once to refresh it")

    data = get_json(USAGE_URL, {
        "Authorization": f"Bearer {token}",
        "ChatGPT-Account-Id": tokens.get("account_id") or "",
        "Accept": "application/json",
    })

    limits = []
    rl = data.get("rate_limit") or {}
    for key in ("primary_window", "secondary_window"):
        w = rl.get(key)
        if not w:
            continue
        pct = w.get("used_percent")
        reset = w.get("reset_at")
        limits.append({
            "label": _window_label(w.get("limit_window_seconds")),
            "percent": pct,
            "resets_at": datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else None,
            "severity": "warning" if (pct or 0) >= 80 else "normal",
            "active": bool(rl.get("limit_reached")),
        })

    return {
        "provider": "Codex",
        "plan": (data.get("plan_type") or "").title(),
        "limits": limits,
        "spend": None,
    }
