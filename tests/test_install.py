"""Installing the in-game apps into a fake Assetto Corsa folder. CSP reloads a Lua app the moment its files change,
and in 2.2 Ghostline replaced the app in the middle of a session (and with an older version over a newer one); that
reload crashed the game. A loaded app is now only replaced while the game is closed, and never by an older one."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["RA_DATA"] = str(TMP / "data")
os.environ["GHOSTLINE_HOME"] = str(TMP / "home")
os.environ["GHOSTLINE_AC_PATH"] = str(TMP / "ac")
os.environ["GHOSTLINE_DOCUMENTS"] = str(TMP / "docs")
for d in ("ac/extension", "ac/apps/python", "ac/apps/lua", "docs/Assetto Corsa/cfg"):
    (TMP / d).mkdir(parents=True)
(TMP / "ac" / "acs.exe").write_bytes(b"")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import ingest  # noqa: E402

LUA = TMP / "ac" / "apps" / "lua" / "GhostlineLogger"
game = {"running": False}
real_ac_running = ingest.ac_running
ingest.ac_running = lambda: game["running"]


def files():
    return {f.relative_to(LUA).as_posix(): f.read_bytes() for f in LUA.rglob("*") if f.is_file()}


def set_version(v):
    m = LUA / "manifest.ini"
    m.write_text(m.read_text().replace(f"VERSION = {ingest._lua_version(LUA)[0]}.{ingest._lua_version(LUA)[1]}", f"VERSION = {v}"))


# 1. first install, even with the game running (nothing is loaded yet)
game["running"] = True
s = ingest.ensure_app()
assert s["installed"] and s["active"] and s["lua"] and s["lua_update"] == "current", s
assert (LUA / "GhostlineLogger.lua").read_bytes() == (ingest.LUA_SRC / "GhostlineLogger.lua").read_bytes()

# 2. an older version is in the game (the 2.2 situation): while the game runs it waits, the files stay as they are
(LUA / "coach.lua").write_text("-- the old coaching")
set_version("2.2")
before = files()
s = ingest.ensure_app()
assert s["lua_update"] == "wait" and files() == before, s
# the Python app (which the game never reloads mid-session) is still kept current
(TMP / "ac/apps/python/RaceLogger/RaceLogger.py").write_text("# old")
ingest.ensure_app()
assert (TMP / "ac/apps/python/RaceLogger/RaceLogger.py").read_bytes() == (ingest.APP_SRC / "RaceLogger.py").read_bytes()
assert files() == before

# 3. the game closes: the update goes in
game["running"] = False
s = ingest.ensure_app()
assert s["lua_update"] == "current" and (LUA / "coach.lua").read_bytes() == (ingest.LUA_SRC / "coach.lua").read_bytes(), s

# 4. a newer version copied in by hand is never replaced by this older one, game running or not
(LUA / "hud.lua").write_text("-- a newer dash")
set_version("9.9")
newer = files()
for running in (True, False):
    game["running"] = running
    s = ingest.ensure_app()
    assert s["lua_update"] == "newer" and files() == newer, (running, s)

# 5. the real process check runs and answers (no game in CI)
assert isinstance(real_ac_running(), bool)
print("install ok")
