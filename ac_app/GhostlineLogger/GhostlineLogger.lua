-- Ghostline Logger: CSP Lua version of the RaceLogger app, for players with Custom Shaders Patch.
-- Copies every car's position, speed and lap times into shared memory ("GhostlineCars.v1"); Ghostline reads it
-- from outside the game and does the rest. Same block layout as ac_app/RaceLogger/RaceLogger.py and
-- backend/carfeed.py. LuaJIT writes the block directly, so the in-game cost is close to nothing.
-- While this runs, the Python RaceLogger sees `luaTicks` moving and stays idle.
-- Settings (rates, which cars, on/off) live in Ghostline's config/logger.json; the window here can change them.

local ffi = ffi or require('ffi')

ffi.cdef [[
typedef struct {
  uint32_t magic, version, seq;
  int32_t cars;
  double simTime, luaTicks;
  uint8_t online, writer, pad[2];
  char track[60];
  uint8_t connected[64], pit[64], lapValid[64], lapCuts[64];
  int16_t gear[64];
  int32_t lapCount[64], validLapCount[64], lastMs[64], bestMs[64];
  float spline[64], x[64], z[64], speed[64];
  double t[64];
  char driver[64][40];
  char car[64][48];
} ghl_cars;
typedef struct {
  uint32_t magic, beat;
  uint8_t want[64];
  uint16_t sampleHz, timingHz, liveHz;
  uint8_t enabled, detail;
  uint32_t settingsRev;
  uint8_t reserved[12];
} ghl_want;
typedef struct {
  uint32_t magic, rev;
  uint16_t sampleHz, timingHz, liveHz;
  uint8_t enabled, detail;
} ghl_settings;
]]

local MAGIC, WANT_MAGIC, SET_MAGIC, MAXC = 0x314C4847, 0x32574847, 0x31534847, 64
local NAMES, CHECK = 5.0, 1.0
local DETAILS = { 'my car', 'my class', 'all cars' }

local d, w, sreq               -- the shared blocks, typed
local rawD, rawW, rawS         -- what CSP returned: keep a reference, a block closes when it's garbage collected
local clock, rr = 0, 0
local step, slow, enabled = 1 / 30, 0.25, true
local slowDue = {}
local namesDue, checkDue = 0, 0
local lastBeat, beatSeen = nil, -1e9
local active, status = false, 'waiting'
local perfSum, perfMax, perfN, perfDue, perfText = 0, 0, 0, 2, ''
local edit, editAt = nil, -1e9   -- settings being changed in the window
local track = ac.getTrackFullID('-')
local online = ac.getSim().isOnlineRace and 1 or 0

local function open()
  local ok, err = pcall(function ()
    rawD = ac.writeMemoryMappedFile('GhostlineCars.v1', ffi.sizeof('ghl_cars'))
    rawW = ac.writeMemoryMappedFile('GhostlineWant.v2', ffi.sizeof('ghl_want'))
    rawS = ac.writeMemoryMappedFile('GhostlineSettings.v1', ffi.sizeof('ghl_settings'))
    d, w, sreq = ffi.cast('ghl_cars*', rawD), ffi.cast('ghl_want*', rawW), ffi.cast('ghl_settings*', rawS)
  end)
  if not ok then status = 'no shared memory: ' .. tostring(err) end
  return ok
end

-- The game's own verdict on every lap, for every car (also remote ones): valid, and how many cuts.
ac.onLapCompleted(-1, function (i, lapTime, valid, cuts, lapCount)
  if d and i >= 0 and i < MAXC then
    d.lapValid[i] = valid and 1 or 0
    d.lapCuts[i] = math.min(cuts or 0, 255)
    d.validLapCount[i] = lapCount or 0
  end
end)

local function check()
  if w.magic == WANT_MAGIC and w.beat ~= lastBeat then
    lastBeat, beatSeen = w.beat, clock
    step, slow, enabled = 1 / math.max(w.sampleHz, 1), 1 / math.max(w.timingHz, 1), w.enabled ~= 0
  end
  local ghostline = clock - beatSeen < 3
  active = ghostline and enabled
  status = not ghostline and 'Ghostline not running' or enabled and 'sending' or 'paused in settings'
end

local function names(n)
  for i = 0, n - 1 do
    ffi.copy(d.driver[i], (ac.getDriverName(i) or ''):sub(1, 39))
    ffi.copy(d.car[i], (ac.getCarID(i) or ''):sub(1, 47))
  end
