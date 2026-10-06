"""Offline test on a throwaway database with the bundled sample laps (no game, no network). Runs in CI."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["RA_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from backend import analysis, content, ingest, store  # noqa: E402
from backend.app import PORT, app  # noqa: E402

# samples load once on an empty database and never twice
ingest.load_samples()
ingest.load_samples()
laps = store.q("SELECT id, source, track, lap_ms, valid FROM laps ORDER BY id")
assert len(laps) == 4 and store.sample_count() == 4, laps
assert all(l["valid"] for l in laps), "a sample ghost was flagged as a cut lap"

# a comparison per track: corners found, time gap matches the lap times
for track in ("monza", "spa"):
    me = next(l for l in laps if l["track"] == track and l["source"] == "player")
    ghost = next(l for l in laps if l["track"] == track and l["source"] == "online")
    c = analysis.compare(me["id"], ghost["id"])
    assert len(c["corners"]) >= 5 and c["insights"], track
    assert abs(c["total"] - (me["lap_ms"] - ghost["lap_ms"]) / 1000) < 0.3, (track, c["total"])
    print(f"{track}: {c['total']:+.3f}s, {len(c['corners'])} corners, worst {c['insights'][0]['corner']}")

# official content only
assert content.supported("lotus_exos_125_s1", "monza") and content.supported("ks_ferrari_488_gt3", "ks_nordschleife-nordschleife")
assert not content.supported("rss_formula_hybrid_2021", "monza") and not content.supported("lotus_exos_125_s1", "some_mod_track")

# web app: pages, admin vs public, host checks
local = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
public = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000),
                    headers={"cf-connecting-ip": "203.0.113.9"})
for p in ("/", "/laps", "/stats", "/live", "/refs", f"/compare/{laps[0]['id']}"):
    assert local.get(p).status_code == 200, p
assert local.get("/nope").status_code == 404
st = local.get("/api/state").json()
assert st["admin"] and st["samples"] == 4 and len(st["groups"]) == 2
assert not public.get("/api/state").json()["admin"]
assert public.post("/api/recorder", json={"on": False}).status_code == 403
assert public.delete(f"/api/laps/{laps[0]['id']}").status_code == 403
assert TestClient(app, base_url="http://evil.example").get("/").status_code == 421
assert "Content-Security-Policy" in local.get("/").headers

# the first real lap clears the samples
store.add_lap({"source": "player", "driver": "Test", "car": "lotus_exos_125_s1", "track": "monza", "lap_ms": 90000,
               "origin": "test-lap"}, {k: v for k, v in store.load_lap(laps[0]["id"]).items()})
store.clear_samples()
assert store.sample_count() == 0 and store.q("SELECT COUNT(*) n FROM laps")[0]["n"] == 1
print("ok")
