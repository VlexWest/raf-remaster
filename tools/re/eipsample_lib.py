"""eipsample.py <pid> [seconds] [thread_index] : sample EIP of a 32-bit process's threads (Wow64GetThreadContext)
and print a histogram per module+offset bucket. thread_index 0 = oldest thread (main)."""
import ctypes, ctypes.wintypes as wt, sys, time, collections, subprocess
k = ctypes.windll.kernel32
class TE(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD), ('th32OwnerProcessID', wt.DWORD),
                ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG), ('dwFlags', wt.DWORD)]
class ME(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('th32ModuleID', wt.DWORD), ('th32ProcessID', wt.DWORD), ('GlblcntUsage', wt.DWORD), ('ProccntUsage', wt.DWORD),
                ('modBaseAddr', ctypes.c_void_p), ('modBaseSize', wt.DWORD), ('hModule', ctypes.c_void_p), ('szModule', ctypes.c_char * 256), ('szExePath', ctypes.c_char * 260)]

def threads(pid):
    snap = k.CreateToolhelp32Snapshot(4, 0); t = TE(); t.dwSize = ctypes.sizeof(TE); out = []
    ok = k.Thread32First(snap, ctypes.byref(t))
    while ok:
        if t.th32OwnerProcessID == pid: out.append(t.th32ThreadID)
        ok = k.Thread32Next(snap, ctypes.byref(t))
    return out
def modules(pid):
    ms = k.CreateToolhelp32Snapshot(0x18, pid); m = ME(); m.dwSize = ctypes.sizeof(ME); out = []
    ok = k.Module32First(ms, ctypes.byref(m))
    while ok:
        out.append((m.modBaseAddr or 0, m.modBaseSize, m.szModule.decode())); ok = k.Module32Next(ms, ctypes.byref(m))
    return out
buf = ctypes.create_string_buffer(0x2CC)
def context(h):
    """(eip, esp, ebp) of a suspended-then-resumed thread."""
    ctypes.memmove(buf, (0x10001).to_bytes(4, 'little'), 4)
    if k.SuspendThread(h) == 0xFFFFFFFF: return None
    r = k.Wow64GetThreadContext(h, buf)
    out = None
    if r:
        g = lambda o: int.from_bytes(buf.raw[o:o+4], 'little')
        out = (g(0xB8), g(0xC4), g(0xB4))
    return out  # caller must ResumeThread
