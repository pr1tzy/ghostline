"""Builds the Windows release: dist/Ghostline/ (the app), then checks that the built exe actually starts, then
Ghostline-portable.zip, GhostlineSetup.exe (if Inno Setup is installed) and SHA256SUMS.txt in dist/release/.

    pip install -r requirements.txt pyinstaller
    python packaging/build.py            # everything
    python packaging/build.py app        # just dist/Ghostline + self-test
    python packaging/build.py package    # zip + installer + checksums from an existing dist/Ghostline
    python packaging/build.py sums       # checksums again (after signing the installer)

The GitHub release workflow runs these stages, with code signing in between once it's set up.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, OUT = ROOT / "dist", ROOT / "dist" / "release"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "backend" / "__init__.py").read_text()).group(1)


def version_info():
    v = tuple(int(x) for x in VERSION.split(".")[:3]) + (0,)
    (ROOT / "packaging" / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Ghostline'), StringStruct('FileDescription', 'Ghostline: sim racing telemetry for Assetto Corsa'),
    StringStruct('FileVersion', '{VERSION}'), StringStruct('InternalName', 'Ghostline'),
    StringStruct('LegalCopyright', 'MIT License, github.com/pr1tzy/ghostline'), StringStruct('OriginalFilename', 'Ghostline.exe'),
    StringStruct('ProductName', 'Ghostline'), StringStruct('ProductVersion', '{VERSION}')])]),
  VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def run(*cmd, **kw):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def selftest(exe):
    """Start the built exe on a spare port with a throwaway data folder; it must serve the site and exit 0."""
    r = subprocess.run([str(exe), "--selftest"], timeout=120)
    if r.returncode != 0:
        sys.exit(f"selftest failed ({r.returncode}): the built exe doesn't start")
    print("selftest passed")


def iscc():
    for p in (shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if p and Path(p).exists():
            return p
    return None


def build_app():
    shutil.rmtree(DIST / "Ghostline", ignore_errors=True)
    version_info()
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST, "--workpath", ROOT / "build",
        ROOT / "packaging" / "ghostline.spec")
    selftest(DIST / "Ghostline" / "Ghostline.exe")


def package():
    app = DIST / "Ghostline"
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(OUT / "Ghostline-portable.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            z.write(f, Path("Ghostline") / f.relative_to(app))
    if os.environ.get("GHOSTLINE_SKIP_INSTALLER") != "1":
        compiler = iscc()
        if compiler:
            run(compiler, f"/DAppVersion={VERSION}", f"/O{OUT}", ROOT / "packaging" / "ghostline.iss")
        else:
            print("Inno Setup not found: skipping GhostlineSetup.exe (https://jrsoftware.org/isinfo.php)")
    sums()
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"\nGhostline {VERSION}: app folder {size / 1e6:.0f} MB")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}: {f.stat().st_size / 1e6:.1f} MB")


def sums():
    files = [f for f in sorted(OUT.iterdir()) if f.is_file() and f.name != "SHA256SUMS.txt"]
    lines = "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in files)
    (OUT / "SHA256SUMS.txt").write_bytes(lines.encode())   # plain \n endings, so `sha256sum -c` works everywhere


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "app"):
        build_app()
    if stage in ("all", "package"):
        package()
    if stage == "sums":
        sums()


if __name__ == "__main__":
    main()
