"""Raise the lobby "Game Unit Limit" (Russian UI "Предел юнитов") maximum.

Usage:
    python tools/build_unitlimit.py <game_dir> <overlay_dir> [--max 10000] [--min 250]

Where the limit lives (RiseAndFall.exe 1.15, read from the decompiled exe):
- dbworld.dat (32-byte records, loader FUN_0060de70, table 0x0f) record 26 holds the range:
  +0x14 = min 250, +0x18 = max 5000. In memory that is [DAT_01020d98 + 0x354 / + 0x358].
- The step 250 (0xfa) is hard-coded in the exe: the lobby combo (control 0xbb) lists
  min, min+250, ... max (FUN_0090fb.. at 0x90fc30 region), the selection handler
  FUN_0090fe40 sets limit = min + index*250.
- The game-settings copy FUN_006dfdb0 (used for network game options, save load and game
  start) resets any limit that is not 80000 and above max to min. So every player needs the
  same max, or a client that has the stock file silently plays with 250 (out of sync).
- In game the per-player cap is world+0xd0 = limit / number of active players
  (FUN_0071cd.., decomp line ~505775), integer, 32 bit.

Only the max (and optionally the min) field of record 26 changes; every other byte is checked to
be stock. Gameplay data: all players need the same overlay.
"""

import argparse
import hashlib
import struct
import sys
from pathlib import Path

DB = Path("Data") / "db" / "dbworld.dat"
REC_SIZE = 32
REC_INDEX = 26
STOCK_COUNT = 138
STEP = 250                      # hard-coded in the exe (0xfa)
UNLIMITED = 80000               # exe sentinel, must stay above any max
STOCK_MIN, STOCK_MAX = 250, 5000


def field_offsets():
    base = 4 + REC_INDEX * REC_SIZE
    return base + 0x14, base + 0x18


def patch(stock: bytes, new_max: int, new_min: int = STOCK_MIN) -> bytes:
    count = struct.unpack_from("<I", stock, 0)[0]
    if count != STOCK_COUNT or len(stock) != 4 + count * REC_SIZE:
        raise ValueError(f"dbworld.dat: count {count}, size {len(stock)}; not the 1.15 layout")
    base = 4 + REC_INDEX * REC_SIZE
    rec_no, rec_idx = struct.unpack_from("<i", stock, base + 8)[0], struct.unpack_from("<i", stock, base + 0x10)[0]
    if (rec_no, rec_idx) != (REC_INDEX + 1, REC_INDEX):
        raise ValueError(f"record {REC_INDEX}: ids {rec_no}/{rec_idx}, expected {REC_INDEX + 1}/{REC_INDEX}")
    o_min, o_max = field_offsets()
    cur_min, cur_max = struct.unpack_from("<II", stock, o_min)
    if (cur_min, cur_max) != (STOCK_MIN, STOCK_MAX):
        raise ValueError(f"record {REC_INDEX}: min/max {cur_min}/{cur_max}, expected stock {STOCK_MIN}/{STOCK_MAX}")
    if not (0 < new_min <= new_max < UNLIMITED):
        raise ValueError(f"need 0 < min <= max < {UNLIMITED}")
    if new_min % STEP or new_max % STEP:
        raise ValueError(f"min and max must be multiples of {STEP} (exe step)")
    out = bytearray(stock)
    struct.pack_into("<II", out, o_min, new_min, new_max)
    diff = [i for i in range(len(out)) if out[i] != stock[i]]
    if any(not (o_min <= i < o_max + 4) for i in diff):
        raise AssertionError("changed bytes outside record 26 min/max")
    return bytes(out)


def entries(new_min: int, new_max: int) -> int:
    return (new_max - new_min) // STEP + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("overlay_dir", type=Path)
    ap.add_argument("--max", type=int, default=10000)
    ap.add_argument("--min", type=int, default=STOCK_MIN)
    a = ap.parse_args(argv)
    stock = (a.game_dir / DB).read_bytes()
    new = patch(stock, a.max, a.min)
    dst = a.overlay_dir / DB
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(new)
    print(f"dbworld.dat: unit limit {a.min}..{a.max} step {STEP} ({entries(a.min, a.max)} lobby entries); "
          f"stock {hashlib.sha256(stock).hexdigest()[:12]} -> {hashlib.sha256(new).hexdigest()[:12]}; {dst}")


if __name__ == "__main__":
    sys.exit(main())
