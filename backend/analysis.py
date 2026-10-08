"""Distance alignment, delta time, corner detection, per-corner metrics and rule-based insights."""
from functools import lru_cache

import numpy as np

from . import store

G = 9.81
STEP = 1.0          # metres per resampled point
OUT_STEP = 2        # send every Nth point to the browser
CHANNELS = ("speed", "throttle", "brake", "gear", "steer")


def _smooth(a, n):
    n = max(int(n), 1)
    if n == 1:
        return a
    pad = np.pad(a, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def track_length(track, raw=None):
    cfg = store.track_cfg(track)
    if cfg.get("length"):
        return float(cfg["length"])
    if raw is not None and "x" in raw:
        L = float(np.sum(np.hypot(np.diff(raw["x"]), np.diff(raw["z"]))))
        store.set_track(track, length=round(L))
        return L
    return 5000.0


@lru_cache(maxsize=32)
def prep(lap_id):
    """Resample a lap onto a 1 m distance grid. Estimates pedals from acceleration when inputs are missing."""
    meta, raw = store.get_lap(lap_id), store.load_lap(lap_id)
    L = track_length(meta["track"], raw)
    pos = raw["pos"].copy()
    q = max(len(pos) // 4, 1)
    pos[:q] = np.where(pos[:q] > 0.5, pos[:q] - 1, pos[:q])      # samples just before the line
    pos[-q:] = np.where(pos[-q:] < 0.5, pos[-q:] + 1, pos[-q:])  # samples just after the line
    d = pos * L
    keep = np.r_[True, d[1:] > np.maximum.accumulate(d)[:-1]]
    d = d[keep]
    grid = np.arange(0, L, STEP)
    p = {"d": grid, "L": L, "meta": meta}
    for k, v in raw.items():
        if k not in ("pos", "t"):
            p[k] = np.interp(grid, d, v[keep])
    v = np.maximum(p["speed"] / 3.6, 1.0)
    t_raw = raw["t"][keep]
    t = np.interp(grid, d, t_raw)
    lo, hi = grid < d[0], grid > d[-1]
    t[lo] = t_raw[0] - (d[0] - grid[lo]) / v[lo]
    t[hi] = t_raw[-1] + (grid[hi] - d[-1]) / v[hi]
    p["t"] = t - t[0]
    if "gear" in p:
        p["gear"] = np.round(p["gear"])
    vs = _smooth(v, 15)
    acc = vs * np.gradient(vs, STEP) / G
    p["accel"] = acc
    p["est"] = not meta["has_inputs"] or "throttle" not in p
    if p["est"]:
        p["brake"] = np.clip((-acc - 0.6) / 1.5, 0, 1)
        p["throttle"] = np.where(p["brake"] > 0, 0, np.clip((acc + 0.5) / 0.7, 0, 1))
    return p



# ---------- small numpy stand-ins for the two scipy functions used here (keeps the install light) ----------
def find_peaks(x, prominence, distance):
    """Same result as scipy.signal.find_peaks(x, prominence=..., distance=...) for these inputs:
    local maxima (middle of flat tops), then the highest peak wins within `distance`, then prominence >= `prominence`."""
    x = np.asarray(x, dtype=float)
    n, peaks, i = len(x), [], 1
    while i < n - 1:
        if x[i - 1] < x[i]:
            j = i + 1
            while j < n - 1 and x[j] == x[i]:
                j += 1
            if x[j] < x[i]:
                peaks.append((i + j - 1) // 2)
                i = j
        i += 1
    peaks = np.array(peaks, dtype=int)
    if len(peaks) and distance > 1:
        keep = np.ones(len(peaks), bool)
        for k in np.argsort(x[peaks])[::-1]:   # default sort, like scipy, so ties break the same way
            if not keep[k]:
                continue
            j = k - 1
            while j >= 0 and peaks[k] - peaks[j] < distance:
                keep[j] = False
                j -= 1
            j = k + 1
            while j < len(peaks) and peaks[j] - peaks[k] < distance:
                keep[j] = False
                j += 1
        peaks = peaks[keep]
    out = []
    for p in peaks:
        left = x[:p + 1]
        higher = np.flatnonzero(left[:-1] > x[p])
        lmin = left[higher[-1] + 1 if len(higher) else 0:].min()
        right = x[p:]
        higher = np.flatnonzero(right[1:] > x[p])
        rmin = right[:higher[0] + 1 if len(higher) else len(right)].min()
        if x[p] - max(lmin, rmin) >= prominence:
            out.append(p)
    return np.array(out, dtype=int), {}


def nearest(ref_xy, pts, chunk=2048):
    """Distance from each point to the closest reference point, and its index (what a KD-tree query gives)."""
    dist, idx = np.empty(len(pts)), np.empty(len(pts), dtype=int)
    for a in range(0, len(pts), chunk):
        d2 = ((pts[a:a + chunk, None, :] - ref_xy[None, :, :]) ** 2).sum(-1)
        idx[a:a + chunk] = d2.argmin(1)
        dist[a:a + chunk] = np.sqrt(d2[np.arange(len(d2)), idx[a:a + chunk]])
    return dist, idx


def find_corners(ref):
    """Corners = speed minima. Segment k runs from the speed peak before corner k to the peak after it."""
    s = _smooth(ref["speed"], 25)
    n = len(s)
    idx, _ = find_peaks(-s, prominence=10, distance=int(80 / STEP))
    mins = []
    for i in idx:                                    # merge chicane halves
        if mins and (i - mins[-1]) * STEP < 200:
            if s[i] < s[mins[-1]]:
                mins[-1] = i
        else:
            mins.append(int(i))
    if not mins:
        return []
    peaks = [mins[k] + int(np.argmax(s[mins[k]:mins[k + 1]])) for k in range(len(mins) - 1)]
    starts, ends = [0] + peaks, peaks + [n - 1]
    cfg = store.track_cfg(ref["meta"]["track"])
    scale = ref["L"] / cfg["length"] if cfg.get("length") else 1
    names = [[x * scale if i != 1 else x for i, x in enumerate(c)] for c in cfg.get("corners", [])]
    out, used = [], set()
    for k, apex in enumerate(mins):
        name = f"T{k + 1}"
        free = [c for c in names if c[1] not in used]
        if free:
            c = min(free, key=lambda c: _off(c, apex * STEP))
            if _off(c, apex * STEP) < 300:
                name = c[1]
                used.add(name)
        out.append({"name": name, "i0": starts[k], "i1": ends[k], "apex": apex})
    return out


def _runs_start(idx, gap=20):
    """Start of the last contiguous run in a sorted index array."""
    if not len(idx):
        return None
    breaks = np.nonzero(np.diff(idx) > gap)[0]
    return int(idx[breaks[-1] + 1] if len(breaks) else idx[0])


def metrics(p, c):
    i0, i1, ia = c["i0"], c["i1"], c["apex"]
    lo, hi = max(i0, ia - 80), min(i1, ia + 80) + 1
    am = lo + int(np.argmin(p["speed"][lo:hi]))
    br = _runs_start(np.nonzero(p["brake"][i0:am + 1] > 0.15)[0])
    th = np.nonzero(p["throttle"][am:i1 + 1] > 0.6)[0]
    ex = min(am + int(150 / STEP), i1)
    sl = slice(i0, i1 + 1)
    coast = (p["throttle"][sl] < 0.1) & (p["brake"][sl] < 0.1)
    v = np.maximum(p["speed"][sl] / 3.6, 1)
    return {
        "time": round(float(p["t"][i1] - p["t"][i0]), 3),
        "brake": None if br is None else round((i0 + br) * STEP),
        "min_speed": round(float(p["speed"][am]), 1),
        "apex": round(am * STEP),
        "throttle": None if not len(th) else round((am + int(th[0])) * STEP),
        "exit": round(float(p["speed"][ex]), 1),
        "top": round(float(p["speed"][sl].max()), 1),
        "coast": round(float(np.sum(STEP / v[coast])), 2),
        "gear": int(p["gear"][am]) if "gear" in p else None,
    }


def tips(m, r, real, est=False):
    """Plain-language advice for one corner. m = mine, r = reference."""
    out = []
    if real:   # different car class: compare shape, not speed
        if m["brake"] is not None and r["brake"] is not None:
            out.append(f"Braking zone {m['apex'] - m['brake']} m vs reference {r['apex'] - r['brake']} m (shape only, different car)")
        pm, pr = m["min_speed"] / max(m["top"], 1) * 100, r["min_speed"] / max(r["top"], 1) * 100
        if pm < pr - 3:
            out.append(f"Apex at {pm:.0f}% of top speed vs {pr:.0f}%: carry more speed relative to the straight")
        if m["throttle"] is not None and r["throttle"] is not None and m["throttle"] - m["apex"] > r["throttle"] - r["apex"] + 15:
            out.append(f"Reference is back on throttle {m['throttle'] - m['apex'] - (r['throttle'] - r['apex'])} m sooner after the apex")
        return out
    if m["brake"] is not None and r["brake"] is not None:
        db = m["brake"] - r["brake"]
        if db < -8:
            out.append(f"Brake {-db} m later (you brake at {m['brake']} m, reference {r['brake']} m)")
        elif db > 8 and m["min_speed"] < r["min_speed"] - 2:
            out.append(f"You brake {db} m later but lose apex speed: brake earlier, release smoother")
    elif m["brake"] is not None and r["brake"] is None:
        out.append("Reference doesn't brake here: lift or just turn in")
    dv = m["min_speed"] - r["min_speed"]
    if dv < -3:
        out.append(f"Carry {-dv:.0f} km/h more through the apex ({m['min_speed']:.0f} vs {r['min_speed']:.0f})")
    if m["throttle"] is not None and r["throttle"] is not None and m["throttle"] - r["throttle"] > 10:
        out.append(f"Get back on throttle {m['throttle'] - r['throttle']} m earlier")
    de = m["exit"] - r["exit"]
    if de < -4:
        out.append(f"Exit {-de:.0f} km/h slower: open the steering earlier and prioritise the exit")
    dc = m["coast"] - r["coast"]
    if dc > 0.15 and not est:   # coasting from estimated pedals is too rough to compare
        out.append(f"{dc:.2f} s more coasting: commit to brake or throttle")
    if m["gear"] and r["gear"] and m["gear"] != r["gear"]:
        out.append(f"Reference uses gear {r['gear']} at the apex (you {m['gear']})")
    if m["top"] < r["top"] - 5 and de >= -4:
        out.append(f"Top speed {r['top'] - m['top']:.0f} km/h lower on the next straight (tow, setup or wing)")
    return out


def _series(p, i_step):
    s = {}
    for k in CHANNELS:
        if k in p:
            s[k] = np.round(p[k][::i_step], 3).tolist()
    return s


def compare(a_id, b_id, ideal_of=None):
    return compare_p(ideal_prep(ideal_of) if ideal_of else prep(int(a_id)), prep(int(b_id)))


def compare_p(a, b):
    n = min(len(a["d"]), len(b["d"]))
    if len(a["d"]) != len(b["d"]):         # different configured lengths: scale b onto a
        for k in ("t",) + CHANNELS:
            if k in b:
                b = dict(b, **{k: np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(b[k])), b[k])})
        a = dict(a, **{k: a[k][:n] for k in ("d", "t") + CHANNELS if k in a})
    delta = a["t"][:n] - b["t"][:n]
    real = store.car_info(a["meta"]["car"])["class"] != store.car_info(b["meta"]["car"])["class"]
    corners = []
    for c in find_corners(b):
        if c["i1"] >= n:
            continue
        ma, mb = metrics(a, c), metrics(b, c)
        corners.append({**c, "start": c["i0"] * STEP, "end": c["i1"] * STEP, "apex_d": c["apex"] * STEP,
                        "loss": round(ma["time"] - mb["time"], 3), "a": ma, "b": mb, "tips": tips(ma, mb, real, a["est"] or b["est"])})
    worst = sorted([c for c in corners if c["loss"] > 0.02], key=lambda c: -c["loss"])[:3]
    insights = [{"corner": c["name"], "loss": c["loss"], "start": c["start"], "end": c["end"],
                 "tips": c["tips"][:3] or ["No single cause: compare the line on the map and the speed trace"]} for c in worst]

    # Track map from whichever lap has coordinates; colour = local time gain/loss per 100 m
    src = a if "x" in a else b
    rate = np.gradient(_smooth(delta, 40), STEP) * 100
    ms = int(5 / STEP)
    mp = {"x": np.round(src["x"][:n:ms], 1).tolist(), "z": np.round(src["z"][:n:ms], 1).tolist(),
          "rate": np.round(rate[::ms], 4).tolist(), "step": ms * STEP,
          "ta": np.round(a["t"][:n:ms], 3).tolist(), "tb": np.round(b["t"][:n:ms], 3).tolist()} if "x" in src else None
    if mp and not real and "x" in a and "x" in b:   # same game, same world coordinates: overlay both lines
        mp.update(bx=np.round(b["x"][:n:ms], 1).tolist(), bz=np.round(b["z"][:n:ms], 1).tolist())

    def meta(p):
        m = dict(p["meta"])
        m.update(car_name=store.car_info(m["car"])["name"], est=bool(p["est"]), setup=store.parse_note(m.get("note")),
                 source_label=store.SOURCES.get(m["source"], m["source"]))
        return m

    return {
        "a": meta(a), "b": meta(b), "L": float(n * STEP), "step": OUT_STEP * STEP,
        "d": a["d"][:n:OUT_STEP].tolist(), "a_s": _series({k: v[:n] for k, v in a.items() if k in CHANNELS}, OUT_STEP),
        "b_s": _series({k: v[:n] for k, v in b.items() if k in CHANNELS}, OUT_STEP),
        "delta": np.round(delta[::OUT_STEP], 3).tolist(), "total": round((a["meta"]["lap_ms"] - b["meta"]["lap_ms"]) / 1000, 3),
        "corners": corners, "insights": insights, "map": mp, "real": real,
        "track_name": store.track_cfg(a["meta"]["track"]).get("name", a["meta"]["track"].title()),
    }


def lap_map(lap_id, n=400):
    p = prep(int(lap_id))
    if "x" not in p:
        return None
    idx = np.linspace(0, len(p["d"]) - 1, n).astype(int)
    return {"x": np.round(p["x"][idx], 1).tolist(), "z": np.round(p["z"][idx], 1).tolist()}


def ideal(lap_ids, sectors=30):
    """Theoretical best: sum of each mini-sector's best time across laps."""
    best = None
    for i in lap_ids:
        p = prep(int(i))
        b = np.interp(np.linspace(0, p["d"][-1], sectors + 1), p["d"], p["t"])
        st = np.diff(b)
        best = st if best is None else np.minimum(best, st)
    return None if best is None else int(best.sum() * 1000)


# ---------- ideal lap, sectors, sessions, stats ----------

def player_best_ids(car, track, limit=15):
    return [r["id"] for r in store.q("SELECT id FROM laps WHERE source='player' AND valid=1 AND car=? AND track=? "
                                     "ORDER BY lap_ms LIMIT ?", (car, track, limit))]


@lru_cache(maxsize=16)
def _ideal(ids, k=30):
    ps = [prep(i) for i in ids]
    n = min(len(p["d"]) for p in ps)
    keys = [k_ for k_ in ("speed", "throttle", "brake", "gear", "steer", "x", "z", "accel") if all(k_ in p for p in ps)]
    out = {k_: np.zeros(n) for k_ in keys + ["t"]}
    edges = np.linspace(0, n - 1, k + 1).astype(int)
    t_acc, src = 0.0, []
    for s in range(k):
        i0, i1 = edges[s], edges[s + 1]
        best = min(ps, key=lambda p: p["t"][i1] - p["t"][i0])
        src.append(best["meta"]["id"])
        out["t"][i0:i1 + 1] = t_acc + best["t"][i0:i1 + 1] - best["t"][i0]
        for k_ in keys:
            out[k_][i0:i1 + 1] = best[k_][i0:i1 + 1]
        t_acc = float(out["t"][i1])
    meta = dict(ps[0]["meta"], id=0, driver="Ideal lap", lap_ms=int(round(t_acc * 1000)), origin=None, note="",
                sources=sorted(set(src)))
    return {**out, "d": ps[0]["d"][:n], "L": ps[0]["L"], "meta": meta, "est": False}


def ideal_prep(lap_id):
    """Best mini-sectors of the player's top laps on this lap's car + track, stitched into one lap."""
    me = store.get_lap(lap_id)
    return _ideal(tuple(player_best_ids(me["car"], me["track"])))


def sectors(p, n=3):
    b = np.interp(np.linspace(0, p["d"][-1], n + 1), p["d"], p["t"])
    st = np.diff(b)
    st *= (p["meta"]["lap_ms"] / 1000) / st.sum()
    return [round(float(x), 3) for x in st]


def stats(car, track):
    laps = store.q("SELECT id, lap_ms, valid, created, note FROM laps WHERE source='player' AND car=? AND track=? "
                   "ORDER BY created", (car, track))
    sess = store.sessions(laps)
    ids = player_best_ids(car, track)
    ideal = _ideal(tuple(ids)) if ids else None
    board = []
    for r in store.q("SELECT * FROM laps WHERE source IN ('online','ai') AND valid=1 AND car=? AND track=? "
                     "ORDER BY lap_ms", (car, track)):
        board.append({**r, "kind": "ghost", "sectors": sectors(prep(r["id"]))})
    if ids:
        me = store.get_lap(ids[0])
        board.append({**me, "kind": "me", "sectors": sectors(prep(ids[0]))})
        board.append({**ideal["meta"], "kind": "ideal", "sectors": sectors(ideal)})
    board.sort(key=lambda r: r["lap_ms"])
    best_sec = [min(r["sectors"][i] for r in board) for i in range(3)] if board else []
    return {"laps": [{**l, "session": next(s["id"] for s in sess if l["id"] in s["ids"])} for l in laps],
            "sessions": sess, "board": board, "best_sectors": best_sec, "best_id": ids[0] if ids else None,
            "ideal_ms": ideal["meta"]["lap_ms"] if ideal else None,
            "ghost_best": next((r["lap_ms"] for r in board if r["kind"] == "ghost"), None)}


def session_view(lap_id):
    me = store.get_lap(lap_id)
    laps = store.q("SELECT id, lap_ms, valid, created, note FROM laps WHERE source='player' AND car=? AND track=? "
                   "ORDER BY created", (me["car"], me["track"]))
    s = next(x for x in store.sessions(laps) if lap_id in x["ids"])
    rows = [l for l in laps if l["id"] in s["ids"]]
    valid = [l for l in rows if l["valid"]] or rows
    best = min(valid, key=lambda l: l["lap_ms"])
    bp = prep(best["id"])
    corners = find_corners(bp)
    n = len(bp["d"])
    out_rows, step = [], 4
    for l in rows:
        p = prep(l["id"])
        m = min(n, len(p["d"]))
        times = [round(float(p["t"][min(c["i1"], m - 1)] - p["t"][min(c["i0"], m - 1)]), 3) for c in corners]
        out_rows.append({**l, "corner_times": times, "speed": np.round(p["speed"][:m:step], 1).tolist()})
    var = []
    for k, c in enumerate(corners):
        ts = np.array([r["corner_times"][k] for r in out_rows if r["valid"]] or [r["corner_times"][k] for r in out_rows])
        var.append({"name": c["name"], "start": c["i0"] * STEP, "end": c["i1"] * STEP, "std": round(float(ts.std()), 3),
                    "best": round(float(ts.min()), 3), "worst": round(float(ts.max()), 3)})
    return {**s, "car_name": store.car_info(me["car"])["name"],
            "track_name": store.track_cfg(me["track"]).get("name", me["track"].title()),
            "best_id": best["id"], "laps": out_rows, "corners": var, "d": bp["d"][::step].tolist()}


# ---------- cut detection for other drivers' laps (the game doesn't share their penalties) ----------
MAX_DEV_M, MAX_SHORT_M = 15.0, 20.0


@lru_cache(maxsize=8)
def _line_ref(track, ref_id):
    p = prep(ref_id)
    return np.c_[p["x"], p["z"]], float(np.sum(np.hypot(np.diff(p["x"]), np.diff(p["z"])))), p["d"]


def line_check(track, x, z):
    """How far a lap strays from my best clean line on this track. None if there's no line to compare with yet."""
    r = store.q("SELECT id FROM laps WHERE source='player' AND valid=1 AND track=? ORDER BY lap_ms LIMIT 1", (track,))
    if not r or len(x) < 50:
        return None
    ref_xy, ref_len, ref_d = _line_ref(track, r[0]["id"])
    dist, idx = nearest(ref_xy, np.c_[x, z])
    worst = int(np.argmax(dist))
    dev, short = float(dist[worst]), ref_len - float(np.sum(np.hypot(np.diff(x), np.diff(z))))
    cut = dev > MAX_DEV_M or short > MAX_SHORT_M
    return {"cut": cut, "dev": round(dev, 1), "short": round(short), "at": round(float(ref_d[idx[worst]]))}


def _off(c, dist):
    """Distance from a named corner: 0 inside its section (AC sections.ini gives start/end), else to its middle."""
    if len(c) >= 4 and c[2] <= dist <= c[3]:
        return 0
    return abs(c[0] - dist)


def cut_reason(track, x, z, off_pos=None):
    """Plain words for why a lap is invalid: a shortcut through a corner, or wheels off somewhere."""
    chk = line_check(track, x, z)
    if chk and chk["cut"]:
        return f"cut at {corner_at(track, chk['at'])} ({chk['dev']:.0f} m off the line)"
    if off_pos is not None:
        L = store.track_cfg(track).get("length")
        if L:
            return f"wheels off at {corner_at(track, round(off_pos * L))}"
    return "more than 2 wheels off track"


def corner_at(track, dist):
    names = store.track_cfg(track).get("corners", [])
    return min(names, key=lambda c: _off(c, dist))[1] if names else f"{dist} m"
