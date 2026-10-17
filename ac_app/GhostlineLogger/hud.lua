-- Ghostline dash: one horizontal panel with standings, timing, gear + delta, pedals and tyres, each section switched
-- on or off in the Ghostline window (place the dash itself from the CSP app bar). Same look as the Ghostline site: solid near-black panels with cut corners and hairlines,
-- Grotesk Gras for the gear, Sligoil for numbers, Lack for labels. Violet is you, cyan is the ghost (the best lap
-- Ghostline sends), teal is time gained, pink is time lost. No icons: text and numbers only.

local H = {}
local coach = nil
function H.setCoach(c) coach = c end

local cfg = ac.storage({ scale = 1, opacity = 0.92, deltaRef = 'ghost', board = false, standings = true, timing = true,
  drive = true, pedals = true, tyres = true, map = true }, 'ghostline.hud.')
H.cfg = cfg

local function hex(r, g, b, a) return rgbm(r / 255, g / 255, b / 255, a or 1) end
local C = {
  bg = hex(11, 10, 15), bg2 = hex(21, 19, 28), fg = hex(239, 236, 244), mute = hex(138, 133, 151),
  line = hex(239, 236, 244, 0.10), line2 = hex(239, 236, 244, 0.22), soft = hex(239, 236, 244, 0.62),
  acc = hex(157, 107, 255), ghost = hex(62, 240, 255), gain = hex(66, 245, 200), loss = hex(255, 79, 129),
}
H.colors = C

-- race flags the game reports (CSP: yellow, blue, black, penalty and chequered work), in their real colours
local FLAGS = {}
if ac.FlagType then
  FLAGS[ac.FlagType.Caution] = { 'YELLOW FLAG', hex(255, 214, 10) }
  FLAGS[ac.FlagType.FasterCar] = { 'BLUE FLAG', hex(40, 120, 255) }
  FLAGS[ac.FlagType.Stop] = { 'BLACK FLAG', hex(239, 236, 244) }
  FLAGS[ac.FlagType.ReturnToPits] = { 'PENALTY', hex(255, 79, 129) }
  FLAGS[ac.FlagType.Finished] = { 'CHEQUERED FLAG', hex(239, 236, 244) }
end
local function flagNow()
  local sim = ac.getSim()
  return sim and sim.raceFlagType and FLAGS[sim.raceFlagType] or nil
end
local panelBg = rgbm(C.bg.r, C.bg.g, C.bg.b, 1)

local dir = (__dirname or '.') .. '/fonts/'
local F = { head = dir .. 'Grotesk-Gras.ttf', num = dir .. 'Sligoil-Micro.ttf', numB = dir .. 'Sligoil-MicroBold.ttf',
            text = dir .. 'Lack-Regular.ttf' }

-- ---------- drawing helpers: everything in panel units, multiplied by the HUD scale ----------
local S, ox, oy = 1, 0, 0
local DASH_H, DRIVE_W = 188, 300
local function v(x, y) return vec2(ox + x * S, oy + y * S) end

-- the dash's background: one solid slab with cut corners and a hairline edge
local function slab(w, h)
  panelBg.mult = cfg.opacity or 0.92
  local cut = 12
  ui.pathClear()
  ui.pathLineTo(v(0, 0)); ui.pathLineTo(v(w - cut, 0)); ui.pathLineTo(v(w, cut))
  ui.pathLineTo(v(w, h)); ui.pathLineTo(v(cut, h)); ui.pathLineTo(v(0, h - cut))
  ui.pathFillConvex(panelBg)
  ui.pathClear()
  ui.pathLineTo(v(0, 0)); ui.pathLineTo(v(w - cut, 0)); ui.pathLineTo(v(w, cut))
  ui.pathLineTo(v(w, h)); ui.pathLineTo(v(cut, h)); ui.pathLineTo(v(0, h - cut))
  ui.pathStroke(C.line, true, 1)
end

-- text at (x, y) = top left; align 1 puts the right edge at x, 0.5 centres it
local function text(font, s, size, x, y, color, align)
  ui.pushDWriteFont(font)
  local px = size * S
  local p = v(x, y)
  if align and align > 0 then p.x = p.x - ui.measureDWriteText(s, px).x * align end
  ui.dwriteDrawText(s, px, p, color)
  ui.popDWriteFont()
end

