"""Drive Rise and Fall for automated smoke tests (Windows only).

Usage:
    python gamectl.py launch <game_dir>        start with the data path args, print PID
    python gamectl.py shot <out.png> [scale]   focus the game and capture the screen
    python gamectl.py key <name> [count]       press a key: esc, enter, space, f1..f12, a letter
    python gamectl.py click <x> <y>            left click at screen pixel x, y
    python gamectl.py mem                      working set and private bytes of the game
    python gamectl.py kill                     kill the game by its exact PID
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

EXE = "RiseAndFall.exe"
VK = {"esc": 0x1B, "enter": 0x0D, "space": 0x20, "tab": 0x09, "up": 0x26, "down": 0x28,
      "left": 0x25, "right": 0x27, **{f"f{i}": 0x6F + i for i in range(1, 13)}}


def game_pid() -> int | None:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.strip('"').split('","')
        if len(parts) > 1 and parts[0].lower() == EXE.lower():
            return int(parts[1])
    return None


def game_hwnd(pid: int) -> int | None:
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def focus() -> None:
    pid = game_pid()
    hwnd = pid and game_hwnd(pid)
    if not hwnd:
        sys.exit("game window not found")
    user32.ShowWindow(hwnd, 9)
    # Windows only lets the process that got the last input steal focus; a dummy Alt press makes that us.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)


def key(name: str, count: int = 1) -> None:
    vk = VK.get(name.lower()) or ord(name.upper())
    scan = user32.MapVirtualKeyW(vk, 0)
    focus()
    for _ in range(count):
        user32.keybd_event(vk, scan, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(vk, scan, 2, 0)
        time.sleep(0.3)


def click(x: int, y: int) -> None:
    focus()
    user32.SetCursorPos(x, y)
    time.sleep(0.1)
    user32.mouse_event(0x02, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x04, 0, 0, 0, 0)


def shot(out: str, scale: float = 0.25) -> None:
    focus()
    time.sleep(0.5)
    img = ImageGrab.grab(all_screens=False)
    if scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    img.save(out)
    print(f"{out} ({img.width}x{img.height}, screen scale {scale})")


def mem() -> None:
    pid = game_pid()
    if not pid:
        sys.exit("game not running")
    ps = ("Get-Process -Id %d | ForEach-Object { '{0} MB working set, {1} MB private, {2} MB virtual' -f "
          "[int]($_.WorkingSet64/1MB), [int]($_.PrivateMemorySize64/1MB), [int]($_.VirtualMemorySize64/1MB) }" % pid)
    print(subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip())


def launch(game_dir: str) -> None:
    game = Path(game_dir)
    proc = subprocess.Popen(f'"{game / EXE}" -datapath "Data\\" -redistpath "Redist\\"', cwd=game)
    print(proc.pid)


def kill() -> None:
    pid = game_pid()
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        print(f"killed {pid}")


def main() -> None:
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "launch":
        launch(args[0])
    elif cmd == "shot":
        shot(args[0], float(args[1]) if len(args) > 1 else 0.25)
    elif cmd == "key":
        key(args[0], int(args[1]) if len(args) > 1 else 1)
    elif cmd == "click":
        click(int(args[0]), int(args[1]))
    elif cmd == "mem":
        mem()
    elif cmd == "kill":
        kill()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
