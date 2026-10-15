"""Rise and Fall Remaster installer for other players (frozen into RaF-Remaster-Setup.exe).

The installer ships no game files and nothing derived from them. It carries our own code
(tools/*.py, shaders/), redistributable tools (texconv, realesrgan-ncnn-vulkan + model, DXVK) and
a list of stock sha256 hashes. On the player's PC it
  1. finds the stock install (registry, Inno Setup uninstall entry, common paths, or browse) and
     checks it against the stock hashes (Russian v1.15),
  2. copies it into a new folder (the original is only read),
  3. builds every overlay from the player's own files with the same builders raf_patch.py uses
     (run in-process), then runs raf_patch.apply on the copy with the release feature set,
  4. writes shortcuts, Deinstallieren.bat and a per-user uninstall entry, and shows the gameplay
     fingerprint the players compare.

    RaF-Remaster-Setup.exe                         GUI (German)
    RaF-Remaster-Setup.exe --selftest --source S --target T --test-root R [--no-hd] [--log F]
        same path without GUI; registry goes to HKCU\\Software\\RaF-Remaster-Installer-Test,
        shortcuts into R; exit code 0 = installed and fingerprint as expected.
Unfrozen (tests): python tools/raf_installer.py ... with RAF_INSTALLER_BUNDLE=<bundle dir>.
"""

import base64
import ctypes
import hashlib
import io
import json
import os
import queue
import runpy
import shutil
import string
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

APP = "Rise and Fall Remaster"
EXE = "RiseAndFall.exe"
UNINSTALL_ID = "RaF-Remaster"
REG_GAME = r"Software\Midway Home Entertainment\Rise and Fall"
REG_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
TEST_ROOT_KEY = r"Software\RaF-Remaster-Installer-Test"
HD_FEATURES = ("hd-terrain", "hd-units")
COPY_SKIP = {"unins000.exe", "unins000.dat", ".raf-remaster"}  # never copy the original's uninstaller
CREATE_NO_WINDOW = 0x08000000
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")

# ---------------------------------------------------------------- bundle + config


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bundle"
    env = os.environ.get("RAF_INSTALLER_BUNDLE")
    if not env:
        sys.exit("RAF_INSTALLER_BUNDLE is not set (unfrozen run)")
    return Path(env)


