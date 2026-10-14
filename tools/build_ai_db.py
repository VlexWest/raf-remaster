"""Build the tuned skirmish AI table (dbcpbehavior.dat) into an overlay.

Usage:
    python tools/build_ai_db.py <game_dir> <overlay_dir>

Only the Hard difficulty is changed (Easy and Medium stay stock), and no resource cheats are
added: the AI attacks earlier, more often and with bigger groups, rebuilds defence faster and
advances epochs sooner. Each edit checks the stock value first, so a different game version
fails loudly instead of being half patched.

The skirmish AI runs inside the lockstep simulation, so every player in a multiplayer game
needs the same file (same remaster version).
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raf_data import pack_obj, unpack_bytes  # noqa: E402

DB = Path("Data") / "db" / "dbcpbehavior.dat"

# (row id, field, stock value, new value, why)
EDITS = [
    (2, "v7", 15, 10, "AttackDelayLevelOfDifficultyHardModifier: first attack sooner"),
    (7, "v7", 30, 20, "AttackFrequencyLevelOfDifficultyHardModifier: attacks more often"),
    (11, "v12", 200.0, 300.0, "AttackGroupSizeLevelOfDifficultyHardModifier: bigger attack waves"),
    (29, "v7", 60, 45, "EpochAdvanceFrequencyLevelOfDifficultyHardModifier: advances epochs sooner"),
    (88, "v12", 4.0, 2.0, "DefenseTimerHard (minutes): reacts to raids faster"),
    (104, "v4", 2, 3, "MilitaryBuildingBonusHard: one more military building"),
]


def build(game: Path, overlay: Path) -> None:
    src = game / DB
    data = src.read_bytes()
    obj = unpack_bytes("dbcpbehavior", data)
    rows = {r["id"]: r for r in obj["records"]}
    for rid, field, old, new, why in EDITS:
        cur = rows[rid][field]
        if cur != old:
            sys.exit(f"row {rid} {field}: expected {old}, found {cur} (different game version?)")
        rows[rid][field] = new
        print(f"row {rid:3d} {field}: {old} -> {new}  ({why})")

    out = overlay / DB
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pack_obj(obj))
    manifest = {
        "step": "ai-hard",
        "files": {DB.as_posix(): {"source_sha256": hashlib.sha256(data).hexdigest()}},
    }
    (overlay / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {out}")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    build(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