local function clipText(font, s, size, x, y, w, color)
  ui.pushDWriteFont(font)
  ui.dwriteDrawTextClipped(s, size * S, v(x, y), v(x + w, y + size * 1.4), ui.Alignment.Start, ui.Alignment.Start, false, color)
  ui.popDWriteFont()
end

local function rect(x0, y0, x1, y1, color) ui.drawRectFilled(v(x0, y0), v(x1, y1), color) end
local function hline(x0, x1, y, color) ui.drawLine(v(x0, y), v(x1, y), color, math.max(1, S)) end
local function vline(x, y0, y1, color, w) ui.drawLine(v(x, y0), v(x, y1), color, (w or 1) * math.max(1, S)) end

local function mix(a, b, t)
  t = math.min(math.max(t, 0), 1)
  return rgbm(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, a.mult + (b.mult - a.mult) * t)
end

local function laptime(ms)
  if not ms or ms <= 0 then return '-:--.---' end
  return string.format('%d:%06.3f', math.floor(ms / 60000), (ms % 60000) / 1000)
end

local function clock(sec)
  if not sec or sec <= 0 then return '--:--' end
  local h = math.floor(sec / 3600)
  if h > 0 then return string.format('%d:%02d:%02d', h, math.floor(sec % 3600 / 60), math.floor(sec % 60)) end
  return string.format('%d:%02d', math.floor(sec / 60), math.floor(sec % 60))
end

local blink = 0
local function flash(hz) return math.floor(blink * hz) % 2 == 0 end

-- ---------- per-frame bookkeeping (from script.update): pedal trace, delta trend, gaps ----------
local TRACE = 240                  -- samples, about 4 s at 60 fps
local trace = { thr = {}, brk = {}, n = 0 }
local deltaHist, deltaPrev, deltaAt = 0, nil, 0
local CP = 200                     -- checkpoints per lap for the gaps between cars
local pass = {}                    -- per car: last two passes of every checkpoint { t0, t1, lap0, lap1, cp }
local maxRpm = {}
local now = 0

local function passTimes(i, c)
  local p = pass[i]
  if not p then p = { t1 = {}, l1 = {}, t0 = {}, l0 = {}, cp = -1 }; pass[i] = p end
  return p
end

local function record(i, c, s)
  local p = passTimes(i)
  local cp = math.floor(s * CP) % CP
  if cp == p.cp then return end
  local lap = c.lapCount
  local steps = (cp - p.cp) % CP
  if p.cp < 0 or steps > 20 then steps = 1 end       -- first sample, or a jump (pits, reset): no filling in
  for k = steps - 1, 0, -1 do
    local q = (cp - k) % CP
    p.t0[q], p.l0[q] = p.t1[q], p.l1[q]
    p.t1[q], p.l1[q] = now, lap
  end
  p.cp = cp
end

-- when car i passed position s on lap `lap` (or its latest pass if lap is nil), interpolated between checkpoints
local function timeAt(i, s, lap)
  local p = pass[i]
  if not p then return nil end
  local f = (s % 1) * CP
  local a = math.floor(f) % CP
  local t
  if lap == nil or p.l1[a] == lap then t = p.t1[a] elseif p.l0[a] == lap then t = p.t0[a] end
  if not t then return nil end
  local b = (a + 1) % CP
  local tb = (lap == nil or p.l1[b] == lap) and p.t1[b] or p.l0[b] == lap and p.t0[b] or nil
  if tb and tb > t and tb - t < 5 then t = t + (tb - t) * (f - math.floor(f)) end
  return t
end

function H.update(dt)
  now, blink = now + dt, blink + dt
  local car = ac.getCar(0)
  if not car then return end
  trace.n = trace.n % TRACE + 1
  trace.thr[trace.n], trace.brk[trace.n] = car.gas, car.brake
  local sim = ac.getSim()
  for i = 0, math.min(sim.carsCount, 64) - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected ~= false then record(i, c, c.splinePosition) end
  end
  if now - deltaAt >= 1 then deltaPrev, deltaAt = deltaHist, now end
end

local function deltaNow(car)
  local info = coach and coach.info and coach.info()
  if cfg.deltaRef == 'ghost' and info and info.delta then
    return info.delta, 'VS BEST LAP  ' .. info.driver:upper(), info.lapMs + info.delta * 1000
  end
  if car.bestLapTimeMs > 0 then
    return car.performanceMeter, 'VS SESSION BEST', car.estimatedLapTimeMs
  end
  return nil, info and 'VS BEST LAP' or 'VS SESSION BEST', nil
end

