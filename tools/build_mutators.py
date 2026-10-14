"""Build "mutators" (optional rule packs) for Rise and Fall as db overlays.

Usage:
    python tools/build_mutators.py <game_dir> <overlay_root> <mutator|all|a+b> [--combine]

    mutator   blitzkrieg | poverty | titans | glasscannon | naval
    all       build every mutator, each into its own folder
    a+b       build one overlay with several mutators; refused unless --combine is given,
              and refused whatever the flag if two of them touch the same field of the same record

Output: <overlay_root>/<mutator>/Data/db/<changed tables>.dat and <overlay_root>/<mutator>/manifest.json
(game files are only read, never written).

A mutator is pure data: a list of (table, record, field, stock value, new value) edits that are
derived from the user's own install at build time. New values are computed from the stock value
with an exact multiplier (rational arithmetic, round half up), so the build is deterministic and
the same for every player. Records are found by name and id, never by position. Every edit checks
the stock value; a different game version fails loudly. After building, the tool re-reads the
packed bytes and proves that exactly the edited fields changed and nothing else.

Every player in a multiplayer game must use the same mutator (lockstep simulation). The AI is
affected the same way as a human player (same tables).
"""

import hashlib
import json
import re
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raf_data import pack_obj, unpack_bytes  # noqa: E402

DB_DIR = Path("Data") / "db"
OBJECTS, TECHTREE = "dbobjects", "dbtechtree"
VERSION = 1

# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def S(v):
    """A string field may be a plain str or {'s': text, 'tail': hex} (garbage after the NUL)."""
    return v["s"] if isinstance(v, dict) else v


def f32(x):
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def scale(value, mult):
    """round_half_up(value * mult) with exact arithmetic; value int or float, mult Fraction."""
    x = Fraction(value) * mult
    return int((x + Fraction(1, 2)).__floor__())


def sha(data):
    return hashlib.sha256(data).hexdigest()


JUNK = re.compile(r"Cinematic|\(Test\)|\bTest\b|XXX|zzz|Scenario|Wreck|Height|Boulder|GREG|TBD|\(Low|"
                  r"UberShip|No Sail|No Rowers|Worker|General|Drummer|Sailor|Envoy|Prisoner|Disabled|Ptolemy|Admiral", re.I)
ARMY_RE = re.compile(r"^A - (Inf0[0-5]|Arc0[0-5]|Cav0[0-5]|Siege0[0-3])")
HERO_RE = re.compile(r"^A - (Inf00|Arc00) - ")
SHIP_RE = re.compile(r"^A - s0\d")
LANDMIL_RE = re.compile(r"^A - b  (Barracks|Archery Range|Stable|Assyrian Stable|Spartan Academy|"
                        r"Gladiator Coliseum|Building Siege)")
EPOCH_TECH_RE = re.compile(r"^A - ACTION - LEVEL (0[2-9]|10) \(Epoch tech\)$")
ARMY_BEHAVIORS = {"Land Patrolling", "Horse Archer", "Naval Onager"}
COST_FIELDS = ("cost_0x7c", "cost_0x80", "cost_0x84", "cost_0x88", "cost_0x8c")
# rec 0x74 holds an event id (e.g. 6 = "A-Hero Level 2 Research", 739 = "Q Hunting Gather Rate +15%")
# and 0x78 is -1/0 in the whole file, so neither is treated as a cost.
GATHER_FIELDS = ("work_rate", "f_0x138", "x_0x13c", "f_0x140", "f_0x144", "f_0x148", "f_0x14c", "f_0x150")


class Edit:
    __slots__ = ("table", "key", "field", "old", "new", "group", "path")

    def __init__(self, table, key, field, old, new, group, path):
        self.table, self.key, self.field, self.old, self.new = table, key, field, old, new
        self.group, self.path = group, path

    def ident(self):
        return (self.table, self.key, self.field)

    def as_json(self):
        return {"table": self.table, "record": self.key, "field": self.field, "old": self.old,
                "new": self.new, "group": self.group}


