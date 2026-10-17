-- Ghostline coaching: brake boards and a racing line that follow your speed, and a 3D ghost of the best lap.
-- Ghostline sends the best lap for the car and track you're driving into shared memory ("GhostlineRef.v1",
-- layout `ghl_ref`, mirrored by backend/coach.py). Everything time-critical happens here, in the game's own frame
-- loop: nothing waits on Ghostline, so the boards and the countdown are as current as the frame on screen.
-- Only you see any of it, online too: it's drawn on your screen, nothing is sent to the server.

local ffi = ffi or require('ffi')

if not pcall(ffi.typeof, 'ghl_ref') then ffi.cdef [[
typedef struct {
  uint32_t magic, rev;
  int32_t n, corners;
  float step, length;
  int32_t lapMs, lapId;
  uint8_t est, pad[3];
  char car[48], track[64], driver[40], model[160], mainModel[160];
  float x[8192], z[8192], t[8192], speed[8192], brake[8192], throttle[8192];
  int8_t gear[8192];
  float cBrake[48], cSpeed[48], cApex[48], cMin[48], cDecel[48], cThrottle[48];
  int8_t cGear[48];
  uint8_t cKind[48];
  char cName[48][24];
} ghl_ref;
]] end

local M = {}
local REF_MAGIC, CHECK = 0x31524847, 0.5
local SHOW = 1200          -- boards appear this far before the corner (m)
local LOCK = 1.0           -- a board stops moving this long before you reach it (s)
local CUES = { 0.6, 0.3, 0 }   -- countdown: two ticks, then "brake", seconds before the board
local cfg = ac.storage({ boards = true, line = true, ghost = true, beep = true, lead = 0, ahead = 200, alpha = 0.35 },
  'ghostline.coach.')