-- a click inside the current section (w x h from its origin) switches a setting
local function clickToggle(key, a, b, w, h)
  if ui.rectHovered(v(0, 0), v(w, h)) and ui.mouseClicked() then cfg[key] = cfg[key] == a and b or a end
end

-- ---------- Gear: segmented rev bar, gear, speed, assists ----------
local function gearBody()
  local car = ac.getCar(0)
  if not car then return end
  local W, Hh = DRIVE_W, 118
  local id = 0
  maxRpm[id] = math.max(maxRpm[id] or 0, car.rpm)
  local lim = car.rpmLimiter and car.rpmLimiter > 1000 and car.rpmLimiter or math.max(maxRpm[id], 3000)
  local N, x0, x1, y0, y1, gap = 20, 14, W - 14, 14, 25, 2.5
  local seg = (x1 - x0 - gap * (N - 1)) / N
  local frac = car.rpm / lim
  local shift = frac >= 0.975
  for i = 0, N - 1 do
    local at = 0.55 + 0.45 * (i + 1) / N               -- the bar covers the top 45 % of the revs
    local lit = frac >= at
    local c = not lit and C.line2 or shift and (flash(10) and C.ghost or C.line2) or
      (i < N * 0.65 and C.soft or i < N * 0.85 and C.acc or C.loss)
    local xa = x0 + i * (seg + gap)
    ui.drawQuadFilled(v(xa + 3, y0), v(xa + seg + 3, y0), v(xa + seg, y1), v(xa, y1), c)   -- slanted segments
  end
  local g = car.gear
  local gs = g < 0 and 'R' or g == 0 and 'N' or tostring(g)
  text(F.head, gs, 66, 12, 26, shift and C.ghost or C.fg)
  text(F.numB, string.format('%d', math.floor(car.speedKmh + 0.5)), 36, W - 14, 30, C.fg, 1)
  text(F.text, 'KM/H', 10, W - 14, 72, C.mute, 1)
  text(F.num, string.format('%d RPM', math.floor(car.rpm / 10 + 0.5) * 10), 11, W - 14, 86, C.mute, 1)
  local x = 14
  local function tag(label, on, active, col)
    local c = not on and C.line2 or active and col or C.mute
    text(F.text, label, 11, x, 98, c)
    ui.pushDWriteFont(F.text)
    x = x + ui.measureDWriteText(label, 11 * S).x / S + 12
    ui.popDWriteFont()
  end
  tag(car.absMode and car.absMode > 0 and ('ABS ' .. car.absMode) or 'ABS OFF', (car.absMode or 0) > 0, car.absInAction, C.loss)
  tag(car.tractionControlMode and car.tractionControlMode > 0 and ('TC ' .. car.tractionControlMode) or 'TC OFF',
    (car.tractionControlMode or 0) > 0, car.tractionControlInAction, C.ghost)
  if car.brakeBias and car.brakeBias > 0.05 then tag(string.format('BB %.1f', car.brakeBias * 100), true, false, C.fg) end
  if car.drsAvailable or car.drsActive then tag('DRS', true, car.drsActive, C.gain) end
  if car.manualPitsSpeedLimiterEnabled or car.speedLimiterInAction then tag('LIMITER', true, true, C.gain) end
end

-- ---------- Delta: gap to the best lap (or session best) right now ----------
local function deltaBody()
  local car = ac.getCar(0)
  if not car then return end
  local W, Hh = DRIVE_W, 60
  clickToggle('deltaRef', 'ghost', 'session', W, Hh)
  local d, label, pred = deltaNow(car)
  deltaHist = d or 0
  local col = not d and C.mute or d <= 0 and C.gain or C.loss
  text(F.numB, d and string.format('%+.3f', d) or '-.---', 30, 14, 8, col)
  text(F.text, label, 10, 14, 43, C.mute)
  local bx0, bx1, by0, by1 = 150, W - 14, 16, 30
  local xc = (bx0 + bx1) / 2
  local half = (bx1 - bx0) / 2
  rect(bx0, by0, bx1, by1, C.bg2)
  if d then
    local w = math.min(math.abs(d), 1) * half
    if d <= 0 then rect(xc - w, by0, xc, by1, C.gain) else rect(xc, by0, xc + w, by1, C.loss) end
    if deltaPrev then vline(xc + math.min(math.max(deltaPrev, -1), 1) * half, by0 - 3, by1 + 3, C.fg) end   -- a second ago
  end
  for q = -3, 3 do if q ~= 0 then vline(xc + q * half / 4, by1, by1 + 3, C.line2) end end   -- every 0.25 s
  vline(xc, by0 - 5, by1 + 5, C.line2)
  if pred then text(F.num, 'PRED ' .. laptime(pred), 11, bx1, 40, C.fg, 1) end
