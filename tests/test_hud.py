"""The dash (ac_app/GhostlineLogger/hud.lua) under real LuaJIT, via lupa, with a fake CSP UI that records every draw
call: every panel must draw without errors in normal and awkward states, and the gaps between cars must be right.
With --png DIR it also renders each panel to a PNG (Pillow, the real fonts) to check the design outside the game.
Offline; needs `pip install lupa` (skipped without it)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "ac_app" / "GhostlineLogger"
try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    print("skipped: pip install lupa")
    sys.exit(0)

from PIL import ImageFont  # noqa: E402

_fonts = {}


def measure(font, s, size):
    """Text width with the real font, so right-aligned numbers land where they will in the game."""
    key = (font, int(round(size)))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(font.decode() if isinstance(font, bytes) else font, max(1, key[1]))
    return _fonts[key].getlength(s.decode() if isinstance(s, bytes) else s)


lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
lua.globals().pyMeasure = measure
lua.execute(r"""
package.path = '%s/?.lua;' .. package.path
__dirname = '%s'
local V2 = {}; V2.__index = V2
V2.__add = function (a, b) return vec2(a.x + b.x, a.y + b.y) end
V2.__sub = function (a, b) return vec2(a.x - b.x, a.y - b.y) end
function vec2(x, y) return setmetatable({ x = x or 0, y = y or 0 }, V2) end
function rgbm(r, g, b, m) return { r = r, g = g, b = b, mult = m } end
calls, store = {}, {}
local function rec(t) calls[#calls + 1] = t end
local function col(c) return { c.r, c.g, c.b, c.mult } end
local cursor = vec2(0, 0)
local path, font = {}, ''
ui = {
  Alignment = { Start = -1, Center = 0, End = 1 },
  getCursor = function () return vec2(cursor.x, cursor.y) end,
  dummy = function (s) rec({ 'size', s.x, s.y }) end,
  pathClear = function () path = {} end,
  pathLineTo = function (p) path[#path + 1] = { p.x, p.y } end,
  pathFillConvex = function (c) rec({ 'poly', path, col(c) }) path = {} end,
  pathStroke = function (c, closed, w) rec({ 'polyline', path, col(c), w }) path = {} end,
  drawRectFilled = function (a, b, c) rec({ 'rect', a.x, a.y, b.x, b.y, col(c) }) end,
  drawQuadFilled = function (a, b, c, d, cl) rec({ 'poly', { { a.x, a.y }, { b.x, b.y }, { c.x, c.y }, { d.x, d.y } }, col(cl) }) end,
  drawLine = function (a, b, c, w) rec({ 'line', a.x, a.y, b.x, b.y, col(c), w }) end,
  pushDWriteFont = function (f) font = f end,
  popDWriteFont = function () end,
  measureDWriteText = function (s, size) return vec2(pyMeasure(font, s, size), size) end,
  dwriteDrawText = function (s, size, p, c) rec({ 'text', s, size, p.x, p.y, col(c), font }) end,
  dwriteDrawTextClipped = function (s, size, a, b, h, v, wrap, c) rec({ 'text', s, size, a.x, a.y, col(c), font, b.x - a.x }) end,
  windowHovered = function () return clickNext end,
  mouseClicked = function () local c = clickNext; clickNext = false; return c end,
  separator = function () end, text = function (s) lastText = s end,
  slider = function (l, v) return v, false end,
}
ac = {
  storage = function (layout) return layout end,
  SessionType = { Practice = 1, Qualify = 2, Race = 3 },
  getSim = function () return sim end,
  getCar = function (i) return cars[i] end,
  getDriverName = function (i) return names[i] end,
}
local function wheel(core, opt)
  return { tyreCoreTemperature = core, tyreInsideTemperature = core + 6, tyreMiddleTemperature = core + 2,
           tyreOutsideTemperature = core - 4, tyreOptimumTemperature = opt, tyrePressure = 27.4, tyreWear = 0.07,
           discTemperature = 410 }
end
local ffi = require('ffi')
ffi.cdef 'typedef struct { int32_t v[8]; int n; } fake_splits;'
local Splits = ffi.metatype('fake_splits', { __index = function (s, k) return s.v[k] end, __len = function (s) return s.n end })
function splits(t) local s = Splits(); s.n = #t; for k = 1, #t do s.v[k - 1] = t[k] end return s end
function makeCar(i, spline, laps)
  return { splinePosition = spline, lapCount = laps, isConnected = true, isInPitlane = false, racePosition = i + 1,
    speedKmh = 247.3, rpm = 7350, rpmLimiter = 7600, gear = 5, gas = 0.92, brake = 0, clutch = 0, steer = -38,
    absMode = 3, tractionControlMode = 2, absInAction = false, tractionControlInAction = false, brakeBias = 0.575,
    lapTimeMs = 63412, previousLapTimeMs = 110204 + i * 400, bestLapTimeMs = 109876 + i * 300, isLapValid = true,
    performanceMeter = -0.214, estimatedLapTimeMs = 109662, fuel = 23.4, fuelPerLap = 3.8,
    currentSplits = splits({ 31012, 32511 }), bestSplits = splits({ 31204, 32300, 46100 }), currentSector = 2,
    wheels = { [0] = wheel(84, 85), wheel(88, 85), wheel(72, 85), wheel(97, 85) } }
end
sim = { carsCount = 8, sessionTimeLeft = 1394000, raceSessionType = 1, ambientTemperature = 24, roadTemperature = 31 }
cars, names = {}, {}
local drivers = { 'pr1tzy', 'Max Lindqvist', 'Joao Pereira-Santos', 'A. Kowalczyk', 'Haruto Sato', 'Lena Fischer', 'Tom Okafor', 'Ines Duarte' }
for i = 0, 7 do cars[i] = makeCar(i, 0.5, 4) names[i] = drivers[i + 1] end
hud = require('hud')
hud.setCoach({ info = function () return ghostInfo end })
ghostInfo = { lapMs = 109876, driver = 'Max Lindqvist', est = true, delta = -0.214, brake = 0.35, throttle = 0.0 }
""" % (str(APP).replace("\\", "/"), str(APP).replace("\\", "/")))
g = lua.globals()
PANELS = ("gear", "delta", "timing", "pedals", "tyres", "standings")


def run(name):
    g.calls = lua.table()
    lua.eval(f"hud.{name}")()
    out = [list(c.values()) for c in g.calls.values()]
    return out


def texts(calls):
    return [c[1].decode() if isinstance(c[1], bytes) else c[1] for c in calls if c[0] == b"text"]


# ---- gaps: cars lapping at different speeds; relative gaps must match distance / speed ----
L, speeds = 5793.0, [70 + k * 0.6 for k in range(8)]
t, dt = 0.0, 1 / 60
start = [0.50, 0.53, 0.47, 0.60, 0.40, 0.56, 0.44, 0.35]
for step in range(60 * 130):   # a bit over a lap
    t += dt
    lua.execute("ghostInfo.delta = %f" % (-0.2 + 0.1 * math.sin(t)))
    for i in range(8):
        d = start[i] * L + speeds[i] * t
        c = g.cars[i]
        c.splinePosition, c.lapCount = (d / L) % 1, int(d // L)
    g.hud.update(dt)
rel = run("standings")
row_text = texts(rel)
assert "RELATIVE" in row_text and "pr1tzy" in row_text, row_text[:12]
me = start[0] * L + speeds[0] * t
checked = 0
for i in range(1, 8):
    other = start[i] * L + speeds[i] * t
    ds = ((other - me) / L + 0.5) % 1 - 0.5
    if abs(ds) > 0.25:
        continue
    # car i ahead by ds*L metres: it was at my spot that many metres ago, at its own speed
    want = ds * L / speeds[i] if ds > 0 else ds * L / speeds[0]
    name = g.names[i].decode() if isinstance(g.names[i], bytes) else g.names[i]
    if name not in row_text:
        continue   # outside the rows shown
    k = row_text.index(name)
    gap = float(next(s for s in row_text[k:] if s[:1] in "+-" and "." in s and ":" not in s))
    assert abs(gap - want) < 0.15, (name, gap, want)
    checked = checked + 1
assert checked >= 4, checked
print(f"relative gaps match distance / speed ({checked} cars)")

# ---- every panel, in normal and awkward states ----
for name in PANELS:
    calls = run(name)
    assert calls and calls[0][0] == b"size", name
gear_t = texts(run("gear"))
assert "5" in gear_t and "247" in gear_t and "ABS 3" in gear_t and "TC 2" in gear_t, gear_t
delta_t = texts(run("delta"))
assert any(s.startswith("VS BEST LAP") for s in delta_t), delta_t
timing_t = texts(run("timing"))
assert "31.012" in timing_t and "S3" in timing_t and "GHOST" in timing_t, timing_t
lua.execute("""
ghostInfo = nil
local c = cars[0]
c.gear, c.rpm, c.isLapValid, c.isInPitlane, c.fuelPerLap, c.bestLapTimeMs = -1, 900, false, true, 0, 0
c.currentSplits, c.bestSplits, c.absMode, c.tractionControlMode, c.brakeBias = splits({}), splits({}), 0, 0, 0
c.wheels[2] = nil
sim.sessionTimeLeft, sim.raceSessionType = 0, 3
""")
for name in PANELS:
    run(name)
assert "R" in texts(run("gear")) and "INVALID" in texts(run("timing"))
g.clickNext = True
run("standings")
assert "STANDINGS" in texts(run("standings")), "click switches relative / full order"
lua.execute("hud.cfg.board = false; clickNext = false")
print("all panels draw in normal and awkward states")

# ---- optional: render each panel to a PNG to review the design ----
if "--png" in sys.argv:
    from PIL import Image, ImageDraw
    out = Path(sys.argv[sys.argv.index("--png") + 1])
    out.mkdir(parents=True, exist_ok=True)
    lua.execute("""
    ghostInfo = { lapMs = 109876, driver = 'Max Lindqvist', est = true, delta = -0.214, brake = 0.35, throttle = 0.0 }
    for i = 0, 7 do cars[i] = makeCar(i, cars[i].splinePosition, cars[i].lapCount) end
    cars[0].brake, cars[0].gas = 0.62, 0.0
    cars[3].isInPitlane = true
    sim.sessionTimeLeft, sim.raceSessionType = 1394000, 1
    hud.cfg.scale = 2
    """)
    fonts = {}
    rgba = lambda c: tuple(int(round(min(max(x, 0), 1) * 255)) for x in (c[0], c[1], c[2], c[3] if len(c) > 3 else 1))
    sheet = []
    for name in PANELS:
        calls = run(name)
        w, h = int(calls[0][1]), int(calls[0][2])
        img = Image.new("RGB", (w + 40, h + 40), (60, 66, 58))   # a grey-green, like a track backdrop
        dr = ImageDraw.Draw(img, "RGBA")
        o = 20
        for c in calls[1:]:
            kind = c[0].decode()
            if kind == "poly":
                pts = [(p[0] + o, p[1] + o) for p in (list(q.values()) for q in c[1].values())]
                dr.polygon(pts, fill=rgba(list(c[2].values())))
            elif kind == "polyline":
                pts = [(p[0] + o, p[1] + o) for p in (list(q.values()) for q in c[1].values())]
                dr.line(pts + pts[:1], fill=rgba(list(c[2].values())), width=1)
            elif kind == "rect":
                dr.rectangle([c[1] + o, c[2] + o, c[3] + o - 1, c[4] + o - 1], fill=rgba(list(c[5].values())))
            elif kind == "line":
                dr.line([c[1] + o, c[2] + o, c[3] + o, c[4] + o], fill=rgba(list(c[5].values())), width=max(1, int(round(c[6]))))
            elif kind == "text":
                s, size, x, y, col, fpath = c[1].decode(), c[2], c[3], c[4], list(c[5].values()), c[6].decode()
                key = (fpath, int(size))
                if key not in fonts:
                    fonts[key] = ImageFont.truetype(fpath, int(size))
                f = fonts[key]
                if len(c) > 7:   # clipped
                    while s and f.getlength(s) > c[7]:
                        s = s[:-1]
                dr.text((x + o, y + o), s, font=f, fill=rgba(col), anchor="la")
        img.save(out / f"{name}.png")
        sheet.append(img)
    W = max(i.width for i in sheet)
    Hs = sum(i.height for i in sheet)
    full = Image.new("RGB", (W, Hs), (60, 66, 58))
    y = 0
    for i in sheet:
        full.paste(i, (0, y)); y += i.height
    full.save(out / "dash.png")
    print("previews:", out)
print("hud ok")
