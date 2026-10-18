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
for p in ("/", "/laps", "/stats", "/live", "/refs", "/story", "/get", f"/compare/{laps[0]['id']}"):
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

# ---------- bad recordings are never kept as ghosts, and stored ones are found again later ----------
import os as _os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

store.q("DELETE FROM laps")
for f in store.LAPDIR.glob("*.npz"):
    f.unlink()
store.kv_set("samples_done", 0)
ingest.load_samples()
laps = store.q("SELECT * FROM laps")
for l in laps:   # the real sample laps pass every check
    raw = store.load_lap(l["id"])
    assert analysis.lap_problems(l["track"], raw, l["lap_ms"], ghost=l["source"] == "online") is None, l
g = next(l for l in laps if l["source"] == "online" and l["track"] == "monza")
raw = store.load_lap(g["id"])
COLS = ["t", "pos", "speed", "x", "z"]


def rows(r):
    return np.c_[r["t"], r["pos"], r["speed"], r["x"], r["z"]]


def ghost(r, lap_ms, origin):
    return ingest.ingest_rows({"source": "online", "driver": "Check " + origin, "car": g["car"], "track": "monza",
                               "lap_ms": lap_ms}, COLS, rows(r), origin=origin)


# the 2.2 bug: the in-game clock ran at double speed, so laps took twice as long as they did
double = {**raw, "t": raw["t"] * 2}
why = analysis.lap_problems("monza", double, g["lap_ms"] * 2, ghost=True)
assert why and "add up to" in why, why
assert ghost(double, g["lap_ms"] * 2, "test:double") is None
# a hole in the recording (2 s missing) and a lap that only covers part of the track
k = len(raw["t"]) // 2
hole = {c: np.r_[raw[c][:k], raw[c][k + 45:]] for c in COLS}
assert "gap" in analysis.lap_problems("monza", hole, g["lap_ms"], ghost=True)
assert ghost(hole, g["lap_ms"], "test:hole") is None
part = {c: raw[c][: len(raw["t"]) * 3 // 4] for c in COLS}
assert analysis.lap_problems("monza", part, g["lap_ms"], ghost=True)
# the same thing on your own lap: kept (it's yours) but it doesn't count, and says why
me = next(l for l in laps if l["source"] == "player" and l["track"] == "monza")
mraw = store.load_lap(me["id"])
mine_bad = ingest.ingest_rows({"source": "player", "driver": "You", "car": me["car"], "track": "monza",
                               "lap_ms": me["lap_ms"] * 2}, list(mraw), np.c_[tuple(mraw[c] * (2 if c == "t" else 1)
                                                                                  for c in mraw)], origin="test:mine2x")
row = store.get_lap(mine_bad)
assert row and not row["valid"] and store.parse_note(row["note"])["cut"].startswith("recording problem"), row

# stored before the checks existed: found again once the checks change, on startup
bad_ghost = store.add_lap({"source": "online", "driver": "Old bad", "car": g["car"], "track": "monza",
                           "lap_ms": g["lap_ms"] * 2, "origin": "test:oldbad"}, double)
k2 = len(mraw["t"]) // 2   # your laps are sampled 60 times a second: 4 s missing
bad_mine = store.add_lap({"source": "player", "driver": "You", "car": me["car"], "track": "monza",
                          "lap_ms": me["lap_ms"], "origin": "test:oldmine"},
                         {c: np.r_[mraw[c][:k2], mraw[c][k2 + 240:]] for c in mraw})
good = {l["id"] for l in laps}
store.kv_set("lap_checks", 0)
ingest.recheck_laps()
assert store.get_lap(bad_ghost) is None, "a bad ghost lap is deleted"
assert store.get_lap(bad_mine) and not store.get_lap(bad_mine)["valid"], "your bad lap is kept but doesn't count"
assert all(store.get_lap(i) and store.get_lap(i)["valid"] for i in good), "good laps are untouched"

# a deleted lap's id is never handed out again (pruning deletes other drivers' laps all the time)
top = store.q("SELECT MAX(id) m FROM laps")[0]["m"]
analysis.prep(top)
store.delete_lap(top)
new_id = store.add_lap({"source": "player", "driver": "You", "car": me["car"], "track": "monza", "lap_ms": me["lap_ms"],
                        "origin": "test:after-delete"}, mraw)
assert new_id > top, (new_id, top)
assert analysis.prep.cache_info().currsize == 0, "caches keyed by lap id are cleared on delete"

# tidy: files without a lap, half-written files, laps without a file, share images of deleted laps
for name in ("999999.npz", f"{new_id}.tmp.npz"):
    np.savez_compressed(store.LAPDIR / name, t=np.zeros(3))
orphan_row = store.add_lap({"source": "player", "driver": "You", "car": me["car"], "track": "monza",
                            "lap_ms": me["lap_ms"], "origin": "test:nofile", "created": time.time() - 3600}, mraw)
(store.LAPDIR / f"{orphan_row}.npz").unlink()
og = store.DATA / "og"
og.mkdir(exist_ok=True)
keep_img, dead_img, old_img = (og / f"{new_id}_{g['id']}_1_2.png", og / f"{top}_{g['id']}_1_2.png",
                               og / f"i{new_id}_{g['id']}_3_4.png")
for f in (keep_img, dead_img, old_img):
    f.write_bytes(b"png")
_os.utime(old_img, (time.time() - 8 * 86400,) * 2)
store.tidy()
assert not (store.LAPDIR / "999999.npz").exists() and not (store.LAPDIR / f"{new_id}.tmp.npz").exists()
assert (store.LAPDIR / f"{new_id}.npz").exists() and store.get_lap(orphan_row) is None
assert keep_img.exists() and not dead_img.exists() and not old_img.exists()

# CSV laps: the old in-game app's logs are deleted once stored, your inbox files are kept in processed, and a file
# that can't be read is moved aside once instead of being retried every 2 seconds
fake_app = Path(_os.environ["RA_DATA"]) / "RaceLogger"
(fake_app / "logs").mkdir(parents=True)
real_app_dir = ingest.app_dir
ingest.app_dir = lambda: fake_app
try:
    shutil.copy(ingest.SAMPLES / "spa_you.csv", fake_app / "logs" / "lap1.csv")
    shutil.copy(ingest.SAMPLES / "monza_you.csv", store.INBOX / "mine.csv")
    broken = fake_app / "logs" / "broken.csv"
    broken.write_text("t,pos,speed\n1,2,x\n")
    w = ingest.Watcher()
    w.scan()
    assert not (fake_app / "logs" / "lap1.csv").exists() and not (fake_app / "logs" / "processed").exists()
    assert (store.INBOX / "processed" / "mine.csv").exists()
    assert broken.exists(), "a new file may still be being written"
    _os.utime(broken, (time.time() - 120,) * 2)
    w.scan()
    assert not broken.exists() and (fake_app / "logs" / "failed" / "broken.csv").exists()
    # 1.x left a copy of every lap in logs/processed: removed once they're stored
    (fake_app / "logs" / "processed").mkdir()
    (fake_app / "logs" / "processed" / "old.csv").write_text("x")
    store.kv_set("cut_check", ingest.CUT_CHECK_VERSION)
    ingest.drop_old_logs()
    assert not (fake_app / "logs" / "processed" / "old.csv").exists()
finally:
    ingest.app_dir = real_app_dir
print("ok")
