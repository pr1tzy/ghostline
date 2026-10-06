"""End-to-end test on a throwaway database: real F1 reference + a lap fed through the inbox CSV path."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["RA_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import analysis, ingest, store  # noqa: E402

ref = ingest.import_f1(2024, "Monza", "Q", "NOR")
other = ingest.import_f1(2024, "Monza", "Q", "LEC")

# Re-export LEC's lap as an in-game-app CSV (no pedal data) to exercise ingestion + estimated inputs
raw = store.load_lap(other)
rows = "\n".join(f"{t:.3f},{p:.6f},{s:.2f},{x:.2f},{z:.2f},{g:.0f}"
                 for t, p, s, x, z, g in zip(raw["t"], raw["pos"], raw["speed"], raw["x"], raw["z"], raw["gear"]))
(store.INBOX / "test_lap.csv").write_text(
    f"# car=ks_ferrari_sf70h\n# track=monza\n# driver=LEC-csv\n# source=online\n# lap_ms={store.get_lap(other)['lap_ms']}\n"
    f"t,pos,speed,x,z,gear\n{rows}")
ingest.Watcher().scan()
mine = store.q("SELECT id FROM laps WHERE driver='LEC-csv'")[0]["id"]

for a in (other, mine):
    c = analysis.compare(a, ref)
    print(f"\n{c['a']['driver']} vs {c['b']['driver']}  total {c['total']:+.3f}s  (lap times {c['a']['lap_ms']} / {c['b']['lap_ms']})")
    print("corners:", ", ".join(f"{k['name']}@{k['apex_d']:.0f} {k['loss']:+.3f}" for k in c["corners"]))
    for i in c["insights"]:
        print(f"  {i['corner']} {i['loss']:+.3f}s: " + " | ".join(i["tips"]))
