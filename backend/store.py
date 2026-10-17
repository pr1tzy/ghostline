"""SQLite lap index + one .npz file of samples per lap. Track/car config in config/*.json."""
import json
import os
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import settings

ROOT = settings.ROOT
DATA = Path(os.environ.get("RA_DATA") or settings.DATA_DIR)
LAPDIR, INBOX = DATA / "laps", DATA / "inbox"
CONFIG = ROOT / "config"
for _p in (LAPDIR, INBOX):
    _p.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()
_db = sqlite3.connect(DATA / "race.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.executescript("""
CREATE TABLE IF NOT EXISTS laps(
  id INTEGER PRIMARY KEY, source TEXT, driver TEXT, car TEXT, track TEXT, lap_ms INTEGER,
  valid INTEGER, has_inputs INTEGER, created REAL, origin TEXT UNIQUE, note TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
""")

SOURCES = {"player": "You", "online": "Online", "ai": "AI", "real": "Real world", "import": "Import"}


def q(sql, args=()):
    with _lock:
        cur = _db.execute(sql, args)
        _db.commit()
        return [dict(r) for r in cur.fetchall()]


def kv_get(k, default=None):
    r = q("SELECT v FROM kv WHERE k=?", (k,))
    return json.loads(r[0]["v"]) if r else default


def kv_set(k, v):
    q("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, json.dumps(v)))


def add_lap(meta, arrays):
    """Insert a lap. Returns its id, or None if this origin was already ingested."""
    with _lock:
        if meta.get("origin") and q("SELECT 1 FROM laps WHERE origin=?", (meta["origin"],)):
            return None
        cur = _db.execute(
            "INSERT INTO laps(source,driver,car,track,lap_ms,valid,has_inputs,created,origin,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (meta["source"], meta.get("driver", ""), meta["car"], meta["track"], int(meta["lap_ms"]),
             int(meta.get("valid", 1)), int(meta.get("has_inputs", 0)), meta.get("created", time.time()),
             meta.get("origin"), meta.get("note", "")))
        _db.commit()
        lap_id = cur.lastrowid
    np.savez_compressed(LAPDIR / f"{lap_id}.npz", **_pack(arrays))
    return lap_id


# Laps are stored at the precision they're measured with, as differences from the previous sample: 2.6x smaller
# than plain floats, and the largest change is 0.5 ms, 2.5 mm or 0.005 km/h. Files from before 2.3 hold plain
# floats; both load the same way.
PACK = {"t": 1e-3, "pos": 1e-7, "speed": 0.01, "x": 0.005, "z": 0.005, "throttle": 1e-3, "brake": 1e-3,
        "steer": 0.01, "gear": 1, "rpm": 1}
FORMAT = 2


def _pack(arrays):
    out = {"format": np.array([FORMAT])}
    for k, v in arrays.items():
        v = np.asarray(v, dtype=float)
        scale = PACK.get(k)
        if scale is not None and len(v) and np.all(np.isfinite(v)):
            d = np.diff(np.round(v / scale).astype(np.int64), prepend=0)
            if np.abs(d).max() < 2 ** 31:
                out["q_" + k] = d.astype(np.int32)
                continue
        out[k] = v
    return out


def _unpack(z):
    keys = z.files if hasattr(z, "files") else z.keys()   # a loaded .npz, or a dict from _pack
    return {(k[2:] if k.startswith("q_") else k):
            (np.cumsum(z[k].astype(np.int64)) * PACK[k[2:]] if k.startswith("q_") else z[k].astype(float))
            for k in keys if k != "format"}


@lru_cache(maxsize=64)
def _load(lap_id):
    with np.load(LAPDIR / f"{lap_id}.npz") as z:
        return _unpack(z)


def compact_laps():
    """One-time (2.3): rewrite lap files from before the compact format. Each file is checked after packing and only
    replaced if every value comes back within its precision; the swap is atomic."""
    if kv_get("laps_format") == FORMAT:
        return
    for f in sorted(LAPDIR.glob("*.npz")):
        try:
            with np.load(f) as z:
                if "format" in z.files:
                    continue
                raw = {k: z[k] for k in z.files}
            packed = _pack(raw)
            back = _unpack(packed)
            if any(np.max(np.abs(back[k] - raw[k]), initial=0) > PACK.get(k, 0) / 2 + 1e-9 for k in raw):
                continue   # not exact enough: keep the original
            tmp = f.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, **packed)
            os.replace(tmp, f)
        except Exception as e:
            print("compact failed", f.name, e)
    _load.cache_clear()
    kv_set("laps_format", FORMAT)


def load_lap(lap_id):
    return dict(_load(int(lap_id)))


def get_lap(lap_id):
    r = q("SELECT * FROM laps WHERE id=?", (int(lap_id),))
    return r[0] if r else None


def list_laps(car=None, track=None, source=None):
    sql, args = "SELECT * FROM laps WHERE 1=1", []
    for col, val in (("car", car), ("track", track), ("source", source)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    return q(sql + " ORDER BY created DESC", args)


def delete_lap(lap_id):
    q("DELETE FROM laps WHERE id=?", (int(lap_id),))
    (LAPDIR / f"{lap_id}.npz").unlink(missing_ok=True)
    _load.cache_clear()


def sample_count():
    return q("SELECT COUNT(*) n FROM laps WHERE origin LIKE 'sample:%'")[0]["n"]


def clear_samples():
    """Sample laps make a new install look alive; they go as soon as a real lap arrives."""
    for r in q("SELECT id FROM laps WHERE origin LIKE 'sample:%'"):
        delete_lap(r["id"])


KEEP_DRIVERS, KEEP_PER_DRIVER = 3, 1   # other drivers' laps kept per car + track


def prune(car, track):
    """Keep only the best lap of the top KEEP_DRIVERS other drivers (online/AI). Your laps and real-world laps stay."""
    rows = q("SELECT id, driver, lap_ms, valid FROM laps WHERE car=? AND track=? AND source IN ('online','ai') "
             "ORDER BY valid DESC, lap_ms", (car, track))
    keep, count = set(), {}
    for r in rows:
        if not r["valid"]:
            continue
        if r["driver"] not in count:
            if len(count) >= KEEP_DRIVERS:
                continue
            count[r["driver"]] = 0
        if count[r["driver"]] < KEEP_PER_DRIVER:
            keep.add(r["id"])
            count[r["driver"]] += 1
    drop = [r["id"] for r in rows if r["id"] not in keep]
    for i in drop:
        delete_lap(i)
    return len(drop)


def prune_all():
    return sum(prune(g["car"], g["track"]) for g in q("SELECT DISTINCT car, track FROM laps WHERE source IN ('online','ai')"))


def parse_note(note):
    try:
        d = json.loads(note) if note else {}
        return {k: str(v)[:80] for k, v in d.items() if k in NOTE_FIELDS and v} if isinstance(d, dict) else {}
    except ValueError:
        return {}


NOTE_FIELDS = ("setup", "tyres", "fuel", "conditions", "notes", "cut")


def set_note(lap_id, fields):
    """Save setup notes. The cut reason is the recorder's, not the user's, so it's kept as is."""
    cur = parse_note((q("SELECT note FROM laps WHERE id=?", (int(lap_id),)) or [{}])[0].get("note"))
    new = {k: str(fields.get(k, ""))[:80] for k in NOTE_FIELDS if k != "cut"}
    q("UPDATE laps SET note=? WHERE id=?", (json.dumps({**new, **({"cut": cur["cut"]} if "cut" in cur else {})}), int(lap_id)))


def sessions(laps, gap=1200):
    """Group laps (sorted by created) into sessions: a new one starts after `gap` seconds without a lap."""
    out = []
    for l in laps:
        if not out or l["created"] - out[-1]["end"] > gap:
            out.append({"id": l["id"], "start": l["created"], "end": l["created"], "ids": []})
        out[-1]["ids"].append(l["id"])
        out[-1]["end"] = l["created"]
    by_id = {l["id"]: l for l in laps}
    for s in out:
        v = [by_id[i]["lap_ms"] for i in s["ids"] if by_id[i]["valid"]]
        s.update(n=len(s["ids"]), valid=len(v), best=min(v) if v else None,
                 avg=int(sum(v) / len(v)) if v else None,
                 spread=int((sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)) ** .5) if len(v) > 1 else None)
    return out[::-1]


def _cfg(name):
    """Bundled defaults (config/), then your own overrides (the user config folder, when installed)."""
    out = {}
    for d in dict.fromkeys((CONFIG, settings.USER_CONFIG)):
        p = d / f"{name}.json"
        if p.exists():
            for k, v in json.loads(p.read_text()).items():
                out[k] = {**out.get(k, {}), **v}
    return out


def _learned():
    p = DATA / "tracks.json"
    return json.loads(p.read_text()) if p.exists() else {}


def track_cfg(track):
    """Track name, length and corners: read from the AC install (official tracks), then lengths learned from the
    game (data/tracks.json), then your overrides in config/tracks.json, which always win."""
    from . import content
    return {**(content.track(track) or {}), **_learned().get(track, {}), **_cfg("tracks").get(track, {})}


def set_track(track, **fields):
    with _lock:
        data = _learned()
        cur = data.setdefault(track, {})
        changed = {k: v for k, v in fields.items() if k not in cur}
        if changed:
            cur.update(changed)
            (DATA / "tracks.json").write_text(json.dumps(data, indent=2))


def car_info(car):
    if car.startswith("f1_"):
        return {"name": car.replace("_", " ").upper(), "class": "f1-real"}
    from . import content
    info = {**(content.car(car) or {"name": car.replace("_", " ").title(), "class": car}), **_cfg("cars").get(car, {})}
    return {**info, "class_name": content.class_name(info["class"])}


def references(lap_id):
    """Candidate reference laps for a lap, best first: same car > same class > real world."""
    me = get_lap(lap_id)
    if not me:
        return []
    cls = car_info(me["car"])["class"]
    out = []
    for l in q("SELECT * FROM laps WHERE track=? AND valid=1 AND id!=? ORDER BY lap_ms", (me["track"], me["id"])):
        same_car, same_cls = l["car"] == me["car"], car_info(l["car"])["class"] == cls
        l["tier"] = 0 if same_car else 1 if same_cls else 2 if l["source"] == "real" else 3
        l["tier_label"] = ["Same car", "Same class", "Real world", "Other"][l["tier"]]
        out.append(l)
    return sorted(out, key=lambda l: (l["tier"], l["lap_ms"]))
