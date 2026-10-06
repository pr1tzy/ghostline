"""Start everything: recorder, log watcher, web app, and the Cloudflare tunnel if it's set up."""
import atexit
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from backend import ingest, settings
from backend.app import PORT, app
from backend.recorder import recorder

ROOT = Path(__file__).resolve().parent
(ROOT / "data").mkdir(exist_ok=True)
PIDFILE = ROOT / "data" / "ghostline.pid"

if sys.stdout is None:   # started hidden with pythonw: log to a file instead of a console
    sys.stdout = sys.stderr = open(ROOT / "data" / "ghostline.log", "a", buffering=1, encoding="utf-8")


def start_tunnel():
    exe = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if "--no-tunnel" in sys.argv or not settings.TUNNEL:
        return "off"
    if not Path(exe).exists():
        return "off (cloudflared not installed)"
    # tunnels left behind by a closed console window would otherwise pile up
    ps = ("Get-CimInstance Win32_Process -Filter \"name='cloudflared.exe'\" | "
          "Where-Object { $_.CommandLine -like '*ghostline.yml*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    p = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--config", str(settings.TUNNEL_CFG), "run", settings.TUNNEL],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    atexit.register(p.terminate)
    return f"starting (https://{settings.PUBLIC_HOST})" if settings.PUBLIC_HOST else "starting"


def already_running():
    import socket
    with socket.socket() as sk:
        return sk.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    if already_running():
        print(f"Ghostline (or another program) is already using port {PORT}. Opening {url}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        sys.exit(0)
    PIDFILE.write_text(str(os.getpid()))
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True))
    s = ingest.ensure_app()
    if s.get("ac_path"):
        print("Assetto Corsa found:", s["ac_path"])
        print("In-game app (for ghosts):", "ready. Restart your AC session if it was already running." if s.get("active") else s.get("error", "not active"))
    else:
        print("Assetto Corsa not found through Steam. Open the References page for help.")
    recorder.start()
    ingest.Watcher().start()
    tunnel = start_tunnel()
    if settings.TUNNEL:
        print("Public site:", tunnel)
    print(f"\nGhostline is running at {url}\nKeep this window open while you drive. Close it to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=False, server_header=False)
