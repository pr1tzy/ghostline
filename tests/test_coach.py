"""In-game coaching (ac_app/GhostlineLogger/coach.lua) under real LuaJIT, via lupa, with a fake CSP API, driving the
bundled Monza sample lap frame by frame: block layout, countdown timing, boards that move with your speed, the
racing line and the ghost. Offline; needs `pip install lupa` (skipped without it)."""
import ctypes
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

os.environ["RA_DATA"] = tempfile.mkdtemp()
os.environ["GHOSTLINE_HOME"] = os.environ["RA_DATA"]
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    print("skipped: pip install lupa")
    sys.exit(0)
from backend import analysis, coach, ingest, store  # noqa: E402

coach.NAME += f".test{os.getpid()}"   # never touch a running Ghostline's block

ingest.load_samples()
me = store.q("SELECT * FROM laps WHERE track='monza' AND source='player'")[0]
p = analysis.prep(me["id"])
CAR, TRACK = me["car"], me["track"]

# publish(): the best lap here goes into the shared block (the sample ghost is faster, its pedals are estimated)
best = coach.publish(CAR, TRACK)
fastest = store.q("SELECT id FROM laps WHERE track='monza' AND valid=1 ORDER BY lap_ms LIMIT 1")[0]["id"]
blk = coach._open()
assert best == fastest and blk.magic == coach.MAGIC and blk.rev % 2 == 0 and blk.lapId == best and blk.n > 2000, (best, blk.n)
assert coach.publish(CAR, TRACK) == best and blk.rev == 2, "republishing the same lap must not rewrite the block"

# the block the game gets in this test: the sample lap with real pedal data
ref = coach.Ref()
corners = coach.fill(ref, p, me, CAR, TRACK)
assert ref.est == 0 and len(corners) >= 5 and ref.rev % 2 == 0
data = bytes(ctypes.string_at(ctypes.addressof(ref), coach.SIZE))

lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
lua.execute(r"""
ffi = require('ffi')
package.path = '%s/?.lua;' .. package.path
blocks, sounds, sim, carState = {}, {}, { t = 0 }, nil
audio = { made = 0, disposed = 0 }
local V = {}; V.__index = V
function vec3(x, y, z) return setmetatable({ x = x or 0, y = y or 0, z = z or 0 }, V) end
function V:set(x, y, z) self.x, self.y, self.z = x, y, z return self end
function V:normalize() local l = math.sqrt(self.x ^ 2 + self.y ^ 2 + self.z ^ 2) if l > 0 then self:set(self.x / l, self.y / l, self.z / l) end return self end
function vec2(x, y) return { x = x, y = y } end
function rgbm(r, g, b, m) return { r = r, g = g, b = b, mult = m } end
local any = setmetatable({}, { __index = function () return function (self) return self end end })
ghost = { pos = nil, visible = false }
mat4x4 = { look = function (p, l, u) ghost.pos = { p.x, p.y, p.z } return {} end }
local node = setmetatable({
  setVisible = function (self, v) ghost.visible = v end,
  setPosition = function (self, p) ghost.pos = { p.x, p.y, p.z } end,
  setOrientation = function (self, l, u) ghost.look = { l.x, l.y, l.z } end,
  loadKN5LODAsync = function (self, f, m, cb) ghost.file = f; cb(nil, any) end,
  dispose = function () end }, { __index = any })
local function refBlock() return ffi.cast('ghl_ref*', blocks['GhostlineRef.v1']) end
ac = {
  getCarID = function () return '%s' end,
  getTrackFullID = function () return '%s' end,
  getCar = function (i) return carState end,
  writeMemoryMappedFile = function (name, size)
    if not blocks[name] then blocks[name] = ffi.new('uint8_t[?]', size) end
    return ffi.cast('void*', blocks[name]) end,
  trackProgressToWorldCoordinate = function (p)
    local r = refBlock(); local f = (p %% 1) * r.length / r.step; local i = math.floor(f) %% r.n
    return vec3(r.x[i], 0, r.z[i]) end,
  getTrackAISplineSides = function () return vec2(6, 6) end,
  findNodes = function () return { createBoundingSphereNode = function () return node end } end,
  isInReplayMode = function () return false end,
  storage = function (layout) return layout end,
  getSim = function () return { trackLengthM = refBlock().length } end,
  SimpleMesh = { carShape = function () return 1 end },
  AudioEvent = { fromFile = function (p)
    audio.made = audio.made + 1
    return { start = function () sounds[#sounds + 1] = { t = sim.t, f = p.filename } end,
             dispose = function () audio.disposed = audio.disposed + 1 end } end },
  onRelease = function (fn) audio.release = fn end,
}
physics = { raycastTrack = function (pos, dir, len, point, normal) if normal then normal:set(0, 1, 0) end return pos.y end }
drawn = { quads = {}, line = {}, text = {} }
render = {
  BlendMode = { AlphaBlend = 1 }, DepthMode = { ReadOnly = 1, ReadOnlyLessEqual = 4 }, CullMode = { None = 2, Back = 1 },
  mesh = function (t) ghost.drawn = (ghost.drawn or 0) + 1 end,
  setBlendMode = function () end, setDepthMode = function () end, setCullMode = function () end,
  on = function (name, fn) drawFn = fn end,
  glBegin = function () end, glEnd = function () end,
  glVertex = function () end,
  -- racing line chevrons only (the ghost's marker is cyan: blue channel 1)
  quad = function (a, b, c, d, col) if col.b < 0.9 then drawn.line[#drawn.line + 1] = { (a.x + b.x) / 2, (a.z + b.z) / 2, col.g } end end,
  debugText = function (p, s) drawn.text[#drawn.text + 1] = s end,
  rectangle = function (p, dir, w, h) drawn.posts = (drawn.posts or 0) + 1 end,
}
ui = { text = function (s) lastText = s end, separator = function () end, sameLine = function () end,
       checkbox = function () return false end, radioButton = function () return false end,
       slider = function (l, v) return v, false end }
local c0 = 0
os.preciseClock = function () c0 = c0 + 1e-6 return c0 end
__dirname = 'app'
""" % (str(ROOT / "ac_app" / "GhostlineLogger").replace("\\", "/"), CAR, TRACK))

