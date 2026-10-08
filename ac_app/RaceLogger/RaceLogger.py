# RaceLogger - Assetto Corsa in-game app (Python 3.3).
# Copies every car's position, speed and lap times into shared memory ("GhostlineCars.v1"). Ghostline reads it
# from outside the game and does all the work there: lap detection, saving ghost laps, standings and gaps.
#
# Built to cost as little as possible inside the game's frame loop:
# - no files, no text, no threads: one fixed binary block, written with struct.pack_into
# - each car is sampled 20 times a second, spread over frames (a few cars per frame, never all at once)
# - full detail (position, speed, gear) only for cars Ghostline asks for (your car / class); the rest get
#   their track position only, plus lap times and pit status twice a second, names every 5 seconds
# - idle when Ghostline isn't running, or when the CSP Lua version of this app (GhostlineLogger) is running
# The window shows what it costs per frame.
import ac
import acsys
import struct
import time
try:
    import mmap
except ImportError:
    mmap = None

APP = "RaceLogger"
CARS, WANT = "GhostlineCars.v1", "GhostlineWant.v1"
SIZE, WANT_SIZE, MAXC = 8672, 72, 64
MAGIC, WANT_MAGIC = 0x314C4847, 0x31574847   # "GHL1", "GHW1"
STEP, SLOW, NAMES, CHECK = 1.0 / 20, 0.5, 5.0, 1.0

# block layout (little-endian, naturally aligned; the Lua app and backend/carfeed.py use the same offsets)
H_FRAME = struct.Struct("<IIIid")        # magic, version, seq, cars, sim clock      @0
H_SEQ = struct.Struct("<I")              # seq                                       @8
H_INFO = struct.Struct("<BB2x60s")       # online, writer, track                      @32
O_CONN, O_PIT, O_GEAR, O_LAPS, O_LAST, O_BEST = 96, 160, 352, 480, 992, 1248
O_SPLINE, O_X, O_Z, O_SPEED, O_T, O_DRIVER, O_CAR = 1504, 1760, 2016, 2272, 2528, 3040, 5600
U8, I16, I32, F32, F64 = struct.Struct("<B"), struct.Struct("<h"), struct.Struct("<i"), struct.Struct("<f"), struct.Struct("<d")
S40, S48 = struct.Struct("<40s"), struct.Struct("<48s")
CS = acsys.CS

buf = want_buf = None
label = None
track = ""
online = 0
clock = 0.0
seq = 0
rr = 0                       # round-robin pointer: next car to sample
slow_due = [0.0] * MAXC
names_due = 0.0
check_due = 0.0
want = [1] * MAXC
active = False               # Ghostline is reading and no Lua writer is running
last_beat = last_lua = None
beat_seen = lua_seen = -1e9
perf_sum = perf_max = 0.0
perf_n = 0
perf_due = 2.0
logged = set()
status = "waiting"


def _log(e):
    msg = "RaceLogger: " + str(e)
    if msg not in logged:
        logged.add(msg)
        ac.log(msg)


def acMain(ac_version):
    global label, track, online, buf, want_buf
    win = ac.newApp(APP)
    ac.setSize(win, 260, 54)
    label = ac.addLabel(win, "Ghostline: waiting")
    ac.setPosition(label, 8, 28)
    cfg = ac.getTrackConfiguration(0)
    track = ac.getTrackName(0) + ("-" + cfg if cfg else "")
    try:
        online = 1 if ac.getServerName() else 0
    except Exception:
        online = 0
    if mmap is None:
        ac.setText(label, "Ghostline: no shared memory here")
        return APP
    try:
        buf = mmap.mmap(-1, SIZE, tagname=CARS)
        want_buf = mmap.mmap(-1, WANT_SIZE, tagname=WANT)
    except Exception as e:
        buf = None
        _log(e)
    return APP


