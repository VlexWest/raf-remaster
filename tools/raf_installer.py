"""Rise and Fall Remaster installer for other players (frozen into RaF-Remaster-Setup.exe).

The installer ships no game files and nothing derived from them. It carries our own code
(tools/*.py, shaders/), redistributable tools (texconv, realesrgan-ncnn-vulkan + model, DXVK) and
a list of stock sha256 hashes. On the player's PC it
  1. finds the stock install (registry, Inno Setup uninstall entry, common paths, or browse) and
     checks it against the stock hashes (Russian v1.15),
  2. probes Vulkan (in a child process): DXVK 3.1.1 only when a GPU meets its requirements,
     otherwise the game keeps the Windows Direct3D 9 (d3d9.dll + dxvk.conf removed after apply),
  3. copies the install into a new folder (the original is only read),
  4. builds every overlay from the player's own files with the same builders raf_patch.py uses
     (run in-process), then runs raf_patch.apply on the copy with the release feature set,
  5. writes shortcuts, Uninstall.bat and a per-user uninstall entry, and shows the gameplay
     fingerprint the players compare.
UI languages: German, Russian, English (raf_installer_text.py), picked from the Windows UI language.

    RaF-Remaster-Setup.exe [--lang de|ru|en]       GUI (language from Windows unless given)
    RaF-Remaster-Setup.exe --selftest --source S --target T --test-root R [--no-hd] [--log F]
                           [--lang de|ru|en] [--force-native]
        same path without GUI; registry goes to HKCU\\Software\\RaF-Remaster-Installer-Test,
        shortcuts into R; exit code 0 = installed and fingerprint as expected.
    RaF-Remaster-Setup.exe --silent --source S --target T [--lang de|ru|en] [--no-hd] [--no-shortcuts]
                           [--force-native] [--log F]
        unattended install for third-party launchers (real registry, no window); exit codes:
        0 installed, fingerprint as expected; 1 failed (nothing left behind); 2 bad arguments;
        3 installed but the fingerprint differs from the release (extra files in the original)
    RaF-Remaster-Setup.exe --update DIR [--wait-pid P] [--lang L] [--relaunch-b64 B] [--headless --log F]
                           [--no-launch]
        update an existing remaster install (started by the launcher RaF Remaster.exe after the
        player clicked "Update now"): rebuilds from the original game remembered in
        DIR/.raf-remaster/install.json into DIR.raf-update, swaps the folders, copies saves and own
        files over, keeps the registry settings, then starts the game. Any failure before the old
        folder is deleted puts the previous version back. Exit 0 ok, 1 failed, 2 refused (game
        running, original not found, not a remaster install).
    RaF-Remaster-Setup.exe --vulkan-probe OUT.json  (used internally; crash-safe child process)
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
import tempfile
import threading
import time
import traceback
from pathlib import Path

import raf_update as ru
from raf_installer_text import LANGS, T, detect_lang, get_lang, set_lang
from raf_version import VERSION

APP = "Rise and Fall Remaster"
EXE = "RiseAndFall.exe"
UNINSTALL_ID = "RaF-Remaster"
UNINSTALL_BAT = "Uninstall.bat"
LAUNCHER_EXE = ru.LAUNCHER_EXE  # bundle/launcher/: RaF Remaster.exe + .raf-launcher/ (tools/raf_launcher.py)
NOTICE_NAME = "REMASTER-NOTICE.txt"
REG_GAME = r"Software\Midway Home Entertainment\Rise and Fall"
REG_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
TEST_ROOT_KEY = r"Software\RaF-Remaster-Installer-Test"
HD_FEATURES = ("hd-terrain", "hd-units")
DXVK_FILES = ("d3d9.dll", "dxvk.conf")
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


def feature_label(name: str) -> str:
    try:
        return T("f_" + name)
    except KeyError:
        return name


# ---------------------------------------------------------------- Vulkan / DXVK probe
# DXVK 3.1.1 (src/dxvk/dxvk_device_info.cpp, checkDeviceCompatibility + getFeatureList): device
# apiVersion >= 1.3, a graphics queue, required extensions below, maxPushConstantsSize >= 256 unless
# VK_EXT_descriptor_heap, plus core features every Vulkan 1.3 desktop driver has (not probed).
DXVK_API = (1, 3)
DXVK_EXTENSIONS = ["VK_KHR_swapchain", "VK_EXT_depth_clip_enable", "VK_EXT_robustness2",
                   "VK_KHR_load_store_op_none", "VK_KHR_maintenance5", "VK_KHR_maintenance6"]
DXVK_PUSH = 256
VK_DEVICE_TYPES = {0: "other", 1: "integrated", 2: "discrete", 3: "virtual", 4: "cpu"}
VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}


def _ver(v: int) -> str:
    return f"{(v >> 22) & 0x7F}.{(v >> 12) & 0x3FF}.{v & 0xFFF}"


def vulkan_probe() -> dict:
    """Query the Vulkan loader of this (64-bit) process. Runs in a child process (--vulkan-probe):
    a broken driver can crash it without taking the installer down."""
    out = {"loader": False, "devices": [],
           "loader32": os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64",
                                                   "vulkan-1.dll"))}
    try:
        vk = ctypes.WinDLL("vulkan-1.dll")
    except OSError:
        return out
    out["loader"] = True
    u32, ptr = ctypes.c_uint32, ctypes.c_void_p
    inst_ver = u32(0)
    try:
        vk.vkEnumerateInstanceVersion(ctypes.byref(inst_ver))
    except AttributeError:
        inst_ver.value = 1 << 22  # 1.0 loader
    out["instance_api"] = _ver(inst_ver.value)

    class AppInfo(ctypes.Structure):
        _fields_ = [("sType", u32), ("pNext", ptr), ("pApplicationName", ctypes.c_char_p),
                    ("applicationVersion", u32), ("pEngineName", ctypes.c_char_p), ("engineVersion", u32),
                    ("apiVersion", u32)]

    class InstInfo(ctypes.Structure):
        _fields_ = [("sType", u32), ("pNext", ptr), ("flags", u32), ("pApplicationInfo", ctypes.POINTER(AppInfo)),
                    ("enabledLayerCount", u32), ("ppEnabledLayerNames", ptr),
                    ("enabledExtensionCount", u32), ("ppEnabledExtensionNames", ptr)]

    api = min(inst_ver.value, (1 << 22) | (3 << 12))
    app = AppInfo(0, None, b"RaF Remaster Setup", 1, b"none", 1, api)
    info = InstInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
    inst = ptr()
    res = vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(inst))
    if res != 0:
        out["error"] = f"vkCreateInstance {res}"
        return out
    try:
        n = u32(0)
        vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(n), None)
        devs = (ptr * n.value)()
        vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(n), devs)
        for d in devs[:n.value]:
            props = ctypes.create_string_buffer(4096)
            vk.vkGetPhysicalDeviceProperties(ptr(d), props)
            raw = props.raw
            apiv, drv, vendor, _devid, dtype = (int.from_bytes(raw[i:i + 4], "little") for i in range(0, 20, 4))
            name = raw[20:276].split(b"\0")[0].decode("utf-8", "replace")
            # VkPhysicalDeviceLimits starts at 296 (8-byte aligned after uuid); maxPushConstantsSize is u32 #9
            push = int.from_bytes(raw[296 + 32:296 + 36], "little")
            m = u32(0)
            vk.vkEnumerateDeviceExtensionProperties(ptr(d), None, ctypes.byref(m), None)
            ext_buf = ctypes.create_string_buffer(260 * max(m.value, 1))
            vk.vkEnumerateDeviceExtensionProperties(ptr(d), None, ctypes.byref(m), ext_buf)
            exts = {ext_buf.raw[i * 260:i * 260 + 256].split(b"\0")[0].decode() for i in range(m.value)}
            out["devices"].append({
                "name": name, "api": _ver(apiv), "type": VK_DEVICE_TYPES.get(dtype, str(dtype)),
                "vendor": VENDORS.get(vendor, hex(vendor)), "driver": drv, "push": push,
                "max_2d": int.from_bytes(raw[296 + 4:296 + 8], "little"),
                "missing": [e for e in DXVK_EXTENSIONS if e not in exts],
                "descriptor_heap": "VK_EXT_descriptor_heap" in exts})
    finally:
        vk.vkDestroyInstance(inst, None)
    return out


def _api_tuple(s: str):
    try:
        return tuple(int(x) for x in s.split(".")[:2])
    except (ValueError, AttributeError):
        return (0, 0)


def dxvk_verdict(info: dict) -> dict:
    """{dxvk: bool, hd: bool, name, api, reason} from a vulkan_probe() result."""
    real = [d for d in info.get("devices", []) if d.get("type") != "cpu"]
    rank = {"discrete": 0, "integrated": 1}
    real.sort(key=lambda d: rank.get(d.get("type"), 2))
    best = real[0] if real else None
    out = {"dxvk": False, "hd": bool(real), "name": best["name"] if best else None,
           "api": best["api"] if best else None, "reason": ""}
    if not info.get("loader"):
        out["reason"] = "no Vulkan driver"
        return out
    if not real:
        out["reason"] = "no Vulkan GPU"
        return out
    if not info.get("loader32"):
        out["reason"] = "no 32-bit Vulkan loader"
        return out
    if _api_tuple(info.get("instance_api", "")) < DXVK_API:
        out["reason"] = f"Vulkan loader {info.get('instance_api')}"
        return out
    reasons = []
    for d in real:
        why = []
        if _api_tuple(d["api"]) < DXVK_API:
            why.append(f"Vulkan {d['api']}")
        if d.get("missing"):
            why.append("missing " + ", ".join(d["missing"]))
        if d.get("push", 0) < DXVK_PUSH and not d.get("descriptor_heap"):
            why.append(f"push constants {d.get('push')}")
        if not why:
            out.update(dxvk=True, name=d["name"], api=d["api"], reason="")
            return out
        reasons.append(f"{d['name']}: " + "; ".join(why))
    out["reason"] = " | ".join(reasons)
    return out


def probe_gpu(timeout=30) -> dict:
    """Run vulkan_probe in a child process (this exe again, or this script unfrozen)."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="raf-vk-")
    os.close(fd)
    cmd = [sys.executable] + ([] if getattr(sys, "frozen", False) else [os.path.abspath(__file__)])
    info = {"loader": False, "devices": [], "error": "probe failed"}
    try:
        subprocess.run(cmd + ["--vulkan-probe", path], timeout=timeout, creationflags=CREATE_NO_WINDOW,
                       capture_output=True)
        txt = Path(path).read_text(encoding="utf-8")
        if txt.strip():
            info = json.loads(txt)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        info["error"] = f"probe failed: {e}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    info["verdict"] = dxvk_verdict(info)
    return info


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
    import winreg

    raw = _inno_locations()
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
    gv = cfg["game_version"]
    if not (src / EXE).is_file():
        return False, T("chk_exe_missing", exe=EXE)
    if is_remaster(src):
        return False, T("chk_is_remaster")
    for name in (EXE, "DX9Rasterizer.dll"):
        want = cfg["stock"].get(name)
        if not (src / name).is_file() or sha256(src / name) != want:
            return False, T("chk_bad_version", name=name, gv=gv)
    return True, T("chk_ok", gv=gv)


