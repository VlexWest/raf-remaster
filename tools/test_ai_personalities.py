#!/usr/bin/env python3
"""Offline checks for the civ AI personalities (tools/build_ai_db.py --personalities).

  python tools/test_ai_personalities.py ["D:\\Games\\Rise and Fall"]

Reads the base install only; writes into a temp directory. The "game" here is a stub of the
exe's own logic, written from the decompile:

  FUN_005f7380 / FUN_005f72b0   load dbcivspecai: per behavior id a table of 12 civ slots,
                                multiplier (default 1.0) and value (default -1.0); the record
                                pairs land in slots 3 (Greece), 4 (Persia), 5 (Rome), 6, 7, 8
                                (placeholders 1-3), 9 (= Rome's pair again), 10 (Egypt), 11
  FUN_0046bd20 / FUN_00468130   combine: neutral -> base; value == -1 -> base * mult; else value

1. stock dbcivspecai is neutral for every id and slot (the premise: nothing changes without us)
2. the generated file, read through the stub loader, gives exactly the values the build reported
3. slot 0 (the main AI setup) and all unlisted ids/slots stay neutral
4. dbcpbehavior differs from stock only in the six Hard edits
5. Easy <= Medium <= Hard order survives for the triplets, for every civ
6. failure paths: wrong stock file, bad multiplier, a triplet made stronger, a rounding tie,
   a duplicate id, an unverified id all stop the build; the stale-file case is cleaned up
7. the build is deterministic and never writes into the game directory
"""
import hashlib
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_ai_db as B  # noqa: E402
from raf_data import unpack_bytes  # noqa: E402

