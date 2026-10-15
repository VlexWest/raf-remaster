"""Stub tests for tools/raf_installer.py (no game, no registry, no shortcuts).

    python tools/test_installer.py

Covers: stock checks (wrong exe, remaster folder, missing/changed/extra gameplay files), target path
rules, the failure path (half-made copy removed, original untouched), the HD fallback, the in-process
builder runner (exit codes) and the generated Deinstallieren.bat (registry restore lines, quoting).
"""

import hashlib
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_installer as ri  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def h(b):
    return hashlib.sha256(b).hexdigest()


def fake_stock(root: Path) -> dict:
    files = {"RiseAndFall.exe": b"MZexe", "DX9Rasterizer.dll": b"MZdll", "Language.dll": b"MZlang",
             "loadscreen.bmp": b"BM", "Data/db/dbworld.dat": b"world", "Data/scenarios/a.scn": b"scn",
             "Data/scenarios/a.lcl": b"text", "unins000.exe": b"MZuninst", "Data/textures/x.dds": b"DDS "}
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    stock = {rel: h(d) for rel, d in files.items() if not rel.endswith((".lcl", ".dds")) and rel != "unins000.exe"}
    return {"stock": stock, "game_version": "v1.15 (test)", "gameplay_dirs": ["Data/db", "Data/scenarios"],
            "extra_bytes": 0, "extra_bytes_hd": 0, "features": ["mips", "hd-terrain", "hd-units", "ai-hard"],
            "labels": {}, "zoom": 2.0, "fingerprint": "x", "remaster_version": "1.0", "local_modules": []}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="raf-inst-test-"))
    try:
        src = tmp / "Rise and Fall"
        cfg = fake_stock(src)

        # -- stock checks
        ok, msg = ri.quick_check(src, cfg)
        check(ok, f"quick_check accepts the stock folder ({msg})")
        errors, warnings = ri.full_check(src, cfg)
        check(not errors and not warnings, "full_check: stock folder is clean")
        (src / "Data/scenarios/custom.scn").write_bytes(b"mine")
        (src / "Data/scenarios/custom.lcl").write_bytes(b"mine")
        errors, warnings = ri.full_check(src, cfg)
        check(not errors and warnings == ["zusätzliche Datei: Data/scenarios/custom.scn"],
              "full_check: extra gameplay file only warns (.lcl ignored)")
        (src / "Data/scenarios/custom.scn").unlink()
        (src / "Data/db/dbworld.dat").write_bytes(b"modded")
        (src / "Data/scenarios/a.scn").unlink()
        errors, _ = ri.full_check(src, cfg)
        check(sorted(errors) == ["fehlt: Data/scenarios/a.scn", "verändert: Data/db/dbworld.dat"],
              "full_check: changed and missing gameplay files are errors")
        (src / "Data/db/dbworld.dat").write_bytes(b"world")
        (src / "Data/scenarios/a.scn").write_bytes(b"scn")
        (src / "RiseAndFall.exe").write_bytes(b"MZother")
        ok, msg = ri.quick_check(src, cfg)
        check(not ok and "unterstützt" in msg, "quick_check rejects another exe version")
        (src / "RiseAndFall.exe").write_bytes(b"MZexe")
        rem = tmp / "Remaster"
        shutil.copytree(src, rem)
        (rem / "REMASTER.txt").write_text("x")
        ok, msg = ri.quick_check(rem, cfg)
        check(not ok and "Remaster" in msg, "quick_check rejects a remaster folder")
        ok, _ = ri.quick_check(tmp / "nothing", cfg)
        check(not ok, "quick_check rejects a folder without the exe")

        # -- target rules
        def ins(dst, **k):
            return ri.Installer(cfg, tmp / "bundle", src, dst, test_root=tmp / "links", log=lambda s: None, **k)

        for dst, what in ((src / "Remaster", "inside the original"), (src, "the original itself"),
                          (rem, "a non-empty folder")):
            try:
                ins(dst).check_paths()
                check(False, f"check_paths refuses {what}")
            except SystemExit:
                check(True, f"check_paths refuses {what}")
        ins(tmp / "new" / "Rise and Fall Remaster").check_paths()
        check(True, "check_paths accepts a new folder")

        # -- failure path: copy done, patcher load fails -> copy removed, original untouched
        before = {p.relative_to(src).as_posix(): h(p.read_bytes()) for p in src.rglob("*") if p.is_file()}
        dst = tmp / "out" / "Rise and Fall Remaster"
        i = ins(dst)
        i.load_patcher = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            i.run()
            check(False, "run raises when a step fails")
        except RuntimeError:
            check(True, "run raises when a step fails")
        check(not dst.exists(), "failure path removes the half-made copy")
        after = {p.relative_to(src).as_posix(): h(p.read_bytes()) for p in src.rglob("*") if p.is_file()}
        check(before == after, "original folder unchanged")

        # copy skips the original's uninstaller
        dst2 = tmp / "copy2"
        j = ins(dst2)
        j.copy()
        check((dst2 / "RiseAndFall.exe").exists() and not (dst2 / "unins000.exe").exists(),
              "copy leaves out unins000.exe")

        # -- HD fallback in build_overlays
        built = []

        class Ov:
            def __init__(self, name, fail=False):
                self.name, self.fail = name, fail

            def build(self, stock):
                if self.fail:
                    raise SystemExit("vulkan missing")
                built.append(self.name)

        rp = types.SimpleNamespace(OVERLAY_ORDER=["mips", "hd-terrain", "hd-units", "ai-hard", "credits"],
                                   OVERLAYS={"mips": Ov("mips"), "hd-terrain": Ov("hd-terrain", True),
                                             "hd-units": Ov("hd-units"), "ai-hard": Ov("ai-hard")},
                                   REPO=tmp / "repo")
        k = ins(tmp / "x")
        k.rp = rp
        feats = k.build_overlays(list(cfg["features"]))
        check(feats == ["mips", "ai-hard"] and built == ["mips", "ai-hard"] and "hd_failed" in k.result,
              "HD failure drops both HD features and keeps going")

        # -- builder runner
        repo = tmp / "repo"
        (repo / "tools").mkdir(parents=True)
        (repo / "tools" / "ok.py").write_text("import sys\nprint('built', sys.argv[1:])\nsys.exit(0)\n")
        (repo / "tools" / "bad.py").write_text("import sys\nsys.exit('stock changed')\n")
        fake_rp = types.ModuleType("raf_patch")
        fake_rp.REPO = repo
        sys.modules["raf_patch"] = fake_rp
        ov = types.SimpleNamespace(name="t", built=lambda: True,
                                   build_cmd=lambda st: ["py", "tools/ok.py", st, "out"])
        ri._run_builder(ov, "STOCK")
        check(True, "runner accepts exit 0")
        ov.build_cmd = lambda st: ["py", "tools/bad.py"]
        try:
            ri._run_builder(ov, "STOCK")
            check(False, "runner raises on a builder error exit")
        except SystemExit as e:
            check(e.code == "stock changed", "runner raises on a builder error exit")
        ov.build_cmd, ov.built = (lambda st: ["py", "tools/ok.py"]), (lambda: False)
        try:
            ri._run_builder(ov, "STOCK")
            check(False, "runner fails when the overlay is missing afterwards")
        except SystemExit:
            check(True, "runner fails when the overlay is missing afterwards")
        del sys.modules["raf_patch"]

        # -- uninstall script
        saved = {"Full Screen Mode": None, "Game Window Width": 1024, "Graphics Settings/Flora Quality": 0}
        bat = ri.uninstall_bat(Path(r"D:\G\Rise and Fall Remaster"), r"Software\T\Rise and Fall", saved,
                               "D:\\Games\\Rise and Fall\\", [r"C:\L\a.lnk"], Path(r"C:\L\Menu"),
                               r"Software\T\Uninstall\RaF-Remaster")
        check('reg delete "HKCU\\Software\\T\\Rise and Fall" /v "Full Screen Mode" /f' in bat, "bat deletes values that did not exist")
        check('/v "Game Window Width" /t REG_DWORD /d 1024' in bat, "bat restores old DWORD values")
        check('"HKCU\\Software\\T\\Rise and Fall\\Graphics Settings" /v "Flora Quality" /t REG_DWORD /d 0' in bat,
              "bat handles subkey values")
        check('/v "Install Directory" /t REG_SZ /d "D:\\Games\\Rise and Fall\\\\" /f' in bat,
              "bat restores Install Directory (trailing backslash doubled for reg.exe)")
        check(bat.index(":running") > bat.index("rd /s /q \"D:\\G\\Rise and Fall Remaster\""), "folder removal is the last step")
        try:
            ri.uninstall_bat(Path(r"D:\100%\x"), "k", {}, None, [], None, "u")
            check(False, "bat refuses % in paths")
        except SystemExit:
            check(True, "bat refuses % in paths")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
