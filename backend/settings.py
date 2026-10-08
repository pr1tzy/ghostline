"""Per-install settings. Everything is optional: with no config the site runs locally only.

Only needed to publish the site online; see docs/advanced.md.

config/site.json (not committed; copy config/site.example.json):
  public_host   hostname the site is published on, e.g. "ghostline.example.com" (empty = local only)
  credit_name   name shown in the footer ("Built by ...")
  credit_url    where that name links to
  port          local port (default 8765)
cloudflared/ghostline.yml (not committed; example in docs/advanced.md) turns on the Cloudflare
Tunnel; its first hostname is used as public_host when site.json doesn't set one.
Environment variables GHOSTLINE_PORT and GHOSTLINE_HOST override both.
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/pr1tzy/ghostline"
TUNNEL_CFG = ROOT / "cloudflared" / "ghostline.yml"


def _site():
    p = ROOT / "config" / "site.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        print("config/site.json is not valid JSON; ignoring it")
        return {}


def _tunnel():
    """(tunnel name, first hostname) from the cloudflared config, if there is one."""
    if not TUNNEL_CFG.exists():
        return "", ""
    text = TUNNEL_CFG.read_text(encoding="utf-8", errors="ignore")
    name = re.search(r"^tunnel:\s*(\S+)", text, re.M)
    host = re.search(r"hostname:\s*(\S+)", text)
    return (name.group(1) if name else ""), (host.group(1) if host else "")


_s = _site()
TUNNEL, _tunnel_host = _tunnel()
PORT = int(os.environ.get("GHOSTLINE_PORT") or _s.get("port") or 8765)
PUBLIC_HOST = (os.environ.get("GHOSTLINE_HOST") or _s.get("public_host") or _tunnel_host).strip().lower()
CREDIT_NAME = str(_s.get("credit_name") or "").strip()
CREDIT_URL = str(_s.get("credit_url") or "").strip()


# ---------- in-game logger settings: config/logger.json (not committed), also editable from the CSP app's window ----------
LOGGER_FILE = ROOT / "config" / "logger.json"
LOGGER_DEFAULTS = {
    "enabled": True,      # the in-game app sends anything at all
    "sample_hz": 30,      # how often the in-game app reads each car (position, speed, gear)
    "timing_hz": 4,       # how often it reads lap count, lap times and pit status
    "live_hz": 20,        # how often Ghostline refreshes standings and the Live page map
    "detail": "class",    # which cars get full detail (for ghost laps): "car", "class" or "all"
}
LOGGER_LIMITS = {"sample_hz": (5, 60), "timing_hz": (1, 10), "live_hz": (2, 30)}
DETAILS = ("car", "class", "all")
_logger_cache = (None, dict(LOGGER_DEFAULTS))


def _clean_logger(d):
    out = dict(LOGGER_DEFAULTS)
    for k, v in (d or {}).items():
        if k == "enabled":
            out[k] = bool(v)
        elif k == "detail" and v in DETAILS:
            out[k] = v
        elif k in LOGGER_LIMITS:
            lo, hi = LOGGER_LIMITS[k]
            try:
                out[k] = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                pass
    return out


def logger():
    """Current logger settings; re-read whenever the file changes."""
    global _logger_cache
    try:
        mtime = LOGGER_FILE.stat().st_mtime
    except OSError:
        mtime = None
    if mtime != _logger_cache[0]:
        try:
            data = json.loads(LOGGER_FILE.read_text(encoding="utf-8")) if mtime else {}
        except ValueError:
            print("config/logger.json is not valid JSON; using defaults")
            data = {}
        _logger_cache = (mtime, _clean_logger(data))
    return _logger_cache[1]


def save_logger(changes):
    new = _clean_logger({**logger(), **changes})
    LOGGER_FILE.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    return logger()
