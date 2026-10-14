"""Apply or revert the Rise and Fall remaster patches on an existing install.

Usage:
    python raf_patch.py apply  <game_dir> [--fullscreen]
    python raf_patch.py revert <game_dir>
    python raf_patch.py status <game_dir>

apply defaults to borderless fullscreen at the desktop resolution; --fullscreen keeps
the original exclusive fullscreen (also at the desktop resolution).

Everything is idempotent. Originals are kept in <game_dir>/.raf-remaster/orig
so `revert` restores the install byte for byte. Registry values the patcher sets
are saved in <game_dir>/.raf-remaster/registry.json and restored by `revert`.
"""

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import shutil
import struct
import sys
import tarfile
import urllib.request
from pathlib import Path

EXE = "RiseAndFall.exe"
STATE_DIR = ".raf-remaster"
CACHE = Path(__file__).resolve().parent.parent / "work" / "cache"

DXVK_VERSION = "3.1.1"
DXVK_URL = f"https://github.com/doitsujin/dxvk/releases/download/v{DXVK_VERSION}/dxvk-{DXVK_VERSION}.tar.gz"
DXVK_TAR_SHA256 = "40565b4a724aadc4433fa4e010b4b23916d9b1f1baeee64e17186db94f54e608"
DXVK_D3D9_SHA256 = "265888c31ca78dffa290c39cb7e50bfb02762590e41927906e46fb32f01497fa"

DXVK_CONF = """\
# Rise and Fall remaster: DXVK settings
d3d9.maxFrameLatency = 1
d3d9.samplerAnisotropy = 16
"""

LAUNCH_BAT = """\
@echo off
cd /d "%~dp0"
start "" RiseAndFall.exe -datapath "Data\\" -redistpath "Redist\\" %*
"""

# Files the patcher creates from scratch; revert deletes them.
CREATED = ["d3d9.dll", "dxvk.conf", "RiseAndFall Remaster.bat"]
# Files the patcher modifies; revert restores them from orig/.
MODIFIED = [EXE, "DX9Rasterizer.dll"]
# Intro movies; the launcher's own install ships without the last four, so the game runs without them.
# apply moves them into orig/, revert moves them back.
REMOVED = [
    "Data/movies/Midway Bink.bik",
    "Data/movies/license.bik",
    "Data/movies/ndgames_logo.bik",
    "Data/movies/nvidia.bik",
    "Data/movies/Opening Video.bik",
]

LAA_FLAG = 0x20

REG_KEY = r"Software\Midway Home Entertainment\Rise and Fall"

# Byte patches: (file, virtual address, original bytes, patched bytes, what it does).
# Addresses are for the v1.15 (08.18.2006) files; every patch checks the original bytes first.
BORDERLESS = [
    # DX9Screen::Capture, fullscreen branch: D3DPRESENT_PARAMETERS.Windowed = ebp (0) -> eax (the
    # HWND returned just before, never 0). The swapchain becomes windowed on the game's WS_POPUP
    # window, which already covers the monitor: borderless fullscreen.
    ("DX9Rasterizer.dll", 0x100326BF, "89ae98000000", "898698000000", "Windowed = TRUE"),
    # same branch: FullScreen_RefreshRateInHz = mode refresh -> ebp (0); windowed swapchains need 0.
    ("DX9Rasterizer.dll", 0x10032701, "898ea8000000", "89aea8000000", "refresh rate = 0"),
    # DX9Screen::CreateAWindow: fullscreen window ex-style WS_EX_TOPMOST -> 0 so alt-tab works.
    ("DX9Rasterizer.dll", 0x100318D3, "6a08", "6a00", "no WS_EX_TOPMOST"),
]

