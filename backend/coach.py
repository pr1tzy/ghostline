"""In-game coaching data: the best lap for the car and track you're driving, sent to the CSP app (GhostlineLogger)
through shared memory ("GhostlineRef.v1"). The app draws brake boards, the racing line and a 3D ghost from it, all
inside the game's own frame loop, so nothing here is on the time-critical path: this only runs when the session
starts or a faster lap is saved.

Block layout: `Ref` below, mirrored by `ghl_ref` in ac_app/GhostlineLogger/GhostlineLogger.lua.
"""
import ctypes
import os
import threading
from ctypes import wintypes

import numpy as np

from . import analysis, ingest, store

NAME = "Local\\GhostlineRef.v1"
MAGIC = 0x31524847          # "GHR1"
MAXP, MAXK = 8192, 48       # track points (2 m apart, wider on very long tracks), corners
G = 9.81
EST_SHIFT = 2.0           # metres, see corners()


class Ref(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_uint32), ("rev", ctypes.c_uint32),      # rev is odd while the block is being written
        ("n", ctypes.c_int32), ("corners", ctypes.c_int32),
        ("step", ctypes.c_float), ("length", ctypes.c_float),
        ("lapMs", ctypes.c_int32), ("lapId", ctypes.c_int32),
        ("est", ctypes.c_uint8), ("pad", ctypes.c_uint8 * 3),       # est: pedals worked out from speed (lap had no inputs)
        ("car", ctypes.c_char * 48), ("track", ctypes.c_char * 64), ("driver", ctypes.c_char * 40),
        ("model", ctypes.c_char * 160), ("mainModel", ctypes.c_char * 160),   # car LOD + main kn5, relative to AC
        ("x", ctypes.c_float * MAXP), ("z", ctypes.c_float * MAXP), ("t", ctypes.c_float * MAXP),
        ("speed", ctypes.c_float * MAXP), ("brake", ctypes.c_float * MAXP), ("throttle", ctypes.c_float * MAXP),
        ("gear", ctypes.c_int8 * MAXP),
        # corners, distances in metres from the line: brake onset, speed there, slowest point and its speed,
        # braking (m/s^2) between them, throttle back on, gear at the apex, kind 1 = brake, 2 = lift
        ("cBrake", ctypes.c_float * MAXK), ("cSpeed", ctypes.c_float * MAXK), ("cApex", ctypes.c_float * MAXK),
        ("cMin", ctypes.c_float * MAXK), ("cDecel", ctypes.c_float * MAXK), ("cThrottle", ctypes.c_float * MAXK),
        ("cGear", ctypes.c_int8 * MAXK), ("cKind", ctypes.c_uint8 * MAXK),
        ("cName", (ctypes.c_char * 24) * MAXK),
    ]


SIZE = ctypes.sizeof(Ref)
_lock = threading.Lock()
_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
_block = {"h": None, "ref": None}
current = {"car": None, "track": None, "lap": None}


def _open():
    if _block["ref"] is None and _k32:
        _k32.CreateFileMappingW.restype = wintypes.HANDLE
        _k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        _k32.MapViewOfFile.restype = ctypes.c_void_p
        _k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        h = _k32.CreateFileMappingW(ctypes.c_void_p(-1).value, None, 0x04, 0, SIZE, NAME)
        addr = _k32.MapViewOfFile(h, 0x0002 | 0x0004, 0, 0, SIZE) if h else None
        if addr:
            _block["h"], _block["ref"] = h, Ref.from_address(addr)
    return _block["ref"]


def best_lap(car, track):
    """The fastest valid lap with this car here, yours or another driver's."""
    r = store.q("SELECT id FROM laps WHERE source IN ('player','online','ai') AND valid=1 AND car=? AND track=? "
                "ORDER BY lap_ms LIMIT 1", (car, track))
    return r[0]["id"] if r else None


def models(car):
    """A light LOD of the car's 3D model for the ghost, plus the main model (which holds the textures)."""
    ac = ingest.find_ac()
    folder = ac / "content" / "cars" / car if ac else None
    if not folder or not folder.is_dir():
        return "", ""
    kn5 = [f for f in folder.glob("*.kn5") if f.name.lower() != "collider.kn5"]
    if not kn5:
        return "", ""
    main = max(kn5, key=lambda f: f.stat().st_size)
    by = {f.stem.lower(): f for f in kn5}
    lod = next((f for k in ("lod_c", "lod_b", "lod_d") for s, f in by.items() if s.endswith(k)), main)
    rel = lambda f: f.relative_to(ac).as_posix()
    return rel(lod), rel(main)


