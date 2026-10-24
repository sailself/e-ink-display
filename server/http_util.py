"""Small HTTP helpers shared by the providers (stdlib + certifi)."""
import json
import ssl
import urllib.error
import urllib.request

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # certifi missing: fall back to the system store
    _CTX = ssl.create_default_context()

USER_AGENT = "eink-dashboard/0.1"


class RateLimited(RuntimeError):
    """HTTP 429: the caller should back off much longer than for an ordinary failure."""


def get_bytes(url, headers=None, timeout=20):
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = " ".join(e.read()[:300].decode("utf-8", "replace").split())
        msg = f"HTTP {e.code} from {url.split('?')[0]}: {body}"
        raise (RateLimited if e.code == 429 else RuntimeError)(msg) from None


def get_json(url, headers=None, timeout=20):
    return json.loads(get_bytes(url, headers, timeout).decode("utf-8"))
