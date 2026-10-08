-- Ghostline Logger: CSP Lua version of the RaceLogger app, for players with Custom Shaders Patch.
-- Copies every car's position, speed and lap times into shared memory ("GhostlineCars.v1"); Ghostline reads it
-- from outside the game and does the rest. Same block layout as ac_app/RaceLogger/RaceLogger.py and
-- backend/carfeed.py. LuaJIT writes the block directly, so the in-game cost is close to nothing.
-- While this runs, the Python RaceLogger sees `luaTicks` moving and stays idle.

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
typedef struct { uint32_t magic, beat; uint8_t want[64]; } ghl_want;
]]

local MAGIC, WANT_MAGIC, MAXC = 0x314C4847, 0x31574847, 64
local STEP, SLOW, NAMES, CHECK = 1 / 20, 0.5, 5.0, 1.0

local d, w                     -- the two shared blocks, typed
local rawD, rawW               -- what CSP returned: keep a reference, the block closes when it's garbage collected
local clock, rr = 0, 0
local slowDue = {}
local namesDue, checkDue = 0, 0
local lastBeat, beatSeen = nil, -1e9
local active, status = false, 'waiting'
local perfSum, perfMax, perfN, perfDue, perfText = 0, 0, 0, 2, ''
local track = ac.getTrackFullID('-')
local online = ac.getSim().isOnlineRace and 1 or 0

local function open()
  local ok, err = pcall(function ()
    rawD = ac.writeMemoryMappedFile('GhostlineCars.v1', ffi.sizeof('ghl_cars'))
    rawW = ac.writeMemoryMappedFile('GhostlineWant.v1', ffi.sizeof('ghl_want'))
    d, w = ffi.cast('ghl_cars*', rawD), ffi.cast('ghl_want*', rawW)
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
  end
  active = clock - beatSeen < 3
  status = active and 'sending' or 'Ghostline not running'
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
    slowDue[i] = clock + SLOW
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
    local k = math.min(n, math.floor(n * dt / STEP) + 1)
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
      perfText = string.format('%.3f ms avg, %.2f max', perfSum / perfN, perfMax)
      perfSum, perfMax, perfN = 0, 0, 0
    end
  end
end

function script.windowMain(dt)
  ui.text('Ghostline: ' .. status)
  if perfText ~= '' then ui.text(perfText) end
end
