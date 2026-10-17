"""Build dist/RaF-Remaster-Setup.exe (tools/raf_installer.py frozen with PyInstaller).

    python tools/build_installer.py [--stock "D:/Games/Rise and Fall"] [--skip-exe] [--scan-only]

Steps:
  1. venv work/tools/installer-venv (uv, Python 3.13) with pyinstaller, numpy, pillow, pefile.
  2. bundle work/installer/bundle: our code (the tools/*.py that raf_patch.apply and the release
     builders import, found by import scan), shaders/, redistributable tools (texconv, realesrgan-
     ncnn-vulkan + realesrgan-x4plus model, DXVK d3d9.dll; hash-checked), licenses, README and
     installer.json (release feature set, zoom, expected fingerprint, stock sha256 list).
     No game file and nothing built from one goes into the bundle: every overlay is built on the
     player's PC from the player's install.
  3. the launcher "RaF Remaster.exe" (tools/raf_launcher.py: update check, then the game), PyInstaller
     --onedir with its runtime in ".raf-launcher" next to it, goes into the bundle (bundle/launcher);
     the installer copies it into the game folder.
     PyInstaller --onefile --windowed -> dist/RaF-Remaster-Setup.exe, README + licenses next to it,
     dist/RaF-Remaster-Setup.exe.sha256 for the GitHub release (docs/release.md).
  4. scan: every file inside the exe (CArchive + PYZ) is hashed and compared with every file of the
     stock install, work/overlay-* and ai/unit ai scripts; the content is also searched for personal
     paths and the account e-mail. Any hit fails the build.
"""

import ast
import re
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
WORK = REPO / "work" / "installer"
BUNDLE = WORK / "bundle"
VENV = REPO / "work" / "tools" / "installer-venv"
VPY = VENV / "Scripts" / "python.exe"
DIST = REPO / "dist"
NAME = "RaF-Remaster-Setup"
LAUNCHER_NAME = "RaF Remaster"
LAUNCHER_CONTENTS = ".raf-launcher"
LAUNCHER_DIST = WORK / "launcher-dist"
UI = WORK / "ui"  # emblem + checkbox images, drawn by tools/make_icon.py at every build

sys.path.insert(0, str(TOOLS))
import make_icon  # noqa: E402
import raf_patch as rp  # noqa: E402

# The release set = the patcher defaults plus zoom-setting; the installer selftest proves the
# fingerprint matches.
FEATURES = [f for f, on in rp.FEATURES.items() if on or f == "zoom-setting"]
ZOOM = 2.0
GAME_VERSION = "v1.15"

ENTRY_MODULES = ["raf_patch", "raf_credits", "zoom_setting", "build_language", "build_textures", "build_shaders",
                 "build_ai_db", "build_ai", "build_survival", "build_unitlimit", "build_coop", "build_crossciv"]
SKIP_IMPORTS = {"capstone", "unicorn"}  # zoom_setting.listing() only (developer disassembly)

REDIST = {  # bundle path -> (source, sha256)
    "repo/work/tools/texconv.exe": (REPO / "work/tools/texconv.exe", None),
    "repo/work/tools/esrgan/bin/realesrgan-ncnn-vulkan.exe": (REPO / "work/tools/esrgan/bin/realesrgan-ncnn-vulkan.exe", None),
    "repo/work/tools/esrgan/bin/vcomp140.dll": (REPO / "work/tools/esrgan/bin/vcomp140.dll", None),
    "repo/work/tools/esrgan/bin/models/realesrgan-x4plus.param": (REPO / "work/tools/esrgan/bin/models/realesrgan-x4plus.param", None),
    "repo/work/tools/esrgan/bin/models/realesrgan-x4plus.bin": (REPO / "work/tools/esrgan/bin/models/realesrgan-x4plus.bin", None),
    f"repo/work/cache/dxvk-{rp.DXVK_VERSION}/x32/d3d9.dll": (rp.CACHE / f"dxvk-{rp.DXVK_VERSION}/x32/d3d9.dll", rp.DXVK_D3D9_SHA256),
}
# Space the copy needs on top of the stock size (measured in the installer selftest):
# backups in .raf-remaster/orig, overlay files, the temporary build tree.
EXTRA_BYTES = 500_000_000
EXTRA_BYTES_HD = 2_300_000_000  # HD PNG work files of hd-units alone: 1.7 GB


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fsha(p: Path) -> str:
    return sha(p.read_bytes())