local raw, blk                 -- the shared block (keep `raw`: the mapping closes when it's garbage collected)
local ref, pend, spare         -- private copies: the one in use, a newer one waiting for the next lap, a free one
local seen, checkDue = -1, 0
local live, n, L, step = false, 0, 1, 2
local Y, Yok                   -- per point: road height under the best lap's line (filled in lazily)
local carId, track = ac.getCarID(0), ac.getTrackFullID('-')
local car, clock, dNow, vNow, lapT, dtLast = nil, 0, 0, 0, 0, 1 / 60
local boards = {}              -- per corner: { at = metres, locked = bool }
local cue = { k = -1, stage = 0, shown = 0 }
local rays = 0                 -- raycasts this frame (the road height is filled in a few points per frame)
local gi, ghostOn, gpos, glook, gup = 0, false, vec3(), vec3(0, 0, 1), vec3(0, 1, 0)
local ghostRoot, ghostModel, ghostFile, ghostMsg = nil, nil, nil, nil
local ride = 0.5               -- height of the car's origin above the road, measured on your own car
local perf = { sum = 0, max = 0, n = 0, due = 2, text = '' }
local down, upv = vec3(0, -1, 0), vec3(0, 1, 0)
local tmp1, tmp2, tmp3, tmp4, nrm = vec3(), vec3(), vec3(), vec3(), vec3()
local colR, colY, colG = rgbm(1, 0.16, 0.1, 0.6), rgbm(1, 0.78, 0.1, 0.55), rgbm(0.15, 1, 0.45, 0.45)
local col = rgbm(1, 1, 1, 1)
local boardCols = { [0] = rgbm(1, 1, 1, 0.55), rgbm(1, 0.85, 0.1, 0.75), rgbm(1, 0.5, 0.05, 0.85), rgbm(1, 0.1, 0.05, 0.95) }

local function open()
  local ok = pcall(function ()
    raw = ac.writeMemoryMappedFile('GhostlineRef.v1', ffi.sizeof('ghl_ref'))
    blk = ffi.cast('ghl_ref*', raw)
  end)
  return ok and blk ~= nil
end

local function str(c) return ffi.string(c) end

-- distance along the lap, wrapped into 0..L
local function wrap(d) return d % L end
local function ahead(from, to) return (to - from) % L end   -- metres from `from` forward to `to`

-- value of a per-point array at distance d, interpolated
local function at(arr, d)
  local f = wrap(d) / step
  local i = math.floor(f)
  local a, b = i % n, (i + 1) % n
  return arr[a] + (arr[b] - arr[a]) * (f - i)
end

-- road height under point i of the reference line; nil while not measured yet (max 40 new rays a frame)
local function ground(i)
  if Yok[i] == 0 then
    if rays >= 40 then return nil end
    rays = rays + 1
    local base = ac.trackProgressToWorldCoordinate(i * step / L)
    tmp1:set(ref.x[i], base.y + 4, ref.z[i])
    local hit = physics.raycastTrack(tmp1, down, 12)
    Y[i] = (hit and hit >= 0) and base.y + 4 - hit or base.y
    Yok[i] = 1
  end
  return Y[i]
end

local function disposeGhost()
  if ghostRoot then pcall(function () ghostRoot:dispose() end) end
  ghostRoot, ghostModel, ghostFile, ghostMsg = nil, nil, nil, nil
end

-- the ghost is the car's own 3D model (a light LOD), see-through and outlined
local function loadGhost()
  local file, main = str(ref.model), str(ref.mainModel)
  if file == ghostFile then return end
  disposeGhost()
  ghostFile = file
  if file == '' then ghostMsg = 'no 3D model for this car: showing a marker' return end
  local ok, err = pcall(function ()
    ghostRoot = ac.findNodes('carsRoot:yes'):createBoundingSphereNode('ghostlineGhost', 5)
    ghostRoot:setVisible(false)
    ghostRoot:loadKN5LODAsync(file, main, function (e, model)
      if e or not model then ghostMsg = 'model failed: ' .. tostring(e) .. ', showing a marker' return end
      ghostModel = model
      pcall(function () model:ensureUniqueMaterials() end)   -- never change the real cars' materials
      pcall(function () model:setShadows(false):excludeFromCubemap(true):excludeFromSecondary(true) end)
      pcall(function () model:setTransparent(true):setBlendMode(render.BlendMode.AlphaBlend) end)
      pcall(function () model:setMaterialProperty('ksAlpha', cfg.alpha) end)
      pcall(function () model:setOutline(rgbm(0.55, 0.8, 1, 1)) end)
    end)
  end)
  if not ok then ghostRoot, ghostMsg = nil, 'model failed: ' .. tostring(err) .. ', showing a marker' end
end

local function activate()
  spare, ref, pend = ref, pend, nil
  n, L, step = ref.n, math.max(ref.length, 1), math.max(ref.step, 0.5)
  live = n > 10 and str(ref.car) == carId and str(ref.track) == track
  boards, cue.k, gi = {}, -1, 0
  if not live then disposeGhost() return end
  Y, Yok = ffi.new('float[?]', n), ffi.new('uint8_t[?]', n)
  loadGhost()
end

local function load()
  local r = blk.rev
  if r % 2 == 1 or r == seen or blk.magic ~= REF_MAGIC then return end
  local copy = spare or ffi.new('ghl_ref')
  ffi.copy(copy, blk, ffi.sizeof('ghl_ref'))
  if blk.rev ~= r then return end   -- Ghostline wrote meanwhile: next time
  seen, spare, pend = r, nil, copy
end

-- where to brake for corner k at the speed you're carrying: the best lap's braking, from your speed down to its
-- slowest point. Your speed at the board is predicted from the best lap's speed profile up to there.
local function boardAt(k)
  local vref = math.max(at(ref.speed, dNow) / 3.6, 5)
  local ratio = math.min(math.max(ref.cSpeed[k] / 3.6 / vref, 0.7), 1.6)
  local vp, vmin = vNow * ratio, ref.cMin[k] / 3.6
  local zone = ahead(ref.cBrake[k], ref.cApex[k])
  if vp <= vmin + 0.5 then return ref.cBrake[k] end
  local back = (vp * vp - vmin * vmin) / (2 * ref.cDecel[k])
  back = math.min(math.max(back, 5), zone + 150)
  return wrap(ref.cApex[k] - back)
end

local function sound(file)
  if not cfg.beep or ac.isInReplayMode and ac.isInReplayMode() then return end
  pcall(function ()
    local e = ac.AudioEvent.fromFile({ filename = (__dirname or '.') .. '/' .. file, use3D = false, loop = false }, false)
    e.volume = 0.8
    e:start()
  end)
end

local function updateBoards()
  local best, bestT = -1, 1e9
  for k = 0, ref.corners - 1 do
    local toApex = ahead(dNow, ref.cApex[k])
    local b = boards[k]
    if toApex > SHOW and toApex < L - 300 then
      boards[k] = nil                               -- far away, or more than 300 m past the corner
    elseif toApex <= SHOW then
      if not b then b = { at = ref.cBrake[k], locked = false }; boards[k] = b end
      local dist = ahead(dNow, b.at)
      if dist > toApex then dist = dist - L end      -- the board is behind you (you're braking past it)
      if not b.locked then
        b.at = boardAt(k)
        dist = ahead(dNow, b.at)
        if dist > toApex then dist = dist - L end
        if (vNow > 1 and dist / vNow < LOCK) or (car.brake > 0.2 and dist < 150) then b.locked = true end
      end
      b.dist = dist
      local tt = dist / math.max(vNow, 1)
      b.stage = dist < -25 and -1 or tt <= 0 and 3 or tt <= CUES[2] and 2 or tt <= CUES[1] and 1 or 0
      if dist > -2 and tt < bestT then best, bestT = k, tt end
    elseif b then
      b.stage, b.dist = -1, -1e9                     -- just past the corner: hidden until it's dropped
    end
    if boards[k] then                                -- for the racing line: apex and full throttle, metres ahead
      local a = toApex > L - 300 and toApex - L or toApex
      boards[k].apexD, boards[k].thrD = a, a + ahead(ref.cApex[k], ref.cThrottle[k])
    end
  end
  -- countdown sounds for the next board, fired on the frame where the moment falls within half a frame
  if best >= 0 and vNow > 15 and not car.isInPitlane then
    if cue.k ~= best then cue.k, cue.stage = best, 0 end
    local lead = (cfg.lead or 0) / 1000
    while cue.stage < #CUES and bestT - lead <= CUES[cue.stage + 1] + dtLast * 0.5 do
      cue.stage = cue.stage + 1
      if bestT - lead > CUES[cue.stage] - 0.15 then   -- not when it's long gone (e.g. you just joined the track)
        sound(cue.stage == #CUES and 'brake.wav' or 'tick.wav')
        cue.shown = clock
      end
    end
  end
end

local function updateGhost()
  ghostOn = false
  if not cfg.ghost or car.isInPitlane then return end
  local T = car.lapTimeMs / 1000
  if T > ref.lapMs / 1000 + 2 then return end
  if gi > 0 and ref.t[gi] > T then gi = 0 end         -- a new lap
  while gi < n - 2 and ref.t[gi + 1] <= T do gi = gi + 1 end
  local t0, t1 = ref.t[gi], ref.t[gi + 1]
  local w = t1 > t0 and math.min(math.max((T - t0) / (t1 - t0), 0), 1) or 0
  local gd = (gi + w) * step
  local gap = ahead(dNow, gd)
  if gap > L / 2 then gap = gap - L end
  if math.abs(gap) > 500 then return end              -- out lap, or far away: nothing to see
  local a, b = gi, (gi + 1) % n
  local x, z = ref.x[a] + (ref.x[b] - ref.x[a]) * w, ref.z[a] + (ref.z[b] - ref.z[a]) * w
  local p, q = (gi - 2) % n, (gi + 3) % n
  local base = ac.trackProgressToWorldCoordinate(gd / L)
  tmp1:set(x, base.y + 4, z)
  local hit = physics.raycastTrack(tmp1, down, 12, nil, nrm)
  local y = (hit and hit >= 0) and base.y + 4 - hit or base.y
  gpos:set(x, y + ride, z)
  glook:set(ref.x[q] - ref.x[p], 0, ref.z[q] - ref.z[p])
  if (hit and hit >= 0) and nrm.y > 0.5 then gup:set(nrm.x, nrm.y, nrm.z) else gup:set(0, 1, 0) end
  local len = math.sqrt(glook.x * glook.x + glook.z * glook.z)
  if len < 0.01 then return end
  glook:set(glook.x / len, -(glook.x / len * gup.x + glook.z / len * gup.z) / gup.y, glook.z / len)   -- along the road's slope
  glook:normalize()
  ghostOn = true
  M.gap = gap
end

-- road height under your car, for placing the ghost at the same height above it
local function measureRide()
  tmp2:set(car.position.x, car.position.y + 2, car.position.z)
  local hit = physics.raycastTrack(tmp2, down, 6)
  if hit and hit >= 0 then
    local h = car.position.y - (car.position.y + 2 - hit)
    if h > -0.5 and h < 1.5 then ride = ride + (h - ride) * 0.05 end
  end
end

function M.update(dt, simClock)
  clock, dtLast, rays = simClock, math.max(dt, 0.001), 0
  if not blk then
    if clock < checkDue then return end
    checkDue = clock + 5
    if not open() then return end
    checkDue = 0   -- read it straight away
  end
  local t0 = os.preciseClock and os.preciseClock() or 0
  if clock >= checkDue then
    checkDue = clock + CHECK
    load()
  end
  car = ac.getCar(0)
  if not car then return end
  if pend and (not ref or not live or car.lapTimeMs < 3000) then activate() end   -- a new best lap: from the next lap on
  if not live then
    ghostOn = false
    if ghostRoot then pcall(function () ghostRoot:setVisible(false) end) end
    return
  end
  dNow, vNow, lapT = car.splinePosition * L, car.speedKmh / 3.6, car.lapTimeMs / 1000
  updateBoards()   -- also behind the racing line and the countdown
  measureRide()
  updateGhost()
  if ghostRoot then
    pcall(function ()
      ghostRoot:setVisible(ghostOn and ghostModel ~= nil)
      if ghostOn then ghostRoot:setPosition(gpos); ghostRoot:setOrientation(glook, gup) end
    end)
  end
  M.delta = lapT - at(ref.t, dNow)
  if os.preciseClock then
    local cost = (os.preciseClock() - t0) * 1000
    perf.sum, perf.n, perf.max = perf.sum + cost, perf.n + 1, math.max(perf.max, cost)
  end
end

-- ---------- drawing (inside the game's 3D pass) ----------

-- the racing line for the next `cfg.ahead` metres, coloured from the same boards (so it moves with your speed too):
-- red = brake (from the board to the slowest point), yellow = get ready (the countdown before a board), lift, or
-- not yet back on full throttle after the apex; green = flat out.
local function lineColour(x)
  local c = colG
  for k, b in pairs(boards) do
    if b.apexD then
      local b0 = b.dist > -1e8 and b.dist or b.apexD - 1
      if x >= b0 and x <= b.apexD then
        if ref.cKind[k] == 1 then return colR end
        c = colY
      elseif (x < b0 and x >= b0 - vNow * CUES[1]) or (x > b.apexD and x <= b.thrD) then
        c = colY
      end
    end
  end
  return c
end

local function drawLine()
  local draw = math.min(math.floor(cfg.ahead / step), n - 1)
  local i0 = math.floor(wrap(dNow + 3) / step)
  render.setBlendMode(render.BlendMode.AlphaBlend)
  render.setDepthMode(render.DepthMode.ReadOnlyLessEqual)
  render.setCullMode(render.CullMode.None)
  render.glBegin(render.GLPrimitiveType.Quads)
  for j = 0, draw - 1 do
    local a, b = (i0 + j) % n, (i0 + j + 1) % n
    local ya, yb = ground(a), ground(b)
    if not ya or not yb then break end
    local x = ahead(dNow, a * step + step / 2)
    local c = lineColour(x)
    -- seen from the cockpit, a flat strip far ahead shrinks to a sliver (and sinks into the road surface), so the line
    -- gets wider, slightly higher and more opaque with distance; faint right under the car, fading out at the end
    local half, lift = math.min(0.35 + 0.006 * x, 2), 0.04 + 0.0025 * x
    local alpha = math.min(1, x / 12) * (1 + 0.6 * math.min(1, x / 150)) * math.min(1, (1 - j / draw) * 10)
    col.r, col.g, col.b, col.mult = c.r, c.g, c.b, math.min(c.mult * alpha, 0.95)
    local dx, dz = ref.x[b] - ref.x[a], ref.z[b] - ref.z[a]
    local len = math.sqrt(dx * dx + dz * dz)
    if len > 0.01 then
      local px, pz = -dz / len * half, dx / len * half
      render.glSetColor(col)
      tmp1:set(ref.x[a] - px, ya + lift, ref.z[a] - pz); render.glVertex(tmp1)
      tmp2:set(ref.x[a] + px, ya + lift, ref.z[a] + pz); render.glVertex(tmp2)
      tmp3:set(ref.x[b] + px, yb + lift, ref.z[b] + pz); render.glVertex(tmp3)
      tmp4:set(ref.x[b] - px, yb + lift, ref.z[b] - pz); render.glVertex(tmp4)
    end
  end
  render.glEnd()
end

-- a point across the road `d` metres into the lap: centre and height of the road there, direction, half its width
local function roadAt(d)
  local p = wrap(d) / L
  local c = ac.trackProgressToWorldCoordinate(p)
  local c2 = ac.trackProgressToWorldCoordinate(wrap(d + 2) / L)
  local dx, dz = c2.x - c.x, c2.z - c.z
  local len = math.sqrt(dx * dx + dz * dz)
  if len < 0.01 then return nil end
  local sides = ac.getTrackAISplineSides(p)
  tmp1:set(c.x, c.y + 4, c.z)
  local hit = physics.raycastTrack(tmp1, down, 12)
  local y = (hit and hit >= 0) and c.y + 4 - hit or c.y
  return c.x, y, c.z, dx / len, dz / len, math.min(math.max((sides.x + sides.y) / 2, 3), 15)
end

local postDir = vec3()
-- a pair of upright posts, one each side of the road: unlike marks on the road they don't flatten out with distance
local function posts(d, h, colour)
  local x, y, z, dx, dz, half = roadAt(d)
  if not x then return end
  postDir:set(-dx, 0, -dz)
  for side = -1, 1, 2 do
    tmp2:set(x - dz * (half + 0.6) * side, y + h / 2, z + dx * (half + 0.6) * side)
    render.rectangle(tmp2, postDir, 0.55, h, colour)
  end
  return x, y, z, dx, dz, half
end

local markCol = rgbm(1, 1, 1, 0.7)
-- a brake board: tall posts each side of the road and a stripe across it where to brake, shorter posts 100 m and
-- 50 m before it, and the gear and slowest speed of the corner above it
local function drawBoard(k, b)
  if b.stage < 0 then return end
  for _, m in ipairs({ 100, 50 }) do
    if b.dist and b.dist > m then posts(b.at - m, 0.9, markCol) end
  end
  local x, y, z, dx, dz, half = posts(b.at, 2.2, boardCols[b.stage])
  if not x then return end
  local sx, sz = -dz * half, dx * half
  local lift = 0.05 + 0.0025 * math.max(b.dist or 0, 0)
  tmp1:set(x - sx, y + lift, z - sz); tmp2:set(x + sx, y + lift, z + sz)
  tmp3:set(x + sx + dx * 1.2, y + lift, z + sz + dz * 1.2); tmp4:set(x - sx + dx * 1.2, y + lift, z - sz + dz * 1.2)
  render.quad(tmp1, tmp2, tmp3, tmp4, boardCols[b.stage])
  if b.dist and b.dist < 600 then
    tmp1:set(x, y + 3, z)
    local gear = ref.cGear[k] > 0 and tostring(ref.cGear[k]) or ''
    local text = ref.cKind[k] == 2 and ('LIFT ' .. gear) or (b.stage == 3 and 'BRAKE ' or '') .. gear .. '  ' .. math.floor(ref.cMin[k])
    render.debugText(tmp1, text, boardCols[b.stage], 1.6)
  end
end

local function drawMarker()   -- the ghost without a 3D model: a see-through footprint
  local lx, lz = glook.x, glook.z
  local sx, sz = -lz * 0.95, lx * 0.95
  local y = gpos.y - ride + 0.06
  tmp1:set(gpos.x - sx - lx * 2.2, y, gpos.z - sz - lz * 2.2); tmp2:set(gpos.x + sx - lx * 2.2, y, gpos.z + sz - lz * 2.2)
  tmp3:set(gpos.x + sx + lx * 2.2, y, gpos.z + sz + lz * 2.2); tmp4:set(gpos.x - sx + lx * 2.2, y, gpos.z - sz + lz * 2.2)
  render.quad(tmp1, tmp2, tmp3, tmp4, rgbm(0.55, 0.8, 1, cfg.alpha))
end

function M.draw()
  if not live or not car or car.isInPitlane then return end
  local t0 = os.preciseClock and os.preciseClock() or 0
  if cfg.line then drawLine() end
  if cfg.boards then
    render.setBlendMode(render.BlendMode.AlphaBlend)
    render.setDepthMode(render.DepthMode.ReadOnlyLessEqual)
    for k, b in pairs(boards) do drawBoard(k, b) end
  end
  if ghostOn and not ghostModel then drawMarker() end
  if ghostOn and M.delta then
    tmp1:set(gpos.x, gpos.y + 1.8, gpos.z)
    render.debugText(tmp1, string.format('%+.2f', M.delta), rgbm(0.55, 0.8, 1, 0.9), 1.1)
  end
  if os.preciseClock then
    local cost = (os.preciseClock() - t0) * 1000
    perf.sum, perf.max = perf.sum + cost, math.max(perf.max, cost)
  end
end

local drawErr = nil
pcall(function ()
  render.on('main.track.transparent', function ()
    if drawErr then return end
    local ok, err = pcall(M.draw)
    if not ok then drawErr = tostring(err) end   -- stop drawing rather than fail every frame; shown in the window
  end)
end)

-- ---------- window ----------

local function laptime(ms)
  return string.format('%d:%06.3f', math.floor(ms / 60000), (ms % 60000) / 1000)
end

function M.window()
  ui.separator()
  if not ref or not live then
    ui.text(blk and 'Coaching: no lap with this car here yet. Drive one valid lap.' or 'Coaching: waiting for Ghostline.')
  else
    ui.text('Coaching vs ' .. laptime(ref.lapMs) .. ' by ' .. str(ref.driver) .. (ref.est ~= 0 and ' (brake points estimated)' or ''))
    if M.delta then ui.text(string.format('Delta: %+.2f s', M.delta)) end
    if ghostMsg then ui.text(ghostMsg) end
    if drawErr then ui.text('Drawing stopped: ' .. drawErr) end
  end
  if ui.checkbox('Brake boards', cfg.boards) then cfg.boards = not cfg.boards end
  ui.sameLine()
  if ui.checkbox('Countdown sound', cfg.beep) then cfg.beep = not cfg.beep end
  if ui.checkbox('Racing line', cfg.line) then cfg.line = not cfg.line end
  ui.sameLine()
  if ui.checkbox('3D ghost', cfg.ghost) then cfg.ghost = not cfg.ghost end
  local v, c = ui.slider('##ahead', cfg.ahead, 50, 400, 'Racing line: %.0f m ahead', true)
  if c then cfg.ahead = math.floor(v) end
  v, c = ui.slider('##lead', cfg.lead, 0, 250, 'Sound early by: %.0f ms', true)
  if c then cfg.lead = math.floor(v) end
  v, c = ui.slider('##alpha', cfg.alpha, 0.1, 0.8, 'Ghost: %.2f opacity', true)
  if c then
    cfg.alpha = v
    if ghostModel then pcall(function () ghostModel:setMaterialProperty('ksAlpha', v) end) end
  end
  if clock >= perf.due and perf.n > 0 then
    perf.due = clock + 2
    perf.text = string.format('Coaching: %.3f ms avg, %.2f max per frame', perf.sum / perf.n, perf.max)
    perf.sum, perf.max, perf.n = 0, 0, 0
  end
  if perf.text ~= '' then ui.text(perf.text) end
end

M.state = function () return { live = live, boards = boards, cue = cue, ghostOn = ghostOn, gpos = gpos, glook = glook,
  gup = gup, ref = ref, dNow = dNow, n = n, L = L } end

return M
