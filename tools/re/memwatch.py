"""memwatch.py <pid> <seconds> <out.csv> : sample private bytes / working set every 5 s, print the peak."""
import ctypes, ctypes.wintypes as wt, sys, time
k = ctypes.windll.kernel32; psapi = ctypes.windll.psapi
class PMC(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('PageFaultCount', wt.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]
pid = int(sys.argv[1]); T = float(sys.argv[2]); h = k.OpenProcess(0x1410, False, pid)
peak = 0; t0 = time.time(); f = open(sys.argv[3], 'w'); f.write('t,private_mb,ws_mb,peak_pagefile_mb\n')
while time.time() - t0 < T:
    m = PMC(); m.cb = ctypes.sizeof(PMC)
    if not psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb): break
    p = m.PrivateUsage / 2**20; peak = max(peak, p)
    f.write(f"{time.time()-t0:.0f},{p:.0f},{m.WorkingSetSize/2**20:.0f},{m.PeakPagefileUsage/2**20:.0f}\n"); f.flush()
    time.sleep(5)
print(f"peak private {peak:.0f} MB, peak pagefile usage {m.PeakPagefileUsage/2**20:.0f} MB")
