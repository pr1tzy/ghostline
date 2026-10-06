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