def load_config(bundle: Path) -> dict:
    return json.loads((bundle / "installer.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def no_console_windows() -> None:
    """Builders start texconv / realesrgan; in a windowed exe every child would flash a console."""
    orig = subprocess.Popen.__init__

    def init(self, *a, **k):
        if os.name == "nt" and not k.get("creationflags"):
            k["creationflags"] = CREATE_NO_WINDOW
        orig(self, *a, **k)

    subprocess.Popen.__init__ = init


# ---------------------------------------------------------------- finding the stock install


def _reg_read(root, path, name, view=0):
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _inno_locations():
    import winreg

    out = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                k = winreg.OpenKey(root, REG_UNINSTALL, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    name = _reg_read(root, REG_UNINSTALL + "\\" + sub, "DisplayName", view) or ""
                    if "rise and fall" in str(name).lower() and "remaster" not in str(name).lower():
                        loc = _reg_read(root, REG_UNINSTALL + "\\" + sub, "InstallLocation", view)
                        if loc:
                            out.append(str(loc))
    return out


def _drives():
    mask = ctypes.windll.kernel32.GetLogicalDrives() if os.name == "nt" else 0
    return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def candidates() -> list:
    """Possible stock install folders, best first, existing and not a remaster copy."""
    raw = []
    import winreg

    raw += _inno_locations()
    inst = _reg_read(winreg.HKEY_CURRENT_USER, REG_GAME, "Install Directory")
    if inst:
        inst = str(inst)
        # the game writes it itself, sometimes without the drive letter ("\GAMES\RAF\")
        raw += [inst] if len(inst) > 1 and inst[1] == ":" else [d + inst.lstrip("\\/") for d in _drives()]
    for d in _drives():
        for rel in (r"Games\Rise and Fall", r"Program Files (x86)\Midway\Rise and Fall",
                    r"Program Files (x86)\Rise and Fall", r"Program Files\Rise and Fall", r"Rise and Fall"):
            raw.append(d + rel)
    seen, out = set(), []
    for c in raw:
        p = Path(c)
        key = os.path.normcase(str(p))
        if key in seen:
            continue
        seen.add(key)
        if (p / EXE).is_file() and not is_remaster(p):
            out.append(p)
    return out


def is_remaster(p: Path) -> bool:
    return (p / "REMASTER.txt").exists() or (p / ".raf-remaster").exists()


def quick_check(src: Path, cfg: dict):
    """(ok, message) from the exe and rasterizer hashes only."""
    if not (src / EXE).is_file():
        return False, f"{EXE} nicht gefunden."
    if is_remaster(src):
        return False, "Das ist schon eine Remaster-Installation. Bitte den Ordner des Originalspiels wählen."
    for name in (EXE, "DX9Rasterizer.dll"):
        want = cfg["stock"].get(name)
        if not (src / name).is_file() or sha256(src / name) != want:
            return False, (f"{name} passt nicht zur unterstützten Version. Unterstützt wird nur "
                           f"Rise and Fall {cfg['game_version']} ohne weitere Patches oder Mods.")
    return True, f"Rise and Fall {cfg['game_version']} erkannt."


def full_check(src: Path, cfg: dict, progress=None):
    """(errors, warnings). Every hashed stock file must exist and match; extra files in the gameplay
    folders only warn (the fingerprint then differs from the other players)."""
    errors, warnings = [], []
    items = sorted(cfg["stock"].items())
    for i, (rel, want) in enumerate(items):
        p = src / rel
        if not p.is_file():
            errors.append(f"fehlt: {rel}")
        elif sha256(p) != want:
            errors.append(f"verändert: {rel}")
        if progress:
            progress(i + 1, len(items))
    known = {r.lower() for r in cfg["stock"]}
    for d in cfg["gameplay_dirs"]:
        for f in (src / d).rglob("*") if (src / d).is_dir() else []:
            rel = f.relative_to(src).as_posix()
            if f.is_file() and f.suffix.lower() != ".lcl" and rel.lower() not in known:
                warnings.append(f"zusätzliche Datei: {rel}")
    return errors, warnings


def folder_size(src: Path) -> int:
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in COPY_SKIP]
        n += sum(os.path.getsize(os.path.join(root, f)) for f in files if f.lower() not in COPY_SKIP)
    return n


def needed_bytes(src_size: int, cfg: dict, hd: bool) -> int:
    return src_size + cfg["extra_bytes"] + (cfg["extra_bytes_hd"] if hd else 0)


def writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".raf-write-test-{os.getpid()}"
        probe.mkdir()
        probe.rmdir()
        return True
    except OSError:
        return False


def default_target(src: Path) -> Path:
    t = src.parent / f"{APP}"
    if writable(src.parent):
        return t
    return Path.home() / "Games" / APP


def free_bytes(target: Path) -> int:
    p = target
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


# ---------------------------------------------------------------- install


class Installer:
    def __init__(self, cfg, bundle, src, dst, hd=True, desktop=True, startmenu=True, test_root=None,
                 log=print, step=lambda text, frac=None: None):
        self.cfg, self.bundle, self.src, self.dst = cfg, bundle, Path(src), Path(dst)
        self.hd, self.desktop, self.startmenu = hd, desktop, startmenu
        self.test_root = Path(test_root) if test_root else None
        self.log, self.step = log, step
        self.reg_game = (TEST_ROOT_KEY + r"\Rise and Fall") if self.test_root else REG_GAME
        self.reg_uninstall = (TEST_ROOT_KEY + r"\Uninstall") if self.test_root else REG_UNINSTALL
        self.created_dst = False
        self.shortcuts = []
        self.result = {}

    # -- paths
    def check_paths(self):
        s, d = self.src.resolve(), self.dst.resolve()
        if d == s or s in d.parents or d in s.parents:
            raise SystemExit("Der Zielordner darf nicht im Originalordner liegen (und umgekehrt).")
        if d.exists() and any(d.iterdir()):
            raise SystemExit(f"Der Zielordner ist nicht leer: {d}\nBitte einen neuen Ordner wählen.")

    def copy(self):
        total = folder_size(self.src)
        need = needed_bytes(total, self.cfg, self.hd)
        free = free_bytes(self.dst)
        if free < need:
            raise SystemExit(f"Zu wenig Speicherplatz: {need / 1e9:.1f} GB nötig, {free / 1e9:.1f} GB frei.")
        self.created_dst = True
        self.dst.mkdir(parents=True, exist_ok=True)
        done = 0
        for root, dirs, files in os.walk(self.src):
            dirs[:] = [x for x in dirs if x.lower() not in COPY_SKIP]
            rel = Path(root).relative_to(self.src)
            (self.dst / rel).mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.lower() in COPY_SKIP:
                    continue
                shutil.copy2(os.path.join(root, f), self.dst / rel / f)
                done += os.path.getsize(os.path.join(root, f))
                self.step(f"Kopiere Spieldateien ({done / 1e9:.1f} von {total / 1e9:.1f} GB)", done / max(total, 1))
        self.log(f"kopiert: {total / 1e9:.2f} GB nach {self.dst}")

    def load_patcher(self):
        """Our code goes into <dst>/.raf-remaster/build (a repo layout: tools/, shaders/, work/)."""
        self.build = self.dst / ".raf-remaster" / "build"
        shutil.copytree(self.bundle / "repo", self.build, dirs_exist_ok=True)
        sys.path.insert(0, str(self.build / "tools"))
        for m in [m for m in sys.modules if m in self.cfg["local_modules"]]:
            del sys.modules[m]
        import raf_patch as rp

        if rp.REPO.resolve() != self.build.resolve():
            raise RuntimeError(f"raf_patch loaded from {rp.REPO}, expected {self.build}")
        rp.REG_KEY = self.reg_game
        rp.Overlay.build = _run_builder
        self.rp = rp

    def build_overlays(self, feats):
        rp = self.rp
        names = [n for n in rp.OVERLAY_ORDER if n in feats and n != "credits"]
        for i, n in enumerate(names):
            if n in HD_FEATURES and "hd_failed" in self.result:
                continue
            label = self.cfg["labels"].get(n, n)
            self.step(f"Erzeuge {label} aus deinen Spieldateien ({i + 1}/{len(names)})", None)
            t = time.time()
            try:
                rp.OVERLAYS[n].build(self.src)
            except BaseException as e:  # noqa: BLE001 - builders end with sys.exit on errors
                if n in HD_FEATURES and not isinstance(e, KeyboardInterrupt):
                    self.log(f"{n}: fehlgeschlagen ({_msg(e)}); HD-Texturen werden übersprungen.")
                    self.result["hd_failed"] = _msg(e)
                    feats = [f for f in feats if f not in HD_FEATURES]
                    continue
                raise
            finally:
                # the HD steps leave their PNG work files (up to 1.7 GB) in work/cache
                shutil.rmtree(rp.REPO / "work" / "cache" / f"hd-{n}", ignore_errors=True)
            self.log(f"{n}: gebaut in {time.time() - t:.0f} s")
        return feats

    def apply(self, feats):
        self.step("Patche die Kopie", None)
        self.install_dir_before = _reg_read_hkcu(self.reg_game, "Install Directory")
        self.rp.apply(self.dst, only=feats, stock=str(self.src), zoom=self.cfg["zoom"], net="auto")
        st = json.loads((self.dst / ".raf-remaster" / "state.json").read_text())
        self.result.update(fingerprint=st["fingerprint"], features=st["features"])

    def finish_files(self):
        shutil.rmtree(self.build, ignore_errors=True)
        shutil.copy2(self.bundle / "README.txt", self.dst / "REMASTER-README.txt")
        shutil.copytree(self.bundle / "licenses", self.dst / "Remaster-Lizenzen", dirs_exist_ok=True)

    def shortcuts_and_uninstall(self):
        if self.test_root:
            desk = self.test_root / "Desktop"
            menu = self.test_root / "Startmenu" / APP
        else:
            desk = Path(_known_folder("Desktop"))
            menu = Path(_known_folder("Programs")) / APP
        exe = self.dst / EXE
        links = []
        if self.desktop:
            links.append((desk / f"{APP}.lnk", exe, '-datapath "Data\\" -redistpath "Redist\\"', exe))
        if self.startmenu:
            links += [
                (menu / f"{APP}.lnk", exe, '-datapath "Data\\" -redistpath "Redist\\"', exe),
                (menu / "Netzwerkspiel hosten.lnk", self.dst / "Host.bat", "", exe),
                (menu / "Netzwerkspiel beitreten.lnk", self.dst / "Join.bat", "", exe),
                (menu / "Fingerabdruck und Version.lnk", self.dst / "REMASTER.txt", "", None),
                (menu / f"{APP} deinstallieren.lnk", self.dst / "Deinstallieren.bat", "", None),
            ]
        if links:
            make_shortcuts(links, self.dst)
        self.shortcuts = [str(p) for p, *_ in links]
        self.menu_dir = menu if self.startmenu else None
        saved = json.loads((self.dst / ".raf-remaster" / "registry.json").read_text())
        bat = uninstall_bat(self.dst, self.reg_game, saved, self.install_dir_before, self.shortcuts,
                            self.menu_dir, self.reg_uninstall + "\\" + UNINSTALL_ID)
        (self.dst / "Deinstallieren.bat").write_bytes(bat.replace("\n", "\r\n").encode("utf-8"))
        size_kb = folder_size(self.dst) // 1024
        _reg_write_uninstall(self.reg_uninstall + "\\" + UNINSTALL_ID, {
            "DisplayName": APP, "DisplayVersion": self.cfg["remaster_version"],
            "Publisher": "Alexander West (thewest.cc/raf)", "InstallLocation": str(self.dst),
            "UninstallString": f'"{self.dst / "Deinstallieren.bat"}"', "DisplayIcon": str(exe),
            "NoModify": 1, "NoRepair": 1, "EstimatedSize": min(size_kb, 0x7FFFFFFF)})
        self.result["uninstall"] = str(self.dst / "Deinstallieren.bat")

    def run(self):
        try:
            self.check_paths()
            self.step("Prüfe das Originalspiel", 0)
            ok, msg = quick_check(self.src, self.cfg)
            if not ok:
                raise SystemExit(msg)
            errors, warnings = full_check(self.src, self.cfg,
                                          lambda i, n: self.step("Prüfe das Originalspiel", i / n))
            if errors:
                raise SystemExit("Das Originalspiel weicht von der unterstützten Version ab:\n"
                                 + "\n".join(errors[:12]) + ("\n..." if len(errors) > 12 else ""))
            for w in warnings:
                self.log("Hinweis: " + w)
            self.result["warnings"] = warnings
            self.copy()
            self.load_patcher()
            feats = list(self.cfg["features"])
            if not self.hd:
                feats = [f for f in feats if f not in HD_FEATURES]
            feats = self.build_overlays(feats)
            self.apply(feats)
            self.finish_files()
            self.shortcuts_and_uninstall()
            self.result["expected_fingerprint"] = self.cfg["fingerprint"]
            self.result["fingerprint_ok"] = self.result["fingerprint"] == self.cfg["fingerprint"]
            self.step("Fertig", 1)
            return self.result
        except BaseException:
            self.cleanup()
            raise

    def cleanup(self):
        """Failure path: put the registry back and remove the half-made copy (only if we made it)."""
        try:
            rp = getattr(self, "rp", None)
            if rp is not None and (self.dst / ".raf-remaster" / "registry.json").exists():
                rp.restore_registry(self.dst)
        except BaseException as e:  # noqa: BLE001
            self.log(f"Registry konnte nicht zurückgesetzt werden: {_msg(e)}")
        if self.created_dst:
            shutil.rmtree(self.dst, ignore_errors=True)
            self.log(f"Abgebrochen, {self.dst} wieder entfernt.")


def _msg(e: BaseException) -> str:
    if isinstance(e, SystemExit):
        return str(e.code)
    return f"{type(e).__name__}: {e}"


def _run_builder(self, stock):
    """Overlay.build replacement: run the builder script in-process (sys.executable is this exe)."""
    import raf_patch as rp

    cmd = [str(c) for c in self.build_cmd(stock)]
    script, argv = rp.REPO / cmd[1], cmd[1:]
    old_argv, old_cwd, old_path = sys.argv, os.getcwd(), list(sys.path)
    os.chdir(rp.REPO)
    sys.argv = [str(script)] + argv[1:]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            raise
    finally:
        sys.argv, sys.path[:] = old_argv, old_path
        os.chdir(old_cwd)
    if not self.built():
        raise SystemExit(f"{self.name}: builder finished but the overlay is missing")


def _reg_read_hkcu(path, name):
    import winreg

    return _reg_read(winreg.HKEY_CURRENT_USER, path, name)


def _reg_write_uninstall(path, values):
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        for n, v in values.items():
            if isinstance(v, int):
                winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, v)
            else:
                winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)


