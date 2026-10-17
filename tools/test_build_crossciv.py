"""Offline checks for build_crossciv.py against the stock dbtechtree/dbobjects (read-only).

    python tools/test_build_crossciv.py [game_dir]
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_crossciv as bc  # noqa: E402
import raf_data  # noqa: E402

GAME = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\Games\Rise and Fall")

# civ -> (barracks, the building its archers come from, stables), SP + MP
BUILDINGS = {
    "Greek": ((2501, 193), (2501, 193), (2502, 488)),
    "Persian": ((2514, 485), (388, 2726), (2515, 489)),
    "Rome": ((984, 486), (984, 486), (986, 490)),
    "Egypt": ((2666, 484), (377, 2729), (2480, 487)),
}
CIV_ID = {name: civ for civ, name in bc.CIVS.items()}


def expect_error(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return
    raise AssertionError("no error")


def flat(data):
    groups, trailing = bc.parse_techtree(data)
    return [nd for g in groups for nd in g], groups, trailing


def main():
    stock = (GAME / bc.TECHTREE).read_bytes()
    objects = (GAME / bc.OBJECTS).read_bytes()
    names = bc.object_names(objects)
    new, rep = bc.patch(stock, objects)
    assert bc.patch(stock, objects)[0] == new, "not deterministic"

    old_nodes, old_groups, old_tr = flat(stock)
    new_nodes, new_groups, new_tr = flat(new)
    # same tree shape, same record count
    assert [len(g) for g in old_groups] == [len(g) for g in new_groups] and old_tr == new_tr
    assert len(new_nodes) == bc.STOCK_NODES

    # only list_a of military unit nodes changes (appended military buildings) plus the slot of
    # the reported families
    mil = {id(nd): key for nd, key in bc.military_nodes(old_nodes, names)}
    moved = {(cls, civ): s for (cls, civ), s in rep["moved"].items()}
    assert moved == {("Arc", "Persian"): (7, 10), ("Arc", "Egypt"): (7, 11)}, moved
    n_list = n_slot = 0
    for o, n in zip(old_nodes, new_nodes):
        assert o.list_b == n.list_b
        if o.list_a != n.list_a:
            assert id(o) in mil, names[o.i32(bc.OFF_OBJ)]
            assert n.list_a[:len(o.list_a)] == o.list_a
            extra = n.list_a[len(o.list_a):]
            assert extra == sorted(extra) and set(extra) <= bc.MILITARY_BUILDINGS and not set(extra) & set(o.list_a)
            n_list += 1
        diff = [i for i in range(bc.NODE) if o.raw[i] != n.raw[i]]
        if diff:
            key = mil.get(id(o))
            assert key and (key[0], key[3]) in moved, names[o.i32(bc.OFF_OBJ)]
            civ = CIV_ID[key[3]]
            off = bc.OFF_SLOT + 8 * civ
            assert all(off <= i < off + 4 for i in diff), diff
            assert (o.slot(civ), n.slot(civ)) == moved[key[0], key[3]]
            n_slot += 1
    assert n_list == len(rep["added"]) == 40 and n_slot == 10, (n_list, n_slot)

    # every civ's archer / spear / sword / cavalry L1-5 trains in every civ's equivalent building
    units = {}
    for nd, (cls, sub, lvl, civ) in bc.military_nodes(new_nodes, names):
        units.setdefault((civ, cls, "Spear" if sub.startswith("Spear Inf") else sub), {})[lvl] = nd
    for civ in BUILDINGS:
        for (ucls, usub), kind in ((("Inf", "Spear"), 0), (("Inf", "Sword Infantry"), 0), (("Arc", "Archer"), 1),
                                   (("Cav", None), 2)):
            if usub is None:
                lines = {lvl: nd for (c, cl, _s), lv in units.items() if c == civ and cl == ucls
                         for lvl, nd in lv.items() if "Elephant" not in _s}
            else:
                lines = units[civ, ucls, usub]
            assert sorted(lines) == [1, 2, 3, 4, 5], (civ, ucls, usub, sorted(lines))
            for other, blds in BUILDINGS.items():
                for b in blds[kind]:
                    for lvl, nd in lines.items():
                        assert b in nd.list_a, (civ, ucls, usub, lvl, other, b)

    # no two unit lines of one civ share a slot in a building they were added to
    for civ in bc.CIVS:
        for b in bc.MILITARY_BUILDINGS:
            seen = {}
            for nd, key in bc.military_nodes(new_nodes, names):
                if nd.raw[bc.OFF_CIV_FLAG + civ] and b in nd.list_a and nd.slot(civ) >= 0:
                    seen.setdefault(nd.slot(civ), set()).add((key[0], key[1] if key[0] != "Cav" else ""))
            clash = {s: f for s, f in seen.items() if len(f) > 1}
            assert not clash, (civ, b, clash)

    # raf_data round trip of the new file; list_a edits read back
    obj = json.loads(json.dumps(raf_data.unpack_bytes("dbtechtree", new), ensure_ascii=False))
    assert raf_data.pack_obj(obj) == new
    rome_arc = next(k for r in obj["roots"] for k in [r] + r["children"] if k["tech_id"] == 6152)
    assert {2501, 193, 388, 2726, 377, 2729} <= set(rome_arc["list_a"])

    # refusals: not stock, wrong layout
    expect_error(bc.patch, new, objects)
    expect_error(bc.patch, stock, objects[:-1])
    added = sum(len(v) for v in rep["added"].values())
    print(f"test_build_crossciv: OK ({n_list} unit nodes +{added} buildings, {n_slot} slot moves, "
          f"{len(new) - len(stock)} bytes larger)")


if __name__ == "__main__":
    main()
