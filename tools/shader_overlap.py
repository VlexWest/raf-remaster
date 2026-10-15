"""Count lines in the repo's shaders/ that also occur in the player's stock .fx files.

Usage:
  python tools/shader_overlap.py <game_dir> [--min 20] [--show]

A line counts when, with whitespace collapsed, it is at least --min characters long
and equals a line of any stock .fx under <game_dir>/Data. Line-script directives
('@@ ...' in *.fxpatch) are references, not stock text, and are skipped. Reads the
tracked files (git ls-files shaders); never writes anything.
"""
import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(line):
    return re.sub(r"\s+", " ", line).strip()


def stock_lines(data_dir, min_len):
    out = {}
    for dp, _, fns in os.walk(data_dir):
        for fn in fns:
            if fn.lower().endswith(".fx"):
                p = os.path.join(dp, fn)
                for line in open(p, encoding="latin1").read().splitlines():
                    n = norm(line)
                    if len(n) >= min_len:
                        out.setdefault(n, os.path.relpath(p, data_dir).replace("\\", "/"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir")
    ap.add_argument("--min", type=int, default=20)
    ap.add_argument("--show", action="store_true", help="print the shared lines")
    a = ap.parse_args(argv)
    stock = stock_lines(os.path.join(a.game_dir, "Data"), a.min)
    files = subprocess.check_output(["git", "-C", REPO, "ls-files", "shaders"], text=True).split("\n")
    total_n = total_hit = 0
    for rel in [f for f in files if f]:
        n = hit = 0
        shared = []
        for line in open(os.path.join(REPO, rel), encoding="latin1").read().splitlines():
            if line.startswith("@@ "):
                continue
            s = norm(line)
            if len(s) < a.min:
                continue
            n += 1
            if s in stock:
                hit += 1
                shared.append((s, stock[s]))
        total_n, total_hit = total_n + n, total_hit + hit
        print(f"{hit:4} / {n:4}  {rel}")
        if a.show:
            for s, where in shared:
                print(f"           {s}    [{where}]")
    print(f"{total_hit:4} / {total_n:4}  total (lines of >= {a.min} chars shared with stock .fx)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
