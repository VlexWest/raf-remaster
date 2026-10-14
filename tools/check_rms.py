#!/usr/bin/env python3
"""Run every offline check of the custom random maps (read only on the game install).

  python tools/check_rms.py [--game "D:/Games/Rise and Fall"]

1. regenerate into a temp dir and compare byte for byte with rms/ (committed output is current)
2. lint self-test (broken scripts must be caught)
3. lint all shipped scripts (0 issues expected)
4. lint rms/ (0 issues expected)
"""
import filecmp
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))


def run(args):
    r = subprocess.run([sys.executable, "-I"] + args, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main():
    extra = sys.argv[1:]
    ok = True
    with tempfile.TemporaryDirectory() as td:
        rc, out = run([os.path.join(HERE, "gen_rms.py"), td])
        same = rc == 0
        for fn in os.listdir(td):
            if not os.path.isfile(os.path.join(REPO, "rms", fn)) or not filecmp.cmp(
                    os.path.join(td, fn), os.path.join(REPO, "rms", fn), shallow=False):
                same = False
                print("  stale output:", fn)
        print("%-4s generator output == rms/" % ("ok" if same else "FAIL"))
        ok &= same
    for name, args in (
            ("lint self-test", [os.path.join(HERE, "test_lint_rms.py")] + extra),
            ("lint shipped scripts", [os.path.join(HERE, "lint_rms.py"), "--shipped"] + extra),
            ("lint rms/", [os.path.join(HERE, "lint_rms.py")] + extra)):
        rc, out = run(args)
        tail = [l for l in out.splitlines() if l.startswith(("TOTAL", "lint self-test"))]
        print("%-4s %s  %s" % ("ok" if rc == 0 else "FAIL", name, tail[-1] if tail else ""))
        ok &= rc == 0
        if rc:
            print(out[-1500:])
    print("ALL OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
