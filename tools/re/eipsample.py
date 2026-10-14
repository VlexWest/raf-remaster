"""eipsample.py <pid> [seconds] [thread_index] : sample EIP of a 32-bit process's threads (Wow64GetThreadContext)
and print a histogram per module+offset bucket. thread_index 0 = oldest thread (main)."""
import ctypes, ctypes.wintypes as wt, sys, time, collections, subprocess
k = ctypes.windll.kernel32
pid = int(sys.argv[1]); T = float(sys.argv[2]) if len(sys.argv) > 2 else 3; ti = int(sys.argv[3]) if len(sys.argv) > 3 else 0
class TE(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD), ('th32OwnerProcessID', wt.DWORD),
                ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG), ('dwFlags', wt.DWORD)]
snap = k.CreateToolhelp32Snapshot(4, 0); te = TE(); te.dwSize = ctypes.sizeof(TE); tids = []
ok = k.Thread32First(snap, ctypes.byref(te))
while ok:
    if te.th32OwnerProcessID == pid: tids.append(te.th32ThreadID)
    ok = k.Thread32Next(snap, ctypes.byref(te))
# WOW64_CONTEXT: ContextFlags at 0, Eip at offset 0xB8, Esp 0xC4, Ebp 0xB4
buf = ctypes.create_string_buffer(0x2CC)
def eip(h):
    ctypes.memmove(buf, (0x10001).to_bytes(4, 'little'), 4)  # WOW64_CONTEXT_CONTROL
    if k.SuspendThread(h) == 0xFFFFFFFF: return None
    r = k.Wow64GetThreadContext(h, buf); k.ResumeThread(h)
    return int.from_bytes(buf.raw[0xB8:0xBC], 'little') if r else None
# module map
mods = []
class ME(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('th32ModuleID', wt.DWORD), ('th32ProcessID', wt.DWORD), ('GlblcntUsage', wt.DWORD), ('ProccntUsage', wt.DWORD),
                ('modBaseAddr', ctypes.c_void_p), ('modBaseSize', wt.DWORD), ('hModule', ctypes.c_void_p), ('szModule', ctypes.c_char * 256), ('szExePath', ctypes.c_char * 260)]
ms = k.CreateToolhelp32Snapshot(0x18, pid); me = ME(); me.dwSize = ctypes.sizeof(ME)
ok = k.Module32First(ms, ctypes.byref(me))
while ok:
    mods.append((me.modBaseAddr or 0, me.modBaseSize, me.szModule.decode())); ok = k.Module32Next(ms, ctypes.byref(me))
def name(a):
    for b, n, m in mods:
        if b <= a < b + n: return m, a - b
    return '?', a
sel = tids if ti < 0 else [tids[ti]]
hs = [(t, k.OpenThread(0x0048, False, t)) for t in sel]
hist = collections.Counter(); n = 0; t0 = time.perf_counter()
while time.perf_counter() - t0 < T:
    for t, h in hs:
        e = eip(h)
        if e: m, o = name(e); hist[(t, m, (o + (0x400000 if m.lower().endswith('.exe') else 0x10000000)) & ~0xF)] += 1; n += 1
    time.sleep(0.001)
print(n, 'samples, threads', tids)
for (t, m, o), c in hist.most_common(40 if ti >= 0 else None): print(f"{c:5d} {t:6d} {m:22s} {o:08x}")
