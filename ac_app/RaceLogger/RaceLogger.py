# RaceLogger - Assetto Corsa in-game app (Python 3.3).
# Logs every other car in the session (online drivers or AI) to logs/*.csv, one file per completed lap, and
# writes live.json (every car's position) for the standings on the Live page. Your own car is recorded by
# the website itself, straight from the game's shared memory.
#
# Kept light on purpose, because it runs inside the game's frame loop:
# - no disk access on the game thread: a background thread does every write (disk and antivirus scans can stall)
# - one pass over the cars per tick, names cached, no json import, each error logged once
import ac
import acsys
import os
import time
try:
    import threading
    import queue
except ImportError:   # no threads: fall back to writing directly
    threading = queue = None

APP = "RaceLogger"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "logs")
LIVE = os.path.join(HERE, "live.json")
STEP = 1.0 / 20       # car samples: 20 per second
LIVE_EVERY = 0.25     # live.json: 4 per second
NAMES_EVERY = 5.0     # driver / car names barely change: refresh every 5 s
MAX_ROWS = 20 * 600   # give up on a "lap" longer than 10 minutes (parked, stuck, AFK)

cars = {}     # car index -> lap being logged
names = {}    # car index -> (driver, car model)
clock = since = live_since = names_since = 0.0
saved = 0
label = None
track = ""
source = "ai"
logged = set()
writer = None


def _log(e):
    msg = "RaceLogger: " + str(e)
    if msg not in logged:   # ac.log writes to disk too: say each thing once
        logged.add(msg)
        ac.log(msg)


def _write(path, text, atomic):
    tmp = path + ".tmp" if atomic else path
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if atomic:   # lap files: the website only picks up *.csv, so it never sees half a file
        os.replace(tmp, path)


class Writer(threading.Thread if threading else object):
    """Does all file writing off the game thread. The newest live.json wins; lap files are written in order."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.q = queue.Queue()
        self.live = None

    def run(self):
        last = None
        while True:
            try:
                path, text = self.q.get(timeout=LIVE_EVERY)
                _write(path, text, True)
            except queue.Empty:
                pass
            except Exception as e:
                _log(e)
            live = self.live
            if live is not None and live is not last:
                last = live
                try:
                    _write(LIVE, live, False)
                except Exception:
                    pass   # the website is reading it right now; the next one is 0.25 s away


def _file(path, text):
    if writer:
        writer.q.put((path, text))
    else:
        _write(path, text, True)


def _str(s):
    return '"' + "".join(c if c not in '"\\' and ord(c) >= 32 else " " for c in str(s)) + '"'


def acMain(ac_version):
    global label, track, source, writer
    win = ac.newApp(APP)
    ac.setSize(win, 210, 54)
    label = ac.addLabel(win, "RaceLogger: waiting")
    ac.setPosition(label, 8, 28)
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    cfg = ac.getTrackConfiguration(0)
    track = ac.getTrackName(0) + ("-" + cfg if cfg else "")
    try:
        source = "online" if ac.getServerName() else "ai"
    except Exception:
        source = "ai"
    if threading:
        try:
            writer = Writer()
            writer.start()
        except Exception as e:
            writer = None
            _log(e)
    return APP


def acShutdown():
    """Session over: write whatever laps are still queued before the game unloads the app."""
    if not writer:
        return
    while True:
        try:
            path, text = writer.q.get_nowait()
            _write(path, text, True)
        except Exception:
            break


def _name(i):
    n = names.get(i)
    if n is None:
        n = names[i] = (ac.getDriverName(i), ac.getCarName(i))
    return n


def _clean(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s)[:24]


def _save(i, c, lap_s):
    global saved
    if c["pit"] or len(c["rows"]) < 100 or lap_s < 20:
        return
    driver, car = _name(i)
    name = "%s_%s_%s_%d.csv" % (time.strftime("%Y%m%d_%H%M%S"), _clean(car), _clean(driver), int(lap_s * 1000))
    head = ["# car=" + car, "# track=" + track, "# driver=" + driver, "# source=" + source,
            "# lap_ms=%d" % int(lap_s * 1000), "# valid=1", "t,pos,speed,x,z,gear"]
    _file(os.path.join(OUT, name), "\n".join(head + c["rows"]))
    saved += 1
    ac.setText(label, "RaceLogger: %d laps saved" % saved)


def _sample(i, pos):
    c = cars.get(i)
    if c is None:
        cars[i] = {"rows": None, "last": pos, "tp": clock, "start": 0.0, "pit": False, "n": 0}
        return
    if c["last"] > 0.9 and pos < 0.1:   # crossed the line: interpolate the exact moment
        span = (1.0 - c["last"]) + pos
        cross = c["tp"] + (clock - c["tp"]) * ((1.0 - c["last"]) / span if span > 0 else 1.0)
        if c["rows"] is not None:
            _save(i, c, cross - c["start"])
        c["rows"], c["start"], c["pit"] = [], cross, False
    elif c["rows"] is not None and pos < c["last"] - 0.05:
        c["rows"] = None   # reset / back to pits
    c["last"], c["tp"] = pos, clock
    rows = c["rows"]
    if rows is None:
        return
    if len(rows) > MAX_ROWS:
        c["rows"] = None
        return
    c["n"] += 1
    if c["n"] % 10 == 0 and ac.isCarInPitline(i):   # twice a second is plenty for the pit lane
        c["pit"] = True
    x, y, z = ac.getCarState(i, acsys.CS.WorldPosition)
    rows.append("%.3f,%.6f,%.2f,%.2f,%.2f,%d" % (clock - c["start"], pos, ac.getCarState(i, acsys.CS.SpeedKMH),
                                                 x, z, ac.getCarState(i, acsys.CS.Gear) - 1))


def _live(i, pos):
    driver, car = _name(i)
    return '{"i":%d,"name":%s,"car":%s,"spline":%.5f,"laps":%d,"last":%d,"best":%d,"pit":%s,"speed":%d}' % (
        i, _str(driver), _str(car), pos, ac.getCarState(i, acsys.CS.LapCount), ac.getCarState(i, acsys.CS.LastLap),
        ac.getCarState(i, acsys.CS.BestLap), "true" if ac.isCarInPitline(i) else "false",
        int(ac.getCarState(i, acsys.CS.SpeedKMH)))


def acUpdate(dt):
    global clock, since, live_since, names_since
    clock += dt
    since += dt
    live_since += dt
    names_since += dt
    if since < STEP:
        return
    since = 0.0
    if names_since >= NAMES_EVERY:   # someone may have joined or left
        names_since = 0.0
        names.clear()
    live = live_since >= LIVE_EVERY
    out = []
    if live:
        live_since = 0.0
    for i in range(ac.getCarsCount()):   # one pass: sample the other cars, collect everyone for live.json
        try:
            if not ac.isConnected(i):
                cars.pop(i, None)
                continue
            pos = ac.getCarState(i, acsys.CS.NormalizedSplinePosition)
            if i:
                _sample(i, pos)
            if live:
                out.append(_live(i, pos))
        except Exception as e:
            _log(e)
    if live:
        text = '{"t":%.3f,"track":%s,"cars":[%s]}' % (time.time(), _str(track), ",".join(out))
        if writer:
            writer.live = text
        else:
            try:
                _write(LIVE, text, False)
            except Exception:
                pass
