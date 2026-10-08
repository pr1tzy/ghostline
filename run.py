"""Ghostline launcher: recorder, car feed, log watcher, web app, tray icon, and the Cloudflare tunnel if it's set up.

  (no flags)       start, open the site in your browser (Start Menu, start.bat)
  --with-game      started by the in-game app: no browser; quits a few minutes after Assetto Corsa closes
  --no-browser     don't open the browser
  --no-tunnel      don't start the Cloudflare tunnel
  --tray / --no-tray   show the tray icon (default: on for the installed app, off for start.bat)
  --set k=v        change an app option (launch_with_game, check_updates) and exit; used by the installer
  --uninstall      remove the in-game apps from Assetto Corsa and exit; used by the uninstaller
  --selftest       start on a spare port, check the site answers, exit 0 or 1; used by the release build
"""
import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ARGS = sys.argv[1:]
if "--selftest" in ARGS:   # a spare port and a throwaway data folder before anything reads its settings
    with socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        os.environ["GHOSTLINE_PORT"] = str(_s.getsockname()[1])
    import tempfile
    os.environ["GHOSTLINE_HOME"] = tempfile.mkdtemp(prefix="ghostline-selftest-")

from backend import settings  # noqa: E402

settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
if sys.stdout is None:   # no console (installed app, pythonw): log to a file instead
    sys.stdout = sys.stderr = open(settings.DATA_DIR / "ghostline.log", "a", buffering=1, encoding="utf-8")

import uvicorn  # noqa: E402

from backend import __version__, carfeed, ingest, runtime  # noqa: E402
from backend.app import PORT, app  # noqa: E402
from backend.recorder import recorder  # noqa: E402

PIDFILE = settings.DATA_DIR / "ghostline.pid"
URL = f"http://127.0.0.1:{PORT}"
QUIT_AFTER_GAME = int(os.environ.get("GHOSTLINE_QUIT_AFTER", 180))   # --with-game: seconds after Assetto Corsa closes
QUIT_IF_NO_GAME = 600 if QUIT_AFTER_GAME >= 180 else QUIT_AFTER_GAME   # ...or if it never shows up
ICON = settings.ROOT / "packaging" / "ghostline.ico"


def start_tunnel():
    exe = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if "--no-tunnel" in ARGS or not settings.TUNNEL:
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
    with socket.socket() as sk:
        return sk.connect_ex(("127.0.0.1", PORT)) == 0


def one_shot_commands():
    """Installer / uninstaller helpers: do one thing and exit."""
    if "--set" in ARGS:
        k, _, v = ARGS[ARGS.index("--set") + 1].partition("=")
        settings.save_app_options({k: v.strip().lower() in ("1", "true", "yes", "on")})
        ingest.write_launch_cfg()
        sys.exit(0)
    if "--uninstall" in ARGS:
        print(ingest.uninstall_app())
        sys.exit(0)


def selftest(server):
    """The release build launches the built exe with this: is the site up and answering?"""
    for _ in range(60):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(urllib.request.Request(URL + "/api/state", headers={"Host": f"127.0.0.1:{PORT}"}), timeout=5) as r:
                ok = r.status == 200 and b'"version"' in r.read()
                print("selftest", "ok" if ok else "bad response", __version__)
                os._exit(0 if ok else 1)
        except Exception:
            continue
    print("selftest: no answer")
    os._exit(1)


def watch_game(stop):
    """--with-game: once the game is gone for a few minutes, Ghostline goes too (also if it never shows up)."""
    started, last_seen = time.time(), None
    while True:
        time.sleep(min(5, QUIT_AFTER_GAME / 3))
        if recorder.state.get("connected"):
            last_seen = time.time()
        gone = time.time() - (last_seen or started)
        if gone > (QUIT_AFTER_GAME if last_seen else QUIT_IF_NO_GAME):
            print("Assetto Corsa closed: stopping")
            stop()
            return


def main():
    one_shot_commands()
    with_game = "--with-game" in ARGS
    tray_on = ("--tray" in ARGS or settings.FROZEN) and "--no-tray" not in ARGS and "--selftest" not in ARGS
    runtime.mode = "game" if with_game else "tray" if tray_on else "console"
    if already_running():
        if not with_game and "--no-browser" not in ARGS:
            webbrowser.open(URL)
        print(f"Ghostline is already running at {URL}")
        sys.exit(0)

    PIDFILE.write_text(str(os.getpid()))
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True))
    if "--selftest" not in ARGS:
        s = ingest.ensure_app()
        if s.get("ac_path"):
            print("Assetto Corsa found:", s["ac_path"])
            print("In-game app (for ghosts):", "ready. Restart your AC session if it was already running." if s.get("active") else s.get("error", "not active"))
        else:
            print("Assetto Corsa not found through Steam. Open the References page for help.")
        recorder.start()
        carfeed.feed.start()
        ingest.Watcher().start()
        runtime.start_update_checks()
        tunnel = start_tunnel()
        if settings.TUNNEL:
            print("Public site:", tunnel)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=False,
                                           server_header=False))
    tray = None

    def stop():
        server.should_exit = True
        if tray:
            tray.stop()

    runtime._quit = stop
    print(f"\nGhostline {__version__} is running at {URL}\n" +
          ("Keep this window open while you drive. Close it to stop.\n" if runtime.mode == "console" else ""))
    if "--selftest" in ARGS:
        threading.Thread(target=selftest, args=(server,), daemon=True).start()
    if with_game:
        threading.Thread(target=watch_game, args=(stop,), daemon=True).start()
    if not with_game and "--no-browser" not in ARGS and "--selftest" not in ARGS:
        threading.Timer(1.5, webbrowser.open, (URL,)).start()

    if tray_on:
        from backend.tray import Tray

        def menu():
            opts = settings.app_options()
            items = [("Open Ghostline", lambda: webbrowser.open(URL), False, True), None,
                     ("Start with Assetto Corsa", lambda: (settings.save_app_options({"launch_with_game": not opts["launch_with_game"]}),
                                                          ingest.write_launch_cfg()), opts["launch_with_game"], True)]
            if runtime.update:
                items.append((f"Update available: {runtime.update['version']}", lambda: webbrowser.open(runtime.update["url"]), False, True))
            return items + [None, ("Quit Ghostline", stop, False, True)]

        tray = Tray(ICON, f"Ghostline {__version__}", lambda: webbrowser.open(URL), menu)
        threading.Thread(target=server.run, daemon=True).start()
        tray.run()                 # until Quit
        server.should_exit = True
        time.sleep(0.5)
    else:
        server.run()


if __name__ == "__main__":
    main()
