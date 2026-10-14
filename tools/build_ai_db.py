"""Build the tuned skirmish AI tables into an overlay.

Usage:
    python tools/build_ai_db.py <game_dir> <overlay_dir> [--personalities]

Step 1 (always): dbcpbehavior.dat. Only the Hard difficulty is changed (Easy and Medium stay
stock), and no resource cheats are added: the AI attacks earlier, more often and with bigger
groups, rebuilds defence faster and advances epochs sooner. Each edit checks the stock value
first, so a different game version fails loudly instead of being half patched.

Step 2 (--personalities, off by default): dbcivspecai.dat. Gives Greece, Persia, Rome and Egypt
their own AI style by multiplying (or, for one parameter, setting) a few dbcpbehavior values per
civilization. Mechanism and table: docs/ai-personalities.md. Everything is checked against the
stock files, round-tripped through raf_data, validated (ordering, size of the change) and
byte-diffed against the stock file before the overlay is written.

The skirmish AI runs inside the lockstep simulation, so every player in a multiplayer game
needs the same files (same remaster version).
"""

import copy
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raf_data import pack_obj, unpack_bytes  # noqa: E402

DB = Path("Data") / "db" / "dbcpbehavior.dat"
DB_CIV = Path("Data") / "db" / "dbcivspecai.dat"

# (row id, field, stock value, new value, why)
EDITS = [
    (2, "v7", 15, 10, "AttackDelayLevelOfDifficultyHardModifier: first attack sooner"),
    (7, "v7", 30, 20, "AttackFrequencyLevelOfDifficultyHardModifier: attacks more often"),
    (11, "v12", 200.0, 300.0, "AttackGroupSizeLevelOfDifficultyHardModifier: bigger attack waves"),
    (29, "v7", 60, 45, "EpochAdvanceFrequencyLevelOfDifficultyHardModifier: advances epochs sooner"),
    (88, "v12", 4.0, 2.0, "DefenseTimerHard (minutes): reacts to raids faster"),
    (104, "v4", 2, 3, "MilitaryBuildingBonusHard: one more military building"),
]

# ---------------------------------------------------------------------------
# Civilization personalities (dbcivspecai.dat)
# ---------------------------------------------------------------------------
# Civ slot = row index in dbphoenixcivtable = the civ id passed to the AI (FUN_007b4120 path).
# FUN_005f72b0 reads the dbcivspecai pairs into slots 3 (Greece), 4 (Persia), 5 (Rome), 10 (Egypt).
CIVS = ("greece", "persia", "rome", "egypt")

# Parameters the personalities may touch: id -> (kind, fields the exe reads, decompile reference).
# kind "int": ROUND(base * mult) (FUN_00468130); "float": base * mult (FUN_0046bd20).
# Fields come from tools/raf_cpnames.py; the reference is where FUN_004701a0 or a getter stores
# the value into the EEComputerPlayer object.
PARAMS = {
    1:   ("int",   ("v4", "v7"), "AttackDelayStarting min/max -> obj+0x1288/0x128c"),
    5:   ("int",   ("v4", "v7", "v12"), "ShipsToMaintain E/M/H, getters 0046e390/e3d0/e410 -> +0x1214..0x121c"),
    6:   ("int",   ("v4", "v7"), "AttackFrequencyStarting min/max -> +0x125c/0x1260"),
    20:  ("float", ("v12",), "MaxMilitaryUnitsOnDefensePercent, FUN_0046bd20 -> +0x118c"),
    30:  ("int",   ("v4", "v12"), "Barracks target/max, getters 0046d3b0/d8b0 -> +0x13b8/0x1300"),
    31:  ("int",   ("v4", "v12"), "ArcheryRange target/max, getters 0046d430/d840 -> +0x13b4/0x12fc"),
    32:  ("int",   ("v4", "v12"), "Stable target/max, getters 0046d470/d920 -> +0x13e0/0x1328"),
    33:  ("int",   ("v4", "v12"), "Dock target/max, getters 0046d4b0/d990 -> +0x13c0/0x1308"),
    35:  ("int",   ("v4", "v12"), "NavalYard target/max, getters 0046d530/da70 -> +0x13d8/0x1320"),
    38:  ("int",   ("v4", "v12"), "University target/max, getters 0046d5f0/dbc0 -> +0x13f0/0x1338"),
    39:  ("int",   ("v4", "v12"), "Temple target/max, getters 0046d630/dc30 -> +0x13e8/0x1330"),
    40:  ("int",   ("v4", "v12"), "AICivSpecialBuildings target/max, getters 0046d670/dca0 -> +0x13c8/0x1310"),
    45:  ("float", ("v12",), "AttackGroupSizePercentage, FUN_0046bd20 -> +0x1124"),
    55:  ("int",   ("v4",), "SpendingLevelEpochBuildings, getter 0046e660 -> +0x1390"),
    57:  ("int",   ("v4",), "SpendingLevelTechResearch, getter 0046e6e0 -> +0x13a4"),
    59:  ("int",   ("v4",), "SpendingLevelPopulationBuildings, getter 0046e760 -> +0x139c"),
    60:  ("int",   ("v4",), "SpendingLevelStandingArmy, getter 0046e7a0 -> +0x13a0"),
    61:  ("int",   ("v4",), "SpendingLevelGuardTroops, getter 0046e7e0 -> +0x1398"),
    63:  ("int",   ("v4",), "SpendingLevelTroopImprovements, getter 0046e860 -> +0x13a8"),
    87:  ("int",   ("v4", "v7"), "DefenseForce min/max -> +0x12b0/0x12b4"),
    88:  ("int",   ("v4", "v7", "v12"), "DefenseTimer E/M/H minutes, getters 0046f310/f350/f390 -> +0x1414..0x141c"),
    99:  ("int",   ("v4",), "SettlementUpgradeInterval -> +0x1378"),
    100: ("int",   ("v4",), "TownCenterUpgradeInterval, getter 0046f6a0 -> +0x13f4"),
    108: ("int",   ("v4", "v12"), "TankFactory target/max, getters 0046d790/de30 -> +0x13e4/0x132c"),
    118: ("int",   ("v4",), "NavalMaintenanceTimer, getter 0046e260 -> +0x1220"),
}
# Easy/Medium/Hard triplets (value rises / falls from Easy to Hard). A personality may only make a
# triplet WEAKER than stock (Hard ceiling), by at most TRIPLET_TOLERANCE; Easy -> Hard order must survive.
TRIPLETS = {5: "higher", 88: "lower"}

