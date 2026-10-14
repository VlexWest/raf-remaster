"""Offline tests for tools/build_mutators.py. Reads the base install only.

    python tools/test_mutators.py [game_dir]      (default D:/Games/Rise and Fall)
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mutators as bm  # noqa: E402

GAME = sys.argv[1] if len(sys.argv) > 1 else "D:/Games/Rise and Fall"
FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def exits(fn, *a, **k):
    try:
        quiet(fn, *a, **k)
    except SystemExit as e:
        return str(e.code)
    return None


def hashes(root, name):
    m = json.loads((Path(root) / name / "manifest.json").read_text(encoding="utf-8"))
    return {f: v["output_sha256"] for f, v in m["files"].items()}, m


def main():
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        for n in bm.MUTATORS:
            quiet(bm.build, GAME, t1, [n])
            quiet(bm.build, GAME, t2, [n])
            h1, m = hashes(t1, n)
            h2, _ = hashes(t2, n)
            check("%s deterministic (two builds identical)" % n, h1 == h2 and len(h1) > 0)
            check("%s has edits and a manifest" % n, len(m["edits"]) > 0 and m["exclusive"])
            for f, info in m["files"].items():
                data = (Path(t1) / n / f).read_bytes()
                check("%s %s size unchanged and sha matches" % (n, f),
                      len(data) == info["size"] and bm.sha(data) == info["output_sha256"])
        # exclusivity
        msg = exits(bm.build, GAME, t1, ["blitzkrieg", "poverty"])
        check("combine without --combine refused", msg and "mutually exclusive" in msg, str(msg))
        for a, b in (("blitzkrieg", "poverty"), ("glasscannon", "titans"), ("poverty", "naval")):
            msg = exits(bm.build, GAME, t1, [a, b], True)
            check("%s + %s refused (same field twice)" % (a, b), msg and "both change" in msg, str(msg))
        for a, b in (("blitzkrieg", "titans"), ("blitzkrieg", "naval"), ("poverty", "glasscannon")):
            msg = exits(bm.build, GAME, t1, [a, b], True)
            check("%s + %s allowed with --combine" % (a, b), msg is None, str(msg))
        # stock check
        g = bm.Game(GAME)
        e = bm.mk_titans(g)[0]
        bad = bm.Edit(e.table, e.key, e.field, e.old + 1, e.new, e.group, e.path)
        msg = exits(bm.apply_edits, g, [bad])
        check("wrong stock value fails loudly", msg and "expected" in msg, str(msg))
        # the proof really detects an unlisted change
        built = bm.apply_edits(g, [e])
        rec = built[e.table][1]["records"][e.path[1]]
        other = built[e.table][1]["records"][e.path[1] + 1]
        other["hit_points"] += 1
        built = {e.table: (bm.pack_obj(built[e.table][1]), built[e.table][1])}
        msg = exits(bm.prove, g, [e], built)
        check("prove() rejects an unlisted extra change", msg and "differs" in msg, str(msg))
        # semantic spot checks on the numbers
        by = {(x.key, x.field): x for x in bm.mk_glasscannon(g)}
        sp = next(v for k, v in by.items() if "Spear Infantry (Level 1 Rome)" in k[0] and k[1] == "hit_points")
        check("spear L1 Rome hp 440 -> 264", (sp.old, sp.new) == (440, 264), str((sp.old, sp.new)))
        check("no hit point or attack edit drops below 1",
              all(x.new >= 1 for x in by.values()))
        for n in bm.MUTATORS:
            es = bm.MUTATORS[n][0](g)
            ids = [x.ident() for x in es]
            check("%s: every edit unique" % n, len(ids) == len(set(ids)))
    print("\n%s" % ("ALL TESTS PASSED" if not FAILED else "FAILED: " + ", ".join(FAILED)))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
