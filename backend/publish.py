"""The always-on copy of the public site: plain files on Cloudflare Pages, so it stays up with this PC off.

Every page and number comes from the same code as the site Ghostline serves here: app.py's handlers in the public
view (other drivers as initials, no local paths), written out as JSON next to the pages. Each lap is compared with
its closest references and your ideal lap; Ghostline on your PC compares any two. The Live page connects to this PC
through the tunnel (live_host in config/site.json) whenever Ghostline is running.

Arrays that many comparisons share (a lap's speed, inputs, distance and line) are stored once per lap, in
data/lap/<id>.json, and a comparison points at them with {"$": [lap, key, n]}: the first n values of that array.
frontend/js/app.js puts them back. That keeps the copy about a fifth of the size.

Publishing: build() writes data/site, then Cloudflare's own tool (wrangler, through npx) uploads
what changed. It runs after a session, once Assetto Corsa is closed, and again on the way out.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import numpy as np
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from . import analysis, settings, store

OUT = settings.DATA_DIR / "site"
REFS_PER_LAP = 3            # each lap against its 3 closest references (plus the fastest ghost for the ideal lap)
WRANGLER = "wrangler@4.150.0"   # pinned: the exact Cloudflare tool every publish runs
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
STATUS = {"state": "off", "at": None, "detail": ""}


def configured():
    c = credentials()
    return bool(settings.PAGES_PROJECT and settings.PUBLIC_HOST and c["account_id"] and c["api_token"])


def credentials():
    """Cloudflare account id + API token (Pages: Edit), from config/cloudflare.json or the environment."""
    c = {}
    try:
        c = json.loads(settings.CLOUDFLARE_CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"account_id": str(os.environ.get("CLOUDFLARE_ACCOUNT_ID") or c.get("account_id") or "").strip(),
            "api_token": str(os.environ.get("CLOUDFLARE_API_TOKEN") or c.get("api_token") or "").strip()}


# ---------- build ----------

def _dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(jsonable_encoder(obj), separators=(",", ":"), ensure_ascii=False, allow_nan=False)   # as the API
    path.write_text(text, encoding="utf-8")


def _lap_arrays(lap_id):
    """The arrays of one lap that comparisons repeat, rounded exactly the way analysis.compare_p rounds them."""
    p = analysis.prep(lap_id)
    out = {"d": p["d"][::analysis.OUT_STEP].tolist()}
    out.update({f"s.{k}": v for k, v in analysis._series({k: p[k] for k in analysis.CHANNELS if k in p}, analysis.OUT_STEP).items()})
    ms = int(5 / analysis.STEP)
    out["t5"] = np.round(p["t"][::ms], 3).tolist()
    if "x" in p:
        out["x5"], out["z5"] = np.round(p["x"][::ms], 1).tolist(), np.round(p["z"][::ms], 1).tolist()
    return out


# which per-lap array each field of a comparison can be: (field path, per-lap key)
SHARED = [(("d",), "d")] + [(("a_s", k), f"s.{k}") for k in analysis.CHANNELS] + \
    [(("b_s", k), f"s.{k}") for k in analysis.CHANNELS] + \
    [(("map", "x"), "x5"), (("map", "z"), "z5"), (("map", "bx"), "x5"), (("map", "bz"), "z5"),
     (("map", "ta"), "t5"), (("map", "tb"), "t5")]


def _share(c, lap_arrays):
    """Swap the arrays that are a prefix of lap a's or lap b's own arrays for a pointer to them."""
    # on copies: the comparison comes from the site's cache, which must keep serving the full arrays
    c = {**c, **{k: dict(c[k]) for k in ("a_s", "b_s", "map") if isinstance(c.get(k), dict)}}
    ids = [i for i in (c["a"].get("id"), c["b"].get("id")) if isinstance(i, int) and i in lap_arrays]
    for path, key in SHARED:
        holder = c
        for p in path[:-1]:
            holder = holder.get(p) if isinstance(holder, dict) else None
        v = holder.get(path[-1]) if isinstance(holder, dict) else None
        if not isinstance(v, list) or not v:
            continue
        for i in ids:
            src = lap_arrays[i].get(key)
            if src is not None and len(src) >= len(v) and src[:len(v)] == v:
                holder[path[-1]] = {"$": [i, key, len(v)]}
                break
    return c


def unshare(c, lap_files):
    """The reverse of _share (what the browser does): used by the tests."""
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("$"), list):
                i, key, n = o["$"]
                return lap_files[i][key][:n]
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list) and o and isinstance(o[0], (dict, list)):
            return [walk(v) for v in o]
        return o
    return walk(c)


def pairs_for(lap, refs, best_ids):
    """Which references a lap is published against: its closest few, the fastest non-player lap (the ideal lap's
    default), and for the best lap of each car + track everything the Stats and References pages link to."""
    if lap["id"] in best_ids:
        picked = [r for r in refs if r["source"] != "player"] + refs[:REFS_PER_LAP]
    else:
        ghost = next((r for r in refs if r["source"] != "player"), None)
        picked = refs[:REFS_PER_LAP] + ([ghost] if ghost else [])
    seen, out = set(), []
    for r in picked:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r["id"])
    return out


def build(out=OUT, log=print):
    """Write the whole public site into `out` (replaced only once it's complete). Returns the number of files."""
    from . import app as web   # the handlers and page templates (imported late: app imports the recorder)

    req = SimpleNamespace(state=SimpleNamespace(admin=False))
    tmp = out.with_name(out.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    data = tmp / "data"
    t0 = time.time()

    st = web.state(req)
    _dump(data / "state.json", st)
    _dump(data / "content.json", web.content_list())
    laps = web.laps(req)
    _dump(data / "laps.json", laps)

    best_ids = {g["best_id"] for g in st["groups"]}
    lap_arrays = {}
    for l in laps:
        try:
            lap_arrays[l["id"]] = _lap_arrays(l["id"])
        except Exception as e:   # a lap file that won't load: leave that lap out rather than fail the copy
            log(f"publish: lap {l['id']} skipped ({e})")
    for i, arr in lap_arrays.items():
        _dump(data / "lap" / f"{i}.json", arr)
        _dump(data / "map" / f"{i}.json", web.lap_map(i))

    n_cmp, ideal_alias, session_of = 0, {}, {}
    groups = {(g["car"], g["track"]): g["best_id"] for g in st["groups"]}
    for l in laps:
        a = l["id"]
        if a not in lap_arrays:
            continue
        refs = [r for r in web.references(req, a) if r["id"] in lap_arrays]
        chosen = pairs_for(l, refs, best_ids)
        written = []
        for b in chosen:
            try:
                _dump(data / "compare" / f"{a}-{b}.json", _share(web.compare(req, a, b), lap_arrays))
            except (HTTPException, ValueError):   # no comparison, or one the API couldn't send either
                continue
            written.append(b)
            n_cmp += 1
        _dump(data / "refs" / f"{a}.json", [r for r in refs if r["id"] in written])
        if l["source"] == "player":
            best = groups.get((l["car"], l["track"]))
            if best:
                ideal_alias[a] = best   # every lap of yours shares its car + track's ideal lap
            if a not in session_of:   # one file per session: every lap in it shows the same page
                try:
                    v = web.session(a)
                except HTTPException:
                    v = None
                if v:
                    key = min(v["ids"])
                    _dump(data / "session" / f"{key}.json", v)
                    session_of.update({i: key for i in v["ids"]})
    # the ideal lap: one per car + track, against what its best lap is published against
    for (car, track), best in groups.items():
        for b in [p.stem.split("-")[1] for p in (data / "compare").glob(f"{best}-*.json")]:
            try:
                _dump(data / "compare" / f"i{best}-{b}.json", _share(web.compare(req, best, int(b), True), lap_arrays))
            except (HTTPException, ValueError):
                continue
            n_cmp += 1
        if SAFE_ID.match(car) and SAFE_ID.match(track):
            _dump(data / "stats" / f"{car}__{track}.json", web.stats(req, car, track))
    _dump(data / "ideal.json", ideal_alias)
    _dump(data / "sessions.json", session_of)

    _pages(tmp, web)
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    files = sum(1 for p in out.rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    log(f"publish: built {files} files ({size / 1e6:.0f} MB, {n_cmp} comparisons) in {time.time() - t0:.0f} s")
    return files


def _pages(out, web):
    """The pages (one HTML file per page, with its own title and description), assets and Cloudflare's rules."""
    front = web.FRONT
    for d in ("css", "js", "fonts", "img", "vendor"):
        if (front / d).exists():
            shutil.copytree(front / d, out / d)
    if (front / "favicon.ico").exists():
        shutil.copy2(front / "favicon.ico", out / "favicon.ico")
    marker = f'<meta name="ghostline-static" content="{settings.LIVE_HOST}">'
    for page in web.PAGES:
        status = 404 if page == "404" else 200
        html = web.index(page, status).body.decode("utf-8").replace("</head>", marker + "</head>", 1)
        (out / f"{page or 'index'}.html").write_text(html, encoding="utf-8")
    (out / "robots.txt").write_bytes(web.robots().body)
    if settings.PUBLIC_HOST:
        (out / "sitemap.xml").write_bytes(web.sitemap().body)
    # Cloudflare Pages: app pages with ids in the path get their page's HTML, old share links go to the comparison
    (out / "_redirects").write_text("\n".join([
        "/s/:a/:b /compare/:a/:b 301",
        "/compare/* /compare 200",
        "/session/* /session 200",
        "/stats/* /stats 200",
    ]) + "\n", encoding="utf-8")
    csp = web.CSP.replace("connect-src 'self'", f"connect-src 'self' https://{settings.LIVE_HOST}" if settings.LIVE_HOST else "connect-src 'self'")
    sec = {**web.SEC_HEADERS, "Content-Security-Policy": csp, "Strict-Transport-Security": "max-age=31536000; includeSubDomains"}
    lines = ["/*"] + [f"  {k}: {v}" for k, v in sec.items()]
    lines += ["/data/*", "  Cache-Control: public, max-age=300"]   # laps change after every session
    for d in ("css", "js", "fonts", "img", "vendor"):
        lines += [f"/{d}/*", "  Cache-Control: public, max-age=3600"]
    (out / "_headers").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- upload ----------

NODE_MIN = 22   # wrangler 4 needs Node.js 22 or newer


def node_major(text):
    m = re.match(r"v?(\d+)\.", (text or "").strip())
    return int(m.group(1)) if m else 0


def tools_problem():
    """Why an upload can't work on this PC (checked before spending a minute on the build), or None."""
    node = shutil.which("node")
    if not node or not (shutil.which("npx") or shutil.which("npx.cmd")):
        return f"Node.js {NODE_MIN} or newer is needed to publish (nodejs.org): it runs Cloudflare's upload tool"
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20, **flags).stdout
    except (OSError, subprocess.SubprocessError):
        v = ""
    if node_major(v) < NODE_MIN:
        return f"Node.js {NODE_MIN} or newer is needed to publish; this PC has {v.strip() or 'an unknown version'} (nodejs.org)"
    return None


class Busy(Exception):
    pass


class _OneAtATime:
    """Across processes too: the tray app and `Ghostline.exe --publish` build into the same folder."""
    STALE = 3600

    def __init__(self):
        self.path = settings.DATA_DIR / "publish.lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime < self.STALE:
                        raise Busy("another publish is running") from None
                    self.path.unlink()   # left behind by a publish that was killed
                except FileNotFoundError:
                    pass
        raise Busy("another publish is running")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)

def deploy(out=OUT, log=print):
    """Upload the built copy with wrangler (Cloudflare's tool; needs Node.js). Only changed files are sent."""
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise RuntimeError("Node.js is needed to publish (nodejs.org); it provides Cloudflare's upload tool")
    c = credentials()
    env = {**os.environ, "CLOUDFLARE_ACCOUNT_ID": c["account_id"], "CLOUDFLARE_API_TOKEN": c["api_token"],
           "WRANGLER_SEND_METRICS": "false", "CI": "1"}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def run(*args):
        r = subprocess.run([npx, "--yes", WRANGLER, *args], env=env, capture_output=True, text=True, timeout=1800,
                           encoding="utf-8", errors="replace", **flags)
        return r.returncode, (r.stdout + r.stderr)[-2000:]

    code, text = run("pages", "deploy", str(out), "--project-name", settings.PAGES_PROJECT, "--branch", "main",
                     "--commit-dirty=true")
    if code != 0 and re.search(r"not found|does not exist|8000007", text, re.I):   # first publish: make the project
        run("pages", "project", "create", settings.PAGES_PROJECT, "--production-branch", "main")
        code, text = run("pages", "deploy", str(out), "--project-name", settings.PAGES_PROJECT, "--branch", "main",
                         "--commit-dirty=true")
    if code != 0:
        raise RuntimeError("upload failed: " + " ".join(text.split())[-400:])
    url = re.search(r"https://\S+\.pages\.dev", text)
    STATUS["url"] = url.group(0) if url else STATUS.get("url")   # the project's own *.pages.dev address
    log(f"publish: online at https://{settings.PUBLIC_HOST}" + (f" ({url.group(0)})" if url else ""))


# ---------- when to publish ----------

def signature():
    """Changes whenever anything the public site shows changes: laps added, removed, re-checked or annotated."""
    rows = store.q("SELECT id, valid, lap_ms, note, driver FROM laps ORDER BY id")
    return hashlib.sha1((json.dumps(rows) + settings.LIVE_HOST + settings.PUBLIC_HOST).encode()).hexdigest()


class Publisher(threading.Thread):
    """Publishes after a session: once laps have changed, nothing's been driven for QUIET seconds and the game is
    closed (building takes a minute or two of CPU, never while you drive)."""
    QUIET, EVERY = 120, 60

    def __init__(self, game_running, driving):
        super().__init__(daemon=True, name="publish")
        self.game_running, self.driving = game_running, driving
        self.lock, self.last_change, self.seen = threading.Lock(), time.time(), None

    def due(self):
        sig = signature()
        if sig != self.seen:
            self.seen, self.last_change = sig, time.time()
        return sig != store.kv_get("published_sig")

    def publish(self, why="", force=False):
        with self.lock:
            sig = signature()
            if sig == store.kv_get("published_sig") and not force:
                return True
            problem = tools_problem()
            if problem:
                STATUS.update(state="error", at=time.time(), detail=problem)
                print("publish:", problem)
                return False
            STATUS.update(state="publishing", detail=why)
            print(f"publish: building the online copy ({why})")
            try:
                with _OneAtATime():
                    build()
                    deploy()
                store.kv_set("published_sig", sig)
                STATUS.update(state="ok", at=time.time(), detail="")
                return True
            except Exception as e:
                STATUS.update(state="error", at=time.time(), detail=str(e)[:300])
                print("publish:", e)
                return False

    def run(self):
        fails = 0
        while True:
            time.sleep(self.EVERY * min(2 ** fails, 30))   # after a failure, try again less and less often
            try:
                if self.due() and time.time() - self.last_change > self.QUIET and not self.driving() and not self.game_running():
                    fails = 0 if self.publish("after the session") else fails + 1
            except Exception as e:
                print("publish:", e)

    def finish(self):
        """On the way out: publish what's new (Ghostline stays in the background until the upload is done)."""
        try:
            if self.due():
                print("Publishing the online site before closing")
                self.publish("on exit")
        except Exception as e:
            print("publish:", e)