end

local function sample(i)
  local c = ac.getCar(i)
  if not c then return end
  if clock >= (slowDue[i] or 0) then
    slowDue[i] = clock + slow
    d.connected[i] = c.isConnected and 1 or 0
    d.pit[i] = c.isInPitlane and 1 or 0
    d.lapCount[i] = c.lapCount
    d.lastMs[i] = c.previousLapTimeMs
    d.bestMs[i] = c.bestLapTimeMs
  end
  d.spline[i] = c.splinePosition
  if w.want[i] ~= 0 then
    d.x[i], d.z[i] = c.position.x, c.position.z
    d.speed[i] = c.speedKmh
    d.gear[i] = c.gear
  end
  d.t[i] = clock
end

function script.update(dt)
  clock = clock + dt
  if not d then
    if clock < checkDue or not open() then checkDue = clock + 5 return end
  end
  local t0 = os.preciseClock and os.preciseClock() or 0
  d.luaTicks = d.luaTicks + 1                 -- tells the Python RaceLogger to stand down
  if clock >= checkDue then checkDue = clock + CHECK check() end
  if active then
    local n = math.min(ac.getSim().carsCount, MAXC)
    d.seq = d.seq + 1                          -- odd: a write is in progress
    if clock >= namesDue then
      namesDue = clock + NAMES
      names(n)
      d.online, d.writer = online, 2
      ffi.copy(d.track, track:sub(1, 59))
    end
    local k = math.min(n, math.floor(n * dt / step) + 1)   -- enough cars per frame that each comes round every step
    for _ = 1, k do
      local i = rr % n
      rr = i + 1
      sample(i)
    end
    d.magic, d.version, d.cars, d.simTime = MAGIC, 1, n, clock
    d.seq = d.seq + 1                          -- even: consistent again
  end
  if os.preciseClock then
    local cost = (os.preciseClock() - t0) * 1000
    perfSum, perfN, perfMax = perfSum + cost, perfN + 1, math.max(perfMax, cost)
    if clock >= perfDue then
      perfDue = clock + 2
      perfText = string.format('%.3f ms avg, %.2f max per frame', perfSum / perfN, perfMax)
      perfSum, perfMax, perfN = 0, 0, 0
    end
  end
end

-- Asks Ghostline to save new settings; it writes config/logger.json and sends them back to both apps.
local function request(sampleHz, timingHz, liveHz, on, detail)
  if not sreq then return end
  sreq.sampleHz, sreq.timingHz, sreq.liveHz = sampleHz, timingHz, liveHz
  sreq.enabled, sreq.detail = on and 1 or 0, detail
  sreq.magic = SET_MAGIC
  sreq.rev = sreq.rev + 1
end

function script.windowMain(dt)
  ui.text('Ghostline: ' .. status)
  if perfText ~= '' then ui.text(perfText) end
  if not w or w.magic ~= WANT_MAGIC then
    ui.text('Settings appear once Ghostline is running.')
    return
  end
  ui.separator()
  -- show the edit in progress until Ghostline has saved it and sent it back (that takes up to a second)
  local cur = (edit and clock - editAt < 2) and edit or { w.sampleHz, w.timingHz, w.liveHz, w.enabled ~= 0, w.detail }
  local hz, timing, live, on, detail = cur[1], cur[2], cur[3], cur[4], cur[5]
  local changed = false
  if ui.checkbox('Send to Ghostline', on) then on, changed = not on, true end
  local v, c = ui.slider('##sample', hz, 5, 60, 'Car samples: %.0f per second', true)
  if c then hz, changed = v, true end
  v, c = ui.slider('##timing', timing, 1, 10, 'Lap times, pit: %.0f per second', true)
  if c then timing, changed = v, true end
  v, c = ui.slider('##live', live, 2, 30, 'Live page: %.0f updates per second', true)
  if c then live, changed = v, true end
  ui.text('Full detail (for ghost laps) for:')
  for k = 0, 2 do
    if ui.radioButton(DETAILS[k + 1], detail == k) then detail, changed = k, true end
    if k < 2 then ui.sameLine() end
  end
  if changed then
    edit, editAt = { math.floor(hz), math.floor(timing), math.floor(live), on, detail }, clock
    request(edit[1], edit[2], edit[3], edit[4], edit[5])
  end
end
