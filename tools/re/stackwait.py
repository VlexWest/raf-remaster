"""stackwait.py <pid> <tid> [samples] : sample a thread's stack, histogram of the first return addresses into game modules."""
import ctypes, sys, time, collections
sys.path.insert(0, 'work/scripts')
import eipsample_lib as E
import memscan
pid = int(sys.argv[1]); tid = int(sys.argv[2]); N = int(sys.argv[3]) if len(sys.argv) > 3 else 300
mods = [m for m in E.modules(pid) if m[2].lower() in ('riseandfall.exe', 'lowlevelengine.dll', 'dx9rasterizer.dll', 'default.dll')]
ph = memscan.openp(pid); th = E.k.OpenThread(0x0048, False, tid)
hist = collections.Counter()
for i in range(N):
    c = E.context(th)
    if c:
        stack = memscan.read(ph, c[1], 4 * 256)
        E.k.ResumeThread(th)
        chain = []
        for j in range(0, len(stack) - 3, 4):
            v = int.from_bytes(stack[j:j+4], 'little')
            for b, n, m in mods:
                if b <= v < b + n:
                    chain.append(f"{m[:4]}:{v - b + (0x400000 if m.lower().endswith('exe') else 0x10000000):08x}"); break
            if len(chain) >= 4: break
        hist[' < '.join(chain)] += 1
    else:
        E.k.ResumeThread(th)
    time.sleep(0.005)
for k_, v in hist.most_common(12): print(v, k_)
