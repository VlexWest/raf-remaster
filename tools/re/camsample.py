"""camsample.py <pid> [seconds] [addr] : sample the camera position (GEViewport 0xd2f748 + 0x1f0 + 0x30) at ~2 kHz;
report how often it changes. Run while the camera scrolls."""
import sys, time, struct
sys.path.insert(0, 'work/scripts')
import memscan
pid = int(sys.argv[1]); T = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
addr = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0xd2f968
h = memscan.openp(pid)
last = None; changes = []; t0 = time.perf_counter()
while time.perf_counter() - t0 < T:
    v = memscan.read(h, addr, 12)
    if v != last:
        changes.append((time.perf_counter() - t0, struct.unpack('<3f', v)))
        last = v
    time.sleep(0.0003)
dt = [b[0] - a[0] for a, b in zip(changes, changes[1:])]
print(f"{len(changes)} distinct values in {T}s = {len(changes)/T:.1f}/s; first {changes[0][1]} last {changes[-1][1]}")
import math
steps = [math.dist(a[1][:2], b[1][:2]) for a, b in zip(changes, changes[1:])]
if steps:
    steps.sort(); print(f"step size: median {steps[len(steps)//2]:.3f} min {steps[0]:.3f} max {steps[-1]:.3f}")
if dt:
    dt.sort(); print(f"interval ms: median {1000*dt[len(dt)//2]:.1f} min {1000*dt[0]:.1f} max {1000*dt[-1]:.1f}")