def full_check(src: Path, cfg: dict, progress=None):
    """(errors, warnings). Every hashed stock file must exist and match; extra files in the gameplay
    folders only warn (the fingerprint then differs from the other players)."""
    errors, warnings = [], []
    items = sorted(cfg["stock"].items())
    for i, (rel, want) in enumerate(items):
        p = src / rel
        if not p.is_file():
            errors.append(T("missing", rel=rel))
        elif sha256(p) != want:
            errors.append(T("changed", rel=rel))
        if progress:
            progress(i + 1, len(items))
    known = {r.lower() for r in cfg["stock"]}
    for d in cfg["gameplay_dirs"]:
        for f in (src / d).rglob("*") if (src / d).is_dir() else []:
            rel = f.relative_to(src).as_posix()
            if f.is_file() and f.suffix.lower() != ".lcl" and rel.lower() not in known:
                warnings.append(T("extra", rel=rel))
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
    if writable(src.parent):
        return src.parent / APP
    return Path.home() / "Games" / APP


def free_bytes(target: Path) -> int:
    p = target
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


# ---------------------------------------------------------------- install


class Installer:
    def __init__(self, cfg, bundle, src, dst, hd=True, dxvk=True, desktop=True, startmenu=True, test_root=None,
                 log=print, step=lambda text, frac=None: None, force_native=False, update_info=None):
        """update_info: install.json of the install being updated (+ "_dir"). Update mode carries
        registry.json over, keeps the player's registry values and restores the values from before
        the update if it fails."""
        self.cfg, self.bundle, self.src, self.dst = cfg, bundle, Path(src), Path(dst)
        self.hd, self.dxvk, self.desktop, self.startmenu = hd, dxvk, desktop, startmenu
        self.force_native, self.update_info = force_native, update_info
        self.reg_snapshot = None
        self.install_dir_before = None
        self.test_root = Path(test_root) if test_root else None
        self.log, self.step = log, step
        self.reg_game = (TEST_ROOT_KEY + r"\Rise and Fall") if self.test_root else REG_GAME
        self.reg_uninstall = (TEST_ROOT_KEY + r"\Uninstall") if self.test_root else REG_UNINSTALL
        self.created_dst = False
        self.shortcuts = []
        self.result = {}

    def check_paths(self):
        s, d = self.src.resolve(), self.dst.resolve()
        if d == s or s in d.parents or d in s.parents:
            raise SystemExit(T("err_nested"))
        if d.exists() and any(d.iterdir()):
            raise SystemExit(T("err_not_empty", d=d))

    def copy(self):
        total = folder_size(self.src)
        need = needed_bytes(total, self.cfg, self.hd)
        free = free_bytes(self.dst)
        if free < need:
            raise SystemExit(T("err_space", need=need / 1e9, free=free / 1e9))
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
                self.step(T("step_copy", done=done / 1e9, total=total / 1e9), done / max(total, 1))
        self.log(T("log_copied", gb=total / 1e9, dst=self.dst))

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
            self.step(T("step_build", label=feature_label(n), i=i + 1, n=len(names)), None)
            t = time.time()
            try:
                rp.OVERLAYS[n].build(self.src)
            except BaseException as e:  # noqa: BLE001 - builders end with sys.exit on errors
                if n in HD_FEATURES and not isinstance(e, KeyboardInterrupt):
                    self.log(T("log_hd_failed", n=n, msg=_msg(e)))
                    self.result["hd_failed"] = _msg(e)
                    feats = [f for f in feats if f not in HD_FEATURES]
                    continue
                raise
            finally:
                # the HD steps leave their PNG work files (up to 1.7 GB) in work/cache
                shutil.rmtree(rp.REPO / "work" / "cache" / f"hd-{n}", ignore_errors=True)
            self.log(T("log_built", n=n, s=f"{time.time() - t:.0f}"))
        return feats

    def apply(self, feats):
        self.step(T("step_patch"), None)
        upd = self.update_info
        if upd is not None:
            # the value from before the FIRST install (the game has rewritten it since)
            self.install_dir_before = upd.get("install_dir_before")
            old_reg = Path(upd["_dir"]) / ".raf-remaster" / "registry.json"
            if old_reg.is_file():  # pre-remaster values for Uninstall.bat; managed values are kept
                (self.dst / ".raf-remaster").mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_reg, self.dst / ".raf-remaster" / "registry.json")
            self._snapshot_registry()
            self.rp.apply(self.dst, only=feats, stock=str(self.src), zoom=self.cfg["zoom"], net="auto",
                          keep_settings=True)
        else:
            self.install_dir_before = _reg_read_hkcu(self.reg_game, "Install Directory")
            self.rp.apply(self.dst, only=feats, stock=str(self.src), zoom=self.cfg["zoom"], net="auto")
        state_path = self.dst / ".raf-remaster" / "state.json"
        st = json.loads(state_path.read_text())
        if not self.dxvk:
            # no Vulkan 1.3 GPU: keep the Windows d3d9 (raf_patch.revert deletes these names anyway)
            for name in DXVK_FILES:
                (self.dst / name).unlink(missing_ok=True)
            st["dxvk"] = False
            state_path.write_text(json.dumps(st, indent=2))
            self.log(T("log_native"))
        self.result.update(fingerprint=st["fingerprint"], features=st["features"], dxvk=self.dxvk)

    def _snapshot_registry(self):
        """Update mode: remember the current value of every name raf_patch.apply writes, so a failed
        update can put the player's values back (registry.json holds the pre-remaster values)."""
        rp, orig = self.rp, self.rp.set_registry

        def wrapped(game, values, release=(), defaults=None, keep=()):
            import winreg

            snap = {}
            for name in set(values) | set(release) | set(defaults or {}):
                path, val = rp._reg_split(name)
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                        snap[name] = winreg.QueryValueEx(k, val)[0]
                except OSError:
                    snap[name] = None
            self.reg_snapshot = snap
            return orig(game, values, release, defaults, keep)

        rp.set_registry = wrapped

    def finish_files(self):
        shutil.rmtree(self.build, ignore_errors=True)
        for lang in LANGS:
            shutil.copy2(self.bundle / f"README_{lang.upper()}.txt", self.dst / f"REMASTER-README_{lang.upper()}.txt")
        shutil.copytree(self.bundle / "licenses", self.dst / "Remaster-Licenses", dirs_exist_ok=True)
        if (self.bundle / "NOTICE").is_file():
            shutil.copy2(self.bundle / "NOTICE", self.dst / NOTICE_NAME)
        launcher = self.bundle / "launcher"
        if (launcher / LAUNCHER_EXE).is_file():
            shutil.copytree(launcher, self.dst, dirs_exist_ok=True)
        info = {"version": self.cfg.get("remaster_version", VERSION), "stock": str(self.src.resolve()),
                "hd": bool(self.hd), "force_native": bool(self.force_native), "desktop": bool(self.desktop),
                "startmenu": bool(self.startmenu), "lang": get_lang(),
                "install_dir_before": self.install_dir_before,
                "test_root": str(self.test_root) if self.test_root else None,
                "fingerprint": self.result.get("fingerprint"), "installed": time.strftime("%Y-%m-%d %H:%M:%S")}
        (self.dst / ".raf-remaster").mkdir(parents=True, exist_ok=True)
        (self.dst / ".raf-remaster" / ru.INSTALL_FILE).write_text(json.dumps(info, indent=1, ensure_ascii=False),
                                                                  encoding="utf-8")

    def shortcuts_and_uninstall(self):
        if self.test_root:
            desk = self.test_root / "Desktop"
            menu = self.test_root / "Startmenu" / APP
        else:
            desk = Path(_known_folder("Desktop"))
            menu = Path(_known_folder("Programs")) / APP
        exe = self.dst / EXE
        args = '-datapath "Data\\" -redistpath "Redist\\"'
        if (self.dst / LAUNCHER_EXE).is_file():  # update check first; the launcher adds the data paths
            target, args = self.dst / LAUNCHER_EXE, ""
        else:
            target = exe
        links = []
        if self.desktop:
            links.append((desk / f"{APP}.lnk", target, args, exe))
        if self.startmenu:
            links += [
                (menu / f"{APP}.lnk", target, args, exe),
                (menu / f"{T('lnk_host')}.lnk", self.dst / "Host.bat", "", exe),
                (menu / f"{T('lnk_join')}.lnk", self.dst / "Join.bat", "", exe),
                (menu / f"{T('lnk_fp')}.lnk", self.dst / "REMASTER.txt", "", None),
                (menu / f"{T('lnk_uninst', app=APP)}.lnk", self.dst / UNINSTALL_BAT, "", None),
            ]
        if links:
            make_shortcuts(links, self.dst)
        self.shortcuts = [str(p) for p, *_ in links]
        self.menu_dir = menu if self.startmenu else None
        saved = json.loads((self.dst / ".raf-remaster" / "registry.json").read_text())
        bat = uninstall_bat(self.dst, self.reg_game, saved, self.install_dir_before, self.shortcuts,
                            self.menu_dir, self.reg_uninstall + "\\" + UNINSTALL_ID)
        (self.dst / UNINSTALL_BAT).write_bytes(bat.replace("\n", "\r\n").encode("utf-8"))
        size_kb = folder_size(self.dst) // 1024
        _reg_write_uninstall(self.reg_uninstall + "\\" + UNINSTALL_ID, {
            "DisplayName": APP, "DisplayVersion": self.cfg.get("remaster_version", VERSION),
            "Publisher": "Alexander West (thewest.cc/raf)", "InstallLocation": str(self.dst),
            "UninstallString": f'"{self.dst / UNINSTALL_BAT}"', "DisplayIcon": str(exe),
            "NoModify": 1, "NoRepair": 1, "EstimatedSize": min(size_kb, 0x7FFFFFFF)})
        self.result["uninstall"] = str(self.dst / UNINSTALL_BAT)

    def run(self, links=True):
        """Install. links=False (update mode) stops before shortcuts and the uninstall entry: they
        name the final folder, which only exists after the swap (run_update calls them later)."""
        try:
            self.check_paths()
            self.step(T("step_check"), 0)
            ok, msg = quick_check(self.src, self.cfg)
            if not ok:
                raise SystemExit(msg)
            errors, warnings = full_check(self.src, self.cfg, lambda i, n: self.step(T("step_check"), i / n))
            if errors:
                raise SystemExit(T("err_stock") + "\n" + "\n".join(errors[:12]) + ("\n..." if len(errors) > 12 else ""))
            for w in warnings:
                self.log(T("log_note", w=w))
            self.result["warnings"] = warnings
            self.copy()
            self.load_patcher()
            feats = list(self.cfg["features"])
            if not self.hd:
                feats = [f for f in feats if f not in HD_FEATURES]
            feats = self.build_overlays(feats)
            self.apply(feats)
            self.finish_files()
            if links:
                self.shortcuts_and_uninstall()
            self.result["expected_fingerprint"] = self.cfg["fingerprint"]
            self.result["fingerprint_ok"] = self.result["fingerprint"] == self.cfg["fingerprint"]
            self.step(T("step_done"), 1)
            return self.result
        except BaseException:
            self.cleanup()
            raise

    def cleanup(self):
        """Failure path: put the registry back and remove the half-made copy (only if we made it)."""
        try:
            rp = getattr(self, "rp", None)
            if self.update_info is not None:
                self.restore_snapshot()
            elif rp is not None and (self.dst / ".raf-remaster" / "registry.json").exists():
                rp.restore_registry(self.dst)
        except BaseException as e:  # noqa: BLE001
            self.log(T("log_reg_fail", msg=_msg(e)))
        if self.created_dst:
            shutil.rmtree(self.dst, ignore_errors=True)
            self.log(T("log_removed", d=self.dst))


    def restore_snapshot(self):
        """Update mode: the registry values as they were before this update's apply."""
        if self.reg_snapshot is None:
            return
        for name, value in self.reg_snapshot.items():
            self.rp._reg_restore(name, value)
        self.log("registry: values from before the update restored")
        self.reg_snapshot = None


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
    ps = f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; [Environment]::GetFolderPath('{name}')"
    out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, creationflags=CREATE_NO_WINDOW).stdout.decode("utf-8", "replace").strip()
    if not out:
        raise RuntimeError(f"folder {name} not found")
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
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("shortcuts: " + (r.stderr or r.stdout).decode("utf-8", "replace").strip()[:400])


