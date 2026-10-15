"""Apply or revert the Rise and Fall remaster patches on an existing install.

Usage:
    python raf_patch.py apply  <game_dir> [--only a,b] [--skip a,b] [--mutator name|none]
                               [--zoom 1.0-2.5] [--stock <dir>] [--rebuild]
    python raf_patch.py revert <game_dir>
    python raf_patch.py status <game_dir>
    python raf_patch.py features

Features (see FEATURES; `features` prints them with their default):
  borderless, smooth-scroll, zoom      exe/DLL byte patches
  mips, hd-terrain, hd-units           texture overlays (hd wins over mips on shared files)
  shaders                              fx overlay (shader.cache is moved aside so the game rebuilds it)
  ai-hard, ai-personalities, unit-ai, maps, survival
                                       gameplay data (all players need the same set: REMASTER.txt)
  lang-en                              English language pack (needs work/lang/en.json, not in the repo)
--mutator <name> installs work/overlay-mutators/<name> last (one at a time, gameplay data);
--mutator none removes it.
Always installed: LAA flag, DXVK, no intro movies, start/host/join scripts, REMASTER.txt.
Without borderless the game runs in exclusive fullscreen at the desktop resolution.
--only/--skip start from the default set; the chosen set is stored in state.json and an
apply without them reuses it.

Overlays are built from a STOCK install (--stock, default the original "Rise and Fall" folder
next to the game dir, else the game dir itself before any overlay is installed) into
<repo>/work/overlay*, never from a modified copy, and every file is checked against the
stock hash before it is replaced. Everything is idempotent. Originals are kept in
<game_dir>/.raf-remaster/orig so `revert` restores the install byte for byte. Registry
values the patcher sets are saved in <game_dir>/.raf-remaster/registry.json.
"""

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REMASTER_VERSION = "0.3.0"
EXE = "RiseAndFall.exe"
STATE_DIR = ".raf-remaster"
REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "work" / "cache"
DEFAULT_STOCK = Path(r"D:\Games\Rise and Fall")

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
type REMASTER.txt
start "" RiseAndFall.exe -datapath "Data\\" -redistpath "Redist\\" %*
"""

# Command line: the game splits it on '-', value between the first pair of quotes,
# so values must not contain '-'.
HOST_BAT = """@echo off
rem Host a LAN / direct-IP network game: Host.bat ["Game name"] ["Player name"]
rem (no '-' in names). The game needs player name, pid and pass next to hostgame.
cd /d "%~dp0"
type REMASTER.txt
echo.
echo Compare the fingerprint above with the other players before starting.
set "NAME=%~1"
if "%NAME%"=="" set "NAME=RAF Remaster"
set "PLAYER=%~2"
if "%PLAYER%"=="" set "PLAYER=%USERNAME%"
start "" RiseAndFall.exe -datapath "Data\\" -redistpath "Redist\\" -hostgame "%NAME%" -playername "%PLAYER%" -pid "1" -pass "raf"
"""

JOIN_BAT = """@echo off
rem Join a network game by IP: Join.bat [1.2.3.4] ["Player name"]   (no '-' in names)
cd /d "%~dp0"
type REMASTER.txt
echo.
echo Compare the fingerprint above with the host before joining.
set "IP=%~1"
if "%IP%"=="" set /p "IP=IP address of the host: "
if "%IP%"=="" exit /b 1
set "PLAYER=%~2"
if "%PLAYER%"=="" set "PLAYER=%USERNAME%"
start "" RiseAndFall.exe -datapath "Data\\" -redistpath "Redist\\" -joinbyip "%IP%" -playername "%PLAYER%" -pid "2" -pass "raf"
"""

# Files the patcher creates from scratch; revert deletes them.
CREATED = ["d3d9.dll", "dxvk.conf", "RiseAndFall Remaster.bat", "Host.bat", "Join.bat", "REMASTER.txt"]
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
# Always applied: -hostgame / -joinbyip crash at startup (FUN_006dc000 writes a "skip menu
# backgrounds" flag into the UIManager before it exists: write to 0x1a2, crash dump in
# work/crashes). The flag is cosmetic, so the write is dropped.
CMDLINE_FIX = [
    (EXE, 0x006DC226, "a1e4cb0101c680a201000001", "909090909090909090909090",
     "no UIManager write in the early command line pass"),
]

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

# Camera zoom is a fraction 0..1 at 0x101dcc0 (camera object 0x101dbbc + 0x104); the wheel
# (FUN_009286c0) and zoom hotkeys (FUN_00908c00) clamp it to 1.0 and a new game starts at 1.0.
# FUN_006d32c0: distance = (base / sin(pitch) - 0.1) * zoom + 0.1, pitch lerps -5 -> -48 deg
# over the zoom range. Letting zoom run past 1.0 tilts the camera to ~-70 deg and shows little
# more ground (tested: zoom 1.5 = height 11.0 vs 7.6 but nearly top-down), so instead the RTS
# preset base distance (FUN_006cf720) goes from -6.7 to -10.05: every zoom step and the maximum
# are 1.5x farther at the same angles. The ZoomStyle 0 distance clamp -13.2 (FUN_006d32c0) would
# cut that (max is now about -13.5), so it moves to -19.8.
DEFAULT_ZOOM = 2.5  # 1.5/2.0/2.5 checked on an 8-player map: clean edges, units render, ~340 fps


def zoom_patches(factor: float):
    """Camera base distance -6.7 x factor, ZoomStyle-0 distance clamp -13.2 x factor."""
    f = lambda v: struct.pack("<f", v).hex()
    return [
        (EXE, 0x006CF731, "bb6666d6c0", "bb" + f(-6.7 * factor), f"RTS camera base distance x{factor}"),
        (EXE, 0x00C5FB50, "333353c1", f(-13.2 * factor), "ZoomStyle 0 distance clamp (compare)"),
        (EXE, 0x006D34CA, "b8333353c1", "b8" + f(-13.2 * factor), "ZoomStyle 0 distance clamp (value)"),
    ]


def unzoom(game: Path) -> None:
    """Put the three zoom sites back to stock whatever factor they carry (factor 0.5..4 accepted)."""
    data = bytearray((game / EXE).read_bytes())
    for (_, va, old, _n, _), base in zip(zoom_patches(1.0), (-6.7, -13.2, -13.2)):
        off = pe_va_to_offset(data, va)
        raw = bytes.fromhex(old)
        cur = bytes(data[off:off + len(raw)])
        op = raw[:len(raw) - 4]
        val = struct.unpack("<f", cur[len(op):])[0]
        if cur[:len(op)] != op or not (base * 4.01 <= val <= base * 0.49):
            sys.exit(f"zoom site {va:#x}: unexpected bytes {cur.hex()}; is this v1.15?")
        data[off:off + len(raw)] = raw
    (game / EXE).write_bytes(data)


def menu_aspect_patch(w: int, h: int):
    return [(EXE, MENU_ASPECT_VA, MENU_ASPECT_OLD, "68" + struct.pack("<f", w / h).hex(), "menu 3D aspect")]


# Menu 3D background aspect experiment (see apply); stock bytes: push 1.3333334
MENU_ASPECT_VA, MENU_ASPECT_OLD = 0x00B30859, "68abaaaa3f"

# Old wheel/hotkey clamp patches (zoom up to 1.5): byte_patches() undoes them on installs that had them.
ZOOM_PAST_ONE = [
    (EXE, 0x009288A7, "d81decd1c400", "d81d34d4c400", "wheel: compare zoom with 1.5"),
    (EXE, 0x009288B2, "b80000803f", "b80000c03f", "wheel: clamp zoom to 1.5"),
    (EXE, 0x00908D1E, "d81decd1c400", "d81d34d4c400", "hotkey: compare zoom with 1.5"),
    (EXE, 0x00908D50, "b80000803f", "b80000c03f", "hotkey: clamp zoom to 1.5"),
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


def _reg_split(name: str):
    """'Sub/Value' -> (REG_KEY\\Sub, Value); plain names live in REG_KEY."""
    sub, _, value = name.rpartition("/")
    return (REG_KEY + "\\" + sub if sub else REG_KEY), value


def set_registry(game: Path, values: dict, release=()) -> None:
    """Set DWORD values (names may be 'Subkey/Value'), saving the values found before the
    first apply; names in `release` go back to their saved value."""
    import winreg

    saved_path = game / STATE_DIR / "registry.json"
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
    for name, value in values.items():
        path, val = _reg_split(name)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            if name not in saved:
                try:
                    saved[name] = winreg.QueryValueEx(key, val)[0]
                except FileNotFoundError:
                    saved[name] = None
            winreg.SetValueEx(key, val, 0, winreg.REG_DWORD, value)
    for name in release:
        if name in saved:
            _reg_restore(name, saved.pop(name))
    saved_path.write_text(json.dumps(saved, indent=2))
    print("registry: " + ", ".join(f"{k}={v}" for k, v in values.items()))


def _reg_restore(name: str, value) -> None:
    import winreg

    path, val = _reg_split(name)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, val)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, val, 0, winreg.REG_DWORD, value)


def restore_registry(game: Path) -> None:
    saved_path = game / STATE_DIR / "registry.json"
    if not saved_path.exists():
        return
    saved = json.loads(saved_path.read_text())
    for name, value in saved.items():
        _reg_restore(name, value)
    print("registry: restored " + ", ".join(saved))



# ---------------------------------------------------------------- overlay features

PY = sys.executable
WORK = REPO / "work"


def _manifest_hashes(path) -> dict:
    """{relative path (lower, '/'): stock sha256 or None} from any of our manifest formats."""
    if path is None or not path.exists():
        return {}
    m = json.loads(path.read_text(encoding="utf-8"))
    files = m.get("files", [])
    if isinstance(files, dict):
        items = files.items()
    else:
        items = [(f.get("file") or f.get("path"), f) for f in files]
    out = {}
    for rel, f in items:
        out[rel.replace("\\", "/").lower()] = f.get("source_sha256") or f.get("stock_sha256")
    return out


class Overlay:
    """A set of files (relative install path -> source file) built from the stock install."""

    def __init__(self, name, root, build, manifest=None, select=None, mapping=None):
        self.name, self.root, self.build_cmd = name, root, build
        self.manifest, self.select, self.mapping = manifest, select, mapping

    def built(self) -> bool:
        if self.mapping:
            files = self.mapping()
            return bool(files) and all(src.exists() for src in files.values())
        marker = self.select or self.manifest
        return (self.root / "Data").is_dir() and (marker is None or marker.exists())

    def build(self, stock: Path) -> None:
        if self.build_cmd is None:
            sys.exit(f"{self.name}: overlay {self.root} is missing; it is built by its own tool (see docs)")
        cmd = [str(c) for c in self.build_cmd(stock)]
        print(f"{self.name}: building: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=REPO, check=True)

    def files(self) -> dict:
        """{rel install path: source path}"""
        if self.mapping:
            return self.mapping()
        keep = set(_manifest_hashes(self.select)) if self.select else None
        out = {}
        for f in sorted((self.root / "Data").rglob("*")):
            if f.is_file():
                rel = f.relative_to(self.root).as_posix()
                if keep is None or rel.lower() in keep:
                    out[rel] = f
        return out

    def stock_hashes(self) -> dict:
        return _manifest_hashes(self.select or self.manifest)


def _unit_ai_files() -> dict:
    src = REPO / "ai" / "unit ai scripts"
    return {f"Data/unit ai scripts/{f.name.lower()}": f for f in sorted(src.glob("*.tai"))}


# Mode A of docs/maps.md: the exe has a fixed table of 13 random-map names, so the new scripts
# replace three slots that are not in the tourney set. The lobby keeps the old names.
MAP_SLOTS = {"archipelago.rmv": "caspian sea.rmv", "twin rivers.rmv": "channels.rmv",
             "uplands.rmv": "peloponnese.rmv"}


def _map_files() -> dict:
    return {f"Data/random map scripts/{slot}": REPO / "rms" / src for src, slot in MAP_SLOTS.items()}


OVERLAYS = {
    "mips": Overlay("mips", WORK / "overlay",
                    lambda st: [PY, "tools/build_textures.py", st, WORK / "overlay"],
                    manifest=WORK / "overlay" / "manifest.json"),
    "hd-terrain": Overlay("hd-terrain", WORK / "overlay-hd",
                          lambda st: [PY, "tools/build_textures.py", "hd-terrain", st, WORK / "overlay-hd"],
                          select=WORK / "overlay-hd" / "manifest-hd-terrain.json"),
    "hd-units": Overlay("hd-units", WORK / "overlay-hd",
                        lambda st: [PY, "tools/build_textures.py", "hd-units", st, WORK / "overlay-hd"],
                        select=WORK / "overlay-hd" / "manifest-hd-units.json"),
    "shaders": Overlay("shaders", WORK / "overlay-shaders",
                       lambda st: [PY, "tools/build_shaders.py", st, WORK / "overlay-shaders"],
                       manifest=WORK / "overlay-shaders" / "shader-manifest.json"),
    "ai-hard": Overlay("ai-hard", WORK / "overlay-ai",
                       lambda st: [PY, "tools/build_ai_db.py", st, WORK / "overlay-ai"],
                       manifest=WORK / "overlay-ai" / "manifest.json"),
    # build_ai_db --personalities writes both tables; this feature installs only dbcivspecai.dat
    "ai-personalities": Overlay("ai-personalities", WORK / "overlay-ai-pers",
                                lambda st: [PY, "tools/build_ai_db.py", st, WORK / "overlay-ai-pers", "--personalities"],
                                mapping=lambda: {"Data/db/dbcivspecai.dat": WORK / "overlay-ai-pers" / "Data" / "db" / "dbcivspecai.dat"}),
    "unit-ai": Overlay("unit-ai", REPO / "ai", lambda st: [PY, "tools/build_ai.py", "build", "--game", st],
                       mapping=_unit_ai_files),
    "maps": Overlay("maps", REPO / "rms", lambda st: [PY, "tools/gen_rms.py"], mapping=_map_files),
    # built by other tools; installed only when present (docs/survival.md, docs/language.md)
    "survival": Overlay("survival", WORK / "overlay-survival", None, manifest=WORK / "overlay-survival" / "manifest.json"),
    "lang-en": Overlay("lang-en", WORK / "overlay-lang-en", None, manifest=WORK / "overlay-lang-en" / "manifest.json"),
}
MUTATOR_DIR = WORK / "overlay-mutators"  # one sub folder per mutator (docs/mutators.md); at most one active


def mutator_overlay(name: str) -> Overlay:
    root = MUTATOR_DIR / name
    if not (root / "Data").is_dir():
        known = sorted(d.name for d in MUTATOR_DIR.iterdir() if d.is_dir()) if MUTATOR_DIR.is_dir() else []
        sys.exit(f"unknown mutator {name!r}; built: {', '.join(known) or 'none'}")
    return Overlay(f"mutator:{name}", root, None, manifest=root / "manifest.json")

# name -> default on. Overlay order = install priority: a later feature wins where two touch a file.
FEATURES = {
    "borderless": True,
    "smooth-scroll": True,
    "zoom": True,
    "ultra": True,
    "mips": True,
    "hd-terrain": True,
    "hd-units": True,
    "shaders": True,
    "ai-hard": True,
    "ai-personalities": False,
    "unit-ai": True,
    "maps": False,
    "survival": False,
    "lang-en": False,
}
# The autodetect does not know the GPU and leaves every quality at 0 ("Низко"); 3 = "Ультра".
# The shader upgrade only shows with the higher techniques.
ULTRA = {f"Graphics Settings/{n} Quality Level": 3 for n in ("Model", "Water", "Particle", "Terrain")}
ULTRA.update({"Graphics Settings/Flora Quality": 3,
              "Render Reflections": 1, "Flora Enabled": 1})
OVERLAY_ORDER = list(OVERLAYS)  # dict order = install priority; the mutator goes last
# Files that decide the simulation; all players must match (REMASTER.txt fingerprint).
GAMEPLAY_DIRS = ["Data/db", "Data/random map scripts", "Data/unit ai scripts"]


def default_stock(game: Path) -> Path:
    if DEFAULT_STOCK.is_dir() and DEFAULT_STOCK.resolve() != game.resolve():
        return DEFAULT_STOCK
    return game


def sync_overlays(game: Path, enabled: list, stock: Path, rebuild: bool, state: dict) -> None:
    """Install the overlay files of the enabled features and put every other managed file back."""
    orig = game / STATE_DIR / "orig"
    managed = dict(state.get("managed", {}))  # rel -> feature currently installed
    created = set(state.get("created", []))   # rel that does not exist in stock
    plan, stock_hash = {}, {}
    active = [OVERLAYS[n] for n in OVERLAY_ORDER if n in enabled]
    if state.get("mutator"):
        active.append(mutator_overlay(state["mutator"]))
    for ov in active:
        name = ov.name
        if (rebuild and ov.build_cmd) or not ov.built():
            ov.build(stock)
        hashes = ov.stock_hashes()
        for rel, src in ov.files().items():
            plan[rel] = (name, src)
            stock_hash[rel] = hashes.get(rel.lower())
    for rel in [r for r in managed if r not in plan]:
        dst, bak = game / rel, orig / rel
        if rel in created:
            dst.unlink(missing_ok=True)
            created.discard(rel)
        elif bak.exists():
            shutil.copy2(bak, dst)
            bak.unlink()
        del managed[rel]
    counts = {}
    for rel, (name, src) in plan.items():
        dst, bak = game / rel, orig / rel
        want = sha256(src)
        if rel not in managed:
            if dst.exists():
                cur = sha256(dst)
                expect = stock_hash.get(rel)
                if expect is None and (stock / rel).exists():
                    expect = sha256(stock / rel)
                if cur != want and expect and cur != expect:
                    sys.exit(f"{rel}: not the stock file (sha {cur[:12]}), refusing to replace it")
                if not bak.exists():
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, bak)
            else:
                created.add(rel)
        if not dst.exists() or sha256(dst) != want:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        managed[rel] = name
        counts[name] = counts.get(name, 0) + 1
    for ov in active:
        print(f"{ov.name}: {counts.get(ov.name, 0)} files")
    state["managed"], state["created"] = managed, sorted(created)


def shader_cache_reset(game: Path) -> None:
    """The game caches shader permutations in shader.cache; move it aside so it is rebuilt."""
    cache, bak = game / "shader.cache", game / STATE_DIR / "orig" / "shader.cache"
    if cache.exists():
        if not bak.exists():
            shutil.move(cache, bak)
        else:
            cache.unlink()
        print("shader.cache: moved aside, the game rebuilds it")


def fingerprint(game: Path) -> str:
    """Short hash over the files that decide the simulation (db, random maps, unit AI)."""
    h = hashlib.sha256()
    for d in GAMEPLAY_DIRS:
        for f in sorted((game / d).rglob("*"), key=lambda p: p.as_posix().lower()):
            if f.is_file():
                h.update(f.relative_to(game).as_posix().lower().encode() + b"\0")
                h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:12]


def check_game_dir(game: Path) -> None:
    if not (game / EXE).is_file():
        sys.exit(f"{EXE} not found in {game}")
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True, text=True).stdout
    if EXE.lower() in out.lower():
        sys.exit(f"{EXE} is running; close the game first")


def load_state(game: Path) -> dict:
    p = game / STATE_DIR / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def choose_features(state: dict, only, skip) -> list:
    if only is None and skip is None and "features" in state:
        return list(state["features"])
    base = [f for f, on in FEATURES.items() if on] if only is None else list(only)
    for f in base + list(skip or []):
        if f not in FEATURES:
            sys.exit(f"unknown feature {f!r}; known: {', '.join(FEATURES)}")
    return [f for f in FEATURES if f in base and f not in (skip or [])]


def apply(game: Path, only=None, skip=None, stock=None, rebuild=False, mutator=None, zoom=None) -> None:
    orig = game / STATE_DIR / "orig"
    orig.mkdir(parents=True, exist_ok=True)
    state = load_state(game)
    feats = choose_features(state, only, skip)
    if mutator is not None:
        state["mutator"] = None if mutator in ("", "none") else mutator
    stock = Path(stock) if stock else default_stock(game)
    for name in MODIFIED:
        if not (orig / name).exists():
            shutil.copy2(game / name, orig / name)

    exe = game / EXE
    if is_laa(exe):
        print("LAA: already set")
    else:
        set_laa(exe)
        print("LAA: set")

    borderless = "borderless" in feats
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

    for name in REMOVED:
        if (game / name).exists():
            (orig / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(game / name, orig / name)
    print("intro movies: removed")

    byte_patches(game, CMDLINE_FIX, True, "host/join command line fix")
    byte_patches(game, BORDERLESS, borderless, "borderless")
    byte_patches(game, SMOOTH_SCROLL, "smooth-scroll" in feats, "smooth-scroll")
    byte_patches(game, ZOOM_PAST_ONE, False, "zoom past 1.0 (old)")
    zoom = float(state.get("zoom", DEFAULT_ZOOM) if zoom is None else zoom)
    unzoom(game)
    byte_patches(game, zoom_patches(zoom), "zoom" in feats, f"zoom x{zoom}")
    # menu-aspect experiment (0xb30859 4:3 -> w/h) un-stretched the menu 3D scene but the menu
    # frame and logo vanished; only undo it on installs that still carry it.
    exe_data = (game / EXE).read_bytes()
    off = pe_va_to_offset(exe_data, MENU_ASPECT_VA)
    cur = exe_data[off:off + 5].hex()
    if cur != MENU_ASPECT_OLD and cur.startswith("68"):
        byte_patches(game, [(EXE, MENU_ASPECT_VA, MENU_ASPECT_OLD, cur, "menu 3D aspect")], False, "menu-aspect (old)")

    had_shaders = "shaders" in state.get("features", [])
    sync_overlays(game, feats, stock, rebuild, state)
    if had_shaders != ("shaders" in feats) or ("shaders" in feats and rebuild):
        shader_cache_reset(game)

    # Full Screen Mode stays 1: the game's own windowed mode hangs on a white window.
    # The game drops a resolution missing from the adapter's mode list back to 1024x768
    # (and autodetect can write 800x600), so we always write the current desktop mode.
    # Wait for VSync 1 = PresentationInterval ONE: frames paced to the display refresh instead of
    # 400+ fps with tearing. Rendering stays decoupled from the simulation (own physics thread).
    reg = {"Full Screen Mode": 1, "Game Window Width": w, "Game Window Height": h,
           "Custom Refresh Rate": hz, "Wait for VSync": 1}
    release = []
    if "zoom" in feats:
        # far clip = this/100 x 43.3; 60 (the autodetected minimum) cuts the far terrain at the
        # new zoom distance; 160 gives 69 units.
        reg["RearClipPlaneModifier"] = int(round(160 * zoom / 1.5))
    else:
        release.append("RearClipPlaneModifier")
    if "ultra" in feats:
        reg.update(ULTRA)
    else:
        release += list(ULTRA)
    set_registry(game, reg, release)

    fp = fingerprint(game)
    (game / "REMASTER.txt").write_text(
        f"Rise and Fall Remaster {REMASTER_VERSION}\r\n"
        f"Features: {', '.join(feats) or '-'}\r\n"
        f"Gameplay fingerprint: {fp}\r\n"
        "All players of a network game need the same fingerprint.\r\n", encoding="ascii")
    for fname, text in (("RiseAndFall Remaster.bat", LAUNCH_BAT), ("Host.bat", HOST_BAT),
                        ("Join.bat", JOIN_BAT)):
        (game / fname).write_bytes(text.replace("\n", "\r\n").encode("ascii"))
    print(f"REMASTER.txt + start scripts: written (fingerprint {fp})")

    state.update({"version": REMASTER_VERSION, "dxvk": DXVK_VERSION, "laa": True, "features": feats,
                  "mode": [w, h, hz], "stock": str(stock), "fingerprint": fp, "zoom": zoom})
    state.pop("borderless", None)
    (game / STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


def revert(game: Path) -> None:
    restore_registry(game)
    state = load_state(game)
    orig = game / STATE_DIR / "orig"
    created = set(state.get("created", []))
    for rel in state.get("managed", {}):
        if rel in created:
            (game / rel).unlink(missing_ok=True)
        elif (orig / rel).exists():
            shutil.copy2(orig / rel, game / rel)
    print(f"overlays: {len(state.get('managed', {}))} files restored")
    if (orig / "shader.cache").exists():
        shutil.copy2(orig / "shader.cache", game / "shader.cache")
        print("restored shader.cache")
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
    state = load_state(game)
    print(f"features: {', '.join(state.get('features', [])) or 'none'}")
    print(f"overlay files: {len(state.get('managed', {}))}, fingerprint: {state.get('fingerprint')}")


def main() -> None:
    argv, opts, args = sys.argv[1:], {}, []
    while argv:
        a = argv.pop(0)
        if a in ("--only", "--skip", "--stock", "--mutator", "--zoom"):
            if not argv:
                sys.exit(__doc__)
            opts[a] = argv.pop(0)
        elif a == "--rebuild":
            opts[a] = True
        elif a.startswith("--"):
            sys.exit(__doc__)
        else:
            args.append(a)
    if args == ["features"]:
        for f, on in FEATURES.items():
            print(f"{f:17s} {'default on' if on else 'default off'}")
        return
    if len(args) != 2 or args[0] not in ("apply", "revert", "status"):
        sys.exit(__doc__)
    game = Path(args[1])
    check_game_dir(game)
    if args[0] == "apply":
        def split(v):
            return None if v is None else [x.strip() for x in v.split(",") if x.strip()]
        apply(game, only=split(opts.get("--only")), skip=split(opts.get("--skip")),
              stock=opts.get("--stock"), rebuild=bool(opts.get("--rebuild")), mutator=opts.get("--mutator"),
              zoom=float(opts["--zoom"]) if "--zoom" in opts else None)
    else:
        {"revert": revert, "status": status}[args[0]](game)


if __name__ == "__main__":
    main()