# The survival .scn chunks are zlib streams (raf_scn.pack_chunk), so their bytes - and the gameplay
# fingerprint - depend on the zlib build: python.org 3.14 for Windows ships zlib-ng 2.2.4, older
# Pythons classic zlib (different stream, fingerprint 5e256.. instead of fabe63..). The frozen exe
# carries its own zlib, so the build Python must be the one the reference install was patched with.
ZLIB_WANT = "1.3.1.zlib-ng"


def ensure_venv():
    if not VPY.exists():
        subprocess.run(["uv", "venv", str(VENV), "--python", "3.14"], check=True)
        subprocess.run(["uv", "pip", "install", "--python", str(VPY), "pyinstaller", "numpy", "pillow", "pefile"],
                       check=True)
    got = subprocess.run([str(VPY), "-c", "import zlib; print(zlib.ZLIB_VERSION)"], capture_output=True,
                         text=True, check=True).stdout.strip()
    if got != zlib_version_here() or got != ZLIB_WANT:
        sys.exit(f"build venv zlib {got}, this Python {zlib_version_here()}, need {ZLIB_WANT} "
                 "(recreate work/tools/installer-venv from python.org 3.14)")


def zlib_version_here():
    return zlib.ZLIB_VERSION


def local_modules():
    """ENTRY_MODULES plus every tools/*.py they import (transitively); also the external imports."""
    local, external, todo = set(), set(), list(ENTRY_MODULES)
    while todo:
        m = todo.pop()
        if m in local:
            continue
        local.add(m)
        tree = ast.parse((TOOLS / f"{m}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for n in names:
                top = n.split(".")[0]
                if (TOOLS / f"{top}.py").exists():
                    todo.append(top)
                elif top not in SKIP_IMPORTS:
                    external.add(n)
    return sorted(local), sorted(external)


def stock_hashes(stock: Path) -> dict:
    out = {}
    for name in (rp.EXE, "DX9Rasterizer.dll", "Language.dll", "loadscreen.bmp"):
        out[name] = fsha(stock / name)
    for d in rp.GAMEPLAY_DIRS:
        for f in sorted((stock / d).rglob("*")):
            if f.is_file() and f.suffix.lower() != ".lcl":
                out[f.relative_to(stock).as_posix()] = fsha(f)
    return out


def expected_fingerprint(stock: Path) -> str:
    """Fingerprint the copy will have: stock gameplay files with the repo's built overlays on top
    (the same computation as raf_patch.fingerprint). Checked for real by the selftest."""
    files = {}
    for d in rp.GAMEPLAY_DIRS:
        for f in (stock / d).rglob("*"):
            if f.is_file() and f.suffix.lower() != ".lcl":
                files[f.relative_to(stock).as_posix().lower()] = f
    for n in rp.OVERLAY_ORDER:
        if n in FEATURES and n != "credits":
            for rel, src in rp.OVERLAYS[n].files().items():
                if any(rel.lower().startswith(d.lower() + "/") for d in rp.GAMEPLAY_DIRS) and not rel.lower().endswith(".lcl"):
                    files[rel.lower()] = src
    h = hashlib.sha256()
    for d in rp.GAMEPLAY_DIRS:  # same order as raf_patch.fingerprint: folder by folder
        for rel in sorted(r for r in files if r.startswith(d.lower() + "/")):
            h.update(rel.encode() + b"\0")
            h.update(hashlib.sha256(files[rel].read_bytes()).digest())
    if "target-priority" in FEATURES:
        h.update(rp.TARGET_PRIORITY_MARK)
    return h.hexdigest()[:12]


def third_party_licenses(dst: Path):
    """License texts of the frozen runtime, taken from the build venv."""
    out = subprocess.run([str(VPY), "-c", "import sys; print(sys.base_prefix)"], capture_output=True,
                         text=True, check=True).stdout.strip()
    base = Path(out)
    shutil.copy2(base / "LICENSE.txt", dst / "Python.txt")
    tk = sorted(base.glob("tcl/tk8*/license.terms"))
    if not tk:
        sys.exit("Tk license.terms not found")
    (dst / "Tcl-Tk.txt").write_text("Tcl and Tk are distributed under the same terms (Tk's license.terms below).\n\n"
                                    + tk[0].read_text(encoding="latin-1"), encoding="utf-8")
    site = VENV / "Lib" / "site-packages"
    for dist, name in (("numpy", "NumPy"), ("pillow", "Pillow"), ("pefile", "pefile"), ("pyinstaller", "PyInstaller")):
        info = next(site.glob(f"{dist}-*.dist-info"))
        if (info / "licenses").is_dir():
            shutil.copytree(info / "licenses", dst / name)
        elif (info / "LICENSE").is_file():
            (dst / name).mkdir()
            shutil.copy2(info / "LICENSE", dst / name / "LICENSE")
        else:
            sys.exit(f"no license in {info}")


def make_bundle(stock: Path):
    shutil.rmtree(BUNDLE, ignore_errors=True)
    (BUNDLE / "repo" / "tools").mkdir(parents=True)
    local, external = local_modules()
    for m in local:
        shutil.copy2(TOOLS / f"{m}.py", BUNDLE / "repo" / "tools" / f"{m}.py")
    shutil.copytree(REPO / "shaders", BUNDLE / "repo" / "shaders")
    for rel, (src, want) in REDIST.items():
        if want and fsha(src) != want:
            sys.exit(f"{src}: hash mismatch")
        (BUNDLE / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, BUNDLE / rel)
    lic = BUNDLE / "licenses"
    shutil.copytree(REPO / "installer" / "licenses", lic)
    shutil.copy2(REPO / "LICENSE", lic / "RaF-Remaster-Apache-2.0.txt")
    shutil.copy2(REPO / "NOTICE", lic / "NOTICE.txt")
    shutil.copy2(REPO / "NOTICE", BUNDLE / "NOTICE")  # -> REMASTER-NOTICE.txt in the game folder
    shutil.copy2(UI / "raf.ico", BUNDLE / "raf.ico")  # -> .raf-remaster/raf.ico: shortcuts, uninstall entry
    (lic / "Microsoft-vcomp140.txt").write_text(
        "vcomp140.dll (OpenMP runtime used by realesrgan-ncnn-vulkan) is part of the Microsoft Visual C++\n"
        "Redistributable and is shipped unchanged as in the upstream Real-ESRGAN ncnn Vulkan release\n"
        "(realesrgan-ncnn-vulkan-20220424-windows.zip), under the Visual Studio redistribution terms.\n",
        encoding="utf-8")
    third_party_licenses(lic)
    for lang in ("DE", "RU", "EN"):
        shutil.copy2(REPO / "installer" / f"README_{lang}.txt", BUNDLE / f"README_{lang}.txt")
    stock_map = stock_hashes(stock)
    fp = expected_fingerprint(stock)
    cfg = {"remaster_version": rp.REMASTER_VERSION, "game_version": GAME_VERSION, "features": FEATURES,
           "zoom": ZOOM, "fingerprint": fp, "gameplay_dirs": rp.GAMEPLAY_DIRS, "stock": stock_map,
           "local_modules": local, "extra_bytes": EXTRA_BYTES, "extra_bytes_hd": EXTRA_BYTES_HD}
    (BUNDLE / "installer.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"bundle: {len(local)} modules, {len(external)} external imports, {len(stock_map)} stock hashes, "
          f"expected fingerprint {fp}")
    return external


def build_launcher():
    """RaF Remaster.exe (onedir: no unpacking at every game start) -> bundle/launcher."""
    shutil.rmtree(LAUNCHER_DIST, ignore_errors=True)
    cmd = [str(VPY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", LAUNCHER_NAME,
           "--contents-directory", LAUNCHER_CONTENTS, "--distpath", str(LAUNCHER_DIST),
           "--workpath", str(WORK / "pyi-launcher"), "--specpath", str(WORK), "--paths", str(TOOLS),
           "--exclude-module", "numpy", "--exclude-module", "PIL", "--exclude-module", "pefile",
           "--icon", str(UI / "raf.ico"), "--add-data", f"{UI}{os.pathsep}ui", str(TOOLS / "raf_launcher.py")]
    subprocess.run(cmd, check=True, cwd=REPO)
    src = LAUNCHER_DIST / LAUNCHER_NAME
    dst = BUNDLE / "launcher"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"launcher: {dst / (LAUNCHER_NAME + '.exe')}, {sum(1 for _ in dst.rglob('*'))} entries, {size / 1e6:.1f} MB")


def pe_subsystem(exe: Path) -> int:
    """2 = Windows GUI (no console window), 3 = console."""
    b = exe.read_bytes()[:4096]
    pe = int.from_bytes(b[0x3C:0x40], "little")
    if b[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{exe}: not a PE file")
    return int.from_bytes(b[pe + 0x5C:pe + 0x5E], "little")


def check_windowed(*exes: Path) -> None:
    for exe in exes:
        sub = pe_subsystem(exe)
        if sub != 2:
            sys.exit(f"{exe}: PE subsystem {sub}, expected 2 (windowed); a console exe opens a console window")
        print(f"windowed: {exe.name} (PE subsystem 2)")


def write_hash(exe: Path) -> str:
    h = fsha(exe)
    (exe.parent / (exe.name + ".sha256")).write_text(f"{h}  {exe.name}\n", encoding="ascii")
    return h


def pyinstaller(external):
    hidden = []
    for n in external:
        hidden += ["--hidden-import", n]
    cmd = [str(VPY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", NAME,
           "--distpath", str(DIST), "--workpath", str(WORK / "pyi"), "--specpath", str(WORK),
           "--add-data", f"{BUNDLE}{os.pathsep}bundle", "--add-data", f"{UI}{os.pathsep}ui",
           "--icon", str(UI / "raf.ico"), "--exclude-module", "capstone", "--exclude-module", "unicorn",
           "--exclude-module", "matplotlib", "--exclude-module", "scipy",
           *hidden, str(TOOLS / "raf_installer.py")]
    subprocess.run(cmd, check=True, cwd=REPO)
    (DIST / "README.txt").unlink(missing_ok=True)  # single German README of the first build
    for lang in ("DE", "RU", "EN"):
        shutil.copy2(BUNDLE / f"README_{lang}.txt", DIST / f"README_{lang}.txt")
    shutil.rmtree(DIST / "licenses", ignore_errors=True)
    shutil.copytree(BUNDLE / "licenses", DIST / "licenses")


# ---------------------------------------------------------------- scan

# Generic leak patterns. Machine-specific ones (your user folder, source path, e-mail) go one per
# line into work/personal-patterns.txt (gitignored) or the file named by RAF_SCAN_PATTERNS.
PERSONAL = [rb"Games\RAF-remaster", b"Games/RAF-remaster", b"raf-inst-scratch"]
PERSONAL_FILE = Path(os.environ.get("RAF_SCAN_PATTERNS", str(REPO / "work" / "personal-patterns.txt")))


def personal_patterns() -> list:
    pats = list(PERSONAL)
    if PERSONAL_FILE.is_file():
        for line in PERSONAL_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(line.encode("utf-8"))
    else:
        print(f"scan: no {PERSONAL_FILE}, checking generic patterns only")
    email = os.environ.get("RAF_SCAN_EMAIL", "").encode()
    return pats + ([email] if email else [])
USERS = re.compile(rb"(?i)[a-z]:[\\/]users[\\/]([a-z0-9_.-]+)")


def exe_entries(exe: Path):
    """(name, bytes) of every file inside the onefile exe, PYZ modules as marshalled code."""
    code = ("import sys, marshal\n"
            "from PyInstaller.archive.readers import CArchiveReader, PKG_ITEM_PYZ\n"
            "a = CArchiveReader(sys.argv[1]); out = sys.stdout.buffer\n"
            "def emit(n, b):\n"
            "    n = n.encode('utf-8', 'replace'); out.write(len(n).to_bytes(4, 'little') + n + len(b).to_bytes(8, 'little') + b)\n"
            "for name, entry in a.toc.items():\n"
            "    if entry[-1] == PKG_ITEM_PYZ:\n"
            "        z = a.open_embedded_archive(name)\n"
            "        for m in z.toc:\n"
            "            d = z.extract(m, raw=True)\n"
            "            emit('PYZ:' + m, d if isinstance(d, bytes) else marshal.dumps(d))\n"
            "    else:\n"
            "        emit(name, a.extract(name))\n")
    raw = subprocess.run([str(VPY), "-c", code, str(exe)], capture_output=True, check=True).stdout
    i = 0
    while i < len(raw):
        n = int.from_bytes(raw[i:i + 4], "little")
        name = raw[i + 4:i + 4 + n].decode()
        i += 4 + n
        size = int.from_bytes(raw[i:i + 8], "little")
        data = raw[i + 8:i + 8 + size]
        i += 8 + size
        if name.startswith("PYZ:"):
            try:
                data = zlib.decompress(data)
            except zlib.error:
                pass
        yield name, data


def scan(exe: Path, stock: Path) -> bool:
    ref = {}
    roots = [stock] + sorted(p for p in (REPO / "work").glob("overlay*") if p.is_dir()) + [REPO / "ai" / "unit ai scripts"]
    for r in roots:
        for f in r.rglob("*"):
            if f.is_file() and f.stat().st_size > 0:
                ref.setdefault(fsha(f), str(f))
    print(f"scan: {len(ref)} reference hashes from {len(roots)} folders")
    patterns = personal_patterns()
    print(f"scan: {len(patterns)} leak patterns")
    hits, n, total, users = [], 0, 0, set()
    for name, data in exe_entries(exe):
        n += 1
        total += len(data)
        users.update(u.decode().lower() for u in USERS.findall(data))
        h = sha(data)
        if h in ref:
            hits.append(f"{name}: identical to {ref[h]}")
        for pat in patterns:
            if pat.lower() in data.lower():
                hits.append(f"{name}: contains {pat!r}")
    # the bundle folder itself (plain files) too
    for f in BUNDLE.rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            if fsha(f) in ref:
                hits.append(f"bundle/{f.relative_to(BUNDLE)}: identical to {ref[fsha(f)]}")
            for pat in patterns:
                if pat.lower() in data.lower():
                    hits.append(f"bundle/{f.relative_to(BUNDLE)}: contains {pat!r}")
    print(f"scan: {n} entries, {total / 1e6:.1f} MB uncompressed; user folders named inside (third-party "
          f"build paths): {', '.join(sorted(users)) or 'none'}")
    if os.environ.get("USERNAME", "").lower() in users:
        hits.append(f"the build user's folder name {os.environ['USERNAME']!r} appears")
    for h in hits:
        print("  HIT", h)
    print("scan: CLEAN" if not hits else f"scan: {len(hits)} hits")
    return not hits


def main():
    args = sys.argv[1:]
    stock = Path(args[args.index("--stock") + 1]) if "--stock" in args else rp.DEFAULT_STOCK
    exe = DIST / f"{NAME}.exe"
    if "--scan-only" not in args:
        ensure_venv()
        shutil.rmtree(UI, ignore_errors=True)
        make_icon.write_all(UI)
        external = make_bundle(stock)
        if "--skip-exe" in args:
            return
        build_launcher()
        pyinstaller(external)
        check_windowed(exe, BUNDLE / "launcher" / f"{LAUNCHER_NAME}.exe")
        print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB), sha256 {write_hash(exe)[:12]} "
              f"(+ {exe.name}.sha256), version {rp.REMASTER_VERSION}")
    if not scan(exe, stock):
        sys.exit(1)


if __name__ == "__main__":
    main()