def uninstall_bat(dst: Path, reg_game: str, saved: dict, install_dir_before, shortcuts, menu_dir,
                  uninstall_key: str) -> str:
    """Uninstall.bat (UTF-8, chcp 65001, texts in the install language): restores the registry values
    the patcher changed (saved = registry.json) and the game's Install Directory, removes shortcuts,
    the uninstall entry and the folder."""
    for s in [str(dst), reg_game] + list(shortcuts) + [str(menu_dir or "")]:
        if "%" in s or '"' in s:
            raise SystemExit(T("err_path_chars", p=s))
    hk = "HKCU\\" + reg_game
    keys = T("un_keys")
    out = ["@echo off", "chcp 65001 >nul", "setlocal",
           f"rem {APP}: uninstall (written by the installer)",
           'if /i "%~1"=="/quiet" goto run',
           f"echo {T('un_title', app=APP)}",
           f"echo {T('un_info')}",
           f'echo {T("un_folder")} "{dst}"',
           f'choice /c {keys} /m "{T("un_ask")}"',
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
            raise SystemExit(T("err_path_chars", p=v))
        # reg.exe eats a trailing backslash before the closing quote: double it
        out.append(f'reg add "{hk}" /v "Install Directory" /t REG_SZ /d "{v + chr(92) if v.endswith(chr(92)) else v}" /f >nul')
    for s in shortcuts:
        out.append(f'del /f /q "{s}" >nul 2>&1')
    if menu_dir:
        out.append(f'rd /s /q "{menu_dir}" >nul 2>&1')
    out += [f'reg delete "HKCU\\{uninstall_key}" /f >nul 2>&1',
            'cd /d "%TEMP%"',
            f"echo {T('un_done', app=APP)}",
            'if /i not "%~1"=="/quiet" timeout /t 3 >nul',
            f'(goto) 2>nul & rd /s /q "{dst}"',
            ":running",
            f"echo {T('un_running')}",
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


# ---------------------------------------------------------------- self test / silent install (no GUI)


def _file_logger(logf: Path):
    logf.parent.mkdir(parents=True, exist_ok=True)

    def out(s):
        with open(logf, "a", encoding="utf-8") as f:
            f.write(s + "\n")

    class W(io.TextIOBase):
        def write(self, s):
            with open(logf, "a", encoding="utf-8") as f:
                f.write(s)
            return len(s)

    sys.stdout = sys.stderr = W()
    return out


def _throttled_step(out):
    last = [0.0]

    def step(text, frac=None):
        if time.time() - last[0] > 5 or frac in (0, 1):
            last[0] = time.time()
            out(f"[step] {text}" + (f" {frac:.0%}" if frac is not None else ""))

    return step


def selftest(argv, silent=False) -> int:
    """--selftest: test registry key + shortcuts under --test-root. --silent: the real thing for
    third-party launchers (real registry, shortcuts unless --no-shortcuts). Exit codes: 0 ok,
    1 failed, 2 bad arguments, 3 installed but the fingerprint differs."""
    opts = {}
    it = iter(argv)
    try:
        for a in it:
            if a in ("--source", "--target", "--test-root", "--log", "--lang"):
                opts[a] = next(it)
            elif a in ("--no-hd", "--force-native", "--no-shortcuts"):
                opts[a] = True
    except StopIteration:
        return 2
    if not opts.get("--source") or not opts.get("--target") or (not silent and not opts.get("--test-root")):
        return 2
    set_lang(opts.get("--lang") or detect_lang())
    out = _file_logger(Path(opts.get("--log") or log_path()))
    bundle = bundle_dir()
    cfg = load_config(bundle)
    out(f"{'silent' if silent else 'selftest'}: bundle {bundle}, frozen={getattr(sys, 'frozen', False)}, "
        f"python {sys.version.split()[0]}, lang {get_lang()}, version {cfg.get('remaster_version')}")
    out(f"candidates: {[str(c) for c in candidates()]}")
    gpu = probe_gpu()
    out("vulkan: " + json.dumps(gpu, ensure_ascii=False))
    v = gpu["verdict"]
    dxvk = v["dxvk"] and "--force-native" not in opts
    out(T("gpu_dxvk", name=v["name"], api=v["api"]) if dxvk else
        T("gpu_native", name=v["name"] or T("gpu_unknown"), reason=v["reason"] or "--force-native"))
    links = "--no-shortcuts" not in opts
    ins = Installer(cfg, bundle, opts["--source"], opts["--target"], hd="--no-hd" not in opts and v["hd"],
                    dxvk=dxvk, desktop=links, startmenu=links, test_root=None if silent else opts["--test-root"],
                    log=out, step=_throttled_step(out), force_native="--force-native" in opts)
    try:
        res = ins.run()
    except BaseException as e:  # noqa: BLE001
        out("FAILED: " + _msg(e))
        out(traceback.format_exc())
        return 1
    out("RESULT " + json.dumps(res, ensure_ascii=False))
    return 0 if res.get("fingerprint_ok") else 3


# ---------------------------------------------------------------- update mode (--update DIR)


def start_installed(dst: Path, tail: str = "") -> None:
    """Start the game of an install: through the launcher (no new update check) when it is there."""
    dst = Path(dst)
    if (dst / LAUNCHER_EXE).is_file():
        cmd = f'"{dst / LAUNCHER_EXE}" --skip-check'
    else:
        cmd = f'"{dst / EXE}" -datapath "Data\\" -redistpath "Redist\\"'
    subprocess.Popen(cmd + (f" {tail}" if tail else ""), cwd=str(dst), close_fds=True)


def _install_dir_from_bat(bat: Path):
    """Install Directory value from before the first install, read back from an old Uninstall.bat."""
    import re

    try:
        text = bat.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'/v "Install Directory" /t REG_SZ /d "(.*)" /f', text)
    if not m:
        return None
    v = m.group(1)
    return v[:-1] if v.endswith("\\\\") else v


def read_update_info(game: Path):
    """install.json (+ "_dir", "_state") of a remaster install, or None. Installs from before
    install.json existed get it reconstructed from state.json and Uninstall.bat."""
    state = ru._read_json(game / ".raf-remaster" / "state.json")
    if not state.get("fingerprint"):
        return None
    info = ru.install_info(game)
    if not info:
        feats = state.get("features", [])
        info = {"version": state.get("version"), "stock": state.get("stock"),
                "hd": any(f in feats for f in HD_FEATURES), "force_native": state.get("dxvk") is False,
                "desktop": True, "startmenu": True, "lang": None,
                "install_dir_before": _install_dir_from_bat(game / UNINSTALL_BAT), "test_root": None}
    info["_dir"], info["_state"] = str(game), state
    return info


class HeadlessUI:
    """--update --headless: no window, no questions (a question = refuse), log into a file."""

    def __init__(self, out):
        self.out = out
        self.step = _throttled_step(out)

    def log(self, s):
        self.out(str(s))

    def ask_retry(self, msg):
        self.out("REFUSED: " + msg)
        return False

    def ask_dir(self, msg):
        self.out("REFUSED: " + msg)
        return None

    def error(self, msg):
        self.out("FAILED: " + msg)

    def done(self, msg):
        self.out("DONE: " + msg)


def run_update(game, ui, bundle, cfg, relaunch="", launch=True, probe=None, running=None, rename=os.rename) -> int:
    """Update the install `game` with this setup's version (see the module doc). Returns 0 updated,
    1 failed (previous version in place), 2 refused."""
    probe = probe or probe_gpu
    running = running or ru.game_running
    game = Path(game).resolve()
    new, old_bak, failed = ru.sibling(game, ".raf-update"), ru.sibling(game, ".raf-old"), ru.sibling(game, ".raf-failed")
    if not game.exists() and old_bak.exists() and (old_bak / ".raf-remaster").exists():
        rename(old_bak, game)  # an earlier update died between the two renames
        ui.log(f"recovered {game} from {old_bak}")
    info = read_update_info(game)
    if info is None:
        ui.error(T("upd_no_info", d=game))
        return 2
    while running(game):
        if not ui.ask_retry(T("upd_running", d=game)):
            return 2
    stock = Path(info.get("stock") or "")
    while True:
        ok, msg = quick_check(stock, cfg) if str(info.get("stock") or "") else (False, "?")
        if ok:
            break
        d = ui.ask_dir(T("upd_stock_missing", p=stock, msg=msg))
        if not d:
            return 2
        stock = Path(d)
        info["stock"] = str(stock)
    for leftover in (new, old_bak, failed):  # earlier attempts (our marker folder only)
        if leftover.exists():
            if (leftover / ".raf-remaster").exists() or not any(leftover.iterdir()):
                shutil.rmtree(leftover, ignore_errors=True)
            if leftover.exists():
                ui.error(T("err_not_empty", d=leftover))
                return 1
    gpu = probe()
    v = gpu["verdict"]
    dxvk = v["dxvk"] and not info.get("force_native")
    ui.log(f"update {info.get('version')} -> {cfg.get('remaster_version')} in {game}, stock {stock}, "
           f"hd {info.get('hd')}, dxvk {dxvk}")
    test_root = info.get("test_root")
    ins = Installer(cfg, bundle, stock, new, hd=bool(info.get("hd")) and v["hd"], dxvk=dxvk,
                    desktop=info.get("desktop", True), startmenu=info.get("startmenu", True),
                    test_root=test_root, log=ui.log, step=ui.step, force_native=bool(info.get("force_native")),
                    update_info=info)
    try:
        res = ins.run(links=False)  # failure: new folder removed, registry values restored
    except BaseException as e:  # noqa: BLE001
        ui.log(traceback.format_exc())
        ui.error(T("upd_failed", msg=_msg(e), log=log_path()))
        return 1
    ui.step(T("step_swap"), None)
    while True:
        try:
            ru.swap(game, new, old_bak, rename)
            break
        except OSError as e:
            if ui.ask_retry(T("upd_in_use", msg=e)):
                continue
            ins.restore_snapshot()
            shutil.rmtree(new, ignore_errors=True)
            ui.error(T("upd_failed", msg=_msg(e), log=log_path()))
            return 1
    try:
        ui.step(T("step_carry"), None)
        new_state = json.loads((game / ".raf-remaster" / "state.json").read_text())
        ru.carry_over(old_bak, game, ru.carry_plan(old_bak, game, info["_state"], new_state), log=ui.log)
        ins.dst = game
        ins.shortcuts_and_uninstall()
    except BaseException as e:  # noqa: BLE001 - roll back: the old folder is still complete
        ui.log(traceback.format_exc())
        try:
            ru.unswap(game, failed, old_bak, rename)
            ins.restore_snapshot()
            shutil.rmtree(failed, ignore_errors=True)
            ui.log("rolled back to the previous version")
        except BaseException as e2:  # noqa: BLE001
            ui.log(f"ROLLBACK FAILED: {_msg(e2)}; the previous version is in {old_bak}")
        ui.error(T("upd_failed", msg=_msg(e), log=log_path()))
        return 1
    shutil.rmtree(old_bak, ignore_errors=True)
    if old_bak.exists():
        ui.log(f"note: {old_bak} could not be deleted completely; it is removed with the next update")
    old_fp = info["_state"].get("fingerprint")
    msg = T("upd_done", ver=cfg.get("remaster_version"), fp=res["fingerprint"])
    if old_fp and old_fp != res["fingerprint"]:
        msg += "\n" + T("upd_fp_changed", old=old_fp, new=res["fingerprint"])
    ui.log("RESULT " + json.dumps(dict(res, old_fingerprint=old_fp), ensure_ascii=False))
    ui.done(msg)
    if launch == "dry-run-only" and not ru.load_override(game).get("dry_run_game"):
        ui.log("not starting the game: headless run without a dry-run override in the new install")
    elif launch:
        start_installed(game, relaunch)
    return 0


def update_main(argv) -> int:
    opts = {}
    it = iter(argv)
    try:
        for a in it:
            if a in ("--update", "--wait-pid", "--lang", "--relaunch-b64", "--log"):
                opts[a] = next(it)
            elif a in ("--headless", "--no-launch"):
                opts[a] = True
    except StopIteration:
        return 2
    game = Path(opts["--update"])
    if opts.get("--wait-pid"):
        ru.wait_pid(int(opts["--wait-pid"]), 30)  # the launcher must be gone before its exe is replaced
    info = ru.install_info(game)
    set_lang(opts.get("--lang") or info.get("lang") or detect_lang())
    relaunch = ""
    if opts.get("--relaunch-b64") not in (None, "-"):
        relaunch = base64.urlsafe_b64decode(opts["--relaunch-b64"].encode("ascii")).decode("utf-8")
    bundle = bundle_dir()
    cfg = load_config(bundle)
    if opts.get("--headless"):
        out = _file_logger(Path(opts.get("--log") or log_path()))
        out(f"update: bundle {bundle}, frozen={getattr(sys, 'frozen', False)}, version {cfg.get('remaster_version')}")
        # headless = tests / scripts: the game is only "started" through a dry-run launcher override
        launch = "--no-launch" not in opts and "dry-run-only"
        return run_update(game, HeadlessUI(out), bundle, cfg, relaunch, launch=launch)
    return update_gui(game, bundle, cfg, relaunch, launch="--no-launch" not in opts)


def update_gui(game, bundle, cfg, relaunch, launch=True) -> int:
    """Progress window for the update; questions are asked on the Tk thread."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    q = queue.Queue()
    sys.stdout = sys.stderr = QueueWriter(q, log_path())
    try:
        log_path().write_text("", encoding="utf-8")
    except OSError:
        pass
    root = tk.Tk()
    root.title(T("upd_setup_title", app=APP, ver=cfg.get("remaster_version")))
    root.minsize(640, 360)
    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=T("upd_setup_title", app=APP, ver=cfg.get("remaster_version")),
              font=("Segoe UI", 13, "bold")).pack(anchor="w")
    step_var = tk.StringVar(value=T("step_check"))
    ttk.Label(frm, textvariable=step_var).pack(anchor="w", pady=(8, 0))
    bar = ttk.Progressbar(frm, mode="determinate", maximum=1000)
    bar.pack(fill="x", pady=4)
    box = tk.Text(frm, height=12, wrap="word", state="disabled", font=("Consolas", 9))
    box.pack(fill="both", expand=True)
    result = {"code": 1, "finished": False}

    class GuiUI:
        def log(self, s):
            q.put(("log", str(s)))

        def step(self, text, frac=None):
            q.put(("step", (text, frac)))

        def _ask(self, kind, msg):
            ev, ans = threading.Event(), {}
            q.put((kind, (msg, ev, ans)))
            ev.wait()
            return ans.get("v")

        def ask_retry(self, msg):
            return bool(self._ask("retry", msg))

        def ask_dir(self, msg):
            return self._ask("dir", msg)

        def error(self, msg):
            self._ask("error", msg)

        def done(self, msg):
            q.put(("done", msg))

    def work():
        try:
            result["code"] = run_update(game, GuiUI(), bundle, cfg, relaunch, launch=launch)
        except BaseException as e:  # noqa: BLE001
            print(traceback.format_exc())
            GuiUI().error(T("upd_failed", msg=_msg(e), log=log_path()))
        q.put(("finished", None))

    def add_log(line):
        box.configure(state="normal")
        box.insert("end", line + "\n")
        box.see("end")
        box.configure(state="disabled")

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
                elif kind in ("retry", "dir", "error"):
                    msg, ev, ans = val
                    if kind == "retry":
                        ans["v"] = messagebox.askretrycancel(APP, msg, parent=root)
                    elif kind == "dir":
                        messagebox.showinfo(APP, msg, parent=root)
                        d = filedialog.askdirectory(title=T("browse_src"), parent=root)
                        ans["v"] = d or None
                    else:
                        messagebox.showerror(APP, msg, parent=root)
                    ev.set()
                elif kind == "done":
                    bar.stop()
                    bar.configure(mode="determinate", value=1000)
                    step_var.set(val)
                    add_log(val)
                elif kind == "finished":
                    root.after(2500 if result["code"] == 0 else 0, root.destroy)
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    root.protocol("WM_DELETE_WINDOW", lambda: None)  # closing mid-update would leave a half-built folder
    threading.Thread(target=work, daemon=True).start()
    poll()
    root.mainloop()
    return result["code"]


# ---------------------------------------------------------------- GUI


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    forced = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv[:-1] else None
    set_lang(forced or detect_lang())
    bundle = bundle_dir()
    cfg = load_config(bundle)
    q = queue.Queue()
    sys.stdout = sys.stderr = QueueWriter(q, log_path())
    try:
        log_path().write_text("", encoding="utf-8")
    except OSError:
        pass

    root = tk.Tk()
    root.minsize(760, 600)
    src_var, dst_var = tk.StringVar(), tk.StringVar()
    hd_var, desk_var, menu_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    lang_var = tk.StringVar(value=LANGS[get_lang()])
    st = {"src_ok": False, "src_size": None, "src_msg": None, "busy": False, "started": False, "gpu": None}
    w = {}  # widgets of the current form

    def build_form():
        for child in root.winfo_children():
            child.destroy()
        root.title(T("title", app=APP, ver=cfg["remaster_version"]))
        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        top = ttk.Frame(frm)
        top.grid(row=0, column=0, columnspan=3, sticky="we")
        ttk.Label(top, text=f"{APP} {cfg['remaster_version']}", font=("Segoe UI", 15, "bold")).pack(side="left")
        lang_box = ttk.Combobox(top, textvariable=lang_var, values=list(LANGS.values()), state="readonly", width=10)
        lang_box.pack(side="right")
        ttk.Label(top, text=T("lang")).pack(side="right", padx=4)
        lang_box.bind("<<ComboboxSelected>>", lambda e: switch_lang())
        w["lang_box"] = lang_box
        ttk.Label(frm, wraplength=720, justify="left", text=T("intro", gv=cfg["game_version"])).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))

        ttk.Label(frm, text=T("lbl_src")).grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=src_var).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Button(frm, text=T("browse"), command=lambda: browse(True)).grid(row=2, column=2)
        w["src_status"] = ttk.Label(frm, wraplength=600, justify="left")
        w["src_status"].grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 8))

        ttk.Label(frm, text=T("lbl_dst")).grid(row=4, column=0, sticky="w")
        ttk.Entry(frm, textvariable=dst_var).grid(row=4, column=1, sticky="we", padx=6)
        ttk.Button(frm, text=T("browse"), command=lambda: browse(False)).grid(row=4, column=2)
        w["space"] = ttk.Label(frm)
        w["space"].grid(row=5, column=1, columnspan=2, sticky="w", pady=(2, 8))

        opts = ttk.Frame(frm)
        opts.grid(row=6, column=0, columnspan=3, sticky="w")
        w["hd"] = ttk.Checkbutton(opts, variable=hd_var, command=update_space, text=T("opt_hd"))
        w["hd"].pack(anchor="w")
        ttk.Checkbutton(opts, variable=desk_var, text=T("opt_desktop")).pack(anchor="w")
        ttk.Checkbutton(opts, variable=menu_var, text=T("opt_menu")).pack(anchor="w")
        w["gpu"] = ttk.Label(frm, wraplength=720, justify="left")
        w["gpu"].grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, columnspan=3, sticky="we", pady=10)
        w["install"] = ttk.Button(btns, text=T("btn_install"), command=start)
        w["install"].pack(side="left")
        w["close"] = ttk.Button(btns, text=T("btn_close"), command=root.destroy)
        w["close"].pack(side="right")

        w["step"] = tk.StringVar(value=T("ready"))
        ttk.Label(frm, textvariable=w["step"]).grid(row=9, column=0, columnspan=3, sticky="w")
        w["bar"] = ttk.Progressbar(frm, mode="determinate", maximum=1000)
        w["bar"].grid(row=10, column=0, columnspan=3, sticky="we", pady=4)
        w["log"] = tk.Text(frm, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        w["log"].grid(row=11, column=0, columnspan=3, sticky="nsew")
        frm.rowconfigure(11, weight=1)
        w["fp"] = ttk.Frame(frm)
        w["fp"].grid(row=12, column=0, columnspan=3, sticky="we", pady=(8, 0))
        show_src_status()
        show_gpu()
        update_space()

    def switch_lang():
        if st["started"]:
            return
        code = next(k for k, v in LANGS.items() if v == lang_var.get())
        set_lang(code)
        build_form()
        if st["src_msg"] is not None:
            check_src()  # the check message comes back in the new language

    def add_log(line):
        box = w["log"]
        box.configure(state="normal")
        box.insert("end", line + "\n")
        box.see("end")
        box.configure(state="disabled")

    def browse(is_src):
        var = src_var if is_src else dst_var
        d = filedialog.askdirectory(title=T("browse_src") if is_src else T("browse_dst"),
                                    initialdir=var.get() or None)
        if d:
            var.set(str(Path(d)))

    def show_src_status():
        if st["src_msg"] is None:
            text = T("checking") if src_var.get().strip() else T("src_none")
        else:
            text = T("ok", msg=st["src_msg"]) if st["src_ok"] else T("error", msg=st["src_msg"])
        w["src_status"].configure(text=text)

    def show_gpu():
        g = st["gpu"]
        if g is None:
            w["gpu"].configure(text=T("gpu_probe"))
            return
        v = g["verdict"]
        text = (T("gpu_dxvk", name=v["name"], api=v["api"]) if v["dxvk"] else
                T("gpu_native", name=v["name"] or T("gpu_unknown"), reason=v["reason"]))
        if not v["hd"]:
            hd_var.set(False)
            w["hd"].configure(state="disabled")
            text += "\n" + T("hd_off")
        w["gpu"].configure(text=text)

    def check_src(*_):
        p = Path(src_var.get().strip()) if src_var.get().strip() else None
        st["src_ok"], st["src_size"], st["src_msg"] = False, None, None
        if "src_status" in w:
            show_src_status()
        if not p:
            return

        def work():
            ok, msg = quick_check(p, cfg)
            size = folder_size(p) if ok else None
            q.put(("src", (str(p), ok, msg, size)))

        threading.Thread(target=work, daemon=True).start()

    def update_space(*_):
        if "space" not in w:
            return
        dst = dst_var.get().strip()
        if not dst or not st["src_size"]:
            w["space"].configure(text="")
            return
        need = needed_bytes(st["src_size"], cfg, hd_var.get())
        try:
            free = free_bytes(Path(dst))
        except OSError:
            w["space"].configure(text=T("drive_missing"))
            return
        mark = T("space_ok") if free >= need else T("space_low")
        w["space"].configure(text=T("space", need=need / 1e9, free=free / 1e9, mark=mark))

    def start():
        if st["busy"]:
            return
        if not st["src_ok"]:
            messagebox.showerror(APP, T("err_choose_src"))
            return
        if not dst_var.get().strip():
            messagebox.showerror(APP, T("err_choose_dst"))
            return
        if st["gpu"] is None:
            return  # probe still running (a few seconds)
        src, dst = Path(src_var.get().strip()), Path(dst_var.get().strip())
        st["busy"] = st["started"] = True
        for k in ("install", "close", "lang_box"):
            w[k].configure(state="disabled")
        v = st["gpu"]["verdict"]
        print("vulkan: " + json.dumps(st["gpu"], ensure_ascii=False))

        def step(text, frac=None):
            q.put(("step", (text, frac)))

        def work():
            ins = Installer(cfg, bundle, src, dst, hd=hd_var.get() and v["hd"], dxvk=v["dxvk"],
                            desktop=desk_var.get(), startmenu=menu_var.get(), log=print, step=step)
            try:
                q.put(("done", ins.run()))
            except BaseException as e:  # noqa: BLE001
                print(traceback.format_exc())
                q.put(("error", _msg(e)))

        threading.Thread(target=work, daemon=True).start()

    def finished(res):
        st["busy"] = False
        w["close"].configure(state="normal")
        bar = w["bar"]
        bar.stop()
        bar.configure(mode="determinate", value=1000)
        fp = w["fp"]
        ttk.Label(fp, text=T("fp_label")).pack(anchor="w")
        e = ttk.Entry(fp, font=("Consolas", 18, "bold"), width=14, justify="center")
        e.insert(0, res["fingerprint"])
        e.configure(state="readonly")
        e.pack(anchor="w", pady=2)
        txt = T("fp_text")
        if not res.get("fingerprint_ok"):
            txt += "\n" + T("fp_mismatch", exp=res["expected_fingerprint"])
        if res.get("hd_failed"):
            txt += "\n" + T("fp_hd_failed")
        if not res.get("dxvk", True):
            txt += "\n" + T("fp_native")
        ttk.Label(fp, text=txt, wraplength=720, justify="left").pack(anchor="w")
        row = ttk.Frame(fp)
        row.pack(anchor="w", pady=6)
        dst = Path(dst_var.get().strip())
        ttk.Button(row, text=T("btn_open"), command=lambda: os.startfile(dst)).pack(side="left")
        ttk.Button(row, text=T("btn_play"), command=lambda: start_installed(dst)).pack(side="left", padx=6)
        w["step"].set(T("done_status"))

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    add_log(val)
                elif kind == "step":
                    text, frac = val
                    w["step"].set(text)
                    bar = w["bar"]
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
                    st["src_ok"], st["src_msg"], st["src_size"] = ok, msg, size
                    show_src_status()
                    if ok and not dst_var.get().strip():
                        dst_var.set(str(default_target(Path(path))))
                    update_space()
                elif kind == "gpu":
                    st["gpu"] = val
                    show_gpu()
                elif kind == "done":
                    finished(val)
                elif kind == "error":
                    st["busy"] = False
                    w["close"].configure(state="normal")
                    w["bar"].stop()
                    w["bar"].configure(mode="determinate", value=0)
                    w["step"].set(T("aborted"))
                    messagebox.showerror(APP, T("err_failed", msg=val, log=log_path()))
        except queue.Empty:
            pass
        root.after(100, poll)

    build_form()
    src_var.trace_add("write", lambda *_: root.after_idle(check_src) if not st["busy"] else None)
    dst_var.trace_add("write", update_space)
    threading.Thread(target=lambda: q.put(("gpu", probe_gpu())), daemon=True).start()
    found = candidates()
    if found:
        src_var.set(str(found[0]))
    else:
        show_src_status()
    root.protocol("WM_DELETE_WINDOW", lambda: None if st["busy"] else root.destroy())
    poll()
    root.mainloop()


def main() -> int:
    if "--vulkan-probe" in sys.argv:
        out = sys.argv[sys.argv.index("--vulkan-probe") + 1]
        Path(out).write_text(json.dumps(vulkan_probe()), encoding="utf-8")
        return 0
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # raf_patch.desktop_mode sets it later anyway
        except Exception:  # noqa: BLE001
            pass
    no_console_windows()
    if "--selftest" in sys.argv:
        return selftest(sys.argv[1:])
    if "--silent" in sys.argv:
        return selftest(sys.argv[1:], silent=True)
    if "--update" in sys.argv:
        return update_main(sys.argv[1:])
    gui()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - last resort: keep the traceback for the player to send
        try:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except OSError:
            pass
        raise