def corners(p):
    """Every braking (or lifting) zone of the lap: where it starts, how hard, and where the car is slowest."""
    out = []
    for c in analysis.find_corners(p):
        m = analysis.metrics(p, c)
        apex = int(m["apex"] / analysis.STEP)
        top = c["i0"] + int(np.argmax(p["speed"][c["i0"]:apex + 1]))   # flat out until here
        on = np.nonzero(p["brake"][top:apex + 1] > 0.05)[0]     # first touch of the pedal after it (chicanes: the first stop)
        if len(on):
            kind, b = 1, top + int(on[0])
            if p["est"]:   # worked out from slowing down: lands 2 m early on average (checked on laps with pedal data)
                b = min(b + int(EST_SHIFT / analysis.STEP), apex - 5)
        else:   # no brakes: a lift, from where the throttle came off
            off = np.nonzero(p["throttle"][top:apex + 1] < 0.3)[0]
            if not len(off):
                continue
            kind, b = 2, top + int(off[0])
        v0, v1 = p["speed"][b] / 3.6, p["speed"][apex] / 3.6
        if apex - b < 5 or v0 - v1 < 3:   # under 10 km/h of slowing: nothing to show
            continue
        decel = (v0 * v0 - v1 * v1) / (2 * (apex - b) * analysis.STEP)
        out.append({"name": c["name"], "brake": b * analysis.STEP, "speed": float(p["speed"][b]), "apex": apex * analysis.STEP,
                    "min": float(p["speed"][apex]), "decel": float(np.clip(decel, 1, 6 * G)), "kind": kind,
                    "throttle": float(m["throttle"] if m["throttle"] is not None else apex * analysis.STEP),
                    "gear": int(m["gear"] or 0)})
    return out[:MAXK]


def fill(ref, p, lap, car, track):
    """Write lap `p` (analysis.prep) into the block, seqlock style: rev is odd while this runs."""
    ref.rev |= 1
    L = float(p["L"])
    k = max(2, int(np.ceil(len(p["d"]) / MAXP)))   # 2 m apart, wider only past 16 km
    idx = np.arange(0, len(p["d"]), k)[:MAXP]
    n = len(idx)
    for name in ("x", "z", "t", "speed", "brake", "throttle"):
        arr = np.ascontiguousarray(p[name][idx], dtype=np.float32)
        ctypes.memmove(getattr(ref, name), arr.ctypes.data, 4 * n)
    gear = np.ascontiguousarray(np.clip(p.get("gear", np.zeros(len(p["d"])))[idx], -1, 12), dtype=np.int8)
    ctypes.memmove(ref.gear, gear.ctypes.data, n)
    cs = corners(p)
    for i, c in enumerate(cs):
        ref.cBrake[i], ref.cSpeed[i], ref.cApex[i], ref.cMin[i] = c["brake"], c["speed"], c["apex"], c["min"]
        ref.cDecel[i], ref.cThrottle[i], ref.cGear[i], ref.cKind[i] = c["decel"], c["throttle"], c["gear"], c["kind"]
        ref.cName[i].value = c["name"].encode("utf-8")[:23]
    ref.n, ref.corners, ref.step, ref.length = n, len(cs), float(k * analysis.STEP), L
    ref.lapMs, ref.lapId, ref.est = int(lap["lap_ms"]), int(lap["id"]), int(bool(p["est"]))
    ref.car, ref.track = car.encode()[:47], track.encode()[:63]
    ref.driver = (lap["driver"] or "").encode("utf-8")[:39]
    lod, main = models(car)
    ref.model, ref.mainModel = lod.encode()[:159], main.encode()[:159]
    ref.magic = MAGIC
    ref.rev += 1   # even: complete
    return cs


def clear(ref):
    ref.rev |= 1
    ref.n = ref.corners = 0
    ref.magic = MAGIC
    ref.rev += 1


def publish(car, track):
    """Called when a session starts and whenever a lap is saved: sends the best lap for this car and track, if it changed."""
    with _lock:
        current["car"], current["track"] = car, track
        ref = _open()
        if ref is None:
            return None
        lap_id = best_lap(car, track) if car and track else None
        if lap_id == current["lap"] and (lap_id is None or ref.lapId == lap_id):
            return lap_id
        try:
            if lap_id is None:
                clear(ref)
            else:
                fill(ref, analysis.prep(lap_id), store.get_lap(lap_id), car, track)
            current["lap"] = lap_id
        except Exception as e:   # never take the recorder down over this
            print("coach", e)
            clear(ref)
            current["lap"] = None
        return lap_id


def lap_saved(car, track):
    """A ghost lap (another driver) was saved: it may be the new best for what you're driving."""
    if car == current["car"] and track == current["track"]:
        publish(car, track)
