"""Let every civilization train its soldiers in the military buildings of the other civilizations.

Usage:
    python tools/build_crossciv.py <game_dir> <overlay_dir>

Why: a player who gets a foreign building (Co-op Roles hand-over, captured buildings) can only
train the units whose dbtechtree node lists that building. Stock lists every barracks in the
sword nodes and every stable in the cavalry nodes, but archers and spearmen only list their
own civ's barracks or archery range (Rome Archer L1, tech 6152: barracks 984, 486).

What the exe does with a node (child loader FUN_008e5550, see docs/crossciv.md):
- list_a (u32 n + i32[n]) = the dbobjects ids of the buildings that produce it; one cost entry
  per building (FUN_008def40), cost multiplier 1.0 from the 6th entry on (we only append).
- bytes 0x140 + civ = "available to civ"; i32 pairs at 0x144 + 8*civ = button slot override per
  civ (first value; -1 = the button's default). The slot is per civ, not per building.

Rule: for each trainable military unit node (object name matches MILITARY_RE, not Spawned or
Building Defender, stock list_a holds a military building) list_a |= the military buildings of
all nodes of the same class + sub-type + level (e.g. Arc "Archer" level 1 of all four civs).
Persian and Egyptian archers sit on slot 7, which is the sword slot in the barracks they now
appear in; such a unit family moves to the lowest slot of the same button row (7..12) that no
other unit family of that civ uses in any of its buildings. Nothing else changes.
Gameplay data: all players need the same overlay.
"""

import argparse
import hashlib
import re
import struct
import sys
from pathlib import Path

DB = Path("Data") / "db"
TECHTREE, OBJECTS = DB / "dbtechtree.dat", DB / "dbobjects.dat"
ROOTS, NODE, OBJ_REC = 14, 452, 2012
STOCK_NODES, STOCK_OBJECTS = 2632, 3079
OFF_TECH, OFF_OBJ = 0x68, 0xa4
OFF_CIV_FLAG, OFF_SLOT = 0x140, 0x144     # byte 0x140 + civ, i32 pair 0x144 + 8 * civ
CIVS = {3: "Greek", 4: "Persian", 5: "Rome", 10: "Egypt"}
SLOT_ROW = range(7, 13)                   # FUN_008e5550 maps slots 7..12 to the same row bit

# barracks, archery ranges, stables (SP + MP) of the four civs
MILITARY_BUILDINGS = frozenset([52, 74, 193, 227, 228, 377, 388, 484, 485, 486, 487, 488, 489, 490, 984, 986,
                                2480, 2501, 2502, 2514, 2515, 2666, 2723, 2726, 2729, 2732, 2888])
# same pattern as build_coop.MILITARY_RE; level and civ from the name
MILITARY_RE = re.compile(r'^A - (Inf|Arc|Cav)(0[1-5])[a-z]? - (.*) \([Ll]evel (\d) (Greek|Persian|Rome|Egypt)\)$')


class Node:
    def __init__(self, raw, list_a, list_b):
        self.raw, self.list_a, self.list_b = bytearray(raw), list(list_a), list(list_b)

    def i32(self, off):
        return struct.unpack_from("<i", self.raw, off)[0]

    def slot(self, civ):
        return self.i32(OFF_SLOT + 8 * civ)


def _ints(data, p):
    n = struct.unpack_from("<I", data, p)[0]
    return list(struct.unpack_from(f"<{n}i", data, p + 4)), p + 4 + 4 * n


def parse_techtree(data):
    """[(child count, [root, *children])] and the trailing bytes."""
    groups, p = [], 0
    for _ in range(ROOTS):
        n = struct.unpack_from("<I", data, p)[0]
        p += 4
        nodes = []
        for _ in range(n + 1):
            raw = data[p:p + NODE]
            a, p = _ints(data, p + NODE)
            b, p = _ints(data, p)
            nodes.append(Node(raw, a, b))
        groups.append(nodes)
    return groups, data[p:]


def pack_techtree(groups, trailing):
    out = bytearray()
    for nodes in groups:
        out += struct.pack("<I", len(nodes) - 1)
        for nd in nodes:
            out += nd.raw
            for lst in (nd.list_a, nd.list_b):
                out += struct.pack(f"<I{len(lst)}i", len(lst), *lst)
    return bytes(out + trailing)


def object_names(data):
    count = struct.unpack_from("<I", data, 0)[0]
    if count != STOCK_OBJECTS or len(data) != 4 + count * OBJ_REC:
        raise ValueError(f"dbobjects.dat: count {count}, size {len(data)}; not the 1.15 layout")
    return [data[4 + i * OBJ_REC:4 + i * OBJ_REC + 100].split(b"\0", 1)[0].decode("cp1252", "replace")
            for i in range(count)]


