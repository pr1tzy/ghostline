"""Watches the in-game app's log folder + data/inbox, imports real-world F1 laps, installs the AC app."""
import ctypes
import json
import os
import filecmp
import re
import shutil
import threading
import time
import winreg
from pathlib import Path

import numpy as np

from . import analysis, content, store

APP_SRC = store.ROOT / "ac_app" / "RaceLogger"
LUA_SRC = store.ROOT / "ac_app" / "GhostlineLogger"   # CSP Lua version: installed when Custom Shaders Patch is there
F1_TRACKS = {"monza": "monza", "spa-francorchamps": "spa", "silverstone": "ks_silverstone-gp", "imola": "imola",
             "barcelona": "ks_barcelona-layout_gp", "spielberg": "ks_red_bull_ring-layout_gp", "zandvoort": "ks_zandvoort"}


# ---------- Assetto Corsa install / in-game app ----------

def find_ac():
    env = os.environ.get("GHOSTLINE_AC_PATH")   # AC installed outside Steam's folders (also used by tests)
    if env:
        return Path(env) if (Path(env) / "acs.exe").exists() else None
    saved = store.kv_get("ac_path")
    if saved and (Path(saved) / "acs.exe").exists():
        return Path(saved)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None
    libs = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"(.+?)"', vdf.read_text(errors="ignore"))]
    for lib in libs:
        p = lib / "steamapps" / "common" / "assettocorsa"
        if (p / "acs.exe").exists():
            store.kv_set("ac_path", str(p))
            return p
    return None


def documents():
    if os.environ.get("GHOSTLINE_DOCUMENTS"):
        return Path(os.environ["GHOSTLINE_DOCUMENTS"])
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL, follows OneDrive redirect
    return Path(buf.value)


def app_dir():
    ac = find_ac()
    return ac / "apps" / "python" / "RaceLogger" if ac else None


def lua_dir():
    ac = find_ac()
    return ac / "apps" / "lua" / "GhostlineLogger" if ac and (ac / "extension").is_dir() else None


def _same(a, b):
    return a.exists() and filecmp.cmp(a, b, shallow=False)


def app_status():
    d, ld = app_dir(), lua_dir()
    installed = bool(d and (d / "RaceLogger.py").exists())
    current = installed and _same(d / "RaceLogger.py", APP_SRC / "RaceLogger.py") and \
        (ld is None or all(_same(ld / f.name, f) for f in LUA_SRC.iterdir()))
    ini = documents() / "Assetto Corsa" / "cfg" / "python.ini"
    active = ini.exists() and re.search(r"\[RACELOGGER\]\s*ACTIVE\s*=\s*1", ini.read_text(errors="ignore"), re.I) is not None
    return {"ac_path": str(find_ac() or ""), "installed": installed, "current": bool(current), "active": active,
            "csp": bool(ld), "lua": bool(ld and (ld / "GhostlineLogger.lua").exists()),
            "logs": str(d / "logs") if d else "", "inbox": str(store.INBOX)}


def install_app():
    d = app_dir()
    if not d:
        raise RuntimeError("Assetto Corsa folder not found")
    shutil.copytree(APP_SRC, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("logs", "__pycache__"))
    (d / "logs").mkdir(exist_ok=True)
    for old in ("live.json", "live.json.tmp"):   # the app shares data through memory now
        (d / old).unlink(missing_ok=True)
    write_launch_cfg()
    if lua_dir():
        shutil.copytree(LUA_SRC, lua_dir(), dirs_exist_ok=True)
    ini = documents() / "Assetto Corsa" / "cfg" / "python.ini"
    if ini.parent.exists():
        text = ini.read_text(errors="ignore") if ini.exists() else ""
        if re.search(r"\[RACELOGGER\]", text, re.I):
            text = re.sub(r"(\[RACELOGGER\]\s*ACTIVE\s*=\s*)0", r"\g<1>1", text, flags=re.I)
        else:
            text = text.rstrip() + "\n\n[RACELOGGER]\nACTIVE=1\n"
        ini.write_text(text)
    return app_status()


def launch_command():
    """How the in-game app starts Ghostline: the installed exe, or pythonw + run.py when running from source."""
    import sys
    from . import settings
    if settings.FROZEN:
        return sys.executable, ["--with-game"]
    venv = store.ROOT / ".venv" / "Scripts" / "pythonw.exe"
    py = venv if venv.exists() else Path(sys.executable).with_name("pythonw.exe")
    return str(py), [str(store.ROOT / "run.py"), "--with-game"]


def write_launch_cfg():
    """Tells the in-game app whether, and how, to start Ghostline when a session starts."""
    from . import settings
    d = app_dir()
    if not d or not d.exists():
        return
    program, args = launch_command()
    on = settings.app_options()["launch_with_game"] and Path(program).exists()
    (d / "launch.cfg").write_text(f"enabled={int(on)}\nprogram={program}\nargs={chr(9).join(args)}\n", encoding="utf-8")


