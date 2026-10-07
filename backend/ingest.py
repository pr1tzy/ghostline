"""Watches the in-game app's log folder + data/inbox, imports real-world F1 laps, installs the AC app."""
import ctypes
import json
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
F1_TRACKS = {"monza": "monza", "spa-francorchamps": "spa", "silverstone": "ks_silverstone-gp", "imola": "imola",
             "barcelona": "ks_barcelona-layout_gp", "spielberg": "ks_red_bull_ring-layout_gp", "zandvoort": "ks_zandvoort"}


# ---------- Assetto Corsa install / in-game app ----------

def find_ac():
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
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL, follows OneDrive redirect
    return Path(buf.value)


def app_dir():
    ac = find_ac()
    return ac / "apps" / "python" / "RaceLogger" if ac else None


def app_status():
    d = app_dir()
    installed = bool(d and (d / "RaceLogger.py").exists())
    current = installed and filecmp.cmp(d / "RaceLogger.py", APP_SRC / "RaceLogger.py", shallow=False)
    ini = documents() / "Assetto Corsa" / "cfg" / "python.ini"
    active = ini.exists() and re.search(r"\[RACELOGGER\]\s*ACTIVE\s*=\s*1", ini.read_text(errors="ignore"), re.I) is not None
    return {"ac_path": str(find_ac() or ""), "installed": installed, "current": bool(current), "active": active,
            "logs": str(d / "logs") if d else "", "inbox": str(store.INBOX)}


def install_app():
    d = app_dir()
    if not d:
        raise RuntimeError("Assetto Corsa folder not found")
    shutil.copytree(APP_SRC, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("logs", "__pycache__"))
    (d / "logs").mkdir(exist_ok=True)
    ini = documents() / "Assetto Corsa" / "cfg" / "python.ini"
    if ini.parent.exists():
        text = ini.read_text(errors="ignore") if ini.exists() else ""
        if re.search(r"\[RACELOGGER\]", text, re.I):
            text = re.sub(r"(\[RACELOGGER\]\s*ACTIVE\s*=\s*)0", r"\g<1>1", text, flags=re.I)
        else:
            text = text.rstrip() + "\n\n[RACELOGGER]\nACTIVE=1\n"
        ini.write_text(text)
    return app_status()


def uninstall_app():
    """Remove the in-game app from AC and switch it off in python.ini. Laps in data/ are kept."""
    d = app_dir()
    if d and d.exists():
        shutil.rmtree(d, ignore_errors=True)
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
    if meta.get("source") in ("online", "ai", "player") and not content.supported(meta.get("car", ""), meta.get("track", "")):
        return None   # mod content: versions differ between servers, so the laps aren't comparable
    a = np.array(rows)
    valid, note = int(meta.get("valid", 1)), ""
    track = meta.get("track", "unknown")
    if meta.get("source") in ("online", "ai") and "x" in header:
        chk = analysis.line_check(track, a[:, header.index("x")], a[:, header.index("z")])
        if chk and chk["cut"]:
            valid, note = 0, json.dumps({"cut": f"off line {chk['dev']} m at {analysis.corner_at(track, chk['at'])}"})
    return store.add_lap(
        {"source": meta.get("source", "import"), "driver": meta.get("driver", ""), "car": meta.get("car", "unknown"),
         "track": track, "lap_ms": int(float(meta.get("lap_ms", a[-1, 0] * 1000))),
         "valid": valid, "has_inputs": int("throttle" in header and "brake" in header),
         "origin": origin or "file:" + Path(path).name, "note": note},
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


# ---------- Real-world reference (FastF1) ----------

def import_f1(year, gp, session="Q", driver=None, track=None):
    import fastf1
    fastf1.Cache.enable_cache(str(store.F1CACHE))
    s = fastf1.get_session(int(year), gp, session)
    s.load(laps=True, telemetry=True, weather=False, messages=False)
    laps = s.laps.pick_drivers(driver.upper()) if driver else s.laps
    lap = laps.pick_fastest()
    if lap is None:
        raise RuntimeError("no timed lap found")
    tel = lap.get_telemetry()
    track = track or F1_TRACKS.get(str(s.event["Location"]).lower(), str(s.event["Location"]).lower().replace(" ", "_"))
    dist = tel["Distance"].to_numpy(float)
    L = store.track_cfg(track).get("length") or float(dist.max())
    store.set_track(track, length=round(L), name=str(s.event["Location"]))
    team = re.sub(r"\W+", "_", str(lap["Team"])).lower()
    return store.add_lap(
        {"source": "real", "driver": f"{lap['Driver']} ({year} {session})", "car": f"f1_{year}_{team}",
         "track": track, "lap_ms": int(lap["LapTime"].total_seconds() * 1000), "valid": 1, "has_inputs": 1,
         "origin": f"f1-{year}-{gp}-{session}-{lap['Driver']}"},
        {"t": tel["Time"].dt.total_seconds().to_numpy(float), "pos": dist / dist.max(),
         "speed": tel["Speed"].to_numpy(float), "throttle": tel["Throttle"].to_numpy(float) / 100,
         "brake": tel["Brake"].to_numpy(float), "gear": tel["nGear"].to_numpy(float),
         "x": tel["X"].to_numpy(float) / 10, "z": -tel["Y"].to_numpy(float) / 10})
