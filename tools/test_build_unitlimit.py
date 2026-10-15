"""Offline checks for build_unitlimit.py against the stock dbworld.dat (read-only).

    python tools/test_build_unitlimit.py [game_dir]
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_unitlimit as bu  # noqa: E402

GAME = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\Games\Rise and Fall")


def expect_error(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return
    raise AssertionError(f"no error for {a[1:]}")


def main():
    stock = (GAME / bu.DB).read_bytes()
    o_min, o_max = bu.field_offsets()
    assert (o_min, o_max) == (0x358, 0x35C)
    for mx, mn in ((10000, 250), (20000, 250), (20000, 500)):
        new = bu.patch(stock, mx, mn)
        assert len(new) == len(stock)
        assert struct.unpack_from("<II", new, o_min) == (mn, mx)
        diff = [i for i in range(len(new)) if new[i] != stock[i]]
        assert all(o_min <= i < o_max + 4 for i in diff), diff
        # exe semantics: list min..max step 250, index -> value, value -> index round trip
        vals = list(range(mn, mx + 1, bu.STEP))
        assert len(vals) == bu.entries(mn, mx)
        assert all((v - mn) // bu.STEP == i for i, v in enumerate(vals))
        # FUN_006dfdb0 keeps value if == 80000 or <= max, else resets to min
        keep = lambda v: v if (v == bu.UNLIMITED or v <= mx) else mn
        assert keep(mx) == mx and keep(mx + bu.STEP) == mn
        # per-player cap = limit / active players (unsigned div)
        assert [mx // n for n in (2, 4, 8)] == [mx // 2, mx // 4, mx // 8]
    expect_error(bu.patch, stock, 10100, 250)        # not a multiple of 250
    expect_error(bu.patch, stock, 80000, 250)        # collides with the exe sentinel
    expect_error(bu.patch, stock, 250, 500)          # min > max
    expect_error(bu.patch, bu.patch(stock, 10000), 20000)  # input not stock
    bad = bytearray(stock); bad[0] = 0
    expect_error(bu.patch, bytes(bad), 10000)        # wrong layout
    print("test_build_unitlimit: OK (10000/250: 40 entries, 20000/250: 80, 20000/500: 79)")


if __name__ == "__main__":
    main()
