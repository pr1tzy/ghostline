"""Ghostline API + static site.

Security model (no login): the site is read-only for everyone except requests made on this PC
directly to 127.0.0.1:<port>. Anything that arrives through Cloudflare (or any proxy) is public:
GET only, other drivers' names masked, no local paths, smaller live stream.
"""
import asyncio
import json
import mimetypes
import os
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query, Request
from html import escape

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from . import analysis, content, ingest, settings, share, store

for _ext, _type in ((".otf", "font/otf"), (".woff2", "font/woff2"), (".svg", "image/svg+xml"), (".js", "text/javascript")):
    mimetypes.add_type(_type, _ext)
from .recorder import recorder

PORT, PUBLIC_HOST = settings.PORT, settings.PUBLIC_HOST
LOCAL_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip")
MAX_PUBLIC_STREAMS = 40
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'; object-src 'none'")
SEC_HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
               "Referrer-Policy": "strict-origin-when-cross-origin", "Cross-Origin-Opener-Policy": "same-origin",
               "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_streams = 0


def is_admin(request: Request):
    h = request.headers
    return (request.client is not None and request.client.host == "127.0.0.1" and h.get("host") in LOCAL_HOSTS
            and not any(k in h for k in PROXY_HEADERS))


@app.middleware("http")
async def guard(request: Request, call_next):
    host = request.headers.get("host", "")
    if host not in LOCAL_HOSTS and not (PUBLIC_HOST and host == PUBLIC_HOST):   # blocks DNS rebinding / unknown hostnames
        return JSONResponse({"detail": "unknown host"}, 421)
    request.state.admin = is_admin(request)
    if not request.state.admin and request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "read-only"}, 403)
    resp = await call_next(request)
    resp.headers.update(SEC_HEADERS)
    if not request.state.admin:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith(("/vendor/", "/img/", "/css/", "/js/", "/fonts/")):
            resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def _mask(l, admin):
    """Public view: hide other people's names and internal fields."""
    if admin:
        return l
    sample = str(l.get("origin") or "").startswith("sample:")
    l = {k: v for k, v in l.items() if k not in ("origin", "note")}
    if l.get("source") in ("online", "ai") and not sample:
        l["driver"] = initials(l.get("driver", "")) or ("Online driver" if l["source"] == "online" else "AI driver")
    return l


def initials(name):
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name) if p and not p.isdigit()]
    return ".".join(p[0].upper() for p in parts[:3]) + "." if parts else ""


def _lap_out(l, admin=True):
    l = {**l, "setup": store.parse_note(l.get("note")), "car_name": store.car_info(l["car"])["name"], "source_label": store.SOURCES.get(l.get("source"), l.get("source", "")),
         "track_name": store.track_cfg(l["track"]).get("name", l["track"].replace("_", " ").title())}
    return _mask(l, admin)


@app.get("/api/state")
def state(request: Request):
    admin = request.state.admin
    groups = []
    for g in store.q("SELECT car, track, COUNT(*) n, MIN(lap_ms) best, MAX(created) last FROM laps "
                     "WHERE source='player' AND valid=1 GROUP BY car, track ORDER BY last DESC"):
        ids = [r["id"] for r in store.q("SELECT id FROM laps WHERE source='player' AND valid=1 AND car=? AND track=? "
                                        "ORDER BY lap_ms LIMIT 15", (g["car"], g["track"]))]
        ref = store.q("SELECT MIN(lap_ms) m FROM laps WHERE source!='player' AND valid=1 AND car=? AND track=?",
                      (g["car"], g["track"]))[0]["m"]
        groups.append({**_lap_out(g), "best_id": ids[0], "ideal": analysis.ideal(ids), "ref_best": ref})
    total = store.q("SELECT COUNT(*) n FROM laps")[0]["n"]
    return {"admin": admin, "groups": groups, "total": total, "samples": store.sample_count(),
            "app": ingest.app_status() if admin else None,
            "recorder": recorder.state, "latest_best": groups[0]["best_id"] if groups else None}


@app.get("/api/laps")
def laps(request: Request, car: str | None = None, track: str | None = None, source: str | None = None):
    return [_lap_out(l, request.state.admin) for l in store.list_laps(car, track, source)]


@app.get("/api/laps/{lap_id}/map")
def lap_map(lap_id: int):
    if not store.get_lap(lap_id):
        raise HTTPException(404)
    return analysis.lap_map(lap_id)


@app.delete("/api/laps/{lap_id}")
def delete(lap_id: int):
    store.delete_lap(lap_id)
    _compare.cache_clear()
    return {"ok": True}


@app.get("/api/references/{lap_id}")
def references(request: Request, lap_id: int):
    return [_lap_out(l, request.state.admin) for l in store.references(lap_id)]


@lru_cache(maxsize=128)
def _compare(a, b, ideal=False, version=0):
    return analysis.compare(a, b, ideal_of=a if ideal else None)


