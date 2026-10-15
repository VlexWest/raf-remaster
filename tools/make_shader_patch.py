"""Turn an edited shader into a line script against the stock file (developer tool).

Usage:
  python tools/make_shader_patch.py <stock.fx> <ours.fx> <out.fxpatch>

The script holds only our lines. Stock lines are referenced, never copied: runs that
stay in place become '@@ keep', removed runs '@@ drop', and our lines that are
identical to a stock line elsewhere (at least MIN_COPY characters) become '@@ copy',
re-spaced when only the whitespace between the words differs. Each reference carries a short hash of the stock text it
covers. tools/build_shaders.py applies the script to the player's stock file; this tool
checks the round trip before writing.

Workflow: build the overlay, edit the built file (outside the repo), run this tool on
the player's stock file and the edited one, rebuild, and compare.
"""
import argparse
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_shaders import BuildError, apply_lines, line_hash  # noqa: E402

MIN_COPY = 20  # same threshold as the overlap scan in check_shader_overlap (non-trivial lines)


def norm(line):
    return re.sub(r"\s+", " ", line).strip()


def trivial(line):
    return len(norm(line)) < MIN_COPY


def respace(line):
    """The whitespace around the words of a line as 't,tt,s,' (None if not plain tabs/spaces)."""
    body = line[:-1] if line.endswith("\n") else line
    parts = re.split(r"([^ \t]+)", body)
    words, gaps = parts[1::2], parts[0::2]
    if not words or words != body.split():
        return None
    return ",".join(g.replace("\t", "t").replace(" ", "s") for g in gaps)


def read_lf(path):
    return open(path, encoding="latin1").read().replace("\r\n", "\n")


def make(stock_txt, ours_txt, header=None):
    st = stock_txt.splitlines(keepends=True)
    ou = ours_txt.splitlines(keepends=True)
    noeol = bool(ou) and not ou[-1].endswith("\n")
    if noeol:
        ou[-1] += "\n"
    for line in ou:
        if line.startswith("@@ "):
            raise ValueError(f"our line starts with '@@ ': {line!r}")

    # where each non-trivial stock line occurs (a final line without newline is never copied)
    where, where_words = {}, {}
    for i, line in enumerate(st):
        if line.endswith("\n") and not trivial(line):
            where.setdefault(line, []).append(i)
            where_words.setdefault(tuple(line.split()), []).append(i)

    sm = difflib.SequenceMatcher(None, st, ou, autojunk=False)
    segs = []  # ['keep', i1, i2] or ['change', i1, i2, j1, j2]; neighbouring changes merged
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" and (i2 - i1) <= 2 and all(trivial(x) for x in st[i1:i2]):
            tag = "replace"  # a stray '{' or '#endif' match only fragments the script
        if tag == "equal":
            segs.append(["keep", i1, i2])
        elif segs and segs[-1][0] == "change":
            segs[-1][2], segs[-1][4] = i2, j2
        else:
            segs.append(["change", i1, i2, j1, j2])
    ops = []  # ('keep'|'drop', i1, i2) on stock, ('add', j1, j2) on ours
    for seg in segs:
        if seg[0] == "keep":
            ops.append(("keep", seg[1], seg[2]))
            continue
        if seg[2] > seg[1]:
            ops.append(("drop", seg[1], seg[2]))
        if seg[4] > seg[3]:
            ops.append(("add", seg[3], seg[4]))

    out = [f"@@ # {h}\n" for h in (header or [])]
    pending = None  # merged keep/drop run: [kind, a, b]

    def flush():
        nonlocal pending
        if pending:
            k, a, b = pending
            out.append(f"@@ {k} {b - a} {line_hash(st[a:b])}\n")
            pending = None

    def add_lines(lines):
        run = None  # [stock start, stock end]

        def end_run():
            nonlocal run
            if run:
                out.append(f"@@ copy {run[0] + 1} {run[1] - run[0]} {line_hash(st[run[0]:run[1]])}\n")
                run = None

        for line in lines:
            if run and run[1] < len(st) and st[run[1]] == line and st[run[1]].endswith("\n"):
                run[1] += 1
                continue
            if line in where:
                end_run()
                run = [where[line][0], where[line][0] + 1]
                continue
            end_run()
            gaps = respace(line)
            if gaps is not None and tuple(line.split()) in where_words:
                i = where_words[tuple(line.split())][0]
                out.append(f"@@ copy {i + 1} 1 {line_hash(st[i:i + 1])} {gaps}\n")
                continue
            out.append(line)
        end_run()

    for kind, a, b in ops:
        if kind == "add":
            flush()
            add_lines(ou[a:b])
        elif pending and pending[0] == kind and pending[2] == a:
            pending[2] = b
        else:
            flush()
            pending = [kind, a, b]
    flush()
    if noeol:
        out.append("@@ noeol\n")
    return "".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stock")
    ap.add_argument("ours")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    stock, ours = read_lf(a.stock), read_lf(a.ours)
    script = make(stock, ours, header=[
        f"raf-remaster line script for the stock '{os.path.basename(a.stock)}'.",
        "Lines starting with '@@ ' reference the player's stock file; all other lines are ours.",
        "Made by tools/make_shader_patch.py, applied by tools/build_shaders.py.",
    ])
    try:
        back, stats = apply_lines(stock, script, os.path.basename(a.out))
    except BuildError as e:
        print("round trip failed:", e, file=sys.stderr)
        return 1
    if back != ours:
        print("round trip failed: output differs", file=sys.stderr)
        return 1
    with open(a.out, "w", encoding="latin1", newline="\n") as f:
        f.write(script)
    print(f"{a.out}: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
