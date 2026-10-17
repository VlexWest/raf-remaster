"""mouseprobe.py <pid> [seconds] : read-only click-offset probe (RAF-6). Prints the mouse state once, then one
line per left click (the probe only watches GetAsyncKeyState; it never moves the mouse or sends input):
OS cursor vs the game's mouse pixel (DX9Rasterizer +0x38, what UI and picking use), and the z=0 ground point
under that pixel through the live viewport 0x101ce68 (terrain picking) and the drawn-frame copy 0xd2f748
(unit picking / what is on screen). Addresses: v1.15 exe, see work/MODLOG.md "Click offset (RAF-6)"."""
import ctypes
import ctypes.wintypes as wt
import math
import struct
import sys
import time

import memscan

RAST_PTR = 0x101CBD8               # GERasterizer* (DX9Rasterizer)
VP_LIVE, VP_DRAWN = 0x101CE68, 0xD2F748
CAM_ZOOM = 0x101DCC0               # camera zoom fraction 0..1
u = ctypes.windll.user32
u.SetProcessDPIAware()


def rd(h, a, fmt):
    n = struct.calcsize(fmt)
    d = memscan.read(h, a, n)
    if len(d) != n:
        sys.exit(f"cannot read {a:#x} (game not running or not v1.15?)")
    return struct.unpack(fmt, d)


def game_window(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(hwnd):
            r = wt.RECT()
            u.GetClientRect(hwnd, ctypes.byref(r))
            o = wt.POINT(0, 0)
            u.ClientToScreen(hwnd, ctypes.byref(o))
            found.append((r.right * r.bottom, o.x, o.y, r.right, r.bottom))
        return True

    u.EnumWindows(cb, 0)
    return max(found)[1:] if found else None


def viewport(h, base):
    v = memscan.read(h, base + 0x138, 0x380 - 0x138)
    f = lambda off: struct.unpack_from("<f", v, off - 0x138)[0]
    return {"rect": [f(0x138 + 4 * i) for i in range(4)],  # bottom, left, right, top
            "inv": [f(0x2F0 + 4 * i) for i in range(16)], "aspect": f(0x354), "fov": f(0x35C),
            "near": f(0x364), "far": f(0x370), "hh": f(0x368), "hw": f(0x36C), "xc": f(0x374), "yc": f(0x378)}


def ground(vp, px, py):
    """Pick ray of GEViewport::Convert2DPositionToWorldRay, cut with z = 0."""
    if not vp["hw"] or not vp["hh"]:
        return None
    nx, ny = (px - vp["xc"]) / vp["hw"], (vp["yc"] - py) / vp["hh"]
    m = vp["inv"]

    def world(d):
        x, y, z = nx * d, ny * d, d
        return (x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13],
                x * m[2] + y * m[6] + z * m[10] + m[14])

    a, b = world(vp["near"]), world(vp["far"])
    if b[2] == a[2]:
        return None
    t = -a[2] / (b[2] - a[2])
    return tuple(a[i] + t * (b[i] - a[i]) for i in range(3))


def state(h):
    r = rd(h, RAST_PTR, "<I")[0]
    norm, px = rd(h, r + 0x30, "<2f"), rd(h, r + 0x38, "<2f")
    scr, idx = rd(h, r + 0x40, "<I")[0], rd(h, r + 0x60, "<I")[0]
    lock, always = rd(h, r + 0x7A, "<B")[0], rd(h, r + 0x7C, "<B")[0]
    arr, cnt = rd(h, r + 0x368, "<I")[0], rd(h, r + 0x374, "<I")[0]
    dxs = rd(h, arr + 4 * idx, "<I")[0] if idx < cnt else 0
    caps = rd(h, dxs + 0x3E4, "<I")[0] if dxs else 0
    clamp = rd(h, scr + 0x3BC, "<4f") if scr else ()
    return {"r": r, "norm": norm, "px": px, "idx": idx, "lock": lock, "always": always, "caps": caps,
            "clamp": clamp, "di": bool(always or not caps & 1)}


def main():
    pid = int(sys.argv[1])
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120
    h = memscan.openp(pid)
    s = state(h)
    win = game_window(pid)
    print(f"rasterizer {s['r']:#x} screen {s['idx']} movement-lock {s['lock']} AlwaysUpdateMouse {s['always']} "
          f"CursorCaps {s['caps']:#x} -> {'DirectInput deltas + SetCursorPosition' if s['di'] else 'GetCursorPos'} branch")
    print(f"clamp rect (bottom,left,right,top) {[round(x, 1) for x in s['clamp']]}  window client (x,y,w,h) {win}")
    for name, base in (("live 0x101ce68", VP_LIVE), ("drawn 0xd2f748", VP_DRAWN)):
        vp = viewport(h, base)
        print(f"viewport {name}: rect {[round(x, 1) for x in vp['rect']]} aspect {vp['aspect']:.4f} "
              f"fov {math.degrees(vp['fov']):.2f} near {vp['near']:.3f} far {vp['far']:.2f}")
    print(f"zoom fraction {rd(h, CAM_ZOOM, '<f')[0]:.3f}")
    print("left-click in the game; columns: OS cursor | game px | OS-game (client) | ground live | ground drawn | live-drawn")
    t0, down = time.time(), False
    while time.time() - t0 < secs:
        pressed = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        if pressed and not down:
            pt = wt.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            s = state(h)
            ox, oy = (win[0], win[1]) if win else (0, 0)
            dx, dy = pt.x - ox - s["px"][0], pt.y - oy - s["px"][1]
            gl, gd = ground(viewport(h, VP_LIVE), *s["px"]), ground(viewport(h, VP_DRAWN), *s["px"])
            fmt = lambda g: "-" if g is None else f"({g[0]:.2f},{g[1]:.2f})"
            diff = "-" if gl is None or gd is None else f"{math.dist(gl[:2], gd[:2]):.3f}"
            print(f"{time.time() - t0:7.2f}s  ({pt.x},{pt.y}) | ({s['px'][0]:.0f},{s['px'][1]:.0f}) | "
                  f"({dx:+.0f},{dy:+.0f}) | {fmt(gl)} | {fmt(gd)} | {diff}", flush=True)
        down = pressed
        time.sleep(0.001)


if __name__ == "__main__":
    main()