def _resolve(a, b, ideal):
    if not store.get_lap(a) or (b is not None and not store.get_lap(b)):
        raise HTTPException(404, "lap not found")
    if b is None:
        refs = [r for r in store.references(a) if not ideal or r["source"] != "player"] or store.references(a)
        if not refs:
            raise HTTPException(404, "no reference lap for this track yet")
        b = refs[0]["id"]
    version = store.q("SELECT COUNT(*) n FROM laps")[0]["n"] if ideal else 0   # ideal changes as laps arrive
    return _compare(a, b, ideal, version), b


@app.get("/api/compare")
def compare(request: Request, a: int, b: int | None = None, ideal: bool = False):
    c, _ = _resolve(a, b, ideal)
    return {**c, "a": _mask(c["a"], request.state.admin), "b": _mask(c["b"], request.state.admin)}


@app.get("/api/content")
def content_list():
    """Official tracks found in the AC install (layouts grouped), with how many laps each has here."""
    cat = content.catalog()
    n = {r["track"]: r["n"] for r in store.q("SELECT track, COUNT(*) n FROM laps GROUP BY track")}
    groups = {}
    for k, v in cat["tracks"].items():
        if not k.startswith(("ks_drag", "drift")):
            groups.setdefault(k if k in content.TRACKS else k.rpartition("-")[0], []).append((k, v))
    tracks = []
    for base, ls in groups.items():
        names = [v["name"] for _, v in ls]
        name = os.path.commonprefix(names).rstrip(" -") if len(ls) > 1 else names[0]
        tracks.append({"id": base, "name": name or names[0], "layouts": len(ls), "laps": sum(n.get(k, 0) for k, _ in ls)})
    return {"cars": len(cat["cars"]), "classes": len({c["class"] for c in cat["cars"].values()}),
            "layouts": sum(len(ls) for ls in groups.values()), "tracks": tracks}


@app.get("/api/stats")
def stats(request: Request, car: str = Query(max_length=80), track: str = Query(max_length=80)):
    st = analysis.stats(car, track)
    admin = request.state.admin
    st["board"] = [_mask(r, admin) for r in st["board"]]
    st["laps"] = [{k: v for k, v in l.items() if k != "note"} for l in st["laps"]]
    return st


@app.get("/api/session/{lap_id}")
def session(lap_id: int):
    l = store.get_lap(lap_id)
    if not l or l["source"] != "player":
        raise HTTPException(404)
    v = analysis.session_view(lap_id)
    v["laps"] = [{k: x for k, x in r.items() if k != "note"} for r in v["laps"]]
    return v


class Note(BaseModel):
    setup: str = Field("", max_length=80)
    tyres: str = Field("", max_length=80)
    fuel: str = Field("", max_length=80)
    conditions: str = Field("", max_length=80)
    notes: str = Field("", max_length=80)


@app.put("/api/laps/{lap_id}/note")
def put_note(lap_id: int, n: Note):
    if not store.get_lap(lap_id):
        raise HTTPException(404)
    store.set_note(lap_id, n.model_dump())
    analysis.prep.cache_clear()
    _compare.cache_clear()
    return {"ok": True}


def _share_key(a: str):
    ideal = a.startswith("i")
    try:
        return int(a[1:] if ideal else a), ideal
    except ValueError:
        raise HTTPException(404)


@app.get("/s/{a}/{b}", include_in_schema=False)
def share_page(request: Request, a: str, b: int):
    """Link preview page for one comparison; people are sent straight on to the app."""
    lap, ideal = _share_key(a)
    c, b = _resolve(lap, b, ideal)
    t = c["total"]
    title = f"{c['track_name']}: {'ideal ' if ideal else ''}{_fmt(c['a']['lap_ms'])} vs ghost {_fmt(c['b']['lap_ms'])} ({t:+.3f}s)"
    desc = (f"Biggest loss: {c['insights'][0]['corner']} +{c['insights'][0]['loss']:.3f}s. " if c["insights"] else "") + \
        "Corner-by-corner telemetry on Ghostline."
    base = f"https://{PUBLIC_HOST}/" if PUBLIC_HOST else str(request.base_url)
    img = f"{base}og/{escape(a)}/{b}.png"
    url = f"/compare/{escape(a)}/{b}"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title>
<meta property="og:type" content="website"><meta property="og:site_name" content="Ghostline">
<meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(desc)}">
<meta property="og:image" content="{img}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(desc)}"><meta name="twitter:image" content="{img}">
<meta name="theme-color" content="#07060d"><meta http-equiv="refresh" content="0;url={url}">
</head><body style="background:#07060d;color:#eeeaf6;font-family:sans-serif"><a href="{url}" style="color:#3ef0ff">Open the comparison</a></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=300"})


@app.get("/og/{a}/{b}.png", include_in_schema=False)
def share_image(a: str, b: int):
    lap, ideal = _share_key(a)
    c, b = _resolve(lap, b, ideal)
    key = f"{a}_{b}_{c['a']['lap_ms']}_{c['b']['lap_ms']}"
    return FileResponse(share.render(c, key), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def _fmt(ms):
    s = ms / 1000
    return f"{int(s // 60)}:{s % 60:06.3f}"


class F1Req(BaseModel):
    year: int = Field(ge=2018, le=2100)
    gp: str = Field(max_length=60)
    session: str = Field("Q", max_length=12)
    driver: str | None = Field(None, max_length=4)
    track: str | None = Field(None, max_length=60)


@app.post("/api/import/f1")
def import_f1(r: F1Req):
    try:
        lap_id = ingest.import_f1(r.year, r.gp, r.session, r.driver or None, r.track or None)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"id": lap_id, "duplicate": lap_id is None}


