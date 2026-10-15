"""Offline tests for the zoom-setting feature (tools/zoom_setting.py). Reads the base install only;
writes into a temp folder; never touches the registry or a running game.

    python tools/test_zoom_setting.py [stock_game_dir]      (default D:/Games/Rise and Fall)

1. patch sites: stock bytes, one whole instruction each, cave free and executable, revert exact
2. the cave + patched game code run in an x86 emulator (unicorn) against stubs of the engine API
   (registry, UIForm::GetControl, UISlider) - normal, failure and release paths
3. UI XML overlay: well-formed, only additions + the view distance range, form conventions
4. Language.dll strings (ru from stock, en from the lang-en overlay when built), LoadString check
5. raf_patch.set_zoom_sites transitions stock/fixed/setting/off on a copy of the exe
"""
import contextlib
import io
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "work" / "tools" / "py"))  # capstone, unicorn, pefile
import capstone  # noqa: E402
import zoom_setting as zs  # noqa: E402
import raf_patch as rp  # noqa: E402

GAME = Path(sys.argv[1] if len(sys.argv) > 1 else "D:/Games/Rise and Fall")
FAILED = []
BASE = 0x400000


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def f32(v):
    return zs.f32(v)


STOCK = (GAME / zs.EXE).read_bytes()
MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def insn_at(data, va):
    return next(MD.disasm(data[va - BASE:va - BASE + 16], va))


