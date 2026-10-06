# RaceLogger - Assetto Corsa in-game app (Python 3.3).
# Logs every other car in the session (online drivers or AI) to logs/*.csv, one file per completed lap.
# The race_analysis website picks the files up automatically. Your own car is recorded by the website itself.
import ac
import acsys
import os
import time
try:
    import json
except ImportError:   # keep lap logging alive even if AC's Python lacks json
    json = None


def _dumps(v):
    if json:
        return json.dumps(v)
    if isinstance(v, dict):
        return "{" + ",".join(_dumps(str(k)) + ":" + _dumps(x) for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ",".join(_dumps(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return '"' + "".join(c if c not in '"\\' and ord(c) >= 32 else " " for c in str(v)) + '"'

APP = "RaceLogger"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
HZ = 20.0
LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live.json")
live_since = 0.0

cars = {}
clock = 0.0
since = 0.0
saved = 0
label = None
track = ""
source = "ai"


def acMain(ac_version):
    global label, track, source
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
    return APP


def _safe(i, what, default=0):
    try:
        return ac.getCarState(i, what)
    except Exception:
        return default


def _clean(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s)[:24]


def _save(i, c, lap_s):
    global saved
    if c["pit"] or len(c["rows"]) < 100 or lap_s < 20:
        return
    car = ac.getCarName(i)
    driver = ac.getDriverName(i)
    name = "%s_%s_%s_%d.csv" % (time.strftime("%Y%m%d_%H%M%S"), _clean(car), _clean(driver), int(lap_s * 1000))
    lines = ["# car=" + car, "# track=" + track, "# driver=" + driver, "# source=" + source,
             "# lap_ms=%d" % int(lap_s * 1000), "# valid=1", "t,pos,speed,x,z,gear"] + c["rows"]
    with open(os.path.join(OUT, name), "w") as f:
        f.write("\n".join(lines))
    saved += 1
    ac.setText(label, "RaceLogger: %d laps saved" % saved)


def _sample(i):
    pos = ac.getCarState(i, acsys.CS.NormalizedSplinePosition)
    c = cars.get(i)
    if c is None:
        cars[i] = {"rows": None, "last": pos, "tp": clock, "start": 0.0, "pit": False}
        return
    if c["last"] > 0.9 and pos < 0.1:
        span = (1.0 - c["last"]) + pos
        cross = c["tp"] + (clock - c["tp"]) * ((1.0 - c["last"]) / span if span > 0 else 1.0)
        if c["rows"] is not None:
            _save(i, c, cross - c["start"])
        c["rows"], c["start"], c["pit"] = [], cross, False
    elif c["rows"] is not None and pos < c["last"] - 0.05:
        c["rows"] = None   # reset / back to pits
    c["last"], c["tp"] = pos, clock
    if c["rows"] is None:
        return
    if ac.isCarInPitline(i):
        c["pit"] = True
    x, y, z = ac.getCarState(i, acsys.CS.WorldPosition)
    c["rows"].append("%.3f,%.6f,%.2f,%.2f,%.2f,%d" % (clock - c["start"], pos, ac.getCarState(i, acsys.CS.SpeedKMH),
                                                     x, z, _safe(i, acsys.CS.Gear, 1) - 1))


def _write_live():
    """Every car's position and lap times, for the standings / gap view on the Live page."""
    cars_out = []
    for i in range(ac.getCarsCount()):
        try:
            if not ac.isConnected(i):
                continue
            cars_out.append({"i": i, "name": ac.getDriverName(i), "car": ac.getCarName(i),
                             "spline": round(ac.getCarState(i, acsys.CS.NormalizedSplinePosition), 5),
                             "laps": _safe(i, acsys.CS.LapCount), "last": _safe(i, acsys.CS.LastLap),
                             "best": _safe(i, acsys.CS.BestLap), "pit": bool(ac.isCarInPitline(i)),
                             "speed": round(ac.getCarState(i, acsys.CS.SpeedKMH))})
        except Exception:
            pass
    tmp = LIVE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dumps({"t": time.time(), "track": track, "cars": cars_out}))
    os.replace(tmp, LIVE)


def acUpdate(dt):
    global clock, since, live_since
    clock += dt
    since += dt
    live_since += dt
    if live_since >= 0.25:
        live_since = 0.0
        try:
            _write_live()
        except Exception as e:
            ac.log("RaceLogger live: " + str(e))
    if since < 1.0 / HZ:
        return
    since = 0.0
    for i in range(1, ac.getCarsCount()):
        try:
            if ac.isConnected(i):
                _sample(i)
            elif i in cars:
                del cars[i]
        except Exception as e:
            ac.log("RaceLogger: " + str(e))