GAME = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\Games\Rise and Fall")
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def raises_exit(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    except ValueError:
        return True
    return False


# ---- stub of the exe -------------------------------------------------------
def stub_load(data):
    """{behavior id: ([12 mult], [12 value])} exactly like FUN_005f7380 + FUN_005f72b0."""
    count = struct.unpack_from("<I", data, 0)[0]
    table = {}
    for i in range(count):
        rec = data[4 + i * 196:4 + (i + 1) * 196]
        bid = struct.unpack_from("<i", rec, 0x6c)[0]
        if not 0 < bid < 0x95:
            continue
        f = lambda off: struct.unpack_from("<f", rec, off)[0]  # noqa: E731
        mult, val = [1.0] * 12, [-1.0] * 12
        for slot, (om, ov) in {3: (0x70, 0x74), 4: (0x78, 0x7c), 5: (0x80, 0x84), 6: (0x90, 0x94),
                               7: (0x98, 0x9c), 8: (0xa0, 0xa4), 9: (0x80, 0x84), 10: (0x88, 0x8c),
                               11: (0xa8, 0xac)}.items():
            mult[slot], val[slot] = f(om), f(ov)
        table[bid] = (mult, val)
    return table


def stub_get(table, bid, slot, base, kind):
    if bid not in table:
        return base
    mult, val = table[bid]
    if mult[slot] == 1.0 and val[slot] == -1.0:
        return base
    v = base * mult[slot] if val[slot] == -1.0 else val[slot]
    return round(v, 4) if kind == "float" else int(round(v))


def rd(path):
    return Path(path).read_bytes()


stock_civ = rd(GAME / B.DB_CIV)
stock_cp = rd(GAME / B.DB)
cp_rows = {r["id"]: dict(r) for r in unpack_bytes("dbcpbehavior", stock_cp)["records"]}

# 1
t = stub_load(stock_civ)
neutral = all(m == [1.0] * 12 and v == [-1.0] * 12 for m, v in t.values())
check(neutral and set(t) == {44}, "stock dbcivspecai: only id 44 is live and it is neutral in every slot")

# build once
tmp = Path(tempfile.mkdtemp(prefix="raf-ai-test-"))
ov = tmp / "ov"
import io, contextlib  # noqa: E401,E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    B.build(GAME, ov, personalities=True)
new_civ = rd(ov / B.DB_CIV)
new_cp = rd(ov / B.DB)
check(b"byte-identical" in buf.getvalue().encode() or "byte-identical" in buf.getvalue(), "build printed the byte-diff summary")

# 2 + 3
t = stub_load(new_civ)
rows = B.personality_rows()
check(set(t) == {44} | set(rows), "generated file has exactly the stock id 44 plus the %d personality ids" % len(rows))
stock_t = {}
bad = []
n = 0
for bid, per in rows.items():
    kind, fields, _ = B.PARAMS[bid]
    for civ, (m, s) in per.items():
        slot = B.CIVS.index(civ)
        slot = {"greece": 3, "persia": 4, "rome": 5, "egypt": 10}[civ]
        for f in fields:
            base = cp_rows[bid][f]
            for rid, field, _o, newv, _w in B.EDITS:  # personalities act on the Hard-tuned table
                if rid == bid and field == f:
                    base = newv
            got = stub_get(t, bid, slot, base, kind)
            want = B.apply_override(base, m, s, kind)
            n += 1
            if kind == "float":
                if abs(got - want) > 1e-3:
                    bad.append((bid, civ, f, got, want))
            elif got != want:
                bad.append((bid, civ, f, got, want))
check(not bad and n > 40, "stub loader + combine reproduce all %d reported values %s" % (n, bad[:3]))

leaks = []
for bid, (mult, val) in t.items():
    for slot in range(12):
        listed = bid in rows and any(
            {"greece": 3, "persia": 4, "rome": 5, "egypt": 10}[c] == slot for c in rows[bid])
        if slot == 9 and bid in rows and "rome" in rows[bid]:
            listed = True  # the exe loads Rome's pair into slot 9 too (placeholder civ 4)
        if not listed and (mult[slot] != 1.0 or val[slot] != -1.0):
            leaks.append((bid, slot))
check(not leaks, "every slot not named by a personality (including slot 0, used by the main setup) is neutral %s" % leaks[:3])
check(all(mult[0] == 1.0 and val[0] == -1.0 for mult, val in t.values()), "slot 0 neutral for every id")

# 4
old, new = unpack_bytes("dbcpbehavior", stock_cp), unpack_bytes("dbcpbehavior", new_cp)
diffs = []
for a, b in zip(old["records"], new["records"]):
    for k in a:
        if a[k] != b[k]:
            diffs.append((a["id"], k))
want = sorted((rid, f) for rid, f, *_ in B.EDITS)
check(sorted(diffs) == want and len(new_cp) == len(stock_cp), "dbcpbehavior differs from stock only in the six Hard edits %s" % diffs)

# 5
for civ, slot in (("greece", 3), ("persia", 4), ("rome", 5), ("egypt", 10)):
    for bid, direction in B.TRIPLETS.items():
        if bid not in rows:
            continue
        vals = []
        for f in ("v4", "v7", "v12"):
            base = cp_rows[bid][f]
            for rid, field, _o, newv, _w in B.EDITS:
                if rid == bid and field == f:
                    base = newv
            vals.append(stub_get(t, bid, slot, base, "int"))
        ok = vals[0] <= vals[1] <= vals[2] if direction == "higher" else vals[0] >= vals[1] >= vals[2]
        check(ok, "%s id %d keeps Easy/Medium/Hard order %s" % (civ, bid, vals))

# 6 failure paths
orig = {k: list(v) for k, v in B.PERSONALITIES.items()}


def with_personalities(p, fn, *a):
    saved = B.PERSONALITIES
    B.PERSONALITIES = p
    try:
        return fn(*a)
    finally:
        B.PERSONALITIES = saved


def bld(p):
    return with_personalities(p, B.make_civspecai, stock_civ, cp_rows, True)


if True:
    check(raises_exit(bld, {"persia": [(1, "mult", 1.6, "x")]}), "multiplier 1.6 is refused")
    check(raises_exit(bld, {"persia": [(5, "mult", 1.25, "x")]}), "ships (Easy/Med/Hard) made stronger than stock is refused")
    check(raises_exit(bld, {"persia": [(88, "mult", 0.8, "x")]}), "defence timer made faster than stock is refused")
    check(raises_exit(bld, {"persia": [(33, "mult", 1.25, "x")]}), "rounding tie (2 * 1.25 = 2.5) is refused")
    check(raises_exit(bld, {"persia": [(1, "mult", 0.9, "x"), (1, "mult", 0.8, "y")]}), "the same id twice for one civ is refused")
    check(raises_exit(bld, {"persia": [(17, "mult", 1.1, "x")]}), "id 17 (CitizenTargetCountMaximum, inverted by FUN_0047d3a0) is not allowed")
    check(raises_exit(bld, {"persia": [(44, "mult", 1.1, "x")]}), "the stock record id 44 is refused")
    broken = bytearray(stock_civ)
    struct.pack_into("<f", broken, 4 + 196 + 0x70, 1.5)
    check(raises_exit(B.make_civspecai, bytes(broken), cp_rows, True), "a non-neutral stock file (other game version) is refused")
    short = stock_civ[:-3]
    check(raises_exit(B.make_civspecai, short, cp_rows, True), "a truncated stock file is refused")

# stale file removal
with contextlib.redirect_stdout(io.StringIO()):
    B.build(GAME, ov, personalities=False)
check(not (ov / B.DB_CIV).exists(), "a build without --personalities removes the stale dbcivspecai.dat")
import json  # noqa: E402
man = json.loads((ov / "manifest.json").read_text())
check(man["step"] == "ai-hard" and list(man["files"]) == ["Data/db/dbcpbehavior.dat"], "manifest back to the plain Hard step")

# 7 determinism and stock untouched
ov2 = tmp / "ov2"
with contextlib.redirect_stdout(io.StringIO()):
    B.build(GAME, ov2, personalities=True)
    B.build(GAME, tmp / "ov3", personalities=True)
h = lambda p: hashlib.sha256(rd(p)).hexdigest()  # noqa: E731
check(h(ov2 / B.DB_CIV) == h(tmp / "ov3" / B.DB_CIV) and h(ov2 / B.DB) == h(tmp / "ov3" / B.DB), "two builds give identical bytes")
check(rd(GAME / B.DB_CIV) == stock_civ and rd(GAME / B.DB) == stock_cp, "the game directory files are unchanged")
man = json.loads((ov2 / "manifest.json").read_text())
check(man["step"] == "ai-hard+personalities" and man["files"]["Data/db/dbcivspecai.dat"]["source_sha256"]
      == hashlib.sha256(stock_civ).hexdigest(), "manifest lists both files with the stock hash")

print()
print("FAILED: %d" % len(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