def unit_key(name):
    """(class, sub-type, level, civ) of a trainable military unit name, else None."""
    m = MILITARY_RE.match(name)
    if not m or "Building Defender" in name or "Spawned" in name:
        return None
    return m.group(1), m.group(3), int(m.group(4)), m.group(5)


def military_nodes(nodes, names):
    """[(node, key)] of the trainable military unit nodes."""
    out = []
    for nd in nodes:
        oi = nd.i32(OFF_OBJ)
        key = unit_key(names[oi]) if 0 <= oi < len(names) else None
        if key and MILITARY_BUILDINGS & set(nd.list_a):
            out.append((nd, key))
    return out


def family(nd, key_of, civ):
    """Nodes sharing a button: the levels of one unit line (same class, civ and stock slot; Persian
    cavalry switches between spear and sword by level on one slot)."""
    k = key_of.get(id(nd))
    return ("unit", k[0], civ, nd.slot(civ)) if k else ("node", nd.i32(OFF_TECH), id(nd))


def patch(techtree: bytes, objects: bytes):
    """Return (new dbtechtree bytes, report dict)."""
    groups, trailing = parse_techtree(techtree)
    nodes = [nd for g in groups for nd in g]
    if len(nodes) != STOCK_NODES:
        raise ValueError(f"dbtechtree.dat: {len(nodes)} nodes, expected {STOCK_NODES}; not the 1.15 layout")
    if pack_techtree(groups, trailing) != techtree:
        raise AssertionError("dbtechtree.dat does not round-trip")
    names = object_names(objects)
    mil = military_nodes(nodes, names)
    key_of = {id(nd): key for nd, key in mil}
    union = {}
    for nd, (cls, sub, lvl, _civ) in mil:
        union.setdefault((cls, sub, lvl), set()).update(MILITARY_BUILDINGS & set(nd.list_a))
    added, new_of = {}, {}
    for nd, (cls, sub, lvl, _civ) in mil:
        new = sorted(union[cls, sub, lvl] - set(nd.list_a))
        if new:
            nd.list_a += new
            added[nd.i32(OFF_TECH)] = new_of[id(nd)] = new
    if not added:
        raise ValueError("dbtechtree.dat: every unit already trains in every building; not the stock file")
    moved = _fix_slots(nodes, key_of, new_of)
    out = pack_techtree(groups, trailing)
    if len(out) != len(techtree) + 4 * sum(len(v) for v in added.values()):
        raise AssertionError("unexpected size change")
    return out, {"added": added, "moved": moved, "units": len(mil)}


def _fix_slots(nodes, key_of, new_of):
    """Move unit families whose slot collides with another family of the same civ in a building
    they were added to, to a slot of the same row no other family of that civ uses (stock
    collisions stay as they are).
    Returns {(class, civ name): (old slot, new slot)}."""
    moved = {}
    for civ in CIVS:
        fams = {}
        for nd in nodes:
            if nd.raw[OFF_CIV_FLAG + civ] and nd.slot(civ) >= 0 and MILITARY_BUILDINGS & set(nd.list_a):
                fams.setdefault(family(nd, key_of, civ), []).append(nd)
        for fam in sorted((f for f in fams if f[0] == "unit"), key=str):
            members, slot = fams[fam], fam[3]
            others = [nd for f, ns in fams.items() if f != fam for nd in ns]
            blds = {b for nd in members for b in new_of.get(id(nd), ())}
            if not any(nd.slot(civ) == slot and blds & set(nd.list_a) for nd in others):
                continue
            free = [s for s in SLOT_ROW if all(nd.slot(civ) != s for nd in others)]
            if not free:
                raise ValueError(f"{fam}: no free slot in {list(SLOT_ROW)} for civ {civ}")
            for nd in members:
                struct.pack_into("<i", nd.raw, OFF_SLOT + 8 * civ, free[0])
            moved[fam[1], CIVS[civ]] = (slot, free[0])
    return moved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("overlay_dir", type=Path)
    a = ap.parse_args(argv)
    stock = (a.game_dir / TECHTREE).read_bytes()
    new, rep = patch(stock, (a.game_dir / OBJECTS).read_bytes())
    dst = a.overlay_dir / TECHTREE
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(new)
    moved = ", ".join(f"{civ} {cls} slot {o}->{n}" for (cls, civ), (o, n) in sorted(rep["moved"].items()))
    print(f"dbtechtree.dat: {len(rep['added'])} of {rep['units']} unit nodes get foreign buildings "
          f"(+{sum(len(v) for v in rep['added'].values())} list entries); {moved or 'no slot moves'}; "
          f"stock {hashlib.sha256(stock).hexdigest()[:12]} -> {hashlib.sha256(new).hexdigest()[:12]}; {dst}")


if __name__ == "__main__":
    sys.exit(main())
