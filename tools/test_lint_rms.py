#!/usr/bin/env python3
"""Self-test of lint_rms.py: each broken script must be caught (fix counter-check).

Usage: python tools/test_lint_rms.py [--game "D:/Games/Rise and Fall"]
Writes only to a temp directory.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, "lint_rms.py")

BASE = """UseMapGenerator "Default"
StringTableID 27009
StringHelpID 26901
#include "Common\\Map Climate"
#include "Common\\Common Conditions"
#if Is2Players
#define (kPercentLand, Between(0.4, 0.4))
#else
#define (kPercentLand, Between(0.4, 0.4))
#endif
PercentLand kPercentLand
"""

CASES = [
    ("good", BASE, 0, 0),
    ("unknown identifier", BASE + "PercentLand kPercentLandTypo\n", 1, None),
    ("unknown keyword", BASE + "MakeEverythingGold true\n", 1, None),
    ("missing include", BASE + '#include "Common\\No Such File"\n', 1, None),
    ("unbalanced #if", BASE + "#if Is3Players\nPercentLand 0.5\n", 1, None),
    ("k-constant missing in a branch",
     BASE.replace("#else\n#define (kPercentLand, Between(0.4, 0.4))\n", "#else\n"), 1, None),
    ("unbalanced parentheses", BASE + "ResourcePerPlayer (Gold, 3\n", 1, None),
    ("value out of shipped range (warning only)",
     BASE.replace("Between(0.4, 0.4))\n#else", "Between(7.5, 7.5))\n#else"), 0, 1),
]


def main():
    extra = sys.argv[1:]
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        for name, text, want_issues, want_warn in CASES:
            p = os.path.join(td, "t.rmv")
            with open(p, "w", newline="") as f:
                f.write(text)
            r = subprocess.run([sys.executable, "-I", LINT, "--quick"] + extra + [p],
                               capture_output=True, text=True)
            last = [l for l in r.stdout.splitlines() if l.startswith("TOTAL")][-1]
            issues = int(last.split("issues=")[1].split()[0])
            warns = int(last.split("warnings=")[1].split()[0])
            # the shared shipped warning (unclosed #if in a game common file) is not ours
            warns_own = len([l for l in r.stdout.splitlines()
                             if l.startswith("WARN") and "random map scripts" not in l])
            ok = (issues == 0) if want_issues == 0 else (issues >= 1)
            if want_warn is not None:
                ok = ok and (warns_own >= 1 if want_warn else warns_own == 0)
            print("%-4s %-45s issues=%d warnings=%d (own %d)" %
                  ("ok" if ok else "FAIL", name, issues, warns, warns_own))
            if not ok:
                bad += 1
                print(r.stdout[-800:])
    print("lint self-test:", "PASS" if bad == 0 else "FAILED (%d)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