class Toggle(BaseModel):
    on: bool


@app.post("/api/recorder")
def toggle(t: Toggle):
    recorder.set_enabled(t.on)
    return recorder.state


@app.post("/api/install-app")
def install():
    try:
        return ingest.install_app()
    except Exception as e:
        raise HTTPException(400, str(e))


PUBLIC_LIVE_KEYS = ("connected", "recording", "enabled", "car", "track", "car_name", "lap_ms", "pos", "speed", "gear",
                    "throttle", "brake", "delta", "last_ms", "best_ms", "ref_id", "recent")


def _public_live(st):
    d = {k: v for k, v in st.items() if k not in ("driver", "error")}
    if d.get("standings"):
        d["standings"] = [{**c, "name": "You" if c["me"] else (initials(c["name"]) or "Driver")} for c in d["standings"]]
    return d


@app.get("/api/live")
async def live(request: Request):
    global _streams
    admin = request.state.admin
    if not admin and _streams >= MAX_PUBLIC_STREAMS:
        raise HTTPException(503, "too many viewers")

    async def gen():
        global _streams
        _streams += not admin
        try:
            while not await request.is_disconnected():
                s = recorder.state if admin else _public_live(recorder.state)
                yield f"data: {json.dumps(s)}\n\n"
                await asyncio.sleep(0.1 if admin else 0.25)
        finally:
            _streams -= not admin
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


FRONT = store.ROOT / "frontend"


PAGES = {   # title, description per page (the frontend mirrors this for in-app navigation)
    "": ("Ghostline", "Sim racing telemetry lab. Every lap against the fastest drivers, corner by corner."),
    "laps": ("Laps", "Every logged lap: mine and the fastest clean ghost laps, by car and track."),
    "compare": ("Delta", "Two laps on one distance grid: delta, speed, inputs and the corners where the time goes."),
    "stats": ("Stats", "Ghost leaderboard with sector times, the ideal lap and lap time progress."),
    "session": ("Session", "One session lap by lap: consistency, spread and best sectors."),
    "live": ("Live", "Live timing from the car: deltas, sectors, standings, tyres and fuel."),
    "refs": ("References", "Where the reference laps come from: online ghosts and real-world data."),
    "404": ("Not found", "Nothing at this address."),
}


@app.get("/", include_in_schema=False)
def index(page="", status=200):
    """index.html with per-page title/description and ?v=<last change> on css/js, so browsers and Cloudflare never serve stale assets."""
    v = format(int(max(p.stat().st_mtime for p in FRONT.rglob("*") if p.suffix in (".css", ".js"))), "x")
    html = re.sub(r'(href|src)="(/(?:css|js|vendor)/[^"?]+)"', rf'\1="\2?v={v}"', (FRONT / "index.html").read_text(encoding="utf-8"))
    if PUBLIC_HOST:   # link previews need absolute URLs
        html = re.sub(r'(<meta (?:property|name)="(?:og:url|og:image|twitter:image)" content=")/', rf"\1https://{PUBLIC_HOST}/", html)
    if settings.CREDIT_NAME:
        html = re.sub(r'<a class="mono credit"[^>]*>.*?</a>', lambda m: f'<a class="mono credit" href="{escape(settings.CREDIT_URL or settings.REPO_URL)}" '
                      f'target="_blank" rel="noopener" data-hover>Built by {escape(settings.CREDIT_NAME)} &#8599;</a>', html)
    if page:
        t, d = PAGES[page]
        html = html.replace("<title>Ghostline</title>", f"<title>{t} · Ghostline</title>")
        html = re.sub(r'(<meta (?:name|property)="(?:og:|twitter:)?description" content=")[^"]*', lambda m: m.group(1) + escape(d), html)
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-cache"})


@app.get("/robots.txt", include_in_schema=False)
def robots():
    if not PUBLIC_HOST:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: https://{PUBLIC_HOST}/sitemap.xml\n")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    if not PUBLIC_HOST:
        raise HTTPException(404)
    urls = "".join(f"  <url><loc>https://{PUBLIC_HOST}/{p}</loc></url>\n" for p in ("", "laps", "stats", "live", "refs"))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n',
                    media_type="application/xml")


class SPAFiles(StaticFiles):
    """Static files, plus index.html for app pages like /compare/42/227 (no file extension)."""
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and "." not in path.rsplit("/", 1)[-1] and not path.startswith(("api", "og", "s/")):
                page = path.replace("\\", "/").strip("/").split("/")[0]   # Windows: path comes os-joined
                return index(page, 200) if page in PAGES and page != "404" else index("404", 404)
            raise


app.mount("/", SPAFiles(directory=FRONT, html=True), name="static")
