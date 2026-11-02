"""The always-on online copy (backend/publish.py), built from the sample laps into a temp folder: every page is
there with its own title, Cloudflare's rules are right, every comparison it offers exists, and what the browser
rebuilds from the files (app.js's own code, run in Node) is exactly what the API returns. Also: the tunnel to this
PC only serves the Live stream, and publishing waits for a change. Nothing is uploaded. Runs in CI."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp())
os.environ.update(RA_DATA=str(TMP / "data"), GHOSTLINE_HOME=str(TMP / "home"), GHOSTLINE_HOST="ghostline.example.com",
                  GHOSTLINE_LIVE_HOST="ghostline-live.example.com")
for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.encoders import jsonable_encoder  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as web  # noqa: E402
from backend import ingest, publish, store  # noqa: E402

ingest.load_samples()
laps = store.q("SELECT id, source FROM laps ORDER BY id")
out = TMP / "site"
req = SimpleNamespace(state=SimpleNamespace(admin=False))
api = lambda o: json.loads(json.dumps(jsonable_encoder(o)))
cached = api(web.compare(req, laps[0]["id"]))   # now in the site's cache, which publishing reads from
publish.build(out)
D = out / "data"

# pages: one per page, each with its own title, the online-copy marker and the live host
for page, (title, _) in web.PAGES.items():
    html = (out / f"{page or 'index'}.html").read_text(encoding="utf-8")
    assert '<meta name="ghostline-static" content="ghostline-live.example.com">' in html, page
    assert (f"<title>{title} · Ghostline</title>" if page else "<title>Ghostline</title>") in html, page
    assert 'content="https://ghostline.example.com/' in html, "link previews need absolute URLs"
for f in ("css/style.css", "js/app.js", "vendor/gsap.min.js", "favicon.ico", "robots.txt", "sitemap.xml"):
    assert (out / f).is_file(), f
assert "Sitemap: https://ghostline.example.com/sitemap.xml" in (out / "robots.txt").read_text()
redirects = (out / "_redirects").read_text()
for rule in ("/compare/* /compare 200", "/session/* /session 200", "/stats/* /stats 200", "/s/:a/:b /compare/:a/:b 301"):
    assert rule in redirects, rule
headers = (out / "_headers").read_text()
assert "connect-src 'self' https://ghostline-live.example.com;" in headers and "Strict-Transport-Security" in headers

# the data: the public view (other drivers as initials), and every reference offered has its comparison
state = json.loads((D / "state.json").read_text(encoding="utf-8"))
assert state["admin"] is False and state["app"] is None and state == api(web.state(req))
assert json.loads((D / "laps.json").read_text(encoding="utf-8")) == api(web.laps(req))
assert not any(l.get("origin") for l in json.loads((D / "laps.json").read_text(encoding="utf-8"))), "no local paths"
files = {p.stem for p in (D / "compare").glob("*.json")}
for l in laps:
    refs = json.loads((D / "refs" / f"{l['id']}.json").read_text(encoding="utf-8"))
    assert refs and all(f"{l['id']}-{r['id']}" in files for r in refs), l
lap_files = {int(p.stem): json.loads(p.read_text()) for p in (D / "lap").glob("*.json")}
shared = 0
for name in files:
    a, b = name.split("-")
    ideal, a, b = a.startswith("i"), int(a.lstrip("i")), int(b)
    c = json.loads((D / "compare" / f"{name}.json").read_text(encoding="utf-8"))
    shared += json.dumps(c).count('"$"')
    assert publish.unshare(c, lap_files) == api(web.compare(req, a, b, ideal)), name
assert shared > 10 * len(files), "the arrays comparisons share are stored once per lap"
assert api(web.compare(req, laps[0]["id"])) == cached, "publishing never changes what the site here serves"
print(f"online copy: {sum(1 for p in out.rglob('*') if p.is_file())} files, {len(files)} comparisons, all identical to the API")

# the browser side: app.js's own static code, run in Node against the files, rebuilds exactly what the API returns
node = shutil.which("node")
if node:
    me = next(l["id"] for l in laps if l["source"] == "player")
    group = next(g for g in state["groups"])
    cases = [("/state", web.state(req)), ("/laps", web.laps(req)), ("/content", web.content_list()),
             (f"/compare?a={me}", web.compare(req, me)), (f"/compare?a={me}&ideal=1", web.compare(req, me, None, True)),
             (f"/session/{me}", web.session(me)), (f"/laps/{me}/map", web.lap_map(me)), (f"/references/{me}", None),
             (f"/stats?car={group['car']}&track={group['track']}", web.stats(req, group["car"], group["track"]))]
    cases += [(f"/compare?a={n.split('-')[0].lstrip('i')}&b={n.split('-')[1]}" + ("&ideal=1" if n.startswith("i") else ""),
               web.compare(req, int(n.split("-")[0].lstrip("i")), int(n.split("-")[1]), n.startswith("i"))) for n in sorted(files)]
    (TMP / "cases.json").write_text(json.dumps([p for p, _ in cases]))
    js = TMP / "check.js"
    js.write_text(r"""