# civ -> [(behavior id, "mult" | "set", value, why)]
PERSONALITIES = {
    "persia": [
        (1, "mult", 0.8, "first attack 20% sooner"),
        (6, "mult", 0.8, "attacks come 20% closer together early on"),
        (45, "mult", 1.25, "bigger attack groups"),
        (60, "mult", 1.15, "more weight on the standing army"),
        (57, "mult", 0.85, "less weight on tech research"),
        (32, "mult", 1.2, "more stables (cavalry)"),
        (87, "mult", 0.8, "smaller defence force"),
        (20, "mult", 0.8, "fewer units held back on defence"),
        (88, "mult", 1.2, "slower reaction to raids"),
        (33, "mult", 0.8, "fewer docks"),
        (5, "mult", 0.8, "smaller standing fleet"),
    ],
    "egypt": [
        (1, "mult", 1.2, "first attack 20% later"),
        (45, "mult", 1.1, "somewhat bigger attack groups when it does attack"),
        (87, "mult", 1.2, "bigger defence force"),
        (20, "mult", 1.25, "more units held back on defence"),
        (61, "mult", 1.2, "more weight on guard troops"),
        (38, "mult", 1.15, "more universities"),
        (39, "mult", 1.2, "more temples"),
        (59, "mult", 1.1, "more weight on population buildings (economy)"),
        (57, "mult", 1.15, "more weight on tech research"),
        (60, "mult", 0.9, "less weight on the standing army"),
    ],
    "greece": [
        (33, "mult", 1.2, "more docks"),
        (35, "mult", 1.2, "more naval yards"),
        (118, "mult", 0.75, "fleet maintenance checked more often"),
        (40, "set", 2.0, "two special buildings (Spartan Academy) instead of one"),
        (30, "mult", 1.15, "more barracks (hoplites)"),
        (57, "mult", 1.1, "more weight on tech research"),
        (38, "mult", 1.15, "more universities"),
        (45, "mult", 0.9, "slightly smaller attack groups"),
    ],
    "rome": [
        (30, "mult", 1.2, "more barracks"),
        (31, "mult", 1.15, "more archery ranges"),
        (108, "mult", 1.2, "more tank factories"),
        (60, "mult", 1.1, "more weight on the standing army"),
        (63, "mult", 1.2, "more weight on troop improvements"),
        (99, "mult", 0.8, "settlements upgraded sooner"),
        (100, "mult", 0.8, "town centre upgraded sooner"),
        (5, "mult", 0.85, "slightly smaller standing fleet"),
    ],
}