class Game:
    """Unpacked stock tables plus lookup indexes."""

    def __init__(self, game_dir):
        self.dir = Path(game_dir) / DB_DIR
        self.raw, self.obj = {}, {}
        for t in (OBJECTS, TECHTREE):
            data = (self.dir / (t + ".dat")).read_bytes()
            o = unpack_bytes(t, data)
            if pack_obj(o) != data:
                sys.exit("%s does not round trip through raf_data" % t)
            self.raw[t], self.obj[t] = data, o
        self.R = self.obj[OBJECTS]["records"]
        # 916 placeholder records carry object_id -1; every record a mutator touches must equal its index
        # tech tree nodes: (record path, node dict, root name)
        self.nodes, self.node_keys = [], {}
        for ri, root in enumerate(self.obj[TECHTREE]["roots"]):
            self.nodes.append((("root", ri), root, S(root["name"]), True))
            for ci, ch in enumerate(root["children"]):
                self.nodes.append((("child", ri, ci), ch, S(root["name"]), False))
        counts = {}
        for path, n, rootname, is_root in self.nodes:
            k = self.node_key(n, rootname, is_root)
            counts[k] = counts.get(k, 0) + 1
        self.dupe_node_keys = {k for k, c in counts.items() if c > 1}
        self.tree_objs = {n["object_index"] for _, n, _, is_root in self.nodes if not is_root}

    @staticmethod
    def node_key(n, rootname, is_root):
        if is_root:
            return "tech:%s|<epoch root>" % rootname
        return "tech:%s|%s|obj%d|id%d" % (rootname, S(n["name"]), n["object_index"], n["tech_id"])

    def obj_key(self, i):
        if self.R[i]["object_id"] != i:
            sys.exit("dbobjects record %d has object_id %d, refusing to edit it" % (i, self.R[i]["object_id"]))
        return "obj:%d|%s" % (i, S(self.R[i]["name"]))

    def name(self, i):
        return S(self.R[i]["name"])

    def beh(self, i):
        return S(self.R[i]["behavior"])

    # ---- object sets (indices into dbobjects) ----
    def army(self):
        out = []
        for i, r in enumerate(self.R):
            n = self.name(i)
            if (ARMY_RE.match(n) and not JUNK.search(n) and self.beh(i) in ARMY_BEHAVIORS
                    and r["hit_points"] > 0 and r["attack"] > 0 and i in self.tree_objs):
                out.append(i)
        return out

    def heroes(self):
        return [i for i in self.army() if HERO_RE.match(self.name(i))]

    def ships(self):
        out = []
        for i, r in enumerate(self.R):
            n = self.name(i)
            if (SHIP_RE.match(n) and not JUNK.search(n) and self.beh(i) == "Sea Patrolling"
                    and r["hit_points"] > 0 and i in self.tree_objs):
                out.append(i)
        return out

    def naval_onagers(self):
        return [i for i, r in enumerate(self.R)
                if "Naval Onager" in self.name(i) and self.beh(i) == "Naval Onager" and not JUNK.search(self.name(i))
                and r["hit_points"] > 0 and i in self.tree_objs]

    def citizens(self):
        return [i for i, r in enumerate(self.R)
                if self.beh(i) in ("Citizen", "Civilian") and any(
                    self.gather_value(r, f) for f in GATHER_FIELDS)]

    @staticmethod
    def gather_value(r, field):
        if field.startswith("x_"):
            f = struct.unpack("<f", bytes.fromhex(r[field]))[0]
            return f if f == f and 1 <= abs(f) <= 100000 and f == int(f) else 0
        return r[field]

    def deposits(self):
        """Resource nodes that run dry: trees, stone, MP gold, forage, huntables (not farms, not SP gold)."""
        out = []
        for i, r in enumerate(self.R):
            n, amt, typ = self.name(i), r["f_0x1a0"], r["i_0x19c"]
            if amt <= 1.5 or amt >= 90000:
                continue
            if (typ == 3 and "Amb - Tree" in n) or (typ == 4 and "Stone Mine" in n) or \
               (typ == 5 and "Gold Mine (MP)" in n) or (typ == 2 and n.startswith("Res - ")):
                out.append(i)
        return out

    # ---- tech tree node selection ----
    def nodes_where(self, pred):
        return [(p, n, rn, root) for p, n, rn, root in self.nodes if pred(p, n, rn, root)]

    def node_obj_in(self, objset):
        s = set(objset)
        return self.nodes_where(lambda p, n, rn, root: (not root) and n["object_index"] in s
                                and n["time_ms"] > 1 and any(n[c] > 0 for c in COST_FIELDS))


