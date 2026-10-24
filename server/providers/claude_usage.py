"""Claude subscription quota, read through the same OAuth usage endpoint Claude Code's /usage uses.

The access token is taken read-only from Claude Code's credentials file. It is never refreshed here:
when it expires, the dashboard shows the last known values as stale until Claude Code is opened again.
"""
import json
import os
import time

from http_util import get_json

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KIND_LABELS = {
    "session": "5-hour session",
    "weekly_all": "Weekly · all models",
    "weekly_scoped": "Weekly · {model}",
}


def _money(m):
    if not m:
        return None
    return m.get("amount_minor", 0) / (10 ** m.get("exponent", 2))


def fetch(cfg):
    path = os.path.expanduser(cfg["claude"]["credentials_file"])
    with open(path, encoding="utf-8") as f:
        creds = json.load(f).get("claudeAiOauth") or {}
    token = creds.get("accessToken")
    if not token:
        raise RuntimeError("No Claude login found in credentials file")
    expires_at = (creds.get("expiresAt") or 0) / 1000
    if expires_at and expires_at < time.time():
        raise RuntimeError("Claude token expired; open Claude Code once to refresh it")

    data = get_json(USAGE_URL, {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
    })

    limits = []
    for lim in data.get("limits") or []:
        kind = lim.get("kind") or "limit"
        model = ((lim.get("scope") or {}).get("model") or {}).get("display_name") or "model"
        limits.append({
            "label": KIND_LABELS.get(kind, kind.replace("_", " ")).format(model=model),
            "percent": lim.get("percent"),
            "resets_at": lim.get("resets_at"),
            "severity": lim.get("severity") or "normal",
            "active": bool(lim.get("is_active")),
        })
    if not limits:  # older payload shape
        for key, label in (("five_hour", KIND_LABELS["session"]), ("seven_day", KIND_LABELS["weekly_all"])):
            w = data.get(key)
            if w:
                limits.append({"label": label, "percent": w.get("utilization"), "resets_at": w.get("resets_at"),
                               "severity": "normal", "active": False})

    spend = None
    s = data.get("spend") or {}
    if s.get("enabled"):
        spend = {
            "used": _money(s.get("used")),
            "limit": _money(s.get("limit")),
            "currency": (s.get("used") or {}).get("currency"),
            "percent": s.get("percent"),
        }

    return {
        "provider": "Claude",
        "plan": (creds.get("subscriptionType") or "").title(),
        "limits": limits,
        "spend": spend,
    }
