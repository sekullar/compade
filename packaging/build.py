"""Compade.exe (PyInstaller, klasör kipi) ve Compade-Setup-<sürüm>.exe (NSIS) üretir.

  python packaging/build.py            # dist/Compade/Compade.exe + dist/Compade-Setup-<sürüm>.exe
  python packaging/build.py --no-installer

Gerekenler: pip install pyinstaller; NSIS (makensis). makensis şu sırayla aranır: MAKENSIS ortam değişkeni, PATH,
Program Files\\NSIS, electron-builder önbelleği.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "compade"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def version():
    return re.search(r'__version__\s*=\s*"([^"]+)"', (PKG / "__init__.py").read_text(encoding="utf-8")).group(1)


def find_makensis():
    cands = [os.environ.get("MAKENSIS"), shutil.which("makensis")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            cands.append(str(Path(base) / "NSIS" / "makensis.exe"))
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / "electron-builder" / "Cache" / "nsis"
    if cache.is_dir():
        cands += [str(p) for p in sorted(cache.glob("nsis-*/makensis.exe"), reverse=True)]
    return next((c for c in cands if c and Path(c).is_file()), None)


def pyinstaller():
    sep = ";" if os.name == "nt" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
           "--name", "Compade", "--icon", str(PKG / "assets" / "compade.ico"),
           "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
           "--add-data", f"{PKG / 'web'}{sep}compade/web",
           "--add-data", f"{PKG / 'assets'}{sep}compade/assets",
           "--exclude-module", "tkinter", "--exclude-module", "compade.gui",
           "--paths", str(ROOT), str(ROOT / "packaging" / "launcher.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    # tasarım denemesi, ürün değil
    for junk in ("mascot3d-test.html",):
        (DIST / "Compade" / "_internal" / "compade" / "web" / junk).unlink(missing_ok=True)
    exe = DIST / "Compade" / "Compade.exe"
    assert exe.is_file(), exe
    return exe


def installer(ver):
    mk = find_makensis()
    if not mk:
        sys.exit("makensis bulunamadı (NSIS kurun ya da MAKENSIS ortam değişkenini verin)")
    out = DIST / f"Compade-Setup-{ver}.exe"
    subprocess.run([mk, "-V2", f"-DVERSION={ver}", f"-DSRC={DIST / 'Compade'}", f"-DOUT={out}",
                    str(ROOT / "packaging" / "compade.nsi")], check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-installer", action="store_true")
    a = ap.parse_args()
    ver = version()
    exe = pyinstaller()
    print(f"exe: {exe}")
    if not a.no_installer:
        out = installer(ver)
        print(f"kurulum: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