# Camera scrolling (keys and screen edge) advances in steps of a 25 ms TMPoll, so the camera
# moves at 40 Hz however fast the game renders. Use a 5 ms step with a 5x smaller distance per
# step (same speed), and keep the old 500 ms catch-up cap (20 x 25 ms = 100 x 5 ms).
SMOOTH_SCROLL = [
    (EXE, 0x0040C801, "19", "05", "scroll TMPoll period 25 ms -> 5 ms"),
    (EXE, 0x0040C788, "14", "64", "catch-up cap compare 20 -> 100 periods"),
    (EXE, 0x0040C78F, "14000000", "64000000", "catch-up cap value 20 -> 100 periods"),
    (EXE, 0x00C4D8B4, "0000803e", "cdcc4c3d", "distance per period 0.25 -> 0.05 (only the 2 scroll fns use it)"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_characteristics_offset(data: bytes) -> int:
    if data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError("PE signature missing")
    return pe + 22


def is_laa(exe: Path) -> bool:
    data = exe.read_bytes()
    return bool(struct.unpack_from("<H", data, pe_characteristics_offset(data))[0] & LAA_FLAG)


def set_laa(exe: Path) -> None:
    data = bytearray(exe.read_bytes())
    off = pe_characteristics_offset(data)
    flags = struct.unpack_from("<H", data, off)[0]
    struct.pack_into("<H", data, off, flags | LAA_FLAG)
    exe.write_bytes(data)


def dxvk_d3d9() -> Path:
    """Return the cached 32-bit DXVK d3d9.dll, downloading and verifying it if needed."""
    dll = CACHE / f"dxvk-{DXVK_VERSION}" / "x32" / "d3d9.dll"
    if dll.exists() and sha256(dll) == DXVK_D3D9_SHA256:
        return dll
    CACHE.mkdir(parents=True, exist_ok=True)
    tar = CACHE / f"dxvk-{DXVK_VERSION}.tar.gz"
    if not tar.exists() or sha256(tar) != DXVK_TAR_SHA256:
        print(f"downloading {DXVK_URL}")
        urllib.request.urlretrieve(DXVK_URL, tar)
        if sha256(tar) != DXVK_TAR_SHA256:
            tar.unlink()
            raise RuntimeError("DXVK archive hash mismatch")
    with tarfile.open(tar) as t:
        member = t.getmember(f"dxvk-{DXVK_VERSION}/x32/d3d9.dll")
        t.extract(member, CACHE, filter="data")
    if sha256(dll) != DXVK_D3D9_SHA256:
        raise RuntimeError("DXVK d3d9.dll hash mismatch")
    return dll


def pe_va_to_offset(data: bytes, va: int) -> int:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = struct.unpack_from("<H", data, pe + 20)[0]
    base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
    sec = pe + 24 + opt
    for i in range(nsec):
        _vsize, vaddr, rsize, raw = struct.unpack_from("<IIII", data, sec + 40 * i + 8)
        if base + vaddr <= va < base + vaddr + rsize:
            return va - base - vaddr + raw
    raise ValueError(f"VA {va:#x} not in file")


def byte_patches(game: Path, patches, enable: bool, label: str) -> None:
    """Apply (enable) or undo (not enable) byte patches; refuses to touch unexpected bytes."""
    by_file = {}
    for name, va, old, new, note in patches:
        by_file.setdefault(name, []).append((va, bytes.fromhex(old), bytes.fromhex(new), note))
    for name, items in by_file.items():
        path = game / name
        data = bytearray(path.read_bytes())
        changed = False
        for va, old, new, note in items:
            off = pe_va_to_offset(data, va)
            want, other = (new, old) if enable else (old, new)
            cur = bytes(data[off : off + len(old)])
            if cur == want:
                continue
            if cur != other:
                sys.exit(f"{name} {va:#x}: unexpected bytes {cur.hex()} ({note}); is this v1.15?")
            data[off : off + len(old)] = want
            changed = True
        if changed:
            path.write_bytes(data)
    print(f"{label}: {'on' if enable else 'off'}")


def desktop_mode() -> tuple[int, int, int]:
    """Current width, height and refresh rate of the primary display."""

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("name", wt.WCHAR * 32), ("ver", wt.WORD * 4), ("fields", wt.DWORD),
                    ("pos", wt.LONG * 2), ("orient", wt.DWORD * 2), ("misc", ctypes.c_short * 5),
                    ("form", wt.WCHAR * 32), ("logpix", wt.WORD), ("bpp", wt.DWORD),
                    ("w", wt.DWORD), ("h", wt.DWORD), ("flags", wt.DWORD), ("hz", wt.DWORD)]

    ctypes.windll.user32.SetProcessDPIAware()
    dm = DEVMODEW()
    dm.ver[2] = ctypes.sizeof(DEVMODEW)
    if not ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
        raise RuntimeError("EnumDisplaySettings failed")
    return dm.w, dm.h, dm.hz


def set_registry(game: Path, values: dict) -> None:
    """Set DWORD values under REG_KEY, saving the values found before the first apply."""
    import winreg

    saved_path = game / STATE_DIR / "registry.json"
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
        for name, value in values.items():
            if name not in saved:
                try:
                    saved[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    saved[name] = None
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    saved_path.write_text(json.dumps(saved, indent=2))
    print("registry: " + ", ".join(f"{k}={v}" for k, v in values.items()))


def restore_registry(game: Path) -> None:
    import winreg

    saved_path = game / STATE_DIR / "registry.json"
    if not saved_path.exists():
        return
    saved = json.loads(saved_path.read_text())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
        for name, value in saved.items():
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    print("registry: restored " + ", ".join(saved))


def check_game_dir(game: Path) -> None:
    if not (game / EXE).is_file():
        sys.exit(f"{EXE} not found in {game}")


def apply(game: Path, borderless: bool = True) -> None:
    orig = game / STATE_DIR / "orig"
    orig.mkdir(parents=True, exist_ok=True)
    for name in MODIFIED:
        if not (orig / name).exists():
            shutil.copy2(game / name, orig / name)

    exe = game / EXE
    if is_laa(exe):
        print("LAA: already set")
    else:
        set_laa(exe)
        print("LAA: set")

    w, h, hz = desktop_mode()
    shutil.copy2(dxvk_d3d9(), game / "d3d9.dll")
    conf = DXVK_CONF
    if not borderless:
        # The game keeps the first refresh rate the adapter lists per resolution (DXVK: the highest,
        # native d3d9: the lowest, which is how exclusive fullscreen ended up at 30 Hz). Only list
        # the desktop rate.
        conf += f"d3d9.forceRefreshRate = {hz}\n"
    (game / "dxvk.conf").write_text(conf, encoding="ascii")
    print(f"DXVK {DXVK_VERSION}: installed")

    (game / "RiseAndFall Remaster.bat").write_text(LAUNCH_BAT, encoding="ascii")
    print("launcher script: written")

    for name in REMOVED:
        if (game / name).exists():
            (orig / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(game / name, orig / name)
    print("intro movies: removed")

    byte_patches(game, BORDERLESS, borderless, "borderless window")
    byte_patches(game, SMOOTH_SCROLL, True, "smooth camera scroll")

    # Full Screen Mode stays 1: the game's own windowed mode hangs on a white window.
    # The game drops a resolution missing from the adapter's mode list back to 1024x768
    # (and autodetect can write 800x600), so we always write the current desktop mode.
    # Wait for VSync 1 = PresentationInterval ONE: frames paced to the display refresh instead of
    # 400+ fps with tearing. Rendering stays decoupled from the simulation (own physics thread).
    set_registry(game, {"Full Screen Mode": 1, "Game Window Width": w, "Game Window Height": h,
                        "Custom Refresh Rate": hz, "Wait for VSync": 1})

    state = {"dxvk": DXVK_VERSION, "laa": True, "borderless": borderless, "mode": [w, h, hz]}
    (game / STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


def revert(game: Path) -> None:
    restore_registry(game)
    orig = game / STATE_DIR / "orig"
    for name in MODIFIED:
        if (orig / name).exists():
            shutil.copy2(orig / name, game / name)
            print(f"restored {name}")
    for name in REMOVED:
        if (orig / name).exists():
            shutil.move(orig / name, game / name)
            print(f"restored {name}")
    for name in CREATED:
        if (game / name).exists():
            (game / name).unlink()
            print(f"removed {name}")
    shutil.rmtree(game / STATE_DIR, ignore_errors=True)


def status(game: Path) -> None:
    print(f"LAA:  {is_laa(game / EXE)}")
    d3d9 = game / "d3d9.dll"
    print(f"DXVK: {d3d9.exists() and sha256(d3d9) == DXVK_D3D9_SHA256}")
    state = game / STATE_DIR / "state.json"
    print(f"state: {state.read_text() if state.exists() else 'none'}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 2 or args[0] not in ("apply", "revert", "status") or flags - {"--fullscreen"}:
        sys.exit(__doc__)
    game = Path(args[1])
    check_game_dir(game)
    if args[0] == "apply":
        apply(game, borderless="--fullscreen" not in flags)
    else:
        {"revert": revert, "status": status}[args[0]](game)


if __name__ == "__main__":
    main()
