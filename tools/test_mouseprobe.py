"""Offline tests for the RAF-6 click-offset diagnosis and its live probe (tools/re/mouseprobe.py). Reads
the base install only; never touches the registry or a running game.

    python tools/test_mouseprobe.py [stock_game_dir]      (default D:/Games/Rise and Fall)

1. stock bytes behind the diagnosis (work/MODLOG.md "Click offset (RAF-6)"):
   DX9Rasterizer::GetUpdateMousePosition takes the DirectInput-delta branch only when
   AlwaysUpdateMousePosition (+0x7C, registry "Use Direct Input To Update Mouse") is 1 or the
   device lacks D3DCURSORCAPS_COLOR (screen +0x3CC = D3DCAPS9, +0x3E4 = CursorCaps); DXVK reports
   COLOR, so the game reads GetCursorPos. GERasterizer::GetMouseScreenLocation = this + 0x38.
   GEViewport::Convert2DPositionToWorldRay uses the view centre/half sizes at +0x374/+0x36C.
   The exe copies the live viewport 0x101CE68 to the drawn-frame copy 0xD2F748 each frame.
2. mouseprobe.ground(): pixel -> z=0 ground point through a synthetic GEViewport inverse matrix
   round-trips a forward projection (21:9 and 4:3 rects).
3. mouseprobe.state()/viewport() decode a fake process memory laid out like the game's.
"""
import math
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "re"))
from raf_patch import pe_va_to_offset  # noqa: E402

FAILED = []


def check(name, ok, info=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else '  ' + str(info)}")
    if not ok:
        FAILED.append(name)


def at(data, va, n):
    off = pe_va_to_offset(data, va)
    return bytes(data[off:off + n]).hex()


def static_checks(game):
    dx9 = (game / "DX9Rasterizer.dll").read_bytes()
    lle = (game / "LowLevelEngine.dll").read_bytes()
    exe = (game / "RiseAndFall.exe").read_bytes()
    check("GetUpdateMousePosition: cmp byte [ecx+0x7c],1 (AlwaysUpdateMousePosition)",
          at(dx9, 0x1002220B, 3) == "38517c", at(dx9, 0x1002220B, 3))
    check("GetUpdateMousePosition: test byte [screen+0x3e4],1 (D3DCAPS9.CursorCaps & COLOR) -> GetCursorPos",
          at(dx9, 0x10022225, 8) == "8490e40300007506", at(dx9, 0x10022225, 8))
    check("GetMouseScreenLocation = lea eax,[ecx+0x38]", at(lle, 0x1001E870, 4) == "8d4138c3", at(lle, 0x1001E870, 4))
    check("Convert2DPositionToWorldRay: (x - [+0x374]) / [+0x36c]",
          at(lle, 0x10065107, 6) == "d8a674030000" and at(lle, 0x10065117, 6) == "d8b66c030000")
    # 0x62E32E (render frame setup): GEViewport::operator=(0xD2F748, 0x101CE68) right after SetCamera
    pat = bytes.fromhex("6868ce0101b948f7d200")  # push 0x101ce68; mov ecx,0xd2f748
    check("exe copies viewport 0x101ce68 -> 0xd2f748 (drawn frame)", exe.count(pat) == 1, exe.count(pat))


def synth_viewport(w, h, fov_y, cam, yaw, pitch):
    """GEViewport-like dict: inverse rows = right*tanx, up*tany, forward, position (z up)."""
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    fwd = (cy * cp, sy * cp, sp)
    right = (sy, -cy, 0.0)
    up = (right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
          right[0] * fwd[1] - right[1] * fwd[0])
    ty = math.tan(fov_y / 2)
    tx = ty * w / h
    inv = [right[0] * tx, right[1] * tx, right[2] * tx, 0, up[0] * ty, up[1] * ty, up[2] * ty, 0,
           fwd[0], fwd[1], fwd[2], 0, cam[0], cam[1], cam[2], 1]
    vp = {"inv": inv, "near": 0.25, "far": 69.0, "hw": w / 2, "hh": h / 2, "xc": w / 2, "yc": h / 2}
    return vp, (right, up, fwd, tx, ty)


