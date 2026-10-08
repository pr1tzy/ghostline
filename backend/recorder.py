"""Records the player's laps from Assetto Corsa shared memory (60 Hz, full inputs).

Only opens AC's existing mappings (never creates them), so it can't interfere with AC, CM or SimHub.
"""
import ctypes
import json
import threading
import time
from ctypes import wintypes

import numpy as np

from . import analysis, carfeed, content, ingest, settings, store

HZ = 60
STATUS_LIVE, STATUS_PAUSE = 2, 3
F4, F3, W33 = ctypes.c_float * 4, ctypes.c_float * 3, ctypes.c_wchar * 33
I, F = ctypes.c_int, ctypes.c_float


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("packetId", I), ("gas", F), ("brake", F), ("fuel", F), ("gear", I), ("rpms", I),
                ("steerAngle", F), ("speedKmh", F), ("velocity", F3), ("accG", F3), ("wheelSlip", F4),
                ("wheelLoad", F4), ("wheelsPressure", F4), ("wheelAngularSpeed", F4), ("tyreWear", F4),
                ("tyreDirtyLevel", F4), ("tyreCoreTemperature", F4), ("camberRAD", F4),
                ("suspensionTravel", F4), ("drs", F), ("tc", F), ("heading", F), ("pitch", F), ("roll", F),
                ("cgHeight", F), ("carDamage", F * 5), ("numberOfTyresOut", I)]


class Graphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("packetId", I), ("status", I), ("session", I), ("currentTime", ctypes.c_wchar * 15),
                ("lastTime", ctypes.c_wchar * 15), ("bestTime", ctypes.c_wchar * 15), ("split", ctypes.c_wchar * 15),
                ("completedLaps", I), ("position", I), ("iCurrentTime", I), ("iLastTime", I), ("iBestTime", I),
                ("sessionTimeLeft", F), ("distanceTraveled", F), ("isInPit", I), ("currentSectorIndex", I),
                ("lastSectorTime", I), ("numberOfLaps", I), ("tyreCompound", W33), ("replayTimeMultiplier", F),
                ("normalizedCarPosition", F), ("carCoordinates", F3), ("penaltyTime", F), ("flag", I),
                ("idealLineOn", I), ("isInPitLane", I)]