MAX_REL_CHANGE = 0.25      # a multiplier stays within [0.75, 1.25]
TRIPLET_TOLERANCE = 0.25   # a triplet value may get weaker than stock by this much


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def apply_override(base, mult: float, setv: float, kind: str):
    """What FUN_0046bd20 (float) / FUN_00468130 (int) return for one stored value."""
    if mult == 1.0 and setv == -1.0:
        return float(base) if kind == "float" else int(base)
    v = base * f32(mult) if setv == -1.0 else f32(setv)
    if kind == "float":
        return f32(v)
    if abs(abs(v - int(v)) - 0.5) < 0.04:
        raise ValueError("value %.4f sits on a rounding tie, pick another multiplier" % v)
    return int(round(v))


def personality_rows() -> dict:
    """{behavior id: {civ: (mult, set)}} from PERSONALITIES."""
    rows = {}
    for civ, items in PERSONALITIES.items():
        seen = set()
        for bid, kind, val, _why in items:
            if bid in seen:
                sys.exit("%s lists behavior %d twice" % (civ, bid))
            seen.add(bid)
            if bid not in PARAMS:
                sys.exit("behavior %d is not a verified live parameter" % bid)
            rows.setdefault(bid, {})[civ] = (val, -1.0) if kind == "mult" else (1.0, val)
    return rows


def effective(cp_rows: dict, rows: dict, hard_edits: bool) -> list:
    """Every effective value as (bid, civ, field, stock, effective); sys.exit on a rule break.

    cp_rows holds the stock dbcpbehavior rows. With hard_edits the EDITS are applied first (the
    personalities multiply the tuned Hard values in that case).
    """
    report = []
    for bid in sorted(rows):
        kind, fields, _ref = PARAMS[bid]
        stock = {f: cp_rows[bid][f] for f in fields}
        if hard_edits:
            for rid, field, _old, new, _w in EDITS:
                if rid == bid and field in stock:
                    stock[field] = new
        for civ, (m, s) in rows[bid].items():
            if s == -1.0 and (m <= 0 or abs(m - 1.0) > MAX_REL_CHANGE + 1e-9):
                sys.exit("behavior %d %s: multiplier %.2f outside +-%d%%" % (bid, civ, m, MAX_REL_CHANGE * 100))
            eff = {f: apply_override(stock[f], m, s, kind) for f in fields}
            for f in fields:
                if eff[f] < 0 <= stock[f]:
                    sys.exit("behavior %d %s %s turned negative" % (bid, civ, f))
                if kind == "int" and stock[f] >= 1 and eff[f] < 1:
                    sys.exit("behavior %d %s %s dropped to zero" % (bid, civ, f))
                if bid not in TRIPLETS and abs(eff[f] - stock[f]) > max(1, MAX_REL_CHANGE * abs(stock[f])) + 1e-6:
                    sys.exit("behavior %d %s %s moved too far: %s -> %s" % (bid, civ, f, stock[f], eff[f]))
            if bid in TRIPLETS:
                e, md, h = eff["v4"], eff["v7"], eff["v12"]
                strong_high = TRIPLETS[bid] == "higher"
                if not (e <= md <= h if strong_high else e >= md >= h):
                    sys.exit("behavior %d %s: Easy/Medium/Hard order broken: %s" % (bid, civ, (e, md, h)))
                for f in fields:
                    if (eff[f] > stock[f]) if strong_high else (eff[f] < stock[f]):
                        sys.exit("behavior %d %s %s: stronger than stock (%s -> %s); triplets may only get weaker"
                                 % (bid, civ, f, stock[f], eff[f]))
                    if abs(eff[f] - stock[f]) > max(1, TRIPLET_TOLERANCE * abs(stock[f])) + 1e-6:
                        sys.exit("behavior %d %s %s moved too far: %s -> %s" % (bid, civ, f, stock[f], eff[f]))
            for f in fields:
                report.append((bid, civ, f, stock[f], round(eff[f], 4) if kind == "float" else eff[f]))
    return report


def byte_diff(a: bytes, b: bytes) -> list:
    """[(start, end)] runs of differing bytes over the common length."""
    runs, start = [], None
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, min(len(a), len(b))))
    return runs