def _known_folder(name: str) -> str:
    """Desktop / Programs via the shell (follows OneDrive redirection)."""
    ps = f"[Environment]::GetFolderPath('{name}')"
    out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, creationflags=CREATE_NO_WINDOW).stdout.strip()
    if not out:
        raise RuntimeError(f"Ordner {name} nicht gefunden")
    return out


def _ps_quote(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcuts(links, workdir: Path) -> None:
    lines = ["$ErrorActionPreference = 'Stop'", "$sh = New-Object -ComObject WScript.Shell"]
    for lnk, target, args, icon in links:
        lines += [f"New-Item -ItemType Directory -Force -Path {_ps_quote(Path(lnk).parent)} | Out-Null",
                  f"$s = $sh.CreateShortcut({_ps_quote(lnk)})",
                  f"$s.TargetPath = {_ps_quote(target)}",
                  f"$s.Arguments = {_ps_quote(args)}",
                  f"$s.WorkingDirectory = {_ps_quote(workdir)}"]
        if icon:
            lines.append(f"$s.IconLocation = {_ps_quote(str(icon) + ',0')}")
        lines.append("$s.Save()")
    enc = base64.b64encode("\n".join(lines).encode("utf-16-le")).decode()
    r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("Verknüpfungen: " + (r.stderr or r.stdout).strip()[:400])


def uninstall_bat(dst: Path, reg_game: str, saved: dict, install_dir_before, shortcuts, menu_dir,
                  uninstall_key: str) -> str:
    """Deinstallieren.bat: restores the registry values the patcher changed (saved = registry.json),
    the game's Install Directory, removes shortcuts, the uninstall entry and the folder."""
    for s in [str(dst), reg_game] + list(shortcuts) + [str(menu_dir or "")]:
        if "%" in s or '"' in s:
            raise SystemExit(f"Pfad mit % oder \" wird nicht unterstützt: {s}")
    hk = "HKCU\\" + reg_game
    out = ["@echo off", "chcp 65001 >nul", "setlocal",
           f"rem {APP}: uninstall (written by the installer)",
           'if /i "%~1"=="/quiet" goto run',
           f"echo {APP} deinstallieren",
           "echo Der Remaster-Ordner wird gelöscht, das Originalspiel bleibt unverändert.",
           f'echo Ordner: "{dst}"',
           'choice /c JN /m "Wirklich deinstallieren"',
           "if errorlevel 2 exit /b 1",
           ":run",
           'tasklist /FI "IMAGENAME eq RiseAndFall.exe" /NH | find /i "RiseAndFall.exe" >nul',
           "if not errorlevel 1 goto running"]
    for name, value in sorted(saved.items()):
        sub, _, val = name.rpartition("/")
        key = hk + ("\\" + sub.replace("/", "\\") if sub else "")
        if value is None:
            out.append(f'reg delete "{key}" /v "{val}" /f >nul 2>&1')
        else:
            out.append(f'reg add "{key}" /v "{val}" /t REG_DWORD /d {int(value)} /f >nul')
    if install_dir_before is None:
        out.append(f'reg delete "{hk}" /v "Install Directory" /f >nul 2>&1')
    else:
        v = str(install_dir_before)
        if "%" in v or '"' in v:
            raise SystemExit("Install Directory enthält % oder \"")
        # reg.exe eats a trailing backslash before the closing quote: double it
        out.append(f'reg add "{hk}" /v "Install Directory" /t REG_SZ /d "{v + chr(92) if v.endswith(chr(92)) else v}" /f >nul')
    for s in shortcuts:
        out.append(f'del /f /q "{s}" >nul 2>&1')
    if menu_dir:
        out.append(f'rd /s /q "{menu_dir}" >nul 2>&1')
    out += [f'reg delete "HKCU\\{uninstall_key}" /f >nul 2>&1',
            'cd /d "%TEMP%"',
            "echo Rise and Fall Remaster wurde entfernt.",
            'if /i not "%~1"=="/quiet" timeout /t 3 >nul',
            f'(goto) 2>nul & rd /s /q "{dst}"',
            ":running",
            "echo Bitte zuerst das Spiel schließen und dann erneut starten.",
            'if /i not "%~1"=="/quiet" pause',
            "exit /b 2"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- output plumbing


class QueueWriter(io.TextIOBase):
    def __init__(self, q, logfile=None):
        self.q, self.buf, self.logfile = q, "", logfile

    def write(self, s):
        if self.logfile:
            try:
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write(s)
            except OSError:
                pass
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.q.put(("log", line))
        return len(s)

    def flush(self):
        pass


def log_path() -> Path:
    return Path(os.environ.get("TEMP", ".")) / "RaF-Remaster-Setup.log"


# ---------------------------------------------------------------- self test (no GUI)


def selftest(argv) -> int:
    opts = {}
    it = iter(argv)
    for a in it:
        if a in ("--source", "--target", "--test-root", "--log"):
            opts[a] = next(it)
        elif a == "--no-hd":
            opts[a] = True
    logf = Path(opts.get("--log") or log_path())

    def out(s):
        with open(logf, "a", encoding="utf-8") as f:
            f.write(s + "\n")

    class W(io.TextIOBase):
        def write(self, s):
            with open(logf, "a", encoding="utf-8") as f:
                f.write(s)
            return len(s)

    sys.stdout = sys.stderr = W()
    bundle = bundle_dir()
    cfg = load_config(bundle)
    out(f"selftest: bundle {bundle}, frozen={getattr(sys, 'frozen', False)}, python {sys.version.split()[0]}")
    out(f"candidates: {[str(c) for c in candidates()]}")
    last = [0.0]

    def step(text, frac=None):
        if time.time() - last[0] > 5 or frac in (0, 1):
            last[0] = time.time()
            out(f"[step] {text}" + (f" {frac:.0%}" if frac is not None else ""))

    ins = Installer(cfg, bundle, opts["--source"], opts["--target"], hd="--no-hd" not in opts,
                    test_root=opts["--test-root"], log=out, step=step)
    try:
        res = ins.run()
    except BaseException as e:  # noqa: BLE001
        out("FAILED: " + _msg(e))
        out(traceback.format_exc())
        return 1
    out("RESULT " + json.dumps(res, ensure_ascii=False))
    return 0 if res.get("fingerprint_ok") else 3


# ---------------------------------------------------------------- GUI


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    bundle = bundle_dir()
    cfg = load_config(bundle)
    q = queue.Queue()
    sys.stdout = sys.stderr = QueueWriter(q, log_path())
    try:
        log_path().write_text("", encoding="utf-8")
    except OSError:
        pass

    root = tk.Tk()
    root.title(f"{APP} {cfg['remaster_version']} – Installation")
    root.minsize(720, 560)
    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text=f"{APP} {cfg['remaster_version']}", font=("Segoe UI", 15, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, wraplength=680, justify="left", text=(
        "Der Installer kopiert dein Rise and Fall in einen neuen Ordner und baut dort das Remaster "
        "aus deinen eigenen Spieldateien. Das Originalspiel wird nicht verändert. Unterstützt wird "
        f"Rise and Fall {cfg['game_version']}.")).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))

    src_var, dst_var = tk.StringVar(), tk.StringVar()
    src_status, space_status = tk.StringVar(), tk.StringVar()
    hd_var, desk_var, menu_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    state = {"src_ok": False, "src_size": None, "busy": False}

    ttk.Label(frm, text="Originalspiel:").grid(row=2, column=0, sticky="w")
    ttk.Entry(frm, textvariable=src_var).grid(row=2, column=1, sticky="we", padx=6)
    ttk.Button(frm, text="Durchsuchen …", command=lambda: browse(src_var, True)).grid(row=2, column=2)
    src_lbl = ttk.Label(frm, textvariable=src_status, wraplength=680, justify="left")
    src_lbl.grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 8))

    ttk.Label(frm, text="Zielordner:").grid(row=4, column=0, sticky="w")
    ttk.Entry(frm, textvariable=dst_var).grid(row=4, column=1, sticky="we", padx=6)
    ttk.Button(frm, text="Durchsuchen …", command=lambda: browse(dst_var, False)).grid(row=4, column=2)
    ttk.Label(frm, textvariable=space_status).grid(row=5, column=1, columnspan=2, sticky="w", pady=(2, 8))

    opts = ttk.Frame(frm)
    opts.grid(row=6, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(opts, variable=hd_var, command=lambda: update_space(), text=(
        "HD-Texturen erzeugen (braucht eine Grafikkarte mit Vulkan, dauert je nach Grafikkarte "
        "3 bis 20 Minuten)")).pack(anchor="w")
    ttk.Checkbutton(opts, variable=desk_var, text="Verknüpfung auf dem Desktop").pack(anchor="w")
    ttk.Checkbutton(opts, variable=menu_var, text="Einträge im Startmenü (Spielen, Hosten, Beitreten, "
                    "Deinstallieren)").pack(anchor="w")

    btns = ttk.Frame(frm)
    btns.grid(row=7, column=0, columnspan=3, sticky="we", pady=10)
    install_btn = ttk.Button(btns, text="Installieren", command=lambda: start())
    install_btn.pack(side="left")
    close_btn = ttk.Button(btns, text="Schließen", command=root.destroy)
    close_btn.pack(side="right")

    step_var = tk.StringVar(value="Bereit.")
    ttk.Label(frm, textvariable=step_var).grid(row=8, column=0, columnspan=3, sticky="w")
    bar = ttk.Progressbar(frm, mode="determinate", maximum=1000)
    bar.grid(row=9, column=0, columnspan=3, sticky="we", pady=4)
    logbox = tk.Text(frm, height=10, wrap="word", state="disabled", font=("Consolas", 9))
    logbox.grid(row=10, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(10, weight=1)

    fp_frame = ttk.Frame(frm)
    fp_frame.grid(row=11, column=0, columnspan=3, sticky="we", pady=(8, 0))

    def add_log(line):
        logbox.configure(state="normal")
        logbox.insert("end", line + "\n")
        logbox.see("end")
        logbox.configure(state="disabled")

    def browse(var, is_src):
        d = filedialog.askdirectory(title="Ordner des Originalspiels wählen" if is_src else "Zielordner wählen",
                                    initialdir=var.get() or None)
        if d:
            var.set(str(Path(d)))
            if is_src:
                check_src()
            else:
                update_space()

    def check_src(*_):
        p = Path(src_var.get().strip()) if src_var.get().strip() else None
        state["src_ok"], state["src_size"] = False, None
        if not p:
            src_status.set("Kein Originalspiel gefunden. Bitte den Ordner mit RiseAndFall.exe wählen.")
            return
        src_status.set("Prüfe …")

        def work():
            ok, msg = quick_check(p, cfg)
            size = folder_size(p) if ok else None
            q.put(("src", (str(p), ok, msg, size)))

        threading.Thread(target=work, daemon=True).start()

    def update_space(*_):
        dst = dst_var.get().strip()
        if not dst or not state["src_size"]:
            space_status.set("")
            return
        need = needed_bytes(state["src_size"], cfg, hd_var.get())
        try:
            free = free_bytes(Path(dst))
        except OSError:
            space_status.set("Laufwerk nicht gefunden.")
            return
        mark = "ausreichend" if free >= need else "ZU WENIG"
        space_status.set(f"Benötigt etwa {need / 1e9:.1f} GB, frei {free / 1e9:.1f} GB ({mark}).")

    dst_var.trace_add("write", update_space)

    def start():
        if state["busy"]:
            return
        if not state["src_ok"]:
            messagebox.showerror(APP, "Bitte zuerst den Ordner des Originalspiels wählen.")
            return
        src, dst = Path(src_var.get().strip()), Path(dst_var.get().strip())
        if not dst_var.get().strip():
            messagebox.showerror(APP, "Bitte einen Zielordner wählen.")
            return
        state["busy"] = True
        install_btn.configure(state="disabled")
        close_btn.configure(state="disabled")

        def step(text, frac=None):
            q.put(("step", (text, frac)))

        def work():
            ins = Installer(cfg, bundle, src, dst, hd=hd_var.get(), desktop=desk_var.get(),
                            startmenu=menu_var.get(), log=print, step=step)
            try:
                q.put(("done", ins.run()))
            except BaseException as e:  # noqa: BLE001
                print(traceback.format_exc())
                q.put(("error", _msg(e)))

        threading.Thread(target=work, daemon=True).start()

    def finished(res):
        state["busy"] = False
        close_btn.configure(state="normal")
        bar.configure(mode="determinate", value=1000)
        bar.stop()
        ttk.Label(fp_frame, text="Gameplay-Fingerabdruck:").pack(anchor="w")
        e = ttk.Entry(fp_frame, font=("Consolas", 18, "bold"), width=14, justify="center")
        e.insert(0, res["fingerprint"])
        e.configure(state="readonly")
        e.pack(anchor="w", pady=2)
        txt = ("Vergleiche diesen Fingerabdruck mit deinem Mitspieler. Nur wenn beide gleich sind, "
               "läuft ein Netzwerkspiel ohne Abbruch. Er steht auch in REMASTER.txt im Spielordner.")
        if not res.get("fingerprint_ok"):
            txt += (f"\nACHTUNG: erwartet war {res['expected_fingerprint']}. Deine Spieldaten weichen ab; "
                    "im Netzwerk mit anderen Remaster-Spielern gibt es wahrscheinlich Abbrüche.")
        if res.get("hd_failed"):
            txt += "\nHD-Texturen konnten nicht erzeugt werden (keine passende Grafikkarte?). Das Spiel läuft ohne sie."
        ttk.Label(fp_frame, text=txt, wraplength=680, justify="left").pack(anchor="w")
        row = ttk.Frame(fp_frame)
        row.pack(anchor="w", pady=6)
        dst = Path(dst_var.get().strip())
        ttk.Button(row, text="Ordner öffnen", command=lambda: os.startfile(dst)).pack(side="left")
        ttk.Button(row, text="Spiel starten", command=lambda: subprocess.Popen(
            [str(dst / EXE), "-datapath", "Data\\", "-redistpath", "Redist\\"], cwd=dst)).pack(side="left", padx=6)
        step_var.set("Installation abgeschlossen.")

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    add_log(val)
                elif kind == "step":
                    text, frac = val
                    step_var.set(text)
                    if frac is None:
                        if str(bar.cget("mode")) != "indeterminate":
                            bar.configure(mode="indeterminate")
                            bar.start(15)
                    else:
                        if str(bar.cget("mode")) != "determinate":
                            bar.stop()
                            bar.configure(mode="determinate")
                        bar.configure(value=int(frac * 1000))
                elif kind == "src":
                    path, ok, msg, size = val
                    if path != src_var.get().strip():
                        continue
                    state["src_ok"], state["src_size"] = ok, size
                    src_status.set(("OK: " if ok else "Fehler: ") + msg)
                    if ok and not dst_var.get().strip():
                        dst_var.set(str(default_target(Path(path))))
                    update_space()
                elif kind == "done":
                    finished(val)
                elif kind == "error":
                    state["busy"] = False
                    install_btn.configure(state="normal")
                    close_btn.configure(state="normal")
                    bar.stop()
                    bar.configure(mode="determinate", value=0)
                    step_var.set("Abgebrochen.")
                    messagebox.showerror(APP, f"Die Installation ist fehlgeschlagen:\n\n{val}\n\n"
                                         f"Protokoll: {log_path()}")
        except queue.Empty:
            pass
        root.after(100, poll)

    src_var.trace_add("write", lambda *_: root.after_idle(check_src) if not state["busy"] else None)
    found = candidates()
    if found:
        src_var.set(str(found[0]))
    else:
        check_src()
    root.protocol("WM_DELETE_WINDOW", lambda: None if state["busy"] else root.destroy())
    poll()
    root.mainloop()


def main() -> int:
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # raf_patch.desktop_mode sets it later anyway
        except Exception:  # noqa: BLE001
            pass
    no_console_windows()
    if "--selftest" in sys.argv:
        return selftest(sys.argv[1:])
    gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