def project(vp, basis, cam, p):
    right, up, fwd, tx, ty = basis
    d = [p[i] - cam[i] for i in range(3)]
    z = sum(d[i] * fwd[i] for i in range(3))
    nx = sum(d[i] * right[i] for i in range(3)) / (z * tx)
    ny = sum(d[i] * up[i] for i in range(3)) / (z * ty)
    return vp["xc"] + nx * vp["hw"], vp["yc"] - ny * vp["hh"]


def ground_checks():
    import mouseprobe

    for w, h in ((3440, 1440), (1024, 768)):
        cam = (40.0, 30.0, 11.36)
        vp, basis = synth_viewport(w, h, math.radians(45), cam, math.radians(30), math.radians(-48))
        worst = 0.0
        for target in ((52.0, 38.0, 0.0), (47.5, 41.0, 0.0), (58.0, 30.0, 0.0), (49.0, 34.5, 0.0)):
            px = project(vp, basis, cam, target)
            g = mouseprobe.ground(vp, *px)
            worst = max(worst, math.dist(g, target))
        check(f"ground(): pixel -> z=0 point round-trips at {w}x{h}", worst < 1e-3, worst)
    vp, _ = synth_viewport(3440, 1440, math.radians(45), (0, 0, 10), 0, math.radians(-48))
    vp["hw"] = 0
    check("ground(): empty viewport -> None", mouseprobe.ground(vp, 10, 10) is None)


def state_checks():
    """mouseprobe.state()/viewport() against a fake process memory with the documented layout."""
    import memscan
    import mouseprobe

    mem = {}

    def put(a, fmt, *v):
        for i, byte in enumerate(struct.pack(fmt, *v)):
            mem[a + i] = byte

    R, SCR, ARR, DXS = 0x2000000, 0x2100000, 0x2200000, 0x2300000
    put(mouseprobe.RAST_PTR, "<I", R)
    put(R + 0x30, "<4f", 0.5, 0.25, 1720.0, 360.0)
    put(R + 0x40, "<I", SCR)
    put(R + 0x60, "<I", 0)
    put(R + 0x7A, "<BxB", 0, 0)
    put(R + 0x368, "<I", ARR)
    put(R + 0x374, "<I", 1)
    put(ARR, "<I", DXS)
    put(DXS + 0x3E4, "<I", 1)
    put(SCR + 0x3BC, "<4f", 1440.0, 0.0, 3440.0, 0.0)
    put(mouseprobe.VP_LIVE + 0x138, "<4f", 1440.0, 0.0, 3440.0, 0.0)
    put(mouseprobe.VP_LIVE + 0x354, "<f", 3440 / 1440)
    put(mouseprobe.VP_LIVE + 0x368, "<4f", 720.0, 1720.0, 69.0, 1720.0)
    put(mouseprobe.VP_LIVE + 0x378, "<f", 720.0)
    real = memscan.read
    memscan.read = lambda h, a, n: bytes(mem.get(a + i, 0) for i in range(n))
    try:
        s = mouseprobe.state(None)
        vp = mouseprobe.viewport(None, mouseprobe.VP_LIVE)
    finally:
        memscan.read = real
    check("state(): mouse pixel / normalized / clamp rect decoded",
          s["px"] == (1720.0, 360.0) and s["norm"] == (0.5, 0.25) and s["clamp"] == (1440.0, 0.0, 3440.0, 0.0), s)
    check("state(): CursorCaps COLOR + AlwaysUpdate 0 -> GetCursorPos branch", s["caps"] == 1 and not s["di"], s)
    check("viewport(): rect, aspect, centre, half sizes, far decoded",
          vp["rect"] == [1440.0, 0.0, 3440.0, 0.0] and abs(vp["aspect"] - 3440 / 1440) < 1e-6
          and (vp["xc"], vp["yc"], vp["hw"], vp["hh"], vp["far"]) == (1720.0, 720.0, 1720.0, 720.0, 69.0), vp)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    game = Path(args[0] if args else "D:/Games/Rise and Fall")
    static_checks(game)
    ground_checks()
    state_checks()
    print("ALL CHECKS PASSED" if not FAILED else f"{len(FAILED)} FAILED")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
