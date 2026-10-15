"""Run every stub test (tools/test_*.py) on the current code and print one line per script.

    python tools/run_stub_tests.py [name-filter]

Exit code 1 if any script fails. The end-to-end update test (tools/e2e_update.py) is not part of
this: it needs the built dist/ and the stock install and takes minutes.
"""

import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def main() -> int:
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    failed = []
    for script in sorted(TOOLS.glob("test_*.py")):
        if flt not in script.name:
            continue
        t = time.time()
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=TOOLS.parent)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        status = "PASS" if r.returncode == 0 else "FAIL"
        print(f"{status} {script.name:32s} {time.time() - t:6.1f} s  {last[:90]}", flush=True)
        if r.returncode:
            failed.append(script.name)
            print("\n".join("     " + x for x in (r.stdout + r.stderr).strip().splitlines()[-15:]))
    print("ALL STUB TESTS PASSED" if not failed else f"FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