# layout: LuaJIT's struct must match backend/coach.py's field for field
lua.execute("require('coach')")
for name, _ in coach.Ref._fields_:
    off = lua.eval(f"tonumber(ffi.offsetof('ghl_ref', '{name}'))")
    assert off == getattr(coach.Ref, name).offset, (name, off, getattr(coach.Ref, name).offset)
assert lua.eval("tonumber(ffi.sizeof('ghl_ref'))") == coach.SIZE
g = lua.globals()


def drive(factor, fps, until=None, laps=1, mine=False):
    """Drive the lap exactly like the reference, `factor` times as fast, `laps` times. Returns what the app did."""
    lua.execute(f"""
    package.loaded['coach'] = nil
    blocks['GhostlineRef.v1'] = ffi.new('uint8_t[?]', {coach.SIZE})
    sounds, drawn = {{}}, {{ quads = {{}}, line = {{}}, text = {{}} }}
    audio = {{ made = 0, disposed = 0 }}
    carState = {{ splinePosition = 0, speedKmh = 0, lapTimeMs = 0, brake = 0, isInPitlane = false, position = vec3(),
                 lapCount = 0, previousLapTimeMs = 0, isLapValid = true }}
    """)
    lua.globals().blob = data
    lua.execute(f"ffi.copy(blocks['GhostlineRef.v1'], blob, {coach.SIZE})")
    m = lua.eval("require('coach')")
    m.cfg.ghostMine = mine
    lapT = p["t"][-1] / factor
    T_end = until / factor if until else lapT * laps
    dt = 1.0 / fps
    out = {"at": {}, "snap": {}}
    clock, T = 0.0, 0.0
    while T < T_end:
        lap, Tl = int(T // lapT), T % lapT
        tr = Tl * factor
        d = float(np.interp(tr, p["t"], p["d"]))
        cs = g.carState
        cs.splinePosition, cs.speedKmh, cs.lapTimeMs = d / p["L"], float(np.interp(d, p["d"], p["speed"])) * factor, int(Tl * 1000)
        cs.lapCount, cs.previousLapTimeMs = lap, int(lapT * 1000) if lap else 0
        cs.brake = float(np.interp(d, p["d"], p["brake"]))
        cs.position.x, cs.position.y, cs.position.z = float(np.interp(d, p["d"], p["x"])), 0.45, float(np.interp(d, p["d"], p["z"]))
        g.sim.t = T
        clock += dt
        m.update(dt, clock)
        lua.execute("drawn.line = {}")
        g.drawFn()
        st = m.state()
        for k, b in st.boards.items():
            out["at"].setdefault(k, set()).add(round(float(b.at), 3))
        for key, at in (("ghost40", 40.0), ("line", None)):
            if key == "ghost40" and abs(Tl - at) < dt / 2:
                gp = st.gpos
                out["snap"]["ghost" if lap == 0 else f"ghost{lap}"] = ([gp.x, gp.y, gp.z], float(m.gap or 0), d, bool(st.ghostOn),
                                                                     m.ghostStatus.decode() if isinstance(m.ghostStatus, bytes) else m.ghostStatus)
        out.setdefault("frames", []).append((T, d, [tuple(q.values()) for q in g.drawn.line.values()]))
        T += dt
    out["sounds"] = [(float(s.t), s.f.decode()) for s in g.sounds.values()]
    out["text"] = list(g.drawn.text.values())
    m.window()
    return out


t_at = lambda dist: float(np.interp(dist, p["d"], p["t"]))
for fps in (60, 120):
    r = drive(1.0, fps)
    brakes = [s for s in r["sounds"] if s[1].endswith("brake.wav")]
    errs = []
    for c in corners:
        if c["kind"] != 1 or c["brake"] < 100:
            continue
        tb = t_at(c["brake"])
        s = min(brakes, key=lambda s: abs(s[0] - tb))
        errs.append(s[0] - tb)
    errs = np.array(errs)
    assert len(errs) >= 4 and np.all(np.abs(errs) <= 0.5 / fps + 0.002), (fps, errs.round(4))
    ticks = [s for s in r["sounds"] if s[1].endswith("tick.wav")]
    assert len(ticks) >= 2 * len(errs), len(ticks)
    print(f"{fps} fps: brake cue vs reference brake point: worst {np.abs(errs).max() * 1000:.1f} ms over {len(errs)} corners")
    # every cue reuses one audio event per sound (2.2 made a new one per cue and never freed it), and both are freed
    # when the script unloads
    assert g.audio.made <= 2 < len(r["sounds"]), (g.audio.made, len(r["sounds"]))
    g.audio.release()
    assert g.audio.disposed == g.audio.made, (g.audio.disposed, g.audio.made)

# the ghost drives the same lap: it sits on your car
pos, gap, d, vis, _ = r["snap"]["ghost"]
x, z = np.interp(d, p["d"], p["x"]), np.interp(d, p["d"], p["z"])
assert vis and abs(gap) < 3 and np.hypot(pos[0] - x, pos[2] - z) < 3, (gap, pos, x, z)
assert abs(pos[1] - 0.45) < 0.05, "ghost at your car's height above the road"

# racing line, 1 s before Roggia's board at the reference speed: green, yellow for the countdown, red from the board
roggia = next(c for c in corners if c["name"] == "Roggia")
T0 = t_at(roggia["brake"]) - 1.0
T, d, cols = min(r["frames"], key=lambda f: abs(f[0] - T0))
ahead_ix = np.nonzero((p["d"] >= d) & (p["d"] < d + 600))[0]
where = lambda q: float(p["d"][ahead_ix[np.argmin(np.hypot(p["x"][ahead_ix] - q[0], p["z"][ahead_ix] - q[1]))]])
red = next(j for j, q in enumerate(cols) if q[2] < 0.3)
d_red = where(cols[red])
assert abs(d_red - roggia["brake"]) < 6, (d_red, roggia["brake"])
assert any(0.7 < q[2] < 0.9 for q in cols[:red]), "yellow before the board"
assert cols[0][2] > 0.9, "green right in front of the car"
assert where(cols[-1]) - d > 180, f"the line reaches {where(cols[-1]) - d:.0f} m ahead"
print(f"racing line turns red {d_red - roggia['brake']:+.1f} m from Roggia's brake point")

# 10% faster: the boards stay where the best lap braked, and the countdown is timed from your speed
r = drive(1.1, 60, until=p["t"][-1] * 0.6)
brakes = [s for s in r["sounds"] if s[1].endswith("brake.wav")]
checked = 0
for k, c in enumerate(corners):
    if c["kind"] != 1 or k not in r["at"] or c["brake"] < 100:
        continue
    assert r["at"][k] == {round(c["brake"], 3)}, (c["name"], r["at"][k], c["brake"])
    tb = t_at(c["brake"]) / 1.1
    if tb > p["t"][-1] * 0.6 / 1.1 - 1:
        continue   # past the end of this shorter run
    assert min(abs(s[0] - tb) for s in brakes) <= 0.5 / 60 + 0.002, c["name"]
    checked += 1
assert checked >= 2, checked
pos, gap, d, vis, _ = r["snap"]["ghost"]
assert gap < -50, f"10% faster: the ghost should be well behind ({gap:.0f} m)"
assert any(t.decode().startswith("BRAKE") for t in r["text"])
assert g.drawn.posts and g.drawn.posts > 1000, "an upright board at each corner"
assert g.ghost.drawn and g.ghost.drawn > 1000, "the ghost silhouette is drawn when it's away from your car"
# corners only: on the straight after the line (no corner within the 250 m drawn) nothing is drawn; full draws it all
m = lua.eval("require('coach')")


def count_at(dist):
    cs = g.carState
    cs.splinePosition, cs.lapTimeMs = dist / p["L"], int(t_at(dist) * 1000)
    cs.speedKmh = float(np.interp(dist, p["d"], p["speed"]))
    m.update(1 / 60, 9999.0)
    lua.execute("drawn.line = {}")
    g.drawFn()
    return len(list(g.drawn.line.values()))


straight = float(min(c["brake"] for c in corners if c["brake"] > 400)) - 450   # 450 m before the first board
full = count_at(straight)
m.cfg.cornersOnly = True
part = count_at(straight)
m.cfg.cornersOnly = False
assert full > 60 and part == 0, (full, part)
print(f"10% faster: {checked} boards stayed put, countdown on time, ghost {gap:.0f} m behind")

# 10% faster, the racing line turns red earlier than the board: where the best lap's braking from your speed starts
roggia = next(c for c in corners if c["name"] == "Roggia")
T0 = t_at(roggia["brake"]) / 1.1 - 1.5
T, d, cols = min(r["frames"], key=lambda f: abs(f[0] - T0))
ahead_ix = np.nonzero((p["d"] >= d) & (p["d"] < d + 600))[0]
where = lambda q: float(p["d"][ahead_ix[np.argmin(np.hypot(p["x"][ahead_ix] - q[0], p["z"][ahead_ix] - q[1]))]])
red = next(j for j, q in enumerate(cols) if q[2] < 0.3)
vp, vmin = 1.1 * roggia["speed"] / 3.6, roggia["min"] / 3.6
want = roggia["apex"] - min(max((vp * vp - vmin * vmin) / (2 * roggia["decel"]), 5), roggia["apex"] - roggia["brake"] + 150)
assert want < roggia["brake"] - 10 and abs(where(cols[red]) - want) < 8, (where(cols[red]), want, roggia["brake"])
print(f"10% faster: the line turns red {roggia['brake'] - where(cols[red]):.0f} m before the board (expected {roggia['brake'] - want:.0f})")

# ghost of your own session best: nothing on the first lap, then it drives your lap
r = drive(1.0, 30, laps=2, mine=True)
assert not r["snap"]["ghost"][3] and "waiting" in r["snap"]["ghost"][4], r["snap"]["ghost"]
pos, gap, d, vis, status = r["snap"]["ghost1"]
assert vis and abs(gap) < 3, (gap, status)
print(f"session-best ghost: off on lap 1, {gap:+.1f} m from you on lap 2 ({status})")
print("coach ok, window:", g.lastText.decode())
