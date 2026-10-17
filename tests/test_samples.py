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

# online lag: a lap where the car jumps ahead faster than it was going is caught (and never becomes a ghost)
import numpy as np  # noqa: E402
for l in laps:
    raw = store.load_lap(l["id"])
    assert analysis.position_jumps(l["track"], raw["t"], raw["pos"], raw["speed"], raw["x"], raw["z"])[0] == 0, l
g = next(l for l in laps if l["source"] == "online" and l["track"] == "monza")
raw = store.load_lap(g["id"])
k = len(raw["pos"]) // 2
pos = raw["pos"].copy()
pos[k:] = (pos[k:] + 150 / analysis.track_length("monza")) % 1      # teleported 150 m ahead in one sample
n, skipped = analysis.position_jumps("monza", raw["t"], pos, raw["speed"], raw["x"], raw["z"])
assert n == 1 and 140 < skipped < 160, (n, skipped)
cols = ["t", "pos", "speed", "x", "z"]
a = np.c_[raw["t"], pos, raw["speed"], raw["x"], raw["z"]]
lid = ingest.ingest_rows({"source": "online", "driver": "Lag Test", "car": "lotus_exos_125_s1", "track": "monza",
                          "lap_ms": 90000}, cols, a, origin="test:lag")
assert lid is None and not store.q("SELECT 1 FROM laps WHERE driver='Lag Test'"), "a lagging ghost lap is not kept"

# compact lap files: every channel comes back within its precision, and an old plain-float file converts once
# without changing a single comparison
for l in laps:
    raw = store.load_lap(l["id"])
    back = store._unpack(store._pack(raw))
    for k in raw:
        assert np.max(np.abs(back[k] - raw[k])) <= store.PACK.get(k, 0) / 2 + 1e-9, (l["id"], k)
me_l = next(l for l in laps if l["source"] == "player" and l["track"] == "spa")
ref_l = next(l for l in laps if l["source"] == "online" and l["track"] == "spa")
before = analysis.compare(me_l["id"], ref_l["id"])
np.savez_compressed(store.LAPDIR / f"{me_l['id']}.npz", **store.load_lap(me_l["id"]))   # as a pre-2.3 file
store.kv_set("laps_format", 1)
store.compact_laps()
with np.load(store.LAPDIR / f"{me_l['id']}.npz") as z:
    assert "format" in z.files
analysis.prep.cache_clear()
after = analysis.compare(me_l["id"], ref_l["id"])
assert after["total"] == before["total"] and [c["name"] for c in after["corners"]] == [c["name"] for c in before["corners"]]

# official content only
assert content.supported("lotus_exos_125_s1", "monza") and content.supported("ks_ferrari_488_gt3", "ks_nordschleife-nordschleife")
assert not content.supported("rss_formula_hybrid_2021", "monza") and not content.supported("lotus_exos_125_s1", "some_mod_track")

# web app: pages, admin vs public, host checks
local = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
public = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000),
                    headers={"cf-connecting-ip": "203.0.113.9"})
# the compare API for every sample lap, against its reference and against your ideal lap: never a 500
for l in laps:
    r = local.get(f"/api/compare?a={l['id']}")
    assert r.status_code == 200, (l, r.status_code)
    r = local.get(f"/api/compare?a={l['id']}&ideal=true")
    mine = analysis.player_best_ids(store.get_lap(l["id"])["car"], l["track"])
    assert r.status_code == (200 if mine else 404), (l, r.status_code)
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