# --------------------------------------------------------------------------------------------
# Edit generators
# --------------------------------------------------------------------------------------------


def obj_edits(g, idxs, field, mult, group, minimum=None):
    mult = Fraction(mult)
    edits = []
    for i in sorted(set(idxs)):
        r = g.R[i]
        if field.startswith("x_"):
            old = g.gather_value(r, field)
            if not old:
                continue
            new = float(scale(old, mult))
            edits.append(Edit(OBJECTS, g.obj_key(i), field, r[field],
                              struct.pack("<f", new).hex(), group, ("rec", i)))
            continue
        old = r[field]
        if not old:
            continue
        new = scale(old, mult)
        if minimum is not None:
            new = max(minimum, new)
        if isinstance(old, float):
            new = f32(new)
        if new != old:
            edits.append(Edit(OBJECTS, g.obj_key(i), field, old, new, group, ("rec", i)))
    return edits


def node_edits(g, nodes, group, cost_mult=None, time_mult=None):
    edits = []
    for path, n, rootname, is_root in nodes:
        key = g.node_key(n, rootname, is_root)
        if key in g.dupe_node_keys:
            sys.exit("tech node key is not unique: %s" % key)
        if cost_mult is not None:
            for c in COST_FIELDS:
                if n[c] > 0:
                    new = max(1, scale(n[c], Fraction(cost_mult)))
                    if new != n[c]:
                        edits.append(Edit(TECHTREE, key, c, n[c], new, group, path))
        if time_mult is not None and n["time_ms"] > 1:
            new = max(1000, scale(n["time_ms"], Fraction(time_mult)))
            if new != n["time_ms"]:
                edits.append(Edit(TECHTREE, key, "time_ms", n["time_ms"], new, group, path))
    return edits


def epoch_nodes(g):
    return g.nodes_where(lambda p, n, rn, root: (not root and EPOCH_TECH_RE.match(S(n["name"]))) or
                         (root and rn in ("Epoch Dark", "Epoch Middle", "Epoch Renaissance", "Epoch Imperial",
                                          "Epoch Atomic - WW1", "Epoch Atomic - WW2")))


def mk_blitzkrieg(g):
    e = node_edits(g, epoch_nodes(g), "epoch advance cost x0.5, time x0.5", Fraction(1, 2), Fraction(1, 2))
    for f in GATHER_FIELDS:
        e += obj_edits(g, g.citizens(), f, Fraction(3, 5), "gather time x0.6 (about +67% gather speed)")
    return e


def mk_poverty(g):
    e = []
    for f in GATHER_FIELDS:
        e += obj_edits(g, g.citizens(), f, Fraction(5, 4), "gather time x1.25 (-20% gather speed)")
    e += obj_edits(g, g.deposits(), "f_0x1a0", Fraction(3, 5), "deposit size x0.6", minimum=1)
    units = g.army() + g.ships() + g.naval_onagers() + [
        i for i in g.citizens() if g.name(i).startswith("A - Cit")]
    e += node_edits(g, g.node_obj_in(units), "unit cost x0.85", Fraction(17, 20), None)
    return e


def mk_titans(g):
    h = g.heroes()
    e = obj_edits(g, h, "hit_points", 2, "hero hit points x2", minimum=1)
    e += obj_edits(g, h, "attack", Fraction(3, 2), "hero attack x1.5", minimum=1)
    e += node_edits(g, g.node_obj_in(h), "hero train/revive time x0.5", None, Fraction(1, 2))
    return e


def mk_glasscannon(g):
    a = g.army()
    e = obj_edits(g, a, "hit_points", Fraction(3, 5), "unit hit points x0.6", minimum=1)
    e += obj_edits(g, a, "attack", Fraction(8, 5), "unit attack x1.6", minimum=1)
    return e