# ---------------------------------------------------------------- 1. static checks
def static_checks(tmp: Path):
    P = zs.patches()
    for _, va, old, new, note in P:
        cur = STOCK[va - BASE:va - BASE + len(old) // 2].hex()
        check(f"stock bytes at {va:#x} ({note})", cur == old, cur)
        check(f"patch length kept at {va:#x}", len(old) == len(new))
        if va != zs.CAVE:
            i = insn_at(STOCK, va)
            check(f"{va:#x} is one whole stock instruction ({i.mnemonic} {i.op_str})", i.size == len(old) // 2)
    cave_len = len(P[0][3]) // 2
    check("cave below its limit", zs.CAVE + cave_len <= zs.CAVE_LIMIT, hex(zs.CAVE + cave_len))
    # cave lives in .RDATA, which is RWX and raw == virtual
    import pefile
    pe = pefile.PE(data=STOCK, fast_load=True)
    sec = next(s for s in pe.sections if s.VirtualAddress + BASE <= zs.CAVE < s.VirtualAddress + BASE + s.Misc_VirtualSize)
    check("cave section is .RDATA, executable + writable",
          sec.Name.rstrip(b"\0") == b".RDATA" and sec.Characteristics & 0xA0000000 == 0xA0000000)
    check("cave section raw == virtual", sec.PointerToRawData == sec.VirtualAddress)
    check("DllCharacteristics without NX_COMPAT (no DEP opt-in)", pe.OPTIONAL_HEADER.DllCharacteristics & 0x100 == 0)
    tail = STOCK[zs.SCAN_RANGE[0] - BASE:zs.SCAN_RANGE[1] - BASE]
    check(".RDATA tail 0xCE3800-0xCE4000 is all zero in stock", tail == bytes(len(tail)))
    # nothing in the image refers into the cave (aligned or not), and no code refers into the tail
    hits, code_hits = [], []
    lo, hi = zs.CAVE, zs.CAVE + cave_len
    for i in range(len(STOCK) - 3):
        v = struct.unpack_from("<I", STOCK, i)[0]
        if lo <= v < hi:
            hits.append(hex(i + BASE))
        if zs.SCAN_RANGE[0] <= v < zs.SCAN_RANGE[1] and BASE + 0x1000 <= i + BASE < 0xCE3000:
            code_hits.append(hex(i + BASE))
    check("no 4-byte value in the stock image points into the cave", not hits, ",".join(hits[:8]))
    check("no reference from the code section into the .RDATA tail", not code_hits, ",".join(code_hits[:8]))
    # apply + revert on a copy
    (tmp / zs.EXE).write_bytes(STOCK)
    quiet(rp.byte_patches, tmp, P, True, "t")
    patched = (tmp / zs.EXE).read_bytes()
    check("patched exe differs only inside the patch sites",
          sum(a != b for a, b in zip(patched, STOCK)) <= sum(len(p[2]) // 2 for p in P) and len(patched) == len(STOCK))
    quiet(rp.byte_patches, tmp, P, True, "t")
    check("apply is idempotent", (tmp / zs.EXE).read_bytes() == patched)
    quiet(rp.byte_patches, tmp, P, False, "t")
    check("revert is byte-exact", (tmp / zs.EXE).read_bytes() == STOCK)
    # every call in the cave goes to a cave entry or a known stock function / IAT slot
    code, ent = zs.build_code()
    ok_targets = set(ent.values()) | {zs.FN_LOAD_GFX, zs.FN_SAVE_GFX}
    iat = {zs.IAT_GET_REG, zs.IAT_SET_REG, zs.IAT_GET_CONTROL, zs.IAT_SET_RANGE, zs.IAT_SET_VALUE, zs.IAT_GET_VALUE}
    bad, n = [], 0
    for i in MD.disasm(code, zs.a(zs.CODE)):
        n += i.size
        if i.mnemonic == "call":
            t = i.op_str
            if t.startswith("dword ptr ["):
                if int(t[11:-1], 16) not in iat:
                    bad.append(t)
            elif int(t, 16) not in ok_targets:
                bad.append(t)
    check("cave disassembles completely (no stray bytes)", n == len(code), f"{n} vs {len(code)}")
    check("cave calls only cave entries, FUN_006e77c0/006e7ad0 and the 6 IAT slots", not bad, str(bad))
    # the patched sites call the right entries
    for va, name in ((0x6CF731, "hook_presets"), (0x6EB2F7, "hook_load"), (0x6ECBA8, "hook_save"),
                     (0x8F4F4D, "hook_init"), (0x8F61A8, "hook_apply")):
        i = insn_at(patched, va)
        check(f"{va:#x} -> call {name}", i.mnemonic == "call" and int(i.op_str, 16) == ent[name])
    nx = [insn_at(patched, 0x8F4F52 + k).mnemonic for k in range(3)]
    check("0x8F4F52..54 are nops and 0x8F4F55 is the stock next instruction",
          nx == ["nop"] * 3 and insn_at(patched, 0x8F4F55).bytes == insn_at(STOCK, 0x8F4F55).bytes)
    # stock IAT slots carry the imports we think they do
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    names = {imp.address: imp.name.decode() for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports if imp.name}
    want = {zs.IAT_GET_REG: "?GetRegistryValue@URegistry@@QAEJJPBD0AAJ@Z",
            zs.IAT_SET_REG: "?CreateRegistryValue@URegistry@@QAEJJPBD0ABJ@Z",
            zs.IAT_GET_CONTROL: "?GetControl@UIForm@@QBEPAVUIControl@@K@Z",
            zs.IAT_SET_RANGE: "?SetRange@UISlider@@QAEXKK@Z",
            zs.IAT_SET_VALUE: "?SetCurrentRangeValue@UISlider@@QAEXJ@Z",
            zs.IAT_GET_VALUE: "?GetCurrentRangeValue@UISlider@@QBEJXZ"}
    for slot, nm in want.items():
        check(f"IAT {slot:#x} = {nm}", names.get(slot) == nm, names.get(slot))
    key = STOCK[zs.REG_KEY_STR - BASE:zs.REG_KEY_STR - BASE + 50].split(b"\0")[0]
    check("0xC608A4 is the game's registry key string", key == b"Software\\Midway Home Entertainment\\Rise and Fall")
    return patched


# ---------------------------------------------------------------- 2. emulation
class Emu:
    STUBS, FORM, SLIDER, STACK = 0x20000000, 0x30000000, 0x30001000, 0x00200000

    def __init__(self, image, fpcw=0x027F):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn import x86_const as X
        self.X = X
        u = self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(BASE, (len(image) + 0xFFF) & ~0xFFF)
        u.mem_write(BASE, image)
        u.mem_map(self.STACK - 0x10000, 0x20000)
        u.mem_map(self.STUBS, 0x1000)
        u.mem_map(self.FORM, 0x2000)
        u.reg_write(X.UC_X86_REG_FPCW, fpcw)
        self.reg = {}          # registry: name -> int
        self.reg_writes = []
        self.slider = None     # current slider value (None = form without the slider)
        self.slider_sets, self.range_sets, self.calls = [], [], []
        self.rear_on_load = 0.6
        stubs = {  # name: (iat slot or code address, bytes popped)
            "get_reg": (zs.IAT_GET_REG, 16), "set_reg": (zs.IAT_SET_REG, 16),
            "get_control": (zs.IAT_GET_CONTROL, 4), "set_range": (zs.IAT_SET_RANGE, 8),
            "set_value": (zs.IAT_SET_VALUE, 4), "get_value": (zs.IAT_GET_VALUE, 0)}
        self.by_addr = {}
        for i, (name, (slot, pop)) in enumerate(stubs.items()):
            addr = self.STUBS + 0x10 * i
            u.mem_write(addr, b"\xc2" + struct.pack("<H", pop) if pop else b"\xc3")
            u.mem_write(slot, struct.pack("<I", addr))
            self.by_addr[addr] = name
        # the wrapped stock functions become stubs too (their bodies need the whole engine)
        u.mem_write(zs.FN_LOAD_GFX, b"\xc3")
        u.mem_write(zs.FN_SAVE_GFX, b"\xb8\x34\x12\x00\x00\xc3")  # mov eax, 0x1234; ret
        self.by_addr[zs.FN_LOAD_GFX] = "load_gfx"
        self.by_addr[zs.FN_SAVE_GFX] = "save_gfx"
        u.hook_add(UC_HOOK_CODE, self._hook, begin=self.STUBS, end=self.STUBS + 0xFFF)
        u.hook_add(UC_HOOK_CODE, self._hook, begin=zs.FN_LOAD_GFX, end=zs.FN_LOAD_GFX)
        u.hook_add(UC_HOOK_CODE, self._hook, begin=zs.FN_SAVE_GFX, end=zs.FN_SAVE_GFX)

    def r(self, name):
        return self.u.reg_read(getattr(self.X, "UC_X86_REG_" + name.upper()))

    def w(self, name, v):
        self.u.reg_write(getattr(self.X, "UC_X86_REG_" + name.upper()), v)

    def d(self, addr):
        return struct.unpack("<I", self.u.mem_read(addr, 4))[0]

    def f(self, addr):
        return struct.unpack("<f", self.u.mem_read(addr, 4))[0]

    def setf(self, addr, v):
        self.u.mem_write(addr, struct.pack("<f", v))

    def cstr(self, addr):
        return bytes(self.u.mem_read(addr, 80)).split(b"\0")[0].decode()

    def _hook(self, uc, addr, size, _):
        name = self.by_addr.get(addr)
        if not name:
            return
        esp = self.r("esp")
        arg = [self.d(esp + 4 + 4 * k) for k in range(4)]
        ecx = self.r("ecx")
        self.calls.append(name)
        if name in ("get_reg", "set_reg"):
            ok = (ecx == zs.OPTIONS and arg[0] == zs.HKCU and
                  self.cstr(arg[1]) == "Software\\Midway Home Entertainment\\Rise and Fall")
            vname = self.cstr(arg[2])
            if not ok:
                self.calls.append("BAD_REG_ARGS")
            if name == "get_reg":
                if vname in self.reg:
                    self.u.mem_write(arg[3], struct.pack("<i", self.reg[vname]))
                    self.w("eax", 0)
                else:
                    self.w("eax", 2)
            else:
                self.reg[vname] = struct.unpack("<i", self.u.mem_read(arg[3], 4))[0]
                self.reg_writes.append((vname, self.reg[vname]))
                self.w("eax", 0)
        elif name == "get_control":
            if ecx != self.FORM:
                self.calls.append("BAD_FORM")
            self.w("eax", self.SLIDER if (arg[0] == zs.IDX_SLIDER and self.slider is not None) else 0)
        elif name == "set_range":
            self.range_sets.append((ecx, arg[0], arg[1]))
        elif name == "set_value":
            self.slider_sets.append((ecx, arg[0]))
            self.slider = arg[0]
        elif name == "get_value":
            if ecx != self.SLIDER:
                self.calls.append("BAD_SLIDER")
            self.w("eax", self.slider)
        elif name == "load_gfx":
            self.setf(zs.REAR_CLIP, self.rear_on_load)
            self.w("eax", 0)
        # scratch registers a real callee may clobber
        if name != "save_gfx":
            self.w("edx", 0xBADBAD)
            if name not in ("get_value",):
                self.w("ecx", 0xBADC0DE)

    REGS = ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")

    def snap(self):
        return {k: self.r(k) for k in self.REGS}

    def top(self):
        return (self.r("fpsw") >> 11) & 7

    def site(self, start, end, **regs):
        """Run the patched game code from start until end with the given registers."""
        base = {"eax": 0x11111111, "ebx": 0x22222222, "ecx": 0x33333333, "edx": 0x44444444,
                "esi": self.FORM, "edi": 0x66666666, "ebp": 0x77777777, "esp": self.STACK}
        base.update(regs)
        for k, v in base.items():
            self.w(k, v)
        before, top = self.snap(), self.top()
        self.u.emu_start(start, end, count=20000)
        return before, self.snap(), top, self.top()

    def call(self, fn, **regs):
        esp = self.STACK
        self.u.mem_write(esp, struct.pack("<I", 0xDEAD0000))
        return self.site(fn, 0xDEAD0000, esp=esp, **regs)

    def zoom(self):
        return self.f(zs.a(zs.D_ZOOM))


def expect_globals(e, z, label):
    got = [e.f(zs.a(o)) for o in (zs.D_ZOOM, zs.D_BASE, zs.D_CL0, zs.D_CL1, zs.D_CL2)]
    want = [f32(z), f32(f32(z) * f32(-6.7)), f32(f32(z) * f32(-13.2)), f32(f32(z) * f32(-17.0)), f32(f32(z) * f32(-9.8))]
    check(f"{label}: zoom {z} -> base/clamps", all(abs(g - w) < 1e-5 for g, w in zip(got, want)),
          f"{got} vs {want}")


def emulation(patched):
    for fpcw, mode in ((0x027F, "round-nearest"), (0x0E7F, "truncate")):
        print(f"-- emulation, FPU {mode}")
        e = Emu(patched, fpcw)
        expect_globals(e, zs.FALLBACK_ZOOM, "static data before load")

        # startup: registry has 200, view distance 0.6 -> floor 2.133
        e.reg["Remaster Camera Zoom"] = 200
        e.rear_on_load = 0.6
        b, a, t0, t1 = e.site(0x6EB2F7, 0x6EB2FC, esi=zs.OPTIONS, ecx=zs.OPTIONS)
        expect_globals(e, 2.0, "load 200")
        check("load: view distance raised to the zoom floor", abs(e.f(zs.REAR_CLIP) - f32(2.0) * f32(zs.FAR_PER_ZOOM)) < 1e-5,
              e.f(zs.REAR_CLIP))
        check("load: registers = stock call result (eax from FUN_006e77c0, callee-saved kept)",
              a["eax"] == 0 and all(a[k] == b[k] for k in ("ebx", "esi", "edi", "ebp", "esp")), str(a))
        check("load: FPU stack balanced", t0 == t1)
        check("load: registry key/args as the stock loader", "BAD_REG_ARGS" not in e.calls)

        # camera presets (patched FUN_006cf720 runs for real)
        cam = 0x101DBBC
        e.call(0x6CF720, ecx=cam)
        check("FUN_006cf720 writes base distance -13.4 to camera +0x20/+0x24",
              abs(e.f(cam + 0x20) - f32(-13.4)) < 1e-5 and abs(e.f(cam + 0x24) - f32(-13.4)) < 1e-5,
              f"{e.f(cam + 0x20)} {e.f(cam + 0x24)}")
        check("FUN_006cf720 other presets unchanged (43.32, 41.57, -21.56)",
              e.d(cam + 0x18) == 0x422D47AE and e.d(cam + 0x28) == 0x422647AE and e.d(cam + 0x30) == 0xC1AC7AE1)

        # distance clamps in FUN_006d32c0 (snippet 0x6D34AF..0x6D350D)
        for style, cl in ((0, -13.2), (1, -17.0), (2, -9.8)):
            lim = f32(f32(2.0) * f32(cl))
            for val, exp in ((lim * 1.5, lim), (lim * 0.5, f32(lim * 0.5)), (lim * 0.99, f32(lim * 0.99))):
                e.u.mem_write(cam + 0x130, struct.pack("<I", style))
                e.setf(Emu.STACK + 0x18, val)
                e.site(0x6D34AF, 0x6D350D, edi=cam, eax=0)
                got = struct.unpack("<f", struct.pack("<I", e.r("eax")))[0]
                check(f"clamp style {style} at zoom 2: {val:.3f} -> {exp:.3f}", abs(got - exp) < 1e-4, got)

        # options page init: slider := 4 (zoom 2.0), range 0..8, stock store kept
        e.slider = 0
        b, a, t0, t1 = e.site(0x8F4F4D, 0x8F4F55, esi=Emu.FORM)
        check("init: SetRange(0, 8) + SetCurrentRangeValue(4) on the slider",
              e.range_sets[-1:] == [(Emu.SLIDER, 0, 8)] and e.slider_sets[-1:] == [(Emu.SLIDER, 4)],
              f"{e.range_sets} {e.slider_sets}")
        check("init: stock store [esp+0x54] = 0xC71C8C", e.d(Emu.STACK + 0x54) == 0xC71C8C)
        check("init: all registers + FPU unchanged", b == a and t0 == t1, f"{b} {a}")

        # options apply: slider moved to 8 -> zoom 3.0, floor 3.2, stock store kept
        e.slider = 8
        e.setf(zs.REAR_CLIP, 1.2)  # what the stock code just took from the view distance slider
        b, a, t0, t1 = e.site(0x8F61A8, 0x8F61AD, esi=Emu.FORM, eax=0x5A5A)
        expect_globals(e, 3.0, "apply slider 8")
        check("apply: stock store [0x101DA08] = eax", e.d(0x101DA08) == 0x5A5A)
        check("apply: view distance floor 3.2", abs(e.f(zs.REAR_CLIP) - f32(3.0) * f32(zs.FAR_PER_ZOOM)) < 1e-5,
              e.f(zs.REAR_CLIP))
        check("apply: all registers + FPU unchanged", b == a and t0 == t1)
        e.call(0x6CF720, ecx=cam)
        check("after apply FUN_006cf720 (camera reset) uses -20.1", abs(e.f(cam + 0x20) - f32(-20.1)) < 1e-5,
              e.f(cam + 0x20))

        # save: writes 300, keeps FUN_006e7ad0's eax
        b, a, t0, t1 = e.site(0x6ECBA8, 0x6ECBAD, esi=zs.OPTIONS, ecx=zs.OPTIONS)
        check("save: registry Remaster Camera Zoom = 300", e.reg_writes[-1:] == [("Remaster Camera Zoom", 300)],
              str(e.reg_writes))
        check("save: eax = FUN_006e7ad0 result, callee-saved kept",
              a["eax"] == 0x1234 and all(a[k] == b[k] for k in ("ebx", "esi", "edi", "ebp", "esp")))
        check("save: FPU stack balanced", t0 == t1)

        # slider to 0 -> zoom 1.0 = stock distances; floor 1.067 below a user view distance of 1.2
        e.slider = 0
        e.setf(zs.REAR_CLIP, 1.2)
        e.site(0x8F61A8, 0x8F61AD, esi=Emu.FORM)
        expect_globals(e, 1.0, "apply slider 0")
        check("slider 0: stock -6.7 / -13.2 / -17 / -9.8",
              [e.d(zs.a(o)) for o in (zs.D_BASE, zs.D_CL0, zs.D_CL1, zs.D_CL2)] ==
              [0xC0D66666, 0xC1533333, 0xC1880000, 0xC11CCCCD])
        check("slider 0: view distance 1.2 kept (above floor)", abs(e.f(zs.REAR_CLIP) - f32(1.2)) < 1e-6)

        # failure paths
        e2 = Emu(patched, fpcw)
        e2.site(0x6EB2F7, 0x6EB2FC, esi=zs.OPTIONS)
        expect_globals(e2, zs.FALLBACK_ZOOM, "load without registry value -> fallback")
        for bad in (10, 49, 401, 5000, -250):
            e2.reg["Remaster Camera Zoom"] = bad
            e2.site(0x6EB2F7, 0x6EB2FC, esi=zs.OPTIONS)
            expect_globals(e2, zs.FALLBACK_ZOOM, f"load ignores out-of-range {bad}")
        e2.reg["Remaster Camera Zoom"] = 260  # --zoom 2.6 (off the 0.25 grid)
        e2.site(0x6EB2F7, 0x6EB2FC, esi=zs.OPTIONS)
        expect_globals(e2, 2.6, "load 260")
        e2.slider = 0
        e2.site(0x8F4F4D, 0x8F4F55, esi=Emu.FORM)
        pos = e2.slider
        check("init: 2.6 shows as slider 6 (or 7 when the FPU rounds up)", pos in (6, 7), pos)
        e2.site(0x8F61A8, 0x8F61AD, esi=Emu.FORM)
        expect_globals(e2, 2.6, "apply with the slider untouched keeps 2.6")
        # form without our slider (XML overlay missing): no-op apart from the stock store + floor
        e2.slider = None
        e2.setf(zs.REAR_CLIP, 0.6)
        b, a, _, _ = e2.site(0x8F61A8, 0x8F61AD, esi=Emu.FORM, eax=0x77)
        expect_globals(e2, 2.6, "apply without slider control keeps zoom")
        check("apply without slider: stock store done, registers kept", e2.d(0x101DA08) == 0x77 and a == b)
        n = len(e2.slider_sets)
        b, a, _, _ = e2.site(0x8F4F4D, 0x8F4F55, esi=Emu.FORM)
        check("init without slider: no slider calls, stock store done, registers kept",
              len(e2.slider_sets) == n and e2.d(Emu.STACK + 0x54) == 0xC71C8C and a == b)
        check("no bad stub arguments seen", not any(c.startswith("BAD") for c in e.calls + e2.calls),
              str([c for c in e.calls + e2.calls if c.startswith("BAD")]))
        # slider extremes and every step
        e3 = Emu(patched, fpcw)
        ok = True
        for v in range(zs.SLIDER_STEPS + 1):
            e3.slider = (v + 1) % (zs.SLIDER_STEPS + 1)  # make sure it differs from the init position
            e3.site(0x8F4F4D, 0x8F4F55, esi=Emu.FORM)
            e3.slider = v
            e3.site(0x8F61A8, 0x8F61AD, esi=Emu.FORM)
            ok &= abs(e3.zoom() - (1 + 0.25 * v)) < 1e-6
            e3.site(0x6ECBA8, 0x6ECBAD, esi=zs.OPTIONS)
            ok &= e3.reg["Remaster Camera Zoom"] == 100 + 25 * v
        check("every slider step 0..8 -> zoom 1.0..3.0 and registry 100..300", ok)


# ---------------------------------------------------------------- 3. XML
def xml_checks(tmp: Path):
    quiet(zs.build, GAME, tmp / "ov")
    src = (GAME / zs.UI_XML).read_bytes()
    out = (tmp / "ov" / zs.UI_XML).read_bytes()
    root = ET.fromstring(out)
    check("XML well-formed (ElementTree)", root.tag == "XMLForm")
    n = int(root.get("NumOfControls"))
    ctrls = root.findall("XMLControl")
    idx = [int(c.get("FormIndex")) for c in ctrls]
    vals = [int(c.get("Value")) for c in ctrls]
    stock_ctrls = ET.fromstring(src).findall("XMLControl")
    check("4 controls added", len(ctrls) == len(stock_ctrls) + 4, f"{len(ctrls)} vs {len(stock_ctrls)}")
    check("FormIndex unique and < NumOfControls", len(set(idx)) == len(idx) and max(idx) < n)
    check("new Values unique", all(vals.count(v) == 1 for v in range(zs.VAL_BASE, zs.VAL_BASE + 4)))
    new = {int(c.get("FormIndex")): c for c in ctrls if int(c.get("FormIndex")) in
           (zs.IDX_LABEL, zs.IDX_SLIDER, zs.IDX_MIN, zs.IDX_MAX)}
    sl = new[zs.IDX_SLIDER].find("HSlider")
    check("slider 0..8, page 1, help string", sl is not None and sl.get("StartRange") == "0" and
          sl.get("EndRange") == str(zs.SLIDER_STEPS) and sl.get("PageSize") == "1" and
          new[zs.IDX_SLIDER].get("HelpStringID") == str(zs.STR_HELP))
    check("all new controls on the Interface group (3)", all(c.get("GroupID") == "3" for c in new.values()))
    check("labels point at the new strings",
          [new[i].find("SingleLineTextLabel").get("StringTableStart") for i in (zs.IDX_LABEL, zs.IDX_MIN, zs.IDX_MAX)]
          == [str(zs.STR_LABEL), str(zs.STR_MIN), str(zs.STR_MAX)])
    # the new block sits in the gap between the Interface columns and overlaps no group-3 control
    def box(c):
        o = c.find("ControlOffsets")
        return [float(o.get(k)) for k in ("LeftOffset", "RightOffset", "TopOffset", "BottomOffset")]
    overl = []
    for c in stock_ctrls:
        if c.get("GroupID") == "3":
            l, r, t, b = box(c)
            for nc in new.values():
                L, R, T, B = box(nc)
                if L < r and l < R and T < b and t < B:
                    overl.append(c.get("FormIndex"))
    check("no overlap with stock Interface controls", not overl, str(overl))
    sliders = [c for c in ctrls if c.get("FormIndex") == "183"]
    check("view distance slider range 0..300", sliders and sliders[0].find("HSlider").get("EndRange") == "300")
    # textual diff: stock text minus our block and the one slider change
    t_out = out.decode("latin-1")
    start = t_out.index("\t<!--RAF Remaster Camera Distance Label-->")
    end = t_out.index("</XMLForm>")
    rest = (t_out[:start] + t_out[end:]).replace(zs.VIEW_DIST_NEW, zs.VIEW_DIST_OLD)
    check("rest of the file byte-identical to stock", rest.encode("latin-1") == src)
    check("CRLF line ends kept", b"\n" not in out.replace(b"\r\n", b""))
    # the exe only asks for form indices it knows; ours are unused by the stock code
    dec = REPO / "decomp" / "RiseAndFall.c"
    if dec.exists():
        txt = dec.read_text(encoding="utf-8", errors="replace")
        used = [i for i in (zs.IDX_LABEL, zs.IDX_SLIDER, zs.IDX_MIN, zs.IDX_MAX)
                if f",{i})" in txt.replace(" ", "") and (f"GetControl(" in txt) and
                any(f"GetControl({p},{v})" in txt.replace(" ", "") for p in ("in_EAX", "in_ECX", "in_EDX", "unaff_ESI", "unaff_EDI", "this") for v in (str(i), hex(i)))]
        check("decomp: no GetControl(form, 131..134) in the stock exe", not used, str(used))


# ---------------------------------------------------------------- 4. Language.dll
def language_checks(tmp: Path):
    import raf_credits as rc
    from build_language import Dll, verify_dll_loads
    for lang, src in (("ru", GAME / "Language.dll"), ("en", REPO / "work" / "overlay-lang-en" / "Language.dll")):
        if not src.exists():
            print(f"skip Language.dll {lang}: {src} not built")
            continue
        for credits in (False, True):
            dst = tmp / f"Language-{lang}-{credits}.dll"
            quiet(rc.patch_language_dll, src, dst, "1.0", extra=zs.string_repl(lang), credits=credits)
            d0, d1 = Dll(str(src)), Dll(str(dst))
            want = dict(d0.strings)
            want.update(zs.string_repl(lang))
            got = {k: v for k, v in d1.strings.items() if k not in (rc.COPYRIGHT_ID, rc.CREDITS_FIRST_ID, rc.CREDITS_TIME_ID)}
            want = {k: v for k, v in want.items() if k not in (rc.COPYRIGHT_ID, rc.CREDITS_FIRST_ID, rc.CREDITS_TIME_ID)}
            check(f"Language.dll {lang} credits={credits}: zoom strings added, nothing else changed", got == want)
            if sys.platform == "win32":
                bad = verify_dll_loads(str(dst), d1.strings)
                check(f"Language.dll {lang} credits={credits}: LoadString matches for all strings", bad == 0, bad)
    check("ru label", zs.STRINGS["ru"][zs.STR_LABEL] == "Отдаление камеры")
    check("en label", zs.STRINGS["en"][zs.STR_LABEL] == "Camera distance")
    try:
        zs_bad = {7700: "x"}  # occupied slot must be refused
        quiet(rc.patch_language_dll, GAME / "Language.dll", tmp / "bad.dll", "1.0", extra=zs_bad, credits=False)
        check("occupied string slot refused", False)
    except SystemExit:
        check("occupied string slot refused", True)


# ---------------------------------------------------------------- 5. patcher transitions
def patcher_checks(tmp: Path):
    g = tmp / "game"
    g.mkdir()
    (g / zs.EXE).write_bytes(STOCK)
    seq = [("fixed", 2.5), ("setting", 2.5), ("fixed", 1.5), ("setting", 3.0), ("setting", 1.0), (None, 2.5)]
    ok = True
    for mode, z in seq:
        quiet(rp.set_zoom_sites, g, mode, z)
        inst = rp.zoom_setting_installed(g)
        ok &= inst == (mode == "setting")
        data = (g / zs.EXE).read_bytes()
        if mode == "fixed":
            ok &= data[0x6CF732 - BASE:0x6CF736 - BASE] == struct.pack("<f", -6.7 * z)
    check("set_zoom_sites: fixed -> setting -> fixed -> setting -> off", ok)
    check("set_zoom_sites off: exe byte-identical to stock", (g / zs.EXE).read_bytes() == STOCK)
    quiet(rp.set_zoom_sites, g, "setting", 2.5)
    a1 = (g / zs.EXE).read_bytes()
    quiet(rp.set_zoom_sites, g, "setting", 2.0)
    check("setting is independent of --zoom (registry carries it)", (g / zs.EXE).read_bytes() == a1)
    # an unexpected byte at a site is refused
    bad = bytearray(STOCK)
    bad[0x6ECBA8 - BASE] = 0x90
    (g / zs.EXE).write_bytes(bad)
    try:
        quiet(rp.set_zoom_sites, g, "setting", 2.5)
        check("foreign bytes at a site refused", False)
    except SystemExit:
        check("foreign bytes at a site refused", True)
    check("feature registered, default off", rp.FEATURES.get("zoom-setting") is False and "zoom-setting" in rp.OVERLAYS)
    check("UI files stay out of the gameplay fingerprint",
          not any(zs.UI_XML.lower().startswith(d.lower()) for d in rp.GAMEPLAY_DIRS))


def main():
    print(f"stock: {GAME}")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        patched = static_checks(t)
        emulation(patched)
        xml_checks(t)
        language_checks(t)
        patcher_checks(t)
    print()
    print("ALL CHECKS PASSED" if not FAILED else f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