def make_civspecai(data: bytes, cp_rows: dict, hard_edits: bool):
    """Stock dbcivspecai bytes -> (new bytes, effective-value report). Exits on any failed check."""
    obj = unpack_bytes("dbcivspecai", data)
    if pack_obj(obj) != data:
        sys.exit("dbcivspecai does not round trip through raf_data")
    recs = obj["records"]
    ids = [r["behavior_id"] for r in recs]
    if ids != [-1, 44]:
        sys.exit("dbcivspecai stock records are %s, expected [-1, 44] (different game version?)" % ids)
    for r in recs:
        for civ in CIVS:
            if r[civ + "_mult"] != 1.0 or r[civ + "_set"] != -1.0:
                sys.exit("stock dbcivspecai record %d is not neutral" % r["behavior_id"])

    rows = personality_rows()
    if 44 in rows or -1 in rows:
        sys.exit("personalities must not use the stock record ids")
    report = effective(cp_rows, rows, hard_edits)

    template = recs[1]  # the clean stock record (id 44); record 0 holds editor memory garbage
    for bid in sorted(rows):
        rec = copy.deepcopy(template)
        rec["behavior_id"] = bid
        for civ, (m, s) in rows[bid].items():
            rec[civ + "_mult"] = m
            rec[civ + "_set"] = s
        recs.append(rec)
    out = pack_obj(obj)

    # proof 1: round trip through raf_data
    again = unpack_bytes("dbcivspecai", out)
    if pack_obj(again) != out or [r["behavior_id"] for r in again["records"]] != [-1, 44] + sorted(rows):
        sys.exit("generated dbcivspecai does not round trip")
    # proof 2: only intended bytes changed
    size = 196
    if out[4:4 + 2 * size] != data[4:4 + 2 * size]:
        sys.exit("the two stock records changed")
    if struct.unpack_from("<I", out, 0)[0] != 2 + len(rows) or len(out) != 4 + (2 + len(rows)) * size:
        sys.exit("count/size wrong")
    tmpl = out[4 + size:4 + 2 * size]
    changed = 0
    for i, bid in enumerate(sorted(rows)):
        chunk = out[4 + (2 + i) * size:4 + (3 + i) * size]
        runs = byte_diff(tmpl, chunk)
        for a, b in runs:
            if not (0x6c <= a and b <= 0xb0):
                sys.exit("record %d differs outside behavior_id and the civ pairs: %d..%d" % (bid, a, b))
        changed += sum(b - a for a, b in runs)
    print("dbcivspecai: %d stock bytes -> %d bytes; count 2 -> %d; the 2 stock records are byte-identical;"
          " %d new records differ from the clean stock record only inside 0x6c..0xb0 (%d bytes)"
          % (len(data), len(out), 2 + len(rows), len(rows), changed))
    return out, report


def print_report(report: list) -> None:
    print("behavior civ     field  stock -> effective")
    for bid, civ, f, old, new in report:
        print("  %3d  %-7s %-4s %8s -> %s" % (bid, civ, f, old, new))


def build(game: Path, overlay: Path, personalities: bool = False) -> None:
    src = game / DB
    data = src.read_bytes()
    obj = unpack_bytes("dbcpbehavior", data)
    if pack_obj(obj) != data:
        sys.exit("dbcpbehavior does not round trip through raf_data")
    rows = {r["id"]: r for r in obj["records"]}
    stock_rows = {k: dict(v) for k, v in rows.items()}
    for rid, field, old, new, why in EDITS:
        cur = rows[rid][field]
        if cur != old:
            sys.exit(f"row {rid} {field}: expected {old}, found {cur} (different game version?)")
        rows[rid][field] = new
        print(f"row {rid:3d} {field}: {old} -> {new}  ({why})")

    out = overlay / DB
    out.parent.mkdir(parents=True, exist_ok=True)
    packed = pack_obj(obj)
    runs = byte_diff(data, packed)
    if len(packed) != len(data) or len(runs) != len(EDITS):
        sys.exit("dbcpbehavior: unexpected byte diff %s" % runs)
    out.write_bytes(packed)
    print("dbcpbehavior: %d bytes, %d changed runs (%d bytes) for %d edits" %
          (len(packed), len(runs), sum(b - a for a, b in runs), len(EDITS)))

    files = {DB.as_posix(): {"source_sha256": hashlib.sha256(data).hexdigest()}}
    step = "ai-hard"
    civ_out = overlay / DB_CIV
    if personalities:
        civ_data = (game / DB_CIV).read_bytes()
        new, report = make_civspecai(civ_data, stock_rows, hard_edits=True)
        print_report(report)
        civ_out.write_bytes(new)
        files[DB_CIV.as_posix()] = {"source_sha256": hashlib.sha256(civ_data).hexdigest(),
                                    "output_sha256": hashlib.sha256(new).hexdigest()}
        step = "ai-hard+personalities"
        print(f"wrote {civ_out}")
    elif civ_out.exists():
        civ_out.unlink()  # stale file from an earlier --personalities run
        print(f"removed stale {civ_out}")
    (overlay / "manifest.json").write_text(json.dumps({"step": step, "files": files}, indent=2))
    print(f"wrote {out}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 2 or not flags <= {"--personalities"}:
        sys.exit(__doc__)
    build(Path(args[0]), Path(args[1]), "--personalities" in flags)


if __name__ == "__main__":
    main()
