"""cursor_motion.py <seconds> : sweep the cursor in a circle at 500 Hz (for frame-update measurements)."""
import ctypes, time, math, sys
u=ctypes.windll.user32; u.SetProcessDPIAware()
t0=time.perf_counter(); T=float(sys.argv[1])
while time.perf_counter()-t0<T:
    t=time.perf_counter()-t0
    u.SetCursorPos(int(1720+300*math.cos(t*6)), int(600+200*math.sin(t*6)))
    time.sleep(0.002)