def uninstall_app():
    """Remove the in-game app from AC and switch it off in python.ini. Laps in data/ are kept."""
    d = app_dir()
    for folder in (d, lua_dir()):
        if folder and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    ini = documents() / "Assetto Corsa" / "cfg" / "python.ini"
    if ini.exists():
        ini.write_text(re.sub(r"(\[RACELOGGER\]\s*ACTIVE\s*=\s*)1", r"\g<1>0", ini.read_text(errors="ignore"), flags=re.I))
    return "removed" if d else "Assetto Corsa not found, nothing to remove"


def ensure_app():
    try:
        s = app_status()
        if s["ac_path"] and not (s["current"] and s["active"]):
            s = install_app()
        return s
    except Exception as e:
        return {"error": str(e)}


# ---------- CSV ingestion ----------

def ingest_csv(path, origin=None):
    meta, header, rows = {}, None, []
    for line in Path(path).read_text(errors="ignore").splitlines():
        if line.startswith("#"):
            k, _, v = line[1:].partition("=")
            meta[k.strip()] = v.strip()
        elif header is None:
            header = line.strip().split(",")
        elif line.strip():
            rows.append([float(x) for x in line.split(",")])
    if not rows or not {"t", "pos", "speed"} <= set(header):
        return None
    return ingest_rows(meta, header, np.array(rows), origin or "file:" + Path(path).name)


def ingest_rows(meta, header, a, origin):
    """Store one lap given as columns (header) x rows. Shared by CSV imports and the live car feed."""
    if meta.get("source") in ("online", "ai", "player") and not content.supported(meta.get("car", ""), meta.get("track", "")):
        return None   # mod content: versions differ between servers, so the laps aren't comparable
    valid, note = int(meta.get("valid", 1)), meta.get("note", "")
    track = meta.get("track", "unknown")
    if valid and meta.get("source") in ("online", "ai") and "x" in header:
        chk = analysis.line_check(track, a[:, header.index("x")], a[:, header.index("z")])
        if chk and chk["cut"]:
            valid, note = 0, json.dumps({"cut": f"off line {chk['dev']} m at {analysis.corner_at(track, chk['at'])}"})
    return store.add_lap(
        {"source": meta.get("source", "import"), "driver": meta.get("driver", ""), "car": meta.get("car", "unknown"),
         "track": track, "lap_ms": int(float(meta.get("lap_ms", a[-1, 0] * 1000))),
         "valid": valid, "has_inputs": int("throttle" in header and "brake" in header), "origin": origin, "note": note},
        {c: a[:, i] for i, c in enumerate(header)})


