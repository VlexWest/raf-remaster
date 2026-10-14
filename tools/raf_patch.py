"""Apply or revert the Rise and Fall remaster patches on an existing install.

Usage:
    python raf_patch.py apply  <game_dir>
    python raf_patch.py revert <game_dir>
    python raf_patch.py status <game_dir>

Everything is idempotent. Originals are kept in <game_dir>/.raf-remaster/orig
so `revert` restores the install byte for byte.
"""

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
MODIFIED = [EXE]
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


def check_game_dir(game: Path) -> None:
    if not (game / EXE).is_file():
        sys.exit(f"{EXE} not found in {game}")


def apply(game: Path) -> None:
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

    shutil.copy2(dxvk_d3d9(), game / "d3d9.dll")
    (game / "dxvk.conf").write_text(DXVK_CONF, encoding="ascii")
    print(f"DXVK {DXVK_VERSION}: installed")

    (game / "RiseAndFall Remaster.bat").write_text(LAUNCH_BAT, encoding="ascii")
    print("launcher script: written")

    for name in REMOVED:
        if (game / name).exists():
            (orig / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(game / name, orig / name)
    print("intro movies: removed")

    state = {"dxvk": DXVK_VERSION, "laa": True}
    (game / STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


def revert(game: Path) -> None:
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
    if len(sys.argv) != 3 or sys.argv[1] not in ("apply", "revert", "status"):
        sys.exit(__doc__)
    game = Path(sys.argv[2])
    check_game_dir(game)
    {"apply": apply, "revert": revert, "status": status}[sys.argv[1]](game)


if __name__ == "__main__":
    main()
