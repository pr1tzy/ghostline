"""Other cars, live: reads the "GhostlineCars.v1" shared memory written by the in-game app (RaceLogger in Python,
or GhostlineLogger in CSP Lua) and does everything the app used to do inside the game: lap detection, saving
ghost laps, and the snapshot behind the Live standings.

Also writes "GhostlineWant.v1": a heartbeat (so the in-game app knows someone is listening and idles otherwise)
and which cars need full detail (your car model or class); the rest only send their track position.
Block layout: see ac_app/GhostlineLogger/GhostlineLogger.lua (ghl_cars / ghl_want).
"""
import ctypes
import json
import threading
import time
from ctypes import wintypes

import numpy as np

from . import ingest, store

CARS, WANT = "Local\\GhostlineCars.v1", "Local\\GhostlineWant.v1"
SIZE, WANT_SIZE, MAXC = 8672, 72, 64
MAGIC, WANT_MAGIC = 0x314C4847, 0x31574847
POLL, ROW_EVERY, MAX_ROWS = 0.01, 0.045, 20 * 600   # read 100 times a second, keep ~20 samples a second per car
SETTLE = 1.0          # wait this long after a car crosses the line, so the game's own lap verdict has arrived
COLS = ("t", "pos", "speed", "x", "z", "gear")

FIELDS = {   # name: (offset, dtype, count)
    "connected": (96, "u1", MAXC), "pit": (160, "u1", MAXC), "lap_valid": (224, "u1", MAXC), "lap_cuts": (288, "u1", MAXC),
    "gear": (352, "<i2", MAXC), "laps": (480, "<i4", MAXC), "valid_lap": (736, "<i4", MAXC), "last": (992, "<i4", MAXC),
    "best": (1248, "<i4", MAXC), "spline": (1504, "<f4", MAXC), "x": (1760, "<f4", MAXC), "z": (2016, "<f4", MAXC),
    "speed": (2272, "<f4", MAXC), "t": (2528, "<f8", MAXC),
}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateFileMappingW.restype = wintypes.HANDLE
_k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
FILE_MAP_READ, FILE_MAP_WRITE, PAGE_READWRITE = 0x0004, 0x0002, 0x04
INVALID_HANDLE = ctypes.c_void_p(-1).value


def _str(b):
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


