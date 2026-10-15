"""No console windows from the windowed setup / launcher (tools/raf_proc.py and every call site).

    python tools/test_no_console.py

1.0.0 bug: the setup's Popen hook only added CREATE_NO_WINDOW when a caller passed no creationflags,
and the HD builders pass BELOW_NORMAL_PRIORITY_CLASS, so every texconv / ESRGAN call opened a
console window. Checks:
  - static: every subprocess call in the modules the setup and launcher ship passes creationflags
    containing NO_WINDOW (so they are hidden even without the hook);
  - hook: real child processes, flags read at _winapi.CreateProcess: no flags, BELOW_NORMAL,
    positional flags, CREATE_NEW_CONSOLE left alone, installed once; counter-check with the 1.0.0
    hook (BELOW_NORMAL call without NO_WINDOW is caught);
  - call paths, recorded at _winapi.CreateProcess before any process starts: texconv decode,
    texconv mip chain, texconv encode (build_textures), git (build_shaders), tasklist + builder
    run (raf_patch), PowerShell folder lookup + shortcuts, game start after install/update
    (raf_installer), game start + update setup start (raf_launcher), the Vulkan probe (a real child);
  - entry points: raf_installer.main in every mode and raf_launcher.main install the hook first;
  - dist (when built): setup and launcher are PE subsystem 2 (windowed).
"""

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import _winapi  # noqa: E402

import raf_proc  # noqa: E402

FAILS = []
NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x4000
NEW_CONSOLE = 0x10
SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


class Recorded(BaseException):
    """Raised instead of starting a process (BaseException: passes `except Exception` in the code)."""


class Recorder:
    """Wraps _winapi.CreateProcess (what subprocess.Popen finally calls) and records the flags."""

    def __init__(self, passthrough=False):
        self.calls, self.passthrough, self.orig = [], passthrough, None

    def __enter__(self):
        self.orig = _winapi.CreateProcess

        def fake(executable, args, pa, ta, inherit, flags, env, cwd, startupinfo):
            self.calls.append((args, flags))
            if self.passthrough:
                return self.orig(executable, args, pa, ta, inherit, flags, env, cwd, startupinfo)
            raise Recorded(args)

        _winapi.CreateProcess = fake
        return self

    def __exit__(self, *exc):
        _winapi.CreateProcess = self.orig
        return False

    def hidden(self):
        return bool(self.calls) and all(f & NO_WINDOW for _, f in self.calls)


def run_recorded(fn, *a, **k):
    with Recorder() as r:
        try:
            fn(*a, **k)
        except Recorded:
            pass
        except Exception as e:  # noqa: BLE001 - only the recorded calls matter
            r.calls.append((f"error {type(e).__name__}: {e}", 0))
    return r


# ---------------------------------------------------------------- static


def shipped_modules():
    import build_installer as bi

    local, _ = bi.local_modules()
    return sorted(set(local) | {"raf_installer", "raf_launcher", "raf_update", "raf_proc", "raf_ui",
                                "raf_installer_text", "raf_version"})