end

-- ---------- Timing: lap, sectors, last / best / ghost, fuel, session ----------
local function timingBody()
  local car = ac.getCar(0)
  if not car then return end
  local sim = ac.getSim()
  local W, Hh = 290, 164
  local flag = flagNow()
  if flag and flash(2) then text(F.text, flag[1], 10, 14, 12, flag[2])
  else text(F.text, 'LAP ' .. (car.lapCount + 1), 10, 14, 12, flag and flag[2] or C.mute) end
  local n = sim.carsCount
  if n > 1 and car.racePosition and car.racePosition > 0 then
    local tot = '/' .. n
    ui.pushDWriteFont(F.num)
    local tw = ui.measureDWriteText(tot, 11 * S).x / S
    ui.popDWriteFont()
    text(F.numB, 'P' .. car.racePosition, 14, W - 16 - tw, 9, C.acc, 1)
    text(F.num, tot, 11, W - 14, 12, C.mute, 1)
  end
  local valid = car.isLapValid ~= false
  text(F.numB, laptime(car.lapTimeMs), 30, 14, 26, valid and C.fg or C.mute)
  if not valid then text(F.text, 'INVALID', 10, W - 14, 40, C.loss, 1) end
  -- sectors of this lap: teal when faster than your best sector, pink when slower
  local ns = car.bestSplits and #car.bestSplits or 0
  if ns <= 0 then ns = 3 end
  local x0, x1, y = 14, W - 14, 70
  local cw = (x1 - x0 - 4 * (ns - 1)) / ns
  local done = car.currentSplits and #car.currentSplits or 0
  for k = 0, ns - 1 do
    local cx = x0 + k * (cw + 4)
    rect(cx, y, cx + cw, y + 22, C.bg2)
    local t = k < done and car.currentSplits[k] or nil
    local best = car.bestSplits and car.bestSplits[k] or 0
    if t and t > 0 then
      local c = (best <= 0 or t <= best) and C.gain or C.loss
      hline(cx, cx + cw, y, c)
      text(F.num, string.format('%.3f', t / 1000), 11, cx + cw / 2, y + 5, C.fg, 0.5)
    else
      local cur = k == (car.currentSector or 0)
      if cur then hline(cx, cx + cw, y, C.line2) end
      text(F.text, 'S' .. (k + 1), 10, cx + cw / 2, y + 5, cur and C.fg or C.mute, 0.5)
    end
  end
  local info = coach and coach.info and coach.info()
  local cols = { { 'LAST', car.previousLapTimeMs, C.fg }, { 'BEST', car.bestLapTimeMs, C.acc } }
  if info then cols[3] = { 'GHOST', info.lapMs, C.ghost } end
  local colW = (W - 28) / 3
  for k, c in ipairs(cols) do
    local cx = 14 + (k - 1) * colW
    text(F.text, c[1], 9, cx, 102, C.mute)
    local col = c[3]
    if k == 1 and car.previousLapTimeMs > 0 and car.bestLapTimeMs > 0 then
      col = car.previousLapTimeMs <= car.bestLapTimeMs and C.gain or C.fg
    end
    text(F.num, laptime(c[2]), 13, cx, 114, col)
  end
  hline(14, W - 14, 136, C.line)
  local fuel = car.fuel or 0
  local fl = string.format('FUEL %.1f L', fuel)
  if car.fuelPerLap and car.fuelPerLap > 0.01 then fl = fl .. string.format('   %.1f LAPS', fuel / car.fuelPerLap) end
  text(F.num, fl, 10, 14, 143, C.fg)
  local left = sim.sessionTimeLeft and sim.sessionTimeLeft / 1000 or 0
  -- in a race: fuel left over at the flag (laps to go x fuel per lap), else the session clock if Standings is off
  local spare = H.fuelSpare(car, sim)
  if spare then text(F.num, string.format('%+.1f L AT FLAG', spare), 10, W - 14, 143, spare >= 0 and C.gain or C.loss, 1)
  elseif left > 0 and not cfg.standings then text(F.num, clock(left), 10, W - 14, 143, C.mute, 1) end
end

