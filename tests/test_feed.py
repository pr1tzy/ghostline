"""End to end, offline: the real in-game RaceLogger app (with a fake AC API) writes shared memory, the real CarFeed
reads it. Checks idling, lap detection and timing, full detail only for your car / class, standings, and cost."""
import importlib.util
import math
import os
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["RA_DATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

N, FPS, L = 24, 60, 5793.0
MINE, OTHER = "lotus_exos_125_s1", "ks_ferrari_488_gt3"
sim = {"t": 0.0}
CS = types.SimpleNamespace(NormalizedSplinePosition=1, WorldPosition=2, SpeedKMH=3, Gear=4, LapCount=5, LastLap=6, BestLap=7)
speed = [70 + i * 0.4 for i in range(N)]                                 # m/s: laps of 74-83 s
model = [MINE if i % 2 == 0 else OTHER for i in range(N)]                # half the grid is a different class


def car_state(i, what):
    d = sim["t"] * speed[i]
    pos = (d / L) % 1.0
    if what == CS.NormalizedSplinePosition:
        return pos
    if what == CS.WorldPosition:
        a = pos * 2 * math.pi
        return (900 * math.cos(a), 0.0, 600 * math.sin(a))
    if what == CS.SpeedKMH:
        return speed[i] * 3.6
    if what == CS.Gear:
        return 6
    if what == CS.LapCount:
        return int(d // L)
    return int(L / speed[i] * 1000) if what in (CS.LastLap, CS.BestLap) else 0


ac = types.ModuleType("ac")
for k, v in dict(newApp=lambda n: 1, setSize=lambda *a: None, addLabel=lambda *a: 2, setPosition=lambda *a: None,
                 setText=lambda w, t: labels.append(t), log=lambda m: print("ac.log:", m), getTrackConfiguration=lambda i: "",
                 getTrackName=lambda i: "monza", getServerName=lambda: "Test server", getCarsCount=lambda: N,
                 isConnected=lambda i: True, getCarState=car_state, getDriverName=lambda i: "Driver %d" % i,
                 getCarName=lambda i: model[i], isCarInPitline=lambda i: False).items():
    setattr(ac, k, v)
acsys = types.ModuleType("acsys")
acsys.CS = CS
sys.modules["ac"], sys.modules["acsys"] = ac, acsys
labels = []

from backend import carfeed, settings, store  # noqa: E402

settings.LOGGER_FILE = Path(os.environ["RA_DATA"]) / "logger.json"   # never touch the real config
# own shared-memory names: never read from, or write into, a Ghostline that's running on this PC
SUFFIX = f".test{os.getpid()}"
carfeed.CARS, carfeed.WANT, carfeed.SET = (carfeed.CARS + SUFFIX, carfeed.WANT + SUFFIX, carfeed.SET + SUFFIX)

spec = importlib.util.spec_from_file_location("RaceLogger", ROOT / "ac_app" / "RaceLogger" / "RaceLogger.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.CARS, app.WANT = app.CARS + SUFFIX, app.WANT + SUFFIX
app.acMain("1.16")
feed = carfeed.CarFeed()
feed.player_car = MINE
feed.settle = 0.2

dt = 1.0 / FPS


def run(seconds, with_feed):
    costs = []
    for _ in range(int(seconds * FPS)):
        sim["t"] += dt
        t0 = time.perf_counter()
        app.acUpdate(dt)
        costs.append((time.perf_counter() - t0) * 1000)
        if with_feed:
            feed.tick(now=sim["t"])
    return sorted(costs)


# 1. nobody listening: the app idles
idle = run(5, with_feed=False)
assert not app.active, "app should idle while Ghostline isn't running"
# 2. Ghostline running: three laps
busy = run(250, with_feed=True)
assert app.active, "app should send once Ghostline's heartbeat is there"
assert any("sending" in t for t in labels), labels[-3:]

laps = store.q("SELECT driver, car, lap_ms, source, valid FROM laps")
mine = [l for l in laps if l["car"] == MINE]
assert laps and all(l["car"] == MINE for l in laps), "only your car / class gets full detail and saved laps"
assert all(l["source"] == "online" for l in laps)
for l in mine:
    i = int(l["driver"].split()[-1])
    assert abs(l["lap_ms"] - L / speed[i] * 1000) < 60, (l, L / speed[i] * 1000)   # timing within 60 ms
drivers = {l["driver"] for l in mine}
assert len(drivers) >= 3, drivers   # pruning keeps the 3 fastest drivers

snap = feed.snap   # snapshot() checks freshness against the wall clock; this test runs on simulated time
assert snap and len(snap["cars"]) == N and snap["track"] == "monza", snap and len(snap["cars"])
c = next(x for x in snap["cars"] if x["i"] == 3)
assert c["name"] == "Driver 3" and c["car"] == OTHER and 0 <= c["spline"] <= 1

# 3. a settings change from the CSP app's window: saved to logger.json, sent back out, picked up by the app
import mmap  # noqa: E402
import struct  # noqa: E402
req = mmap.mmap(-1, carfeed.SET_SIZE, tagname="GhostlineSettings.v1" + SUFFIX)
struct.pack_into("<IIHHHBB", req, 0, carfeed.SET_MAGIC, 7, 45, 6, 25, 1, 2)
run(3, with_feed=True)
saved = settings.logger()
assert saved == {"enabled": True, "sample_hz": 45, "timing_hz": 6, "live_hz": 25, "detail": "all"}, saved
assert settings.LOGGER_FILE.exists() and abs(app.step - 1 / 45) < 1e-9 and abs(app.slow - 1 / 6) < 1e-9, (app.step, app.slow)

# 3. the CSP Lua app starts sending: the Python app stands down
for k in range(1, 4 * FPS):
    struct.pack_into("<d", app.buf, 24, float(k))   # what GhostlineLogger.lua does every frame
    sim["t"] += dt
    app.acUpdate(dt)
assert not app.active and app.status == "CSP app is sending", app.status

print(f"idle: {sum(idle) / len(idle):.4f} ms avg | sending: {sum(busy) / len(busy):.4f} ms avg, "
      f"p99 {busy[int(len(busy) * .99)]:.3f} ms, max {busy[-1]:.2f} ms | ghost laps saved {feed.saved}, kept {len(laps)}")
print("ok")
