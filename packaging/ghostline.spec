# PyInstaller build for Ghostline.exe. Run through packaging/build.py, which writes version_info.txt first.
# A folder build (not one self-unpacking file) and no UPX: both look far less suspicious to antivirus heuristics.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
DATAS = [
    ("frontend", "frontend"), ("ac_app/RaceLogger/RaceLogger.py", "ac_app/RaceLogger"),
    ("ac_app/GhostlineLogger", "ac_app/GhostlineLogger"), ("samples", "samples"), ("backend/assets", "backend/assets"),
    ("config/tracks.json", "config"), ("config/cars.json", "config"), ("config/site.example.json", "config"),
    ("config/logger.example.json", "config"), ("packaging/ghostline.ico", "packaging"),
    ("LICENSE", "."), ("THIRD_PARTY_NOTICES.md", "."),
]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / src), dst) for src, dst in DATAS],
    hiddenimports=collect_submodules("uvicorn") + ["backend.tray"],
    excludes=["tkinter", "unittest", "pydoc_data", "test", "lib2to3", "setuptools", "pip", "numpy.f2py", "numpy.testing",
              "PIL.ImageQt", "PIL.ImageTk"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Ghostline",
    icon=str(ROOT / "packaging" / "ghostline.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Ghostline", upx=False)