def mk_naval(g):
    ships, nonagers = g.ships(), g.naval_onagers()
    e = obj_edits(g, ships + nonagers, "hit_points", Fraction(3, 2), "ship hit points x1.5", minimum=1)
    e += obj_edits(g, nonagers, "attack", Fraction(3, 2), "naval onager attack x1.5", minimum=1)
    e += node_edits(g, g.node_obj_in(ships + nonagers), "ship cost x0.7, build time x0.8", Fraction(7, 10),
                    Fraction(4, 5))
    land = g.nodes_where(lambda p, n, rn, root: (not root) and LANDMIL_RE.match(S(n["name"]))
                         and not JUNK.search(S(n["name"])) and any(n[c] > 0 for c in COST_FIELDS))
    e += node_edits(g, land, "land military building cost x1.5", Fraction(3, 2), None)
    return e


MUTATORS = {
    "blitzkrieg": (mk_blitzkrieg, "Epochs half price and half time, citizens gather about 67% faster."),
    "poverty": (mk_poverty, "Gathering 20% slower, deposits 40% smaller, units 15% cheaper."),
    "titans": (mk_titans, "Heroes: 2x hit points, 1.5x attack, half the train time."),
    "glasscannon": (mk_glasscannon, "All army units: 1.6x attack, 0.6x hit points."),
    "naval": (mk_naval, "Ships 30% cheaper, 20% faster to build, 1.5x hit points; land military buildings 1.5x cost."),
}

# --------------------------------------------------------------------------------------------
# Applying and proving
# --------------------------------------------------------------------------------------------


def byte_runs(a, b):
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


def check_conflicts(edits_by_mut):
    seen = {}
    for m, edits in edits_by_mut.items():
        local = set()
        for e in edits:
            if e.ident() in local:
                sys.exit("mutator %s edits %s twice" % (m, e.ident()))
            local.add(e.ident())
            if e.ident() in seen:
                sys.exit("refusing to combine: %s and %s both change %s %s [%s]"
                         % (seen[e.ident()], m, e.key, e.field, e.table))
            seen[e.ident()] = m


def get_target(obj, table, path):
    if table == OBJECTS:
        return obj["records"][path[1]]
    roots = obj["roots"]
    return roots[path[1]] if path[0] == "root" else roots[path[1]]["children"][path[2]]


def apply_edits(g, edits):
    """Apply to fresh copies of the stock tables; returns {table: (new bytes, new obj)}."""
    out = {}
    for table in sorted({e.table for e in edits}):
        obj = unpack_bytes(table, g.raw[table])
        for e in (x for x in edits if x.table == table):
            rec = get_target(obj, table, e.path)
            if rec[e.field] != e.old:
                sys.exit("%s %s: expected %r, found %r (different game version?)"
                         % (e.key, e.field, e.old, rec[e.field]))
            rec[e.field] = e.new
        out[table] = (pack_obj(obj), obj)
    return out


def flat_records(table, obj):
    if table == OBJECTS:
        return {("rec", i): r for i, r in enumerate(obj["records"])}
    d = {}
    for ri, root in enumerate(obj["roots"]):
        d[("root", ri)] = root
        for ci, ch in enumerate(root["children"]):
            d[("child", ri, ci)] = ch
    return d


def prove(g, edits, built):
    """Re-read the packed bytes and show that exactly the edited fields changed."""
    summary = {}
    for table, (data, _obj) in built.items():
        stock = g.raw[table]
        if len(data) != len(stock):
            sys.exit("%s changed size" % table)
        again = unpack_bytes(table, data)
        if pack_obj(again) != data:
            sys.exit("%s output does not round trip" % table)
        a = flat_records(table, unpack_bytes(table, stock))
        b = flat_records(table, again)
        if a.keys() != b.keys():
            sys.exit("%s record set changed" % table)
        diffs = {}
        for path in a:
            ra, rb = a[path], b[path]
            if ra is rb:
                continue
            for f in ra:
                if f == "children":
                    continue
                if ra[f] != rb[f]:
                    diffs[(path, f)] = (ra[f], rb[f])
        want = {(e.path, e.field): (e.old, e.new) for e in edits if e.table == table}
        if diffs != want:
            extra = set(diffs) - set(want)
            missing = set(want) - set(diffs)
            sys.exit("%s: diff differs from edit list (unexpected %s, missing %s)"
                     % (table, sorted(extra)[:3], sorted(missing)[:3]))
        runs = byte_runs(stock, data)
        nbytes = sum(b_ - a_ for a_, b_ in runs)
        if nbytes > 4 * len(want):
            sys.exit("%s: more changed bytes (%d) than 4 per edit (%d)" % (table, nbytes, len(want)))
        summary[table] = {"edits": len(want), "records": len({p for p, _ in want}),
                          "changed_bytes": nbytes, "changed_runs": len(runs), "size": len(data)}
    return summary


