"""State shared between the launcher (run.py) and the web app: how Ghostline was started, and whether an update exists."""
import json
import threading
import time
import urllib.request

from . import __version__, settings

mode = "console"        # "console" (start.bat), "tray" (Start Menu / installed), "game" (started by the in-game app)
update = None           # {"version": "2.1.1", "url": "..."} when GitHub has a newer release
_quit = None            # set by run.py: stops everything cleanly


def _ver(v):
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3] if x.isdigit())


def check_update():
    """Once a day: ask GitHub for the newest release. Sends nothing but the request itself."""
    global update
    if not settings.app_options()["check_updates"]:
        update = None
        return
    try:
        req = urllib.request.Request("https://api.github.com/repos/pr1tzy/ghostline/releases/latest",
                                     headers={"User-Agent": f"Ghostline/{__version__}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rel = json.loads(r.read().decode("utf-8"))
        tag = rel.get("tag_name", "")
        update = {"version": tag.lstrip("v"), "url": rel.get("html_url")} if _ver(tag) > _ver(__version__) else None
    except Exception:
        pass   # offline, rate limited: try again tomorrow


def start_update_checks():
    def loop():
        while True:
            check_update()
            time.sleep(24 * 3600)
    threading.Thread(target=loop, daemon=True).start()


def quit_app():
    if _quit:
        _quit()