-- ---------- Pedals: clutch / brake / throttle with the ghost's pedals where you are, trace, steering ----------
local function pedalsBody()
  local car = ac.getCar(0)
  if not car then return end
  local W, Hh = 220, 132
  local info = coach and coach.info and coach.info()
  local top, bot = 14, 142
  local function bar(x, val, col, label, ghostVal, hot)
    rect(x, top, x + 18, bot, C.bg2)
    local h = (bot - top) * math.min(math.max(val, 0), 1)
    if h > 0.5 then rect(x, bot - h, x + 18, bot, hot and flash(12) and C.fg or col) end
    if ghostVal then
      local gy = bot - (bot - top) * math.min(math.max(ghostVal, 0), 1)
      ui.drawLine(v(x - 3, gy), v(x + 21, gy), C.ghost, 2 * math.max(1, S))
    end
    text(F.text, label, 10, x + 9, bot + 6, C.mute, 0.5)
  end
  bar(14, car.clutch, C.mute, 'C')
  bar(40, car.brake, C.loss, 'B', info and info.brake, car.absInAction)
  bar(66, car.gas, C.gain, 'T', info and info.throttle, car.tractionControlInAction)
  -- the last ~4 seconds
  local tx0, tx1 = 100, W - 14
  rect(tx0, top, tx1, bot, C.bg2)
  hline(tx0, tx1, top + (bot - top) / 2, C.line)
  local function line(arr, col)
    local prev
    for k = 0, TRACE - 1 do
      local idx = (trace.n - k - 1) % TRACE + 1
      local val = arr[idx]
      if val == nil then break end
      local p = v(tx1 - (tx1 - tx0) * k / (TRACE - 1), bot - (bot - top) * math.min(math.max(val, 0), 1))
      if prev then ui.drawLine(prev, p, col, 1.5 * math.max(1, S)) end
      prev = p
    end
  end
  line(trace.thr, C.gain)
  line(trace.brk, C.loss)
  -- steering: a marker on a hairline, plus the angle
  local sy = bot + 14
  hline(tx0, tx1, sy, C.line2)
  local st = math.min(math.max((car.steer or 0) / 450, -1), 1)
  local sx = (tx0 + tx1) / 2 + st * (tx1 - tx0) / 2
  rect(sx - 2, sy - 5, sx + 2, sy + 5, C.fg)
  vline((tx0 + tx1) / 2, sy - 3, sy + 3, C.line2)
  text(F.num, string.format('%d', math.floor((car.steer or 0) + 0.5)), 9, tx1, sy + 3, C.mute, 1)
end

-- ---------- Tyres: inside / middle / outside temperature against the tyre's optimum, core, pressure, wear, brakes ----------
local function tyreColour(t, opt)
  if not t or t <= 0 then return C.line2 end
  opt = (opt and opt > 20) and opt or 85
  local d = t - opt
  if d < -12 then return C.ghost end      -- cold
  if d <= 6 then return C.gain end        -- in the window
  if d <= 15 then return C.fg end         -- warm
  return C.loss                           -- hot
end

local function tyresBody()
  local car = ac.getCar(0)
  if not car or not car.wheels then return end
  local sim = ac.getSim()
  local W, Hh = 236, 184
  local compound = ''
  pcall(function () compound = ac.getTyresName(0, car.compoundIndex or 0) or '' end)
  clipText(F.text, compound ~= '' and compound:upper() or 'TYRES', 10, 14, 12, 110, C.mute)
  local dmg = 0
  if car.damage then for z = 0, 3 do dmg = math.max(dmg, car.damage[z] or 0) end end
  if dmg >= 5 then
    text(F.num, string.format('DAMAGE %d', math.floor(dmg + 0.5)), 10, W - 14, 12, C.loss, 1)   -- hardest hit, km/h
  elseif sim.ambientTemperature then
    text(F.num, string.format('AIR %d  TRACK %d', math.floor(sim.ambientTemperature + 0.5), math.floor((sim.roadTemperature or 0) + 0.5)), 10, W - 14, 12, C.mute, 1)
  end
  local spots = { [0] = { 14, 32, false }, { W - 14 - 30, 32, true }, { 14, 108, false }, { W - 14 - 30, 108, true } }
  for i = 0, 3 do
    local wl = car.wheels[i]
    if wl then
      local x, y, right = spots[i][1], spots[i][2], spots[i][3]
      local opt = wl.tyreOptimumTemperature
      -- three strips, inside towards the middle of the car
      local strips = right and { wl.tyreInsideTemperature, wl.tyreMiddleTemperature, wl.tyreOutsideTemperature }
        or { wl.tyreOutsideTemperature, wl.tyreMiddleTemperature, wl.tyreInsideTemperature }
      for k = 1, 3 do rect(x + (k - 1) * 10, y, x + k * 10 - 1, y + 52, tyreColour(strips[k], opt)) end
      -- wear: what's left, under the tyre
      local left = 1 - math.min(math.max(wl.tyreWear or 0, 0), 1)
      rect(x, y + 56, x + 29, y + 59, C.bg2)
      rect(x, y + 56, x + 29 * left, y + 59, left > 0.9 and C.fg or left > 0.75 and C.acc or C.loss)
      -- numbers on the inner side
      local nx, al = right and x - 10 or x + 40, right and 1 or 0
      local core = wl.tyreCoreTemperature or 0
      text(F.numB, string.format('%d', math.floor(core + 0.5)), 18, nx, y - 1, tyreColour(core, opt), al)
      text(F.num, string.format('%.1f', wl.tyrePressure or 0), 11, nx, y + 22, C.fg, al)
      local disc = wl.discTemperature or 0
      if disc > 0 then text(F.num, string.format('BRK %d', math.floor(disc + 0.5)), 10, nx, y + 37, disc > 750 and C.loss or C.mute, al) end
    end
  end
