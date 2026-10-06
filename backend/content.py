"""Official Assetto Corsa content: names, lengths, corner names and classes, read straight from the AC install.

Only Kunos cars and tracks are supported. Most servers run them, and mod versions differ from server to server,
so a mod lap is never a fair comparison. config/tracks.json and config/cars.json override anything read here.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

TRACKS = {"imola", "magione", "monza", "mugello", "spa", "trento-bondone", "drift", "ks_barcelona", "ks_black_cat_county",
          "ks_brands_hatch", "ks_drag", "ks_highlands", "ks_laguna_seca", "ks_monza66", "ks_nordschleife", "ks_nurburgring",
          "ks_red_bull_ring", "ks_silverstone", "ks_silverstone1967", "ks_vallelunga", "ks_zandvoort"}
LEGACY_CARS = {   # Kunos cars from before the ks_ prefix
    "abarth500", "abarth500_s1", "alfa_romeo_giulietta_qv", "alfa_romeo_giulietta_qv_le", "bmw_1m", "bmw_1m_s3",
    "bmw_m3_e30", "bmw_m3_e30_drift", "bmw_m3_e30_dtm", "bmw_m3_e30_gra", "bmw_m3_e30_s1", "bmw_m3_e92",
    "bmw_m3_e92_drift", "bmw_m3_e92_s1", "bmw_m3_gt2", "bmw_z4", "bmw_z4_drift", "bmw_z4_gt3", "bmw_z4_s1",
    "ferrari_312t", "ferrari_458", "ferrari_458_gt2", "ferrari_458_s3", "ferrari_599xxevo", "ferrari_f40",
    "ferrari_f40_s3", "ferrari_laferrari", "ktm_xbow_r", "lotus_2_eleven", "lotus_2_eleven_gt4", "lotus_49",
    "lotus_98t", "lotus_elise_sc", "lotus_elise_sc_s1", "lotus_elise_sc_s2", "lotus_evora_gtc", "lotus_evora_gte",
    "lotus_evora_gte_carbon", "lotus_evora_gx", "lotus_evora_s", "lotus_evora_s_s2", "lotus_exige_240",
    "lotus_exige_240_s3", "lotus_exige_s", "lotus_exige_s_roadster", "lotus_exige_scura", "lotus_exige_v6_cup",
    "lotus_exos_125", "lotus_exos_125_s1", "mclaren_mp412c", "mclaren_mp412c_gt3", "mercedes_sls", "mercedes_sls_gt3",
    "p4-5_2011", "pagani_huayra", "pagani_zonda_r", "ruf_yellowbird", "shelby_cobra_427sc", "tatuusfa1"}
CLASS_NAMES = {"formula-modern": "Modern formula", "formula-classic": "Classic formula", "formula-junior": "Junior formula",
               "gt3": "GT3", "gte": "GT2 / GTE", "gt4": "GT4", "prototype": "Prototype", "touring": "Touring",
               "cup": "One-make cup", "drift": "Drift", "race": "Race", "street-light": "Road, light",
               "street-sport": "Road, sport", "street-super": "Road, super", "f1-real": "Real-world F1"}
STRAIGHT = re.compile(r"straight|rettifilo|rettilineo|gerade|recta|rechte|start/finish", re.I)


def official_car(car):
    return car.startswith("ks_") or car in LEGACY_CARS


def official_track(track):
    """Track ids are '<track>' or '<track>-<layout>' (how the recorder and the in-game app name them)."""
    return track in TRACKS or track.rpartition("-")[0] in TRACKS


def supported(car, track):
    return official_car(car) and official_track(track)


def _json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig", errors="replace"), strict=False)
    except (OSError, ValueError):
        return {}


def _num(s):
    s = str(s or "").lower().replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group())
    return v * 1000 if "km" in s or v < 100 else v


def _sections(p, L):
    """Corner names from the track's data/sections.ini: [dist at middle, name, start, end] in metres."""
    secs, cur = [], {}
    for line in p.read_text(errors="replace").splitlines() + ["[END]"]:
        line = line.strip()
        if line.startswith("["):
            if {"IN", "OUT", "TEXT"} <= cur.keys():
                secs.append(cur)
            cur = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip().upper()] = v.strip()
    out = []
    for s in secs:
        try:
            a, b = float(s["IN"]), float(s["OUT"])
        except ValueError:
            continue
        if s["TEXT"] and not STRAIGHT.search(s["TEXT"]) and 0 <= a < b <= 1:
            out.append([round((a + b) / 2 * L), s["TEXT"], round(a * L), round(b * L)])
    return sorted(out)


def _track(ui, sections):
    L = _num(ui.get("length"))
    return {"name": str(ui.get("name") or "").strip(), "length": round(L) if L else None, "country": ui.get("country", ""),
            "corners": _sections(sections, L) if L and sections.exists() else []}


def _class(car, ui):
    tags = {str(t).lower().lstrip("#") for t in ui.get("tags", [])}
    has = lambda *k: any(any(x in t for x in k) for t in tags)
    bhp, kg = _num(ui.get("specs", {}).get("bhp")), _num(ui.get("specs", {}).get("weight"))
    if car.endswith("_drift") or "drift" in tags:
        return "drift"
    if has("singleseater", "formula", "open wheel", "openwheel"):
        if has("vintage", "classic"):
            return "formula-classic"
        return "formula-junior" if bhp and bhp < 300 else "formula-modern"
    if has("gt3"):
        return "gt3"
    if has("gte", "gt2"):
        return "gte"
    if has("gt4"):
        return "gt4"
    if has("prototype", "lmp", "group c"):
        return "prototype"
    if has("dtm", "touring", "group a", "wtcc", "btcc"):
        return "touring"
    if has("cup"):
        return "cup"
    if str(ui.get("class", "")).lower() == "race":
        return "race"
    pw = bhp / kg * 1000 if bhp and kg else 0
    return "street-light" if pw < 150 else "street-sport" if pw < 300 else "street-super"


@lru_cache(maxsize=1)
def catalog():
    from .ingest import find_ac   # late import: ingest imports store, which imports this module's users
    cars, tracks = {}, {}
    root = find_ac()
    c = Path(root) / "content" if root else None
    if c and (c / "cars").is_dir():
        for d in (c / "cars").iterdir():
            ui = d / "ui" / "ui_car.json"
            if official_car(d.name) and ui.exists():
                u = _json(ui)
                cls = _class(d.name, u)
                cars[d.name] = {"name": str(u.get("name") or d.name).strip(), "brand": u.get("brand", ""), "class": cls}
    for t in sorted(TRACKS):
        d = c / "tracks" / t if c else None
        if not d or not d.is_dir():
            continue
        if (d / "ui" / "ui_track.json").exists():
            tracks[t] = _track(_json(d / "ui" / "ui_track.json"), d / "data" / "sections.ini")
        for lay in (d / "ui").iterdir() if (d / "ui").is_dir() else []:
            if (lay / "ui_track.json").exists():
                tracks[f"{t}-{lay.name}"] = _track(_json(lay / "ui_track.json"), d / lay.name / "data" / "sections.ini")
    return {"cars": cars, "tracks": tracks}


def car(car_id):
    return catalog()["cars"].get(car_id)


def track(track_id):
    return catalog()["tracks"].get(track_id)


def class_name(cls):
    return CLASS_NAMES.get(cls, cls.replace("_", " ").replace("-", " ").title())