class Static(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("smVersion", ctypes.c_wchar * 15), ("acVersion", ctypes.c_wchar * 15), ("numberOfSessions", I),
                ("numCars", I), ("carModel", W33), ("track", W33), ("playerName", W33), ("playerSurname", W33),
                ("playerNick", W33), ("sectorCount", I), ("maxTorque", F), ("maxPower", F), ("maxRpm", I),
                ("maxFuel", F), ("suspensionMaxTravel", F4), ("tyreRadius", F4), ("maxTurboBoost", F),
                ("deprecated_1", F), ("deprecated_2", F), ("penaltiesEnabled", I), ("aidFuelRate", F),
                ("aidTireRate", F), ("aidMechanicalDamage", F), ("aidAllowTyreBlankets", I), ("aidStability", F),
                ("aidAutoClutch", I), ("aidAutoBlip", I), ("hasDRS", I), ("hasERS", I), ("hasKERS", I),
                ("kersMaxJ", F), ("engineBrakeSettingsCount", I), ("ersPowerControllerCount", I),
                ("trackSPlineLength", F), ("trackConfiguration", W33)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
FILE_MAP_READ = 4


class Page:
    def __init__(self, name, struct):
        self.struct, self.size = struct, ctypes.sizeof(struct)
        self.h = _k32.OpenFileMappingW(FILE_MAP_READ, False, name)
        if not self.h:
            raise OSError("not running")
        self.addr = _k32.MapViewOfFile(self.h, FILE_MAP_READ, 0, 0, self.size)
        if not self.addr:
            _k32.CloseHandle(self.h)
            raise OSError("map failed")

    def read(self):
        return self.struct.from_buffer_copy(ctypes.string_at(self.addr, self.size))

    def close(self):
        _k32.UnmapViewOfFile(self.addr)
        _k32.CloseHandle(self.h)


def _clean(s):
    return s if s and s.isprintable() and s.isascii() and len(s) < 40 else ""


class PhysicsX(ctypes.Structure):   # rest of SPageFilePhysics (AC 1.x), used when the game's page is big enough
    _pack_ = 4
    _fields_ = Physics._fields_ + [
        ("pitLimiterOn", I), ("abs", F), ("kersCharge", F), ("kersInput", F), ("autoShifterOn", I), ("rideHeight", F * 2),
        ("turboBoost", F), ("ballast", F), ("airDensity", F), ("airTemp", F), ("roadTemp", F), ("localAngularVel", F3),
        ("finalFF", F), ("performanceMeter", F), ("engineBrake", I), ("ersRecoveryLevel", I), ("ersPowerLevel", I),
        ("ersHeatCharging", I), ("ersIsCharging", I), ("kersCurrentKJ", F), ("drsAvailable", I), ("drsEnabled", I),
        ("brakeTemp", F4), ("clutch", F), ("tyreTempI", F4), ("tyreTempM", F4), ("tyreTempO", F4), ("isAIControlled", I),
        ("tyreContactPoint", F * 12), ("tyreContactNormal", F * 12), ("tyreContactHeading", F * 12), ("brakeBias", F),
        ("localVelocity", F3)]


class GraphicsX(ctypes.Structure):
    _pack_ = 4
    _fields_ = Graphics._fields_ + [("surfaceGrip", F), ("mandatoryPitDone", I), ("windSpeed", F), ("windDirection", F)]


SESSIONS = {0: "Practice", 1: "Qualifying", 2: "Race", 3: "Hotlap", 4: "Time attack", 5: "Drift", 6: "Drag"}
FLAGS = {1: "Blue", 2: "Yellow", 3: "Black", 4: "White", 5: "Chequered", 6: "Penalty"}


def _ok(v, lo, hi, nd=1):
    """Hide values that are clearly not what we think they are (layout differences between AC versions)."""
    try:
        return round(float(v), nd) if lo <= v <= hi else None
    except TypeError:
        return None


def _arr(a, lo, hi, nd=1):
    vals = [_ok(x, lo, hi, nd) for x in a]
    return vals if all(v is not None for v in vals) else None


class Standings:
    """Every car's track position (from the car feed, or the old app's live.json) -> order and gaps."""

    def __init__(self):
        self.hist, self.last_read, self.data = {}, 0.0, None

    def read(self):
        now = time.time()
        if now - self.last_read < 1.0 / settings.logger()["live_hz"]:
            return self.data
        self.last_read = now
        raw = carfeed.feed.snapshot()
        if raw is None:   # an older RaceLogger that still writes live.json
            d = ingest.app_dir()
            try:
                raw = json.loads((d / "live.json").read_text(encoding="utf-8")) if d else None
            except (OSError, ValueError):
                return self.data
        if not raw or now - raw.get("t", 0) > 5:
            self.data = None
            return None
        for c in raw["cars"]:
            h = self.hist.setdefault(c["name"], [])
            prog = c["laps"] + c["spline"]
            if h and prog < h[-1][0] - 0.5:      # spline wrapped before the lap counter ticked
                prog += 1
            if not h or prog > h[-1][0]:
                h.append((prog, now))
            del h[:-2400]                        # ~10 minutes of history per car
            c["prog"] = prog
        self.data = raw
        return raw

    def _reached(self, name, prog):
        h = self.hist.get(name, [])
        for k in range(len(h) - 1, 0, -1):
            if h[k - 1][0] <= prog <= h[k][0]:
                (p0, t0), (p1, t1) = h[k - 1], h[k]
                return t0 + (t1 - t0) * ((prog - p0) / (p1 - p0) if p1 > p0 else 0)
        return None

    def table(self, race):
        raw = self.read()
        if not raw:
            return None
        cars = [c for c in raw["cars"]]
        me = next((c for c in cars if c["i"] == 0), None)
        now = time.time()
        if race:
            cars.sort(key=lambda c: -c["prog"])
        else:
            cars.sort(key=lambda c: (c["best"] <= 0, c["best"]))
        out = []
        for pos, c in enumerate(cars, 1):
            gap = None
            if me and c is not me:
                if race:
                    if c["prog"] > me["prog"]:
                        t = self._reached(c["name"], me["prog"])
                        gap = None if t is None else round(-(now - t), 2)        # ahead of me: negative
                    else:
                        t = self._reached(me["name"], c["prog"])
                        gap = None if t is None else round(now - t, 2)           # behind me: positive
                    if gap is not None and abs(gap) > 300:
                        gap = None
                elif c["best"] > 0 and me["best"] > 0:
                    gap = round((c["best"] - me["best"]) / 1000, 3)
            out.append({"pos": pos, "name": c["name"], "me": c is me, "best": c["best"] or None, "last": c["last"] or None,
                        "gap": gap, "pit": c["pit"], "spline": c["spline"], "laps": c["laps"]})
        return out


class Recorder(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.enabled = True   # always records after a restart; a pause only lasts until then
        self.state = {"connected": False, "recording": False, "enabled": self.enabled, "recent": []}
        self.standings = Standings()
        self.pb = self.ghost = None
        self.corners = []

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.state["enabled"] = self.enabled

    def _open(self, name, big, small):
        try:
            return Page(name, big)
        except OSError:
            return Page(name, small)

    def run(self):
        while True:
            if not self.enabled:
                self.state.update(connected=False, recording=False)
                time.sleep(0.5)
                continue
            try:
                pages = [self._open("Local\\acpmf_physics", PhysicsX, Physics),
                         self._open("Local\\acpmf_graphics", GraphicsX, Graphics), Page("Local\\acpmf_static", Static)]
            except OSError:
                self.state.update(connected=False, recording=False)
                time.sleep(2)
                continue
            try:
                self._loop(*pages)
            except Exception as e:  # keep the thread alive whatever happens
                self.state["error"] = str(e)
                time.sleep(1)
            finally:
                for p in pages:
                    p.close()

    def _info(self, st):
        track = st.track + (f"-{_clean(st.trackConfiguration)}" if _clean(st.trackConfiguration) else "")
        if 500 < st.trackSPlineLength < 40000:
            store.set_track(track, length=round(st.trackSPlineLength))
        parts = list(dict.fromkeys(x.strip() for x in (st.playerName, st.playerSurname) if x and x.strip()))
        driver = " ".join(parts) or "You"   # dict.fromkeys: "pr1tzy pr1tzy" when both fields hold the same name
        self.max_rpm = st.maxRpm if 1000 < st.maxRpm < 25000 else None
        self.max_fuel = _ok(st.maxFuel, 1, 500)
        return st.carModel, track, driver

    def _refresh_ref(self, car, track):
        pb = store.q("SELECT id FROM laps WHERE source='player' AND valid=1 AND car=? AND track=? ORDER BY lap_ms LIMIT 1", (car, track))
        gh = store.q("SELECT id FROM laps WHERE source IN ('online','ai') AND valid=1 AND car=? AND track=? ORDER BY lap_ms LIMIT 1", (car, track))
        self.pb = analysis.prep(pb[0]["id"]) if pb else None
        self.ghost = analysis.prep(gh[0]["id"]) if gh else None
        base = self.ghost or self.pb
        self.corners = analysis.find_corners(base) if base else []

    def _loop(self, phys, gfx, stat):
        rows, recording = [], False
        last_pkt, last_laps, last_pos, stale_since = None, None, None, time.time()
        car = track = driver = None
        lap = {}
        sess_best_sectors, fuel_hist, last_sectors = {}, [], []
        while self.enabled:
            time.sleep(1 / HZ)
            g, p = gfx.read(), phys.read()
            now = time.time()
            if p.packetId == last_pkt:
                if g.status != STATUS_PAUSE and now - stale_since > 5:
                    return   # AC closed or frozen: reconnect
                continue
            last_pkt, stale_since = p.packetId, now
            if g.status != STATUS_LIVE:
                continue
            if car is None or last_laps is None or g.completedLaps < last_laps:
                car, track, driver = self._info(stat.read())
                carfeed.feed.player_car = car   # full detail only for cars that can be your ghost
                self._refresh_ref(car, track)
                rows, recording, sess_best_sectors, fuel_hist = [], False, {}, []
            pos = g.normalizedCarPosition

            if last_laps is not None and g.completedLaps > last_laps:
                if recording and lap.get("sectors") and g.iLastTime > 0:     # final sector = lap minus the others
                    k, rest = len(lap["sectors"]), g.iLastTime - sum(lap["sectors"])
                    if 0 < rest < 600000:
                        lap["sectors"].append(rest)
                        sess_best_sectors[k] = min(sess_best_sectors.get(k, 10 ** 9), rest)
                    last_sectors = lap["sectors"]
                if recording and len(rows) > 200:
                    self._save(rows, car, track, driver, g.iLastTime)
                    if lap.get("fuel0") is not None and lap["fuel0"] > p.fuel:
                        fuel_hist = (fuel_hist + [lap["fuel0"] - p.fuel])[-5:]
                rows, recording = [], True
                lap = {"fuel0": p.fuel, "sectors": [], "corners": [], "seg_in": {}, "tyres_out": 0, "sector_idx": 0}
            elif recording and last_pos is not None and pos < last_pos - 0.05 and not (last_pos > 0.9 and pos < 0.1):
                rows, recording = [], False          # teleported / reset to pits
            if g.isInPit == 1 or g.isInPitLane == 1:
                rows, recording = [], False
            last_laps, last_pos = g.completedLaps, pos

            t_lap = g.iCurrentTime / 1000
            if recording:
                rows.append((t_lap, pos, p.speedKmh, p.gas, p.brake, p.steerAngle, p.gear - 1,
                             p.rpms, g.carCoordinates[0], g.carCoordinates[2], p.numberOfTyresOut))
                lap["tyres_out"] = max(lap["tyres_out"], p.numberOfTyresOut)
                if g.currentSectorIndex != lap["sector_idx"] and 0 < g.lastSectorTime < 600000:
                    k = len(lap["sectors"])
                    lap["sectors"].append(g.lastSectorTime)
                    sess_best_sectors[k] = min(sess_best_sectors.get(k, 10 ** 9), g.lastSectorTime)
                    lap["sector_idx"] = g.currentSectorIndex
                self._corner_feedback(lap, pos, t_lap, now)

            base = self.ghost or self.pb
            dist = pos * base["L"] if base else None
            at = lambda ref: float(ref["t"][min(int(pos * ref["L"]), len(ref["t"]) - 1)])
            live_ok = recording and 0.01 < pos < 0.99
            d_pb = round(t_lap - at(self.pb), 3) if live_ok and self.pb else None
            d_gh = round(t_lap - at(self.ghost), 3) if live_ok and self.ghost else None
            ghost_pos = None
            if recording and self.ghost:
                gi = int(np.searchsorted(self.ghost["t"], t_lap))
                ghost_pos = round(min(gi, len(self.ghost["t"]) - 1) / len(self.ghost["t"]), 4)
            fpl = round(sum(fuel_hist) / len(fuel_hist), 2) if fuel_hist else None
            ext = hasattr(p, "brakeTemp")
            race = g.session == 2
            table = self.standings.table(race)
            self.state.update(
                connected=True, recording=recording, car=car, track=track, driver=driver,
                car_name=store.car_info(car)["name"], track_name=store.track_cfg(track).get("name") or track,
                supported=content.supported(car, track), lap_ms=g.iCurrentTime, pos=round(pos, 4), dist=dist and round(dist),
                speed=round(p.speedKmh), gear=p.gear - 1, rpm=p.rpms, max_rpm=self.max_rpm,
                throttle=round(p.gas, 2), brake=round(p.brake, 2), clutch=_ok(getattr(p, "clutch", -1), 0, 1, 2),
                delta=d_gh if d_gh is not None else d_pb, delta_pb=d_pb, delta_ghost=d_gh,
                predicted_ms=int((self.pb["meta"]["lap_ms"] / 1000 + d_pb) * 1000) if d_pb is not None else None,
                pb_ms=self.pb["meta"]["lap_ms"] if self.pb else None, ghost_ms=self.ghost["meta"]["lap_ms"] if self.ghost else None,
                ghost_pos=ghost_pos, last_ms=g.iLastTime, best_ms=g.iBestTime,
                ref_id=(self.ghost or self.pb)["meta"]["id"] if (self.ghost or self.pb) else None,
                session=SESSIONS.get(g.session, "Session"), time_left=_ok(g.sessionTimeLeft, 0, 86400000, 0),
                position=g.position if 0 < g.position < 100 else None, num_cars=len(table) if table else None,
                laps_done=g.completedLaps, laps_total=g.numberOfLaps if 0 < g.numberOfLaps < 1000 else None,
                valid=not recording or lap.get("tyres_out", 0) <= 2, tyres_out=p.numberOfTyresOut,
                penalty=_ok(g.penaltyTime, 0.01, 3600), flag=FLAGS.get(g.flag),
                in_pit=bool(g.isInPitLane == 1 or g.isInPit == 1), limiter=bool(getattr(p, "pitLimiterOn", 0) == 1),
                fuel=_ok(p.fuel, 0, 500), fuel_per_lap=fpl, fuel_laps=round(p.fuel / fpl, 1) if fpl else None,
                sectors=lap.get("sectors", []) if recording else [], last_sectors=last_sectors, best_sectors=[sess_best_sectors[k] for k in sorted(sess_best_sectors)],
                last_corner=lap.get("corners", [])[-1] if recording and lap.get("corners") else None,
                corners_lap=lap.get("corners", []) if recording else [],
                tyre_core=_arr(p.tyreCoreTemperature, 0, 300), tyre_press=_arr(p.wheelsPressure, 5, 60),
                tyre_wear=_arr(p.tyreWear, 0, 100), brake_temp=_arr(p.brakeTemp, 0, 1500, 0) if ext else None,
                tc=_ok(p.tc, 0, 1, 2), abs=_ok(getattr(p, "abs", -1), 0, 1, 2),
                bias=_ok(getattr(p, "brakeBias", -1), 0.3, 0.9, 3), damage=round(sum(p.carDamage), 2) if all(0 <= x < 1000 for x in p.carDamage) else None,
                air=_ok(getattr(p, "airTemp", -99), -30, 60), road=_ok(getattr(p, "roadTemp", -99), -30, 80),
                grip=_ok(getattr(g, "surfaceGrip", -1), 0.5, 1.2, 3), standings=table, error=None)

    def _corner_feedback(self, lap, pos, t_lap, now):
        """Time for each corner (entry to exit) against my PB and the ghost, as soon as I leave it."""
        base = self.ghost or self.pb
        if not base or not self.corners:
            return
        d = int(pos * base["L"])
        for c in self.corners:
            key = c["name"]
            if c["i0"] <= d < c["i0"] + 40 and key not in lap["seg_in"]:
                lap["seg_in"][key] = t_lap
            elif d >= (end := min(c["i1"], c["apex"] + 150)) and key in lap["seg_in"] and not any(x["name"] == key for x in lap["corners"]):
                seg = t_lap - lap["seg_in"][key]   # braking point to 150 m after the apex
                ref = lambda r: (float(r["t"][min(end, len(r["t"]) - 1)] - r["t"][min(c["i0"], len(r["t"]) - 1)])) if r else None
                pb, gh = ref(self.pb), ref(self.ghost)
                lap["corners"].append({"name": key, "time": round(seg, 3), "at": now,
                                       "vs_pb": round(seg - pb, 3) if pb else None, "vs_ghost": round(seg - gh, 3) if gh else None})

    def _save(self, rows, car, track, driver, lap_ms):
        if not content.supported(car, track):
            return   # mod content isn't recorded (see content.py)
        a = np.array(rows, dtype=float)
        off = np.flatnonzero(a[:, 10] > 2)
        cut = bool(len(off))
        note = json.dumps({"cut": analysis.cut_reason(track, a[:, 8], a[:, 9], float(a[off[0], 1]))}) if cut else ""
        cols = ("t", "pos", "speed", "throttle", "brake", "steer", "gear", "rpm", "x", "z")
        lap_id = store.add_lap(
            {"source": "player", "driver": driver, "car": car, "track": track, "lap_ms": lap_ms, "valid": not cut,
             "has_inputs": 1, "origin": f"player-{time.time():.3f}", "note": note},
            {c: a[:, i] for i, c in enumerate(cols)})
        store.clear_samples()   # after the insert, so a new lap never reuses a sample's id
        self._refresh_ref(car, track)
        self.state["recent"] = ([{"id": lap_id, "lap_ms": lap_ms, "valid": not cut}] + self.state["recent"])[:6]


recorder = Recorder()