def _check():
    """Once a second: is Ghostline reading (its heartbeat moves), and is the Lua app writing instead of us?"""
    global active, last_beat, last_lua, beat_seen, lua_seen, want, status
    magic, beat = struct.unpack_from("<II", want_buf, 0)
    if magic == WANT_MAGIC and beat != last_beat:
        last_beat, beat_seen = beat, clock
        want = list(want_buf[8:8 + MAXC])
    lua = F64.unpack_from(buf, 24)[0]
    if last_lua is not None and lua != last_lua:   # the Lua app counts up every frame
        lua_seen = clock
    last_lua = lua
    ghostline = clock - beat_seen < 3.0
    lua_running = clock - lua_seen < 2.0
    active = ghostline and not lua_running
    status = "CSP app is sending" if lua_running else "sending" if ghostline else "Ghostline not running"


def _names(n):
    for i in range(n):
        S40.pack_into(buf, O_DRIVER + 40 * i, ac.getDriverName(i).encode("utf-8", "replace")[:39])
        S48.pack_into(buf, O_CAR + 48 * i, ac.getCarName(i).encode("utf-8", "replace")[:47])


def _sample(i):
    if clock >= slow_due[i]:   # things that change a few times per lap at most
        slow_due[i] = clock + SLOW
        U8.pack_into(buf, O_CONN + i, 1 if ac.isConnected(i) else 0)
        U8.pack_into(buf, O_PIT + i, 1 if ac.isCarInPitline(i) else 0)
        I32.pack_into(buf, O_LAPS + 4 * i, ac.getCarState(i, CS.LapCount))
        I32.pack_into(buf, O_LAST + 4 * i, ac.getCarState(i, CS.LastLap))
        I32.pack_into(buf, O_BEST + 4 * i, ac.getCarState(i, CS.BestLap))
    F32.pack_into(buf, O_SPLINE + 4 * i, ac.getCarState(i, CS.NormalizedSplinePosition))
    if want[i]:
        x, y, z = ac.getCarState(i, CS.WorldPosition)
        F32.pack_into(buf, O_X + 4 * i, x)
        F32.pack_into(buf, O_Z + 4 * i, z)
        F32.pack_into(buf, O_SPEED + 4 * i, ac.getCarState(i, CS.SpeedKMH))
        I16.pack_into(buf, O_GEAR + 2 * i, ac.getCarState(i, CS.Gear) - 1)
    F64.pack_into(buf, O_T + 8 * i, clock)


def acUpdate(dt):
    global clock, seq, rr, names_due, check_due, perf_sum, perf_max, perf_n, perf_due
    clock += dt
    if buf is None:
        return
    t0 = time.perf_counter()
    if clock >= check_due:
        check_due = clock + CHECK
        try:
            _check()
        except Exception as e:
            _log(e)
    if active:
        n = min(ac.getCarsCount(), MAXC)
        seq += 1
        H_SEQ.pack_into(buf, 8, seq)                       # odd: a write is in progress
        try:
            if clock >= names_due:
                names_due = clock + NAMES
                _names(n)
                H_INFO.pack_into(buf, 32, online, 1, track.encode("utf-8", "replace")[:59])
            k = min(n, int(n * dt / STEP) + 1)              # enough cars per frame that each comes round every STEP
            for _ in range(k):
                i = rr % n
                rr = i + 1
                _sample(i)
        except Exception as e:
            _log(e)
        seq += 1
        H_FRAME.pack_into(buf, 0, MAGIC, 1, seq, n, clock)  # even: consistent again
    cost = (time.perf_counter() - t0) * 1000
    perf_sum += cost
    perf_n += 1
    if cost > perf_max:
        perf_max = cost
    if clock >= perf_due:   # what this costs the game, so it can be checked in a real session
        perf_due = clock + 2.0
        ac.setText(label, "Ghostline %s | %.3f ms avg, %.2f max" % (status, perf_sum / perf_n, perf_max))
        perf_sum = perf_max = 0.0
        perf_n = 0