class CarFeed(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.player_car = None     # set by the recorder: decides which cars need full detail
        self.cars_addr = self.want_addr = None
        self._want_h = self._cars_h = None
        self.beat, self.next_want, self.next_open = 0, 0.0, 0.0
        self.seq, self.seq_since = None, 0.0
        self.st, self.pending = {}, []
        self.snap, self.snap_at, self.saved = None, 0.0, 0
        self.settle = SETTLE

    # ---------- shared memory ----------
    def _open_want(self):
        h = _k32.CreateFileMappingW(INVALID_HANDLE, None, PAGE_READWRITE, 0, WANT_SIZE, WANT)
        if h:
            self._want_h, self.want_addr = h, _k32.MapViewOfFile(h, FILE_MAP_WRITE, 0, 0, WANT_SIZE)

    def _open_cars(self):
        h = _k32.OpenFileMappingW(FILE_MAP_READ, False, CARS)   # the in-game app creates it; never create it here
        if h:
            self._cars_h, self.cars_addr = h, _k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, SIZE)

    def _write_want(self, names):
        mine = self.player_car
        cls = store.car_info(mine)["class"] if mine else None
        want = bytearray(MAXC)
        for i, car in enumerate(names):
            want[i] = int(i > 0 and (mine is None or car == mine or (car and store.car_info(car)["class"] == cls)))
        self.beat = (self.beat + 1) & 0xFFFFFFFF
        data = MAGIC_W + self.beat.to_bytes(4, "little") + bytes(want)
        ctypes.memmove(self.want_addr, data, len(data))

    def _read(self):
        """A consistent copy of the block: the writer makes `seq` odd while it writes."""
        for _ in range(5):
            s1 = ctypes.c_uint32.from_address(self.cars_addr + 8).value
            if s1 & 1:
                continue
            raw = ctypes.string_at(self.cars_addr, SIZE)
            if ctypes.c_uint32.from_address(self.cars_addr + 8).value == s1:
                return raw
        return None

    # ---------- per tick ----------
    def tick(self, now=None):
        now = time.time() if now is None else now
        if self.want_addr is None:
            self._open_want()
        if self.cars_addr is None:
            if now >= self.next_open:
                self.next_open = now + 2.0
                self._open_cars()
            if self.cars_addr is None:
                self.snap = None
                if self.want_addr and now >= self.next_want:   # keep beating so the app starts writing
                    self.next_want = now + 1.0
                    self._write_want([])
                return
        raw = self._read()
        if raw is None:
            return
        magic, version, seq, n = np.frombuffer(raw, "<u4", 3, 0).tolist() + [int(np.frombuffer(raw, "<i4", 1, 12)[0])]
        if magic != MAGIC or not 0 < n <= MAXC:
            names = []
        else:
            names = [_str(raw[5600 + 48 * i:5600 + 48 * (i + 1)]) for i in range(n)]
        if self.want_addr and now >= self.next_want:
            self.next_want = now + 1.0
            self._write_want(names)
        if seq != self.seq:
            self.seq, self.seq_since = seq, now
        if magic != MAGIC or not 0 < n <= MAXC or now - self.seq_since > 3.0:   # nobody writing (game closed, app idle)
            self.snap = None
            return
        f = {k: np.frombuffer(raw, dt, cnt, off) for k, (off, dt, cnt) in FIELDS.items()}
        online, writer = raw[32], raw[33]
        track = _str(raw[36:96])
        drivers = [_str(raw[3040 + 40 * i:3040 + 40 * (i + 1)]) for i in range(n)]
        for i in range(1, n):   # car 0 is you: the recorder has the full telemetry for that
            if f["connected"][i]:
                self._car(i, f, drivers[i], names[i], track, online, writer, now)
        self._finish_due(f, writer, now)
        if now - self.snap_at >= 0.25:
            self.snap_at = now
            self.snap = {"t": now, "track": track, "cars": [
                {"i": i, "name": drivers[i], "car": names[i], "spline": round(float(f["spline"][i]), 5), "laps": int(f["laps"][i]),
                 "last": int(f["last"][i]), "best": int(f["best"][i]), "pit": bool(f["pit"][i]), "speed": round(float(f["speed"][i]))}
                for i in range(n) if f["connected"][i] and drivers[i]]}

    def _car(self, i, f, driver, car, track, online, writer, now):
        pos, t = float(f["spline"][i]), float(f["t"][i])
        key = (driver, car, track)
        st = self.st.get(i)
        if st is None or st["key"] != key:   # new car in this slot
            self.st[i] = {"key": key, "rows": None, "last": pos, "tp": t, "start": 0.0, "pit": False, "rt": -1.0}
            return
        if t <= st["tp"]:
            return   # no new sample yet
        if st["last"] > 0.9 and pos < 0.1:   # crossed the line: interpolate the exact moment
            span = (1.0 - st["last"]) + pos
            cross = st["tp"] + (t - st["tp"]) * ((1.0 - st["last"]) / span if span > 0 else 1.0)
            if st["rows"] is not None:
                self.pending.append({"due": now + self.settle, "i": i, "rows": st["rows"], "lap_s": cross - st["start"],
                                     "pit": st["pit"], "driver": driver, "car": car, "track": track, "online": online,
                                     "laps": int(f["laps"][i]), "writer": writer, "wall": now})
            st["rows"], st["start"], st["pit"], st["rt"] = [], cross, False, -1.0
        elif st["rows"] is not None and pos < st["last"] - 0.05:
            st["rows"] = None   # reset / back to the pits
        st["last"], st["tp"] = pos, t
        rows = st["rows"]
        if rows is None:
            return
        if f["pit"][i]:
            st["pit"] = True
        if len(rows) > MAX_ROWS:
            st["rows"] = None
        elif t - st["rt"] >= ROW_EVERY and (f["x"][i] or f["z"][i]):   # only cars sent with full detail
            st["rt"] = t
            rows.append((t - st["start"], pos, float(f["speed"][i]), float(f["x"][i]), float(f["z"][i]), int(f["gear"][i])))

    def _finish_due(self, f, writer, now):
        keep = []
        for p in self.pending:
            if p["due"] > now:
                keep.append(p)
                continue
            try:
                self._save(p, f, writer)
            except Exception as e:
                print("ghost lap failed", e)
        self.pending = keep

    def _save(self, p, f, writer):
        if p["pit"] or len(p["rows"]) < 100 or p["lap_s"] < 20:
            return
        i, valid, note = p["i"], 1, ""
        # CSP reports the game's own verdict for every car; it refers to this lap if its lap count matches
        if p["writer"] == 2 and int(f["valid_lap"][i]) == int(f["laps"][i]) and int(f["laps"][i]) >= p["laps"]:
            if not f["lap_valid"][i]:
                cuts = int(f["lap_cuts"][i])
                valid, note = 0, json.dumps({"cut": f"game flagged the lap ({cuts} cut{'s' if cuts != 1 else ''})"})
        a = np.array(p["rows"], dtype=float)
        meta = {"source": "online" if p["online"] else "ai", "driver": p["driver"], "car": p["car"], "track": p["track"],
                "lap_ms": int(p["lap_s"] * 1000), "valid": valid, "note": note}
        lap_id = ingest.ingest_rows(meta, list(COLS), a, origin=f"live:{p['track']}:{p['car']}:{p['driver']}:{p['wall']:.3f}")
        if lap_id:
            self.saved += 1
            store.clear_samples()
            store.prune(p["car"], p["track"])

    def snapshot(self):
        s = self.snap
        return s if s and time.time() - s["t"] < 5 else None

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:   # keep the thread alive whatever happens
                print("car feed", e)
                time.sleep(1)
            time.sleep(POLL)


MAGIC_W = WANT_MAGIC.to_bytes(4, "little")
feed = CarFeed()
