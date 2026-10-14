"""Keep the display on while this runs (ES_CONTINUOUS|ES_DISPLAY_REQUIRED|ES_SYSTEM_REQUIRED). Kill by PID to release."""
import ctypes, time, os
print(os.getpid(), flush=True)
ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
while True: time.sleep(60)