def check_static():
    mods = shipped_modules()
    bad, n = [], 0
    for m in mods:
        tree = ast.parse((TOOLS / f"{m}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in SUBPROCESS_CALLS and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"):
                continue
            n += 1
            kw = {k.arg: k.value for k in node.keywords}
            if "creationflags" not in kw or "NO_WINDOW" not in ast.unparse(kw["creationflags"]):
                bad.append(f"{m}.py:{node.lineno}")
    check(n >= 12 and not bad, f"static: {n} subprocess calls in {len(mods)} shipped modules all pass NO_WINDOW "
                               f"{bad or ''}")
    check("build_textures" in mods and "raf_proc" in mods, "static: builders and raf_proc are in the setup bundle")


# ---------------------------------------------------------------- hook semantics


def check_hook():
    cmd = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"), "/c", "exit 0"]
    raf_proc.uninstall()
    with Recorder(passthrough=True) as r:
        subprocess.run(cmd, creationflags=BELOW_NORMAL)
    check(r.calls and not r.calls[0][1] & NO_WINDOW, "counter-check: without the hook a BELOW_NORMAL call has no NO_WINDOW")

    def old_hook():  # the 1.0.0 version (raf_installer.no_console_windows)
        orig = subprocess.Popen.__init__

        def init(self, *a, **k):
            if not k.get("creationflags"):
                k["creationflags"] = NO_WINDOW
            orig(self, *a, **k)

        subprocess.Popen.__init__ = init
        return orig

    orig = old_hook()
    with Recorder(passthrough=True) as r:
        subprocess.run(cmd, creationflags=BELOW_NORMAL)
    subprocess.Popen.__init__ = orig
    check(r.calls and not r.calls[0][1] & NO_WINDOW, "counter-check: the 1.0.0 hook misses BELOW_NORMAL calls (the bug)")

    raf_proc.install()
    raf_proc.install()
    check(getattr(subprocess.Popen.__init__, "_raf_no_window", False)
          and not getattr(subprocess.Popen.__init__._raf_orig, "_raf_no_window", False), "hook: installed once")
    with Recorder(passthrough=True) as r:
        p = subprocess.run(cmd)
        subprocess.run(cmd, creationflags=BELOW_NORMAL)
        subprocess.run(cmd, capture_output=True, text=True)
        subprocess.Popen(cmd, -1, None, None, None, None, None, True, False, None, None, None, None,
                         BELOW_NORMAL).wait()
        subprocess.run(cmd, creationflags=NEW_CONSOLE)
    f = [c[1] for c in r.calls]
    check(p.returncode == 0 and len(f) == 5, "hook: children really start and exit 0")
    check(f[0] & NO_WINDOW and f[2] & NO_WINDOW, "hook: no flags -> NO_WINDOW")
    check(f[1] == BELOW_NORMAL | NO_WINDOW and f[3] == BELOW_NORMAL | NO_WINDOW,
          "hook: BELOW_NORMAL (keyword and positional) keeps the priority and adds NO_WINDOW")
    check(f[4] == NEW_CONSOLE, "hook: an explicit CREATE_NEW_CONSOLE is left alone")
    raf_proc.uninstall()
    check(not getattr(subprocess.Popen.__init__, "_raf_no_window", False), "hook: removable (tests)")


# ---------------------------------------------------------------- call paths (hook off: flags must be explicit)


def check_paths(tmp: Path):
    import numpy as np  # noqa: F401 - build_textures needs it

    import build_shaders as bs
    import build_textures as bt
    import raf_installer as ri
    import raf_launcher as rl
    import raf_patch as rp

    raf_proc.uninstall()
    bt.TEXCONV = bt.ESRGAN_EXE = str(tmp / "nothing.exe")
    dxt1 = {"w": 8, "h": 8, "faces": 1, "mips": 1, "fmt": "DXT1", "bpp": 4, "off": 128}
    src = bytes(128) + bytes(32)
    r = run_recorded(bt.process, "t.dds", dxt1, src, str(tmp / "bt"))
    check(r.hidden(), f"build_textures: texconv mip chain hidden {r.calls[:1]}")
    item = ("t.dds", dict(dxt1), src, 0, False, False)
    r = run_recorded(bt.hd_prepare, item, str(tmp / "bt2"))
    check(r.hidden(), f"build_textures: texconv decode (HD) hidden {r.calls[:1]}")
    rgb = np.zeros((8, 8, 3), np.float32)
    a = np.full((8, 8), 255.0, np.float32)
    r = run_recorded(bt.hd_finish, ("t.dds", dict(dxt1), src, 0, False, True), rgb, a, str(tmp / "bt3"))
    check(r.hidden(), f"build_textures: texconv encode (HD) hidden {r.calls[:1]}")
    r = run_recorded(bs.git_rev)
    check(r.hidden(), "build_shaders: git hidden")

    game = tmp / "game"
    game.mkdir()
    (game / rp.EXE).write_bytes(b"MZ")
    r = run_recorded(rp.check_game_dir, game)
    check(r.hidden(), "raf_patch: tasklist hidden")
    ov = next(iter(rp.OVERLAYS.values()))
    old_cmd = ov.build_cmd
    ov.build_cmd = lambda stock: [sys.executable, "tools/x.py"]
    try:
        r = run_recorded(rp.Overlay.build, ov, game)
    finally:
        ov.build_cmd = old_cmd
    check(r.hidden(), "raf_patch: builder subprocess hidden")

    r = run_recorded(ri._known_folder, "Desktop")
    check(r.hidden(), "raf_installer: PowerShell folder lookup hidden")
    r = run_recorded(ri.make_shortcuts, [(tmp / "a.lnk", game / rp.EXE, "", None)], game)
    check(r.hidden(), "raf_installer: PowerShell shortcuts hidden")
    r = run_recorded(ri.start_installed, game)
    check(r.hidden(), "raf_installer: game start after install / update hidden flag")
    r = run_recorded(rl.start_game, game, "-x", {})
    check(r.hidden(), "raf_launcher: game start carries NO_WINDOW (ignored by Windows for the GUI game)")

    # launcher -> update setup: run() with every network/dialog step stubbed
    ru = rl.ru
    saved = {k: getattr(ru, k) for k in ("load_override", "install_info", "installed_version", "download_dir",
                                         "cleanup_downloads", "check", "to_offer", "installed_fingerprint",
                                         "download_setup")}
    try:
        ru.load_override = lambda g: {"test_answer": "update", "test": True}
        ru.install_info = lambda g: {"lang": "en"}
        ru.installed_version = lambda g: "1.0.0"
        ru.download_dir = lambda o: tmp
        ru.cleanup_downloads = lambda f: None
        ru.check = lambda g, force=False, override=None: {"source": "stub", "error": None, "release": {"tag": "v9"}}
        ru.to_offer = lambda g, rel, cur: {"tag": "v9"}
        ru.installed_fingerprint = lambda g: "fp"
        ru.download_setup = lambda offer, folder, test=False: tmp / "setup.exe"
        r = run_recorded(rl.run, ["--game", str(game)], "")
    finally:
        for k, v in saved.items():
            setattr(ru, k, v)
    check(r.hidden() and "--update" in str(r.calls[0][0]), f"raf_launcher: update setup start hidden {r.calls[:1]}")

    with Recorder(passthrough=True) as r:
        info = ri.probe_gpu(timeout=60)
    check(r.hidden() and "verdict" in info, f"raf_installer: Vulkan probe child hidden (loader {info.get('loader')})")


# ---------------------------------------------------------------- entry points


def check_entries():
    import raf_installer as ri
    import raf_launcher as rl

    seen = {}
    saved = (ri.selftest, ri.update_main, ri.gui, ri.vulkan_probe, rl.run, sys.argv)
    hooked = lambda: bool(getattr(subprocess.Popen.__init__, "_raf_no_window", False))  # noqa: E731
    try:
        ri.selftest = lambda argv, silent=False: seen.setdefault("silent" if silent else "selftest", hooked()) and 0
        ri.update_main = lambda argv: seen.setdefault("update", hooked()) and 0
        ri.gui = lambda: seen.setdefault("gui", hooked())
        ri.vulkan_probe = lambda: seen.setdefault("probe", hooked()) and {}
        out = Path(tempfile.gettempdir()) / "raf-noconsole-probe.json"
        for args in (["--selftest"], ["--silent"], ["--update", "x"], [], ["--vulkan-probe", str(out)]):
            raf_proc.uninstall()
            sys.argv = ["setup"] + args
            ri.main()
        out.unlink(missing_ok=True)
        raf_proc.uninstall()
        rl.run = lambda argv, tail: seen.setdefault("launcher", hooked()) and 0
        sys.argv = ["launcher"]
        rl.main()
    finally:
        ri.selftest, ri.update_main, ri.gui, ri.vulkan_probe, rl.run, sys.argv = saved
        raf_proc.uninstall()
    want = ["selftest", "silent", "update", "gui", "probe", "launcher"]
    check(all(seen.get(k) for k in want), f"entry points install the hook first {seen}")


def check_dist():
    import build_installer as bi

    for exe in (bi.DIST / f"{bi.NAME}.exe", bi.BUNDLE / "launcher" / f"{bi.LAUNCHER_NAME}.exe"):
        if exe.is_file():
            check(bi.pe_subsystem(exe) == 2, f"dist: {exe.name} is windowed (PE subsystem 2)")
        else:
            print(f"skip {exe} (not built)")


def main():
    if os.name != "nt":
        print("Windows only")
        return 0
    check_static()
    check_hook()
    with tempfile.TemporaryDirectory(prefix="raf-noconsole-") as t:
        check_paths(Path(t))
    check_entries()
    check_dist()
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