end

-- ---------- Standings: cars around you on track (relative) or the full order; click to switch ----------
local function rowsRelative(sim, me, n)
  local out = {}
  for i = 0, math.min(sim.carsCount, 64) - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected ~= false then
      local ds = (c.splinePosition - me.splinePosition + 0.5) % 1 - 0.5   -- > 0: ahead of you on track
      local gap
      if i == 0 then gap = 0
      elseif ds > 0 then local t = timeAt(i, me.splinePosition) gap = t and (now - t) or nil
      else local t = timeAt(0, c.splinePosition) gap = t and -(now - t) or nil end
      local laps = (c.lapCount + c.splinePosition) - (me.lapCount + me.splinePosition)
      out[#out + 1] = { i = i, c = c, ds = ds, gap = gap, lapDiff = laps > 0.5 and 1 or laps < -0.5 and -1 or 0 }
    end
  end
  table.sort(out, function (a, b) return a.ds > b.ds end)
  local mine = 1
  for k, r in ipairs(out) do if r.i == 0 then mine = k end end
  local half = math.floor((n - 1) / 2)
  local from = math.max(1, math.min(mine - half, #out - n + 1))
  local rows = {}
  for k = from, math.min(#out, from + n - 1) do rows[#rows + 1] = out[k] end
  return rows
end

local function rowsBoard(sim, n)
  local out = {}
  for i = 0, math.min(sim.carsCount, 64) - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected ~= false then out[#out + 1] = { i = i, c = c } end
  end
  table.sort(out, function (a, b)
    local pa, pb = a.c.racePosition or 99, b.c.racePosition or 99
    if pa ~= pb then return pa < pb end
    return a.i < b.i
  end)
  local leader = out[1]
  local race = sim.raceSessionType == (ac.SessionType and ac.SessionType.Race or 3)
  for _, r in ipairs(out) do
    if r == leader then r.gap = nil
    elseif race then
      local laps = (leader.c.lapCount + leader.c.splinePosition) - (r.c.lapCount + r.c.splinePosition)
      if laps >= 1 then r.lapsDown = math.floor(laps)
      else local t = timeAt(leader.i, r.c.splinePosition, r.c.lapCount) r.gap = t and (now - t) or nil end
    elseif r.c.bestLapTimeMs > 0 and leader.c.bestLapTimeMs > 0 then
      r.gap = (r.c.bestLapTimeMs - leader.c.bestLapTimeMs) / 1000
    end
  end
  local mine = 1
  for k, r in ipairs(out) do if r.i == 0 then mine = k end end
  local rows = {}
  for k = 1, math.min(#out, n) do rows[#rows + 1] = out[k] end
  if mine > n then rows[n] = out[mine] end   -- always show yourself
  return rows
end

local function standingsBody()
  local me = ac.getCar(0)
  if not me then return end
  local sim = ac.getSim()
  local n = 7
  local W, Hh = 344, DASH_H
  clickToggle('board', true, false, W, Hh)
  text(F.text, cfg.board and 'STANDINGS' or 'RELATIVE', 10, 14, 12, C.mute)
  local left = sim.sessionTimeLeft and sim.sessionTimeLeft / 1000 or 0
  if left > 0 then text(F.num, clock(left), 10, W - 14, 12, C.mute, 1) end
  local info = coach and coach.info and coach.info()
  local rows = cfg.board and rowsBoard(sim, n) or rowsRelative(sim, me, n)
  for k, r in ipairs(rows) do
    local y = 30 + (k - 1) * 22
    local c, mine = r.c, r.i == 0
    if mine then rect(8, y - 2, W - 8, y + 18, C.bg2) end
    local name = ac.getDriverName(r.i) or ''
    local isGhost = info and info.driver ~= '' and name == info.driver      -- the driver whose lap is your ghost
    -- you: violet; the ghost's driver: cyan; a lap ahead of you: pink; a lap behind or in the pits: grey
    local nameCol = mine and C.acc or isGhost and C.ghost or c.isInPitlane and C.mute or r.lapDiff == 1 and C.loss
      or r.lapDiff == -1 and C.mute or C.fg
    text(F.numB, tostring(c.racePosition or ''), 12, 34, y + 1, mine and C.acc or C.fg, 1)
    clipText(F.text, name, 12, 44, y + 1, 150, nameCol)
    if c.isInPitlane then text(F.text, 'PIT', 10, 268, y + 3, C.mute, 1)
    else text(F.num, laptime(c.previousLapTimeMs), 10, 268, y + 3, C.mute, 1) end
    local gs, gc = '', C.fg
    if mine then gs = ''
    elseif r.lapsDown then gs, gc = '+' .. r.lapsDown .. 'L', C.mute
    elseif r.gap then gs = string.format('%+.1f', r.gap); gc = cfg.board and C.fg or (r.gap > 0 and C.loss or C.gain) end
    text(F.numB, gs, 12, W - 14, y + 1, gc, 1)
  end
end

-- ---------- the dash: sections side by side ----------
-- ---------- Map: the track with every car on it ----------
local trackPts, trackBox = nil, nil
local function buildTrack()
  local pts, x0, x1, z0, z1 = {}, 1e9, -1e9, 1e9, -1e9
  for i = 0, 199 do
    local p = ac.trackProgressToWorldCoordinate(i / 200)
    pts[#pts + 1] = { p.x, p.z }
    x0, x1, z0, z1 = math.min(x0, p.x), math.max(x1, p.x), math.min(z0, p.z), math.max(z1, p.z)
  end
  if x1 - x0 < 1 then return end
  trackPts, trackBox = pts, { x0, x1, z0, z1 }
end

local MAP_W = 200
local function mapBody()
  local W = MAP_W
  if not trackPts then buildTrack() end
  text(F.text, 'MAP', 10, 14, 12, C.mute)
  if not trackPts then return end
  local x0, x1, z0, z1 = trackBox[1], trackBox[2], trackBox[3], trackBox[4]
  local box, top = W - 28, 32
  local k = math.min(box / (x1 - x0), (DASH_H - top - 14) / (z1 - z0))
  local cx, cz = 14 + box / 2, top + (DASH_H - top - 14) / 2
  local mx, mz = (x0 + x1) / 2, (z0 + z1) / 2
  -- the same way round as the game's own track map (content/tracks/<track>/map.png): x to the right, z down
  local function at(x, z) return v(cx + (x - mx) * k, cz + (z - mz) * k) end
  ui.pathClear()
  for i = 1, #trackPts do ui.pathLineTo(at(trackPts[i][1], trackPts[i][2])) end
  ui.pathStroke(C.line2, true, 3 * math.max(1, S))   -- one closed path: clean joins
  local s0 = at(trackPts[1][1], trackPts[1][2])
  ui.drawCircleFilled(s0, 3 * S, C.fg, 8)            -- start / finish
  local sim = ac.getSim()
  for i = math.min(sim.carsCount, 64) - 1, 0, -1 do   -- you last, so you're drawn on top
    local c = ac.getCar(i)
    if c and c.isConnected ~= false then
      local col = i == 0 and C.acc or c.isInPitlane and C.mute or C.fg
      ui.drawCircleFilled(at(c.position.x, c.position.z), (i == 0 and 4.5 or 3) * S, col, 12)
    end
  end
  if coach and coach.ghostAt then
    local gx, gz = coach.ghostAt()
    if gx then ui.drawCircleFilled(at(gx, gz), 3.5 * S, C.ghost, 12) end
  end
end

local SECTIONS = {
  { key = 'standings', w = 344, draw = function () standingsBody() end },
  { key = 'timing', w = 290, draw = function () timingBody() end },
  { key = 'drive', w = DRIVE_W, draw = function ()   -- gear on top, delta under it
      gearBody()
      local y0 = oy
      oy = y0 + 122 * S
      hline(14, DRIVE_W - 14, -4, C.line)
      deltaBody()
      oy = y0
    end },
  { key = 'pedals', w = 220, draw = function () pedalsBody() end },
  { key = 'tyres', w = 236, draw = function () tyresBody() end },
  { key = 'map', w = MAP_W, draw = function () mapBody() end },
}

function H.dash()
  S = math.min(math.max(cfg.scale or 1, 0.5), 2.5)
  local c = ui.getCursor()
  local x0, y0 = c.x, c.y
  local total = 0
  for _, sec in ipairs(SECTIONS) do if cfg[sec.key] then total = total + sec.w end end
  if total == 0 then
    ui.text('Ghostline dash: every section is switched off (Ghostline window).')
    return
  end
  ui.dummy(vec2(total * S, DASH_H * S))   -- sizes the window (AUTO_RESIZE)
  ox, oy = x0, y0
  slab(total, DASH_H)
  local flag = flagNow()
  if flag then rect(12, 0, total - 12, 3, flag[2]) end
  local x = 0
  for _, sec in ipairs(SECTIONS) do
    if cfg[sec.key] then
      ox, oy = x0 + x * S, y0
      if x > 0 then vline(0, 14, DASH_H - 14, C.line) end   -- hairline between sections
      sec.draw()
      x = x + sec.w
    end
  end
  ox, oy = x0, y0
end

-- ---------- settings, in the main Ghostline window ----------
function H.settings()
  ui.separator()
  ui.text('Dash: show it from the CSP app bar (Ghostline Dash). Sections:')
  for k, sec in ipairs(SECTIONS) do
    local label = ({ standings = 'Standings', timing = 'Timing', drive = 'Gear + delta', pedals = 'Pedals', tyres = 'Tyres', map = 'Map' })[sec.key]
    if ui.checkbox(label, cfg[sec.key]) then cfg[sec.key] = not cfg[sec.key] end
    if k < #SECTIONS then ui.sameLine() end
  end
  local v1, c1 = ui.slider('##hudscale', cfg.scale, 0.6, 2, 'Dash size: %.2fx', true)
  if c1 then cfg.scale = v1 end
  local v2, c2 = ui.slider('##hudalpha', cfg.opacity, 0.3, 1, 'Dash background: %.2f', true)
  if c2 then cfg.opacity = v2 end
  ui.text('Click Delta to switch best lap / session best, Standings to switch relative / full order.')
  ui.text(H.fontsLoaded() and 'Dash fonts: loaded (Grotesk, Sligoil, Lack).' or 'Dash fonts: not loaded, using the Windows font.')
end

H.sections = SECTIONS

-- did CSP load the dash's own fonts? Sligoil (monospaced) measures differently from the default font if so
local fontsOk = nil
function H.fontsLoaded()
  if fontsOk == nil then
    local probe = 'iiii0000WWWW'
    local base = ui.measureDWriteText(probe, 20).x
    ui.pushDWriteFont(F.num)
    local ours = ui.measureDWriteText(probe, 20).x
    ui.popDWriteFont()
    fontsOk = math.abs(ours - base) > 1
  end
  return fontsOk
end

-- in a race with a known length: fuel left at the flag (laps to go x fuel per lap), nil otherwise
function H.fuelSpare(car, sim)
  if sim.raceSessionType ~= (ac.SessionType and ac.SessionType.Race or 3) or not car.fuelPerLap or car.fuelPerLap < 0.01 then
    return nil
  end
  local session = ac.getSession and ac.getSession(sim.currentSessionIndex or 0)
  local togo
  if session and session.laps and session.laps > 0 and not session.isTimedRace then
    togo = session.laps - car.lapCount - car.splinePosition
  elseif sim.sessionTimeLeft and sim.sessionTimeLeft > 0 and car.bestLapTimeMs > 0 then
    togo = sim.sessionTimeLeft / car.bestLapTimeMs + 1 - car.splinePosition   -- timed race: the lap after the clock runs out too
  end
  if not togo or togo <= 0 then return nil end
  return (car.fuel or 0) - togo * car.fuelPerLap
end
return H
