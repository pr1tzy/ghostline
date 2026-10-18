"""The player-lap recorder against a fake game running 10x faster than real time: a lap is recorded from the line
to the line with no samples missing, also while the previous lap is being saved (2.2 lost the first 0.6-1.9 s of a
lap doing that), and lands in the database with the game's lap time."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["RA_DATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend import coach, ingest, recorder as rec_mod, store  # noqa: E402

coach.NAME += f".test{os.getpid()}"   # never touch a running Ghostline's block
ingest.app_dir = lambda: None         # no live.json from a real AC install

m = np.genfromtxt([x for x in (ROOT / "samples" / "monza_you.csv").read_text().splitlines() if not x.startswith("#")],
                  delimiter=",", names=True)
T = float(m["t"][-1])                  # one lap of the sample, s
m = m[:-1]                             # the last row is already past the line (position 0.0001)
SPEED = 10                             # game seconds per real second
rec_mod.HZ = 60 * SPEED                # so the recorder samples 60 times per game second
t0 = time.perf_counter()


def game_t():
    return (time.perf_counter() - t0) * SPEED


class Fake:
    def __getattr__(self, name):
        return 0


class Phys(Fake):
    def __init__(self):
        self.pkt = 0
        self.tyreCoreTemperature, self.wheelsPressure, self.tyreWear, self.brakeTemp = [80] * 4, [27] * 4, [99] * 4, [300] * 4
        self.carDamage = [0] * 5

    def read(self):
        self.pkt += 1
        self.packetId = self.pkt
        lt = game_t() % T
        self.speedKmh, self.gas, self.brake = (float(np.interp(lt, m["t"], m[k])) for k in ("speed", "throttle", "brake"))
        self.gear, self.rpms, self.fuel = 4, 7000, 30
        return self


class Gfx(Fake):
    def read(self):
        gt = game_t()
        lt = gt % T
        self.status = rec_mod.STATUS_LIVE
        self.completedLaps = int(gt // T)
        self.normalizedCarPosition = float(np.interp(lt, m["t"], m["pos"]))
        self.iCurrentTime = int(lt * 1000)
        self.iLastTime = int(T * 1000) if self.completedLaps else 0
        self.carCoordinates = [float(np.interp(lt, m["t"], m["x"])), 0.0, float(np.interp(lt, m["t"], m["z"]))]
        return self


class Stat(Fake):
    track, trackConfiguration, carModel, playerName, playerSurname = "monza", "", "lotus_exos_125_s1", "Test", ""
    trackSPlineLength, maxRpm, maxFuel = 5793.0, 8000, 50

    def read(self):
        return self


# the save is made slow on purpose (as it is on a busy PC): it must not hold up the sampling
real_save = rec_mod.Recorder._save


def slow_save(self, *a):
    time.sleep(1.0)   # 10 s of game time
    real_save(self, *a)


rec_mod.Recorder._save = slow_save
rec = rec_mod.Recorder()
threading.Thread(target=rec._saver, daemon=True).start()
loop = threading.Thread(target=rec._loop, args=(Phys(), Gfx(), Stat()), daemon=True)
loop.start()
while game_t() < 3.2 * T:   # laps 2 and 3 are full laps (recording starts at the first line crossing)
    time.sleep(0.2)
rec.enabled = False
loop.join(5)
deadline = time.time() + 20
while len(store.q("SELECT id FROM laps")) < 2 and time.time() < deadline:
    time.sleep(0.1)

laps = store.q("SELECT * FROM laps ORDER BY id")
assert len(laps) == 2, laps
for l in laps:
    raw = store.load_lap(l["id"])
    gaps = np.diff(raw["t"])
    assert l["valid"] and l["lap_ms"] == int(T * 1000), l
    # nothing missing: a save in the sampling loop leaves a 10 s hole (1 s real). Sampling itself is ~20 ms; the
    # limit leaves room for a slow CI machine (150 ms real)
    assert raw["t"][0] < 1.5 and gaps.max() < 1.5, (l["id"], raw["t"][0], gaps.max())
    assert raw["t"][-1] > T - 0.25, (l["id"], raw["t"][-1])
print(f"ok: {len(laps)} laps, largest gap {max(np.diff(store.load_lap(l['id'])['t']).max() for l in laps) * 1000:.0f} ms")
