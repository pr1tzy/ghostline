"""The CSP Lua app (GhostlineLogger) under real LuaJIT, via lupa, with a fake CSP API: its shared-memory block must
parse with backend/carfeed.py's layout. Needs `pip install lupa`; skipped without it."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    print("skipped: pip install lupa")
    sys.exit(0)
from backend import carfeed  # noqa: E402

lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
N, L = 6, 5793.0
lua.execute("""
ffi = require('ffi')
blocks = {}
sim = { t = 0 }
local cars = {}
local speeds = {}
for i = 0, %d - 1 do speeds[i] = 70 + i * 0.4 end
ac = {
  getTrackFullID = function(sep) return 'ks_nordschleife' .. sep .. 'nordschleife' end,
  getSim = function() return { isOnlineRace = true, carsCount = %d } end,
  writeMemoryMappedFile = function(name, size)
    local b = ffi.new('uint8_t[?]', size); blocks[name] = { buf = b, size = size }; return ffi.cast('void*', b) end,
  getDriverName = function(i) return 'Lua Driver ' .. i end,
  getCarID = function(i) return i %% 2 == 0 and 'lotus_exos_125_s1' or 'ks_ferrari_488_gt3' end,
  getCar = function(i)
    local d = sim.t * speeds[i]; local pos = (d / %f) %% 1
    return { isConnected = true, isInPitlane = false, lapCount = math.floor(d / %f), previousLapTimeMs = 81000, bestLapTimeMs = 80500,
             splinePosition = pos, position = { x = 900 * math.cos(pos * 6.2832), z = 600 * math.sin(pos * 6.2832) },
             speedKmh = speeds[i] * 3.6, gear = 5 }
  end,
  onLapCompleted = function(i, cb) lapCb = cb end,
}
ui = { text = function(s) lastText = s end }
local clock0 = 0
os.preciseClock = function() clock0 = clock0 + 0.000001; return clock0 end
script = {}
""" % (N, N, L, L))
src = open(ROOT / "ac_app" / "GhostlineLogger" / "GhostlineLogger.lua", encoding="utf-8").read()
lua.execute(src)
g = lua.globals()
# Ghostline's heartbeat + want mask (cars 1..N-1 wanted)
for step in range(1, 400):
    g.sim.t = step / 60.0
    if step == 1 or step % 60 == 0:   # write heartbeat like carfeed does
        lua.execute("""
        local b = blocks['GhostlineWant.v1']
        if b then
          local w = ffi.cast('uint32_t*', b.buf); w[0] = 0x31574847; w[1] = w[1] + 1
          for i = 9, 71 do b.buf[i] = 1 end
        end""")
    g.script.update(1 / 60.0)
g.lapCb(3, 81234, False, 2, 7)    # the game says car 3's lap 7 was invalid, 2 cuts
raw = bytes(lua.eval("ffi.string(blocks['GhostlineCars.v1'].buf, blocks['GhostlineCars.v1'].size)"))
assert len(raw) == carfeed.SIZE, len(raw)
f = {k: np.frombuffer(raw, dt, cnt, off) for k, (off, dt, cnt) in carfeed.FIELDS.items()}
magic, version, seq = np.frombuffer(raw, "<u4", 3, 0)
n = int(np.frombuffer(raw, "<i4", 1, 12)[0])
assert magic == carfeed.MAGIC and version == 1 and seq % 2 == 0 and n == N and raw[32] == 1 and raw[33] == 2
assert carfeed._str(raw[36:96]) == "ks_nordschleife-nordschleife" and np.frombuffer(raw, "<f8", 1, 24)[0] > 0
assert carfeed._str(raw[3040 + 80:3040 + 120]) == "Lua Driver 2" and carfeed._str(raw[5600 + 48:5600 + 96]) == "ks_ferrari_488_gt3"
t = g.sim.t
for i in range(N):
    pos = (t * (70 + i * 0.4) / L) % 1
    assert abs(f["spline"][i] - pos) < 0.002, (i, f["spline"][i], pos)
    assert f["best"][i] == 80500 and f["t"][i] > 0
    if i:   # wanted: full detail
        assert f["speed"][i] > 250 and f["gear"][i] == 5 and (f["x"][i] or f["z"][i])
assert f["x"][0] == 0 and f["speed"][0] == 0, "car 0 (you) is recorded by Ghostline itself"
assert f["lap_valid"][3] == 0 and f["lap_cuts"][3] == 2 and f["valid_lap"][3] == 7
g.script.windowMain(0)
print("lua app ok, window:", g.lastText.decode())