def sanity(g, edits):
    for e in edits:
        if isinstance(e.new, (int, float)) and not isinstance(e.new, bool):
            if e.field in ("hit_points", "attack", "time_ms", "f_0x1a0") + COST_FIELDS and e.new < 1:
                sys.exit("%s %s dropped below 1" % (e.key, e.field))
            if isinstance(e.new, int) and abs(e.new) >= 2 ** 31:
                sys.exit("%s %s overflows int32" % (e.key, e.field))
            if e.old > 0 and not 0.3 <= e.new / e.old <= 3.0:
                sys.exit("%s %s changes by more than 3x: %s -> %s" % (e.key, e.field, e.old, e.new))


def build(game_dir, overlay_root, names, combine=False):
    if len(names) > 1 and not combine:
        sys.exit("mutators are mutually exclusive; pass --combine to try %s" % "+".join(names))
    for n in names:
        if n not in MUTATORS:
            sys.exit("unknown mutator %r; choose from %s" % (n, ", ".join(MUTATORS)))
    g = Game(game_dir)
    per = {n: MUTATORS[n][0](g) for n in names}
    check_conflicts(per)
    edits = [e for n in names for e in per[n]]
    sanity(g, edits)
    built = apply_edits(g, edits)
    summary = prove(g, edits, built)

    label = "+".join(names)
    root = Path(overlay_root) / label
    files = {}
    for table, (data, _o) in built.items():
        p = root / DB_DIR / (table + ".dat")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        files[(DB_DIR / (table + ".dat")).as_posix()] = {"source_sha256": sha(g.raw[table]),
                                                        "output_sha256": sha(data), **summary[table]}
    for stale in (root / DB_DIR).glob("*.dat"):
        if stale.stem not in built:
            stale.unlink()
    groups = {}
    for e in edits:
        k = (e.group, e.table, e.field)
        groups.setdefault(k, []).append(e)
    group_list = []
    for (grp, table, field), es in sorted(groups.items()):
        ex = es[0]
        group_list.append({"change": grp, "table": table, "field": field, "records": len(es),
                           "example": {"record": ex.key, "old": ex.old, "new": ex.new}})
    manifest = {"mutator": label, "version": VERSION,
                "description": " ".join(MUTATORS[n][1] for n in names),
                "exclusive": not combine,
                "generator_sha256": sha(Path(__file__).read_bytes()),
                "files": files, "groups": group_list, "edits": [e.as_json() for e in edits]}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")

    print("== %s: %s" % (label, manifest["description"]))
    for grp in group_list:
        print("  %-52s %-10s %-11s %4d rec  e.g. %s: %s -> %s" % (
            grp["change"], grp["table"], grp["field"], grp["records"], grp["example"]["record"][:46],
            grp["example"]["old"], grp["example"]["new"]))
    for f, info in files.items():
        print("  byte diff %s: %d edits in %d records, %d bytes changed in %d runs, size %d unchanged, "
              "round trip ok, diff == edit list" % (f, info["edits"], info["records"], info["changed_bytes"],
                                                     info["changed_runs"], info["size"]))
    return manifest


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 3 or not flags <= {"--combine"}:
        sys.exit(__doc__)
    game, root, which = args
    if which == "all":
        for n in MUTATORS:
            build(game, root, [n])
    else:
        build(game, root, which.split("+"), "--combine" in flags)


if __name__ == "__main__":
    main()