const fs = require('fs'), path = require('path');
const [, , appjs, site, casesFile] = process.argv;
const block = fs.readFileSync(appjs, 'utf8').split('// ---- online copy: start')[1].split('// ---- online copy: end')[0].replace(/^[^\n]*\n/, '');   // the rest of the marker line (CRLF in a Windows checkout)
globalThis.document = { querySelector: () => ({ content: 'ghostline-live.example.com' }) };
globalThis.fetch = async u => {
  const f = path.join(site, u.split('?')[0]), ok = fs.existsSync(f);
  return { ok, status: ok ? 200 : 404, json: async () => JSON.parse(fs.readFileSync(f, 'utf8')) };
};
const { staticApi, LIVE_URL } = new Function(block + '\nreturn { staticApi, LIVE_URL };')();
(async () => {
  const out = { live: LIVE_URL, got: [] };
  for (const p of JSON.parse(fs.readFileSync(casesFile, 'utf8'))) {
    try { out.got.push(await staticApi(p)); } catch (e) { out.got.push({ error: e.message }); }
  }
  try { await staticApi('/laps/1/note', { method: 'PUT' }); out.put = 'allowed'; } catch (e) { out.put = e.message; }
  try { await staticApi('/compare?a=999999&b=1'); out.missing = 'found'; } catch (e) { out.missing = e.message; }
  fs.writeFileSync(path.join(path.dirname(casesFile), 'got.json'), JSON.stringify(out));
})();
""")
    subprocess.run([node, str(js), str(ROOT / "frontend" / "js" / "app.js"), str(out), str(TMP / "cases.json")], check=True)
    got = json.loads((TMP / "got.json").read_text(encoding="utf-8"))
    assert got["live"] == "https://ghostline-live.example.com/api/live", got["live"]
    assert got["put"] == "This is the read-only online copy" and got["missing"] == "not in the online copy", got
    for (p, want), g in zip(cases, got["got"]):
        if want is None:
            assert g and "error" not in g, p
            continue
        assert g == api(want), p
    print(f"browser side (Node): {len(cases)} requests rebuilt exactly")
else:
    print("browser side skipped: no Node.js")

# the tunnel to this PC on the live host: the Live stream only; the site itself is on Cloudflare Pages
client = TestClient(web.app, base_url="https://ghostline-live.example.com")
r = client.get("/laps", headers={"cf-connecting-ip": "1.2.3.4"}, follow_redirects=False)
assert r.status_code == 301 and r.headers["location"] == "https://ghostline.example.com/laps", (r.status_code, r.headers)
for path in ("/api/state", "/api/compare?a=1&b=2"):
    r = client.get(path, headers={"cf-connecting-ip": "1.2.3.4"}, follow_redirects=False)
    assert r.status_code == 301 and "api" not in r.headers.get("access-control-allow-origin", ""), path
assert client.put("/api/laps/1/note", json={}, headers={"cf-connecting-ip": "1.2.3.4"}).status_code in (403, 404)
assert TestClient(web.app, base_url="https://evil.example").get("/api/state").status_code == 421

# publishing: not without an account and token; once it has published, only again after something changes
assert not publish.configured()
assert [publish.node_major(v) for v in ("v20.17.0", "v22.11.0\n", "", "x")] == [20, 22, 0, 0]
calls = []
publish.deploy = lambda out=None, log=None: calls.append(1)
publish.tools_problem = lambda: "Node.js 22 or newer is needed to publish; this PC has v20.17.0"
p = publish.Publisher(lambda: False, lambda: False)
assert not p.publish("test") and not calls and "Node.js 22" in publish.STATUS["detail"], "checked before building"
publish.tools_problem = lambda: None
with publish._OneAtATime():   # `Ghostline.exe --publish` while the app is publishing: one waits its turn
    assert not p.publish("test") and "another publish" in publish.STATUS["detail"] and not calls
assert p.due() and p.publish("test") and len(calls) == 1
assert not p.due() and p.publish("again") and len(calls) == 1, "nothing changed: no upload"
store.q("UPDATE laps SET note=? WHERE id=?", ('{"tyres": "softs"}', laps[0]["id"]))
assert p.due(), "a changed note is a change"
print("publish ok")