class Watcher(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.last = []

    def scan(self):
        touched = set()
        dirs = [store.INBOX] + ([app_dir() / "logs"] if app_dir() else [])
        for d in dirs:
            if not d.exists():
                continue
            done = d / "processed"
            for f in sorted(d.glob("*.csv")):
                try:
                    lap_id = ingest_csv(f)
                    if lap_id:
                        store.clear_samples()
                        self.last = ([lap_id] + self.last)[:20]
                        l = store.get_lap(lap_id)
                        if l["source"] in ("online", "ai"):
                            touched.add((l["car"], l["track"]))
                    done.mkdir(exist_ok=True)
                    shutil.move(str(f), done / f.name)
                except PermissionError:
                    pass   # still being written
                except Exception as e:
                    print("ingest failed", f.name, e)
        for car, track in touched:
            store.prune(car, track)

    def run(self):
        try:
            load_samples()
            recheck_ghosts()
            explain_my_invalid_laps()
        except Exception as e:
            print("recheck failed", e)
        store.prune_all()
        while True:
            self.scan()
            time.sleep(2)


SAMPLES = store.ROOT / "samples"


def load_samples():
    """First run only: two sample comparisons (Monza and Spa) so the site isn't empty before the first drive."""
    if store.kv_get("samples_done") or store.q("SELECT 1 FROM laps LIMIT 1"):
        return
    for f in sorted(SAMPLES.glob("*_you.csv")) + sorted(SAMPLES.glob("*_ghost.csv")):   # own laps first: ghosts are checked against them
        ingest_csv(f, origin="sample:" + f.name)
    store.kv_set("samples_done", 1)


def explain_my_invalid_laps():
    """One-time: give my older invalid laps a reason, so the site can say why a faster lap doesn't count."""
    if store.kv_get("cut_reasons"):
        return
    for l in store.q("SELECT id, track, note FROM laps WHERE source='player' AND valid=0"):
        if "cut" in store.parse_note(l["note"]):
            continue
        raw = store.load_lap(l["id"])
        if "x" in raw:
            note = {**json.loads(l["note"] or "{}"), "cut": analysis.cut_reason(l["track"], raw["x"], raw["z"])}
            store.q("UPDATE laps SET note=? WHERE id=?", (json.dumps(note), l["id"]))
    store.kv_set("cut_reasons", 1)


CUT_CHECK_VERSION = 1


def recheck_ghosts():
    """One-time: re-run cut detection on stored ghosts and re-import logged laps that were pruned before it existed."""
    if store.kv_get("cut_check") == CUT_CHECK_VERSION:
        return
    for l in store.q("SELECT id, track FROM laps WHERE source IN ('online','ai') AND valid=1"):
        raw = store.load_lap(l["id"])
        if "x" in raw:
            chk = analysis.line_check(l["track"], raw["x"], raw["z"])
            if chk and chk["cut"]:
                store.q("UPDATE laps SET valid=0 WHERE id=?", (l["id"],))
    d = app_dir()
    for f in sorted((d / "logs" / "processed").glob("*.csv")) if d else []:
        try:
            ingest_csv(f)
        except Exception:
            pass
    store.kv_set("cut_check", CUT_CHECK_VERSION)


# ---------- Real-world reference (OpenF1: free, seasons from 2023, no extra packages) ----------

OPENF1 = "https://api.openf1.org/v1/"
F1_SESSIONS = {"Q": "Qualifying", "R": "Race", "S": "Sprint", "SQ": "Sprint Qualifying", "SS": "Sprint Shootout",
               "FP1": "Practice 1", "FP2": "Practice 2", "FP3": "Practice 3"}


def _openf1(path, **params):
    import urllib.parse
    import urllib.request
    q = "&".join(f"{k.replace('__gte', '>=').replace('__lte', '<=')}{'' if k.endswith(('__gte', '__lte')) else '='}"
                 f"{urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(OPENF1 + path + "?" + q, headers={"User-Agent": "Ghostline (github.com/pr1tzy/ghostline)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _when(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def import_f1(year, gp, session="Q", driver=None, track=None):
    """Fastest lap of a real F1 session (any driver, or one driver by code like NOR), with speed, pedals, gear and line."""
    name = F1_SESSIONS.get(session.upper(), session)
    gp_l = gp.lower()
    found = [x for x in _openf1("sessions", year=int(year)) if x.get("session_name", "").lower() == name.lower() and any(
        gp_l in str(x.get(k, "")).lower() for k in ("location", "circuit_short_name", "country_name", "meeting_name"))]
    if not found:
        raise RuntimeError(f"No {name} found for {gp} {year} (OpenF1 has seasons from 2023)")
    key, location = found[0]["session_key"], found[0].get("location", gp)
    drivers = {d["driver_number"]: d for d in _openf1("drivers", session_key=key)}
    if driver:
        nums = [n for n, d in drivers.items() if str(d.get("name_acronym", "")).upper() == driver.upper()]
        if not nums:
            raise RuntimeError(f"No driver {driver.upper()} in that session")
        laps = _openf1("laps", session_key=key, driver_number=nums[0])
    else:
        laps = _openf1("laps", session_key=key)
    laps = [x for x in laps if x.get("lap_duration") and x.get("date_start") and not x.get("is_pit_out_lap")]
    if not laps:
        raise RuntimeError("no timed lap found")
    lap = min(laps, key=lambda x: x["lap_duration"])
    num, t0 = lap["driver_number"], _when(lap["date_start"])
    t1 = t0 + lap["lap_duration"]
    window = {"session_key": key, "driver_number": num, "date__gte": lap["date_start"],
              "date__lte": __import__("datetime").datetime.fromtimestamp(t1 + 1, __import__("datetime").timezone.utc).isoformat()}
    car = sorted(_openf1("car_data", **window), key=lambda r: r["date"])
    loc = sorted(_openf1("location", **window), key=lambda r: r["date"])
    if len(car) < 50 or len(loc) < 50:
        raise RuntimeError("not enough telemetry for that lap")
    t = np.array([_when(r["date"]) - t0 for r in car])
    keep = (t >= 0) & (t <= t1 - t0)
    car, t = [r for r, k in zip(car, keep) if k], t[keep]
    speed = np.array([r["speed"] for r in car], float)
    dist = np.concatenate([[0.0], np.cumsum(np.diff(t) * (speed[1:] + speed[:-1]) / 2 / 3.6)])   # distance from speed
    lt = np.array([_when(r["date"]) - t0 for r in loc])
    x = np.interp(t, lt, [r["x"] for r in loc])
    y = np.interp(t, lt, [r["y"] for r in loc])
    d = drivers.get(num, {})
    code = d.get("name_acronym") or str(num)
    track = track or F1_TRACKS.get(str(location).lower(), str(location).lower().replace(" ", "_"))
    L = store.track_cfg(track).get("length") or float(dist.max())
    store.set_track(track, length=round(L), name=str(location))
    team = re.sub(r"\W+", "_", str(d.get("team_name", "f1"))).lower()
    return store.add_lap(
        {"source": "real", "driver": f"{code} ({year} {session.upper()})", "car": f"f1_{year}_{team}",
         "track": track, "lap_ms": int(lap["lap_duration"] * 1000), "valid": 1, "has_inputs": 1,
         "origin": f"f1-{year}-{gp}-{session}-{code}"},
        {"t": t, "pos": dist / dist.max(), "speed": speed, "throttle": np.array([r["throttle"] for r in car], float) / 100,
         "brake": (np.array([r["brake"] for r in car], float) > 0).astype(float), "gear": np.array([r["n_gear"] for r in car], float),
         "x": x / 10, "z": -y / 10})
