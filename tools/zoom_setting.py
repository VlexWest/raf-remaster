"""Camera zoom as an in-game setting (feature `zoom-setting`).

The fixed `zoom` feature bakes the camera distance into two exe immediates. This module instead
puts the distance into a small code cave that reads it from the registry at startup, shows it as a
slider on the Interface page of the options screen and applies it when the player presses OK.

    python tools/zoom_setting.py build <stock_game_dir> <overlay_dir>   UI XML overlay + manifest
    python tools/zoom_setting.py listing                                cave disassembly

Exe (v1.15, VA = file offset + 0x400000):
  cave         0xCE3980..  tail of the .RDATA section (RWX, zero padding after the export names,
               no code reference into 0xCE3800-0xCE3FFF; scanned in test_zoom_setting.py)
  0x6CF731     FUN_006cf720 (camera presets): mov ebx,-6.7  -> call cave (ebx = [BASE])
  0x6D34BD..   FUN_006d32c0 (camera distance): the three ZoomStyle clamps -13.2/-17/-9.8 read
               [CL0]/[CL1]/[CL2] instead of their rdata constants and immediates
  0x6EB2F7     options loader FUN_006e95d0: call FUN_006e77c0 (graphics) -> cave: same call, then
               HKCU "...\\Rise and Fall\\Remaster Camera Zoom" (DWORD, zoom x 100) -> globals
  0x6ECBA8     options saver FUN_006ebd60: call FUN_006e7ad0 -> cave: same call, then writes it
  0x8F4F4D     options Interface page init FUN_008f4e80: slider (form index 132) := zoom
  0x8F61A8     options apply FUN_008f55a0: zoom := slider; view distance floor; the stock code
               then calls camera reset FUN_006d5920(1) -> FUN_006cf720, so it applies at once
Nothing here is on a network or simulation path: camera presets, UI and registry only.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

EXE = "RiseAndFall.exe"
REG_NAME = "Remaster Camera Zoom"
UI_XML = "Data/user interface/game settings screen.xml"

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 1.0, 3.0, 0.25
SLIDER_STEPS = round((ZOOM_MAX - ZOOM_MIN) / ZOOM_STEP)  # 8
FALLBACK_ZOOM = 2.5          # used when the registry value is missing or out of range
REG_RANGE = (50, 400)        # accepted registry values (zoom 0.5 .. 4.0); --zoom can go past the slider
FAR_PER_ZOOM = 160 / 1.5 / 100  # view distance floor = this x zoom (the measured 160 at x1.5)

# form indices are free slots in game settings screen.xml (NumOfControls 191; 131-159 unused,
# no GetControl in the exe asks for them); Values are unused control ids
IDX_LABEL, IDX_SLIDER, IDX_MIN, IDX_MAX = 131, 132, 133, 134
VAL_BASE = 5131
# free string slots in Language.dll block 482 (7696-7711; 7700-7708 are the graphics strings)
STR_LABEL, STR_HELP, STR_MIN, STR_MAX = 7709, 7710, 7696, 7697
STRINGS = {
    "ru": {STR_LABEL: "Отдаление камеры",
           STR_HELP: "Насколько далеко камера может отъехать. Применяется сразу после нажатия «OK».",
           STR_MIN: "1x", STR_MAX: "3x"},
    "en": {STR_LABEL: "Camera distance",
           STR_HELP: "How far the camera can pull back. Applies as soon as you press OK.",
           STR_MIN: "1x", STR_MAX: "3x"},
}

# ---------------------------------------------------------------- exe addresses (v1.15)
IAT_GET_REG = 0xC4A830      # URegistry::GetRegistryValue(long root, char*, char*, long&)
IAT_SET_REG = 0xC4A7F4      # URegistry::CreateRegistryValue(long root, char*, char*, long const&)
IAT_GET_CONTROL = 0xC4CB50  # UIForm::GetControl(ulong) const
IAT_SET_RANGE = 0xC4BBAC    # UISlider::SetRange(ulong, ulong)
IAT_SET_VALUE = 0xC4BB60    # UISlider::SetCurrentRangeValue(long)
IAT_GET_VALUE = 0xC4CB5C    # UISlider::GetCurrentRangeValue() const
REG_KEY_STR = 0xC608A4      # "Software\\Midway Home Entertainment\\Rise and Fall"
HKCU = 0x80000001
OPTIONS = 0x101D1F0         # options object (URegistry this in the loader/saver)
REAR_CLIP = 0x101D930       # options + 0x740: RearClipPlaneModifier / 100 (far clip = this x 43.32)
FN_LOAD_GFX = 0x6E77C0
FN_SAVE_GFX = 0x6E7AD0

CAVE = 0xCE3980
CAVE_LIMIT = 0xCE3C00       # keep clear of the 0xCE3C8C / 0xCE3E8C coincidental data values
SCAN_RANGE = (0xCE3800, 0xCE4000)

# data layout
D_ZOOM, D_BASE, D_CL0, D_CL1, D_CL2, D_TMP = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
K_100, K_BASE, K_CL0, K_CL1, K_CL2, K_ONE, K_STEP, K_FAR = 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x30, 0x34
D_NAME = 0x40
CODE = 0x60
STOCK_BASE, STOCK_CL = -6.7, (-13.2, -17.0, -9.8)


def a(off):
    return CAVE + off


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def data_bytes() -> bytes:
    z = FALLBACK_ZOOM
    d = bytearray(CODE)
    vals = {D_ZOOM: z, D_BASE: STOCK_BASE * z, D_CL0: STOCK_CL[0] * z, D_CL1: STOCK_CL[1] * z,
            D_CL2: STOCK_CL[2] * z, K_100: 100.0, K_BASE: STOCK_BASE, K_CL0: STOCK_CL[0],
            K_CL1: STOCK_CL[1], K_CL2: STOCK_CL[2], K_ONE: 1.0, K_STEP: ZOOM_STEP, K_FAR: FAR_PER_ZOOM}
    for off, v in vals.items():
        struct.pack_into("<f", d, off, v)
    name = REG_NAME.encode("ascii") + b"\0"
    assert D_NAME + len(name) <= CODE
    d[D_NAME:D_NAME + len(name)] = name
    return bytes(d)


# ---------------------------------------------------------------- a tiny x86-32 assembler
class Asm:
    """Just the encodings the cave needs; every byte is checked by disassembling it again."""

    def __init__(self, origin):
        self.origin, self.b, self.labels, self.fix = origin, bytearray(), {}, []

    @property
    def here(self):
        return self.origin + len(self.b)

    def label(self, name):
        self.labels[name] = self.here

    def raw(self, *bs):
        self.b += bytes(bs)

    def u32(self, v):
        self.b += struct.pack("<I", v & 0xFFFFFFFF)

    def m(self, op: bytes, addr):  # opcode + modrm(disp32) + abs address
        self.b += op
        self.u32(addr)

    def call(self, target):
        self.raw(0xE8)
        self.u32(target - (self.here + 4))

    def call_iat(self, slot):
        self.m(b"\xff\x15", slot)

    def jcc8(self, op, name):  # short jump to a label resolved in finish()
        self.raw(op, 0)
        self.fix.append((len(self.b) - 1, name))

    def push32(self, v):
        self.raw(0x68)
        self.u32(v)

    def push8(self, v):
        assert 0 <= v < 0x80
        self.raw(0x6A, v)

    def finish(self):
        for pos, name in self.fix:
            rel = self.labels[name] - (self.origin + pos + 1)
            assert -128 <= rel < 128, name
            self.b[pos] = rel & 0xFF
        return bytes(self.b)


# opcodes (all with an absolute 32-bit address operand)
FLD, FST, FSTP = b"\xd9\x05", b"\xd9\x15", b"\xd9\x1d"
FMUL, FDIV, FSUB, FCOM = b"\xd8\x0d", b"\xd8\x35", b"\xd8\x25", b"\xd8\x15"
FILD, FISTP = b"\xdb\x05", b"\xdb\x1d"
MOV_EBX_M, CMP_EBX_M = b"\x8b\x1d", b"\x3b\x1d"
PUSHAD, POPAD, RET = 0x60, 0x61, 0xC3
JE, JNE, JL, JLE, JG, JGE = 0x74, 0x75, 0x7C, 0x7E, 0x7F, 0x7D


def build_code():
    """Returns (code bytes at CAVE+CODE, {entry name: VA})."""
    s = Asm(a(CODE))
    entries = {}

    def entry(name):
        s.label(name)
        entries[name] = s.here

    # recalc: BASE/CL0..2 = stock x ZOOM
    entry("recalc")
    for k, dst in ((K_BASE, D_BASE), (K_CL0, D_CL0), (K_CL1, D_CL1), (K_CL2, D_CL2)):
        s.m(FLD, a(D_ZOOM)); s.m(FMUL, a(k)); s.m(FSTP, a(dst))
    s.raw(RET)

    # set_from_int: eax = zoom x 100; ignored outside REG_RANGE
    entry("set_from_int")
    s.raw(0x3D); s.u32(REG_RANGE[0]); s.jcc8(JL, "sfi_out")       # cmp eax, lo; jl
    s.raw(0x3D); s.u32(REG_RANGE[1]); s.jcc8(JG, "sfi_out")       # cmp eax, hi; jg
    s.m(b"\xa3", a(D_TMP))                                         # mov [TMP], eax
    s.m(FILD, a(D_TMP)); s.m(FDIV, a(K_100)); s.m(FSTP, a(D_ZOOM))
    s.call(entries["recalc"])
    s.label("sfi_out")
    s.raw(RET)

    # far_floor: RearClip = max(RearClip, ZOOM x FAR_PER_ZOOM)
    entry("far_floor")
    s.m(FLD, a(D_ZOOM)); s.m(FMUL, a(K_FAR))
    s.m(FCOM, REAR_CLIP)
    s.raw(0xDF, 0xE0)                    # fnstsw ax
    s.raw(0xF6, 0xC4, 0x41)              # test ah, C0|C3  (st0 <= rear: keep)
    s.jcc8(JNE, "ff_keep")
    s.m(FST, REAR_CLIP)
    s.label("ff_keep")
    s.raw(0xDD, 0xD8)                    # fstp st(0)
    s.raw(RET)

    # slider_pos: eax = clamp(round((ZOOM - 1) / STEP), 0, SLIDER_STEPS)
    entry("slider_pos")
    s.m(FLD, a(D_ZOOM)); s.m(FSUB, a(K_ONE)); s.m(FDIV, a(K_STEP)); s.m(FISTP, a(D_TMP))
    s.m(b"\xa1", a(D_TMP))               # mov eax, [TMP]
    s.raw(0x85, 0xC0); s.jcc8(JGE, "sp_hi")   # test eax,eax; jge
    s.raw(0x33, 0xC0)                    # xor eax, eax
    s.label("sp_hi")
    s.raw(0x83, 0xF8, SLIDER_STEPS); s.jcc8(JLE, "sp_out")   # cmp eax, 8; jle
    s.raw(0xB8); s.u32(SLIDER_STEPS)     # mov eax, 8
    s.label("sp_out")
    s.raw(RET)

    def reg_call(slot):
        s.push32(a(D_TMP)); s.push32(a(D_NAME)); s.push32(REG_KEY_STR); s.push32(HKCU)
        s.raw(0xB9); s.u32(OPTIONS)      # mov ecx, options
        s.call_iat(slot)                 # thiscall, callee pops 16

    # hook 0x6CF731: mov ebx, [BASE]
    entry("hook_presets")
    s.m(MOV_EBX_M, a(D_BASE))
    s.raw(RET)

    # hook 0x6EB2F7: graphics settings loaded -> read our value
    entry("hook_load")
    s.call(FN_LOAD_GFX)
    s.raw(PUSHAD)
    reg_call(IAT_GET_REG)
    s.raw(0x85, 0xC0); s.jcc8(JNE, "hl_floor")    # not found: keep the fallback
    s.m(b"\xa1", a(D_TMP))
    s.call(entries["set_from_int"])
    s.label("hl_floor")
    s.call(entries["far_floor"])
    s.raw(POPAD, RET)

    # hook 0x6ECBA8: graphics settings saved -> write our value
    entry("hook_save")
    s.call(FN_SAVE_GFX)
    s.raw(PUSHAD)
    s.m(FLD, a(D_ZOOM)); s.m(FMUL, a(K_100)); s.m(FISTP, a(D_TMP))
    reg_call(IAT_SET_REG)
    s.raw(POPAD, RET)

    # hook 0x8F4F4D (8 bytes): mov dword [esp+0x54], 0xC71C8C; esi = form
    entry("hook_init")
    s.raw(0xC7, 0x44, 0x24, 0x58); s.u32(0xC71C8C)   # same store, +4 for our return address
    s.raw(PUSHAD)
    s.push32(IDX_SLIDER); s.raw(0x8B, 0xCE)          # push idx; mov ecx, esi
    s.call_iat(IAT_GET_CONTROL)
    s.raw(0x85, 0xC0); s.jcc8(JE, "hi_out")          # no slider (XML not installed)
    s.raw(0x8B, 0xF8)                                # mov edi, eax
    s.push8(SLIDER_STEPS); s.push8(0); s.raw(0x8B, 0xCF)   # SetRange(0, 8)
    s.call_iat(IAT_SET_RANGE)
    s.call(entries["slider_pos"])
    s.raw(0x50, 0x8B, 0xCF)                          # push eax; mov ecx, edi
    s.call_iat(IAT_SET_VALUE)
    s.label("hi_out")
    s.raw(POPAD, RET)

    # hook 0x8F61A8 (5 bytes): mov [0x101DA08], eax; esi = form
    entry("hook_apply")
    s.m(b"\xa3", 0x101DA08)
    s.raw(PUSHAD)
    s.push32(IDX_SLIDER); s.raw(0x8B, 0xCE)
    s.call_iat(IAT_GET_CONTROL)
    s.raw(0x85, 0xC0); s.jcc8(JE, "ha_floor")
    s.raw(0x8B, 0xC8)                                # mov ecx, eax
    s.call_iat(IAT_GET_VALUE)
    s.raw(0x8B, 0xD8)                                # mov ebx, eax
    s.call(entries["slider_pos"])
    s.raw(0x3B, 0xD8); s.jcc8(JE, "ha_floor")        # cmp ebx, eax: slider untouched -> keep exact zoom
    s.raw(0x6B, 0xC3, int(ZOOM_STEP * 100))          # imul eax, ebx, 25
    s.raw(0x83, 0xC0, int(ZOOM_MIN * 100))           # add eax, 100
    s.call(entries["set_from_int"])
    s.label("ha_floor")
    s.call(entries["far_floor"])
    s.raw(POPAD, RET)

    code = s.finish()
    assert a(CODE) + len(code) <= CAVE_LIMIT, hex(a(CODE) + len(code))
    return code, entries


def rel32(at, target, op=0xE8):
    return bytes([op]) + struct.pack("<i", target - (at + 5))


def patches():
    """(file, va, original hex, patched hex, note) in raf_patch.byte_patches() format."""
    code, e = build_code()
    blob = data_bytes() + code
    cl = (a(D_CL0), a(D_CL1), a(D_CL2))
    P = [
        (EXE, CAVE, "00" * len(blob), blob.hex(), f"zoom setting cave ({len(blob)} bytes)"),
        (EXE, 0x006CF731, "bb6666d6c0", rel32(0x6CF731, e["hook_presets"]).hex(), "camera base distance from cave"),
        (EXE, 0x006D34BD, "d81d50fbc500", "d81d" + struct.pack("<I", cl[0]).hex(), "ZoomStyle 0 clamp compare"),
        (EXE, 0x006D34CA, "b8333353c1", "a1" + struct.pack("<I", cl[0]).hex(), "ZoomStyle 0 clamp value"),
        (EXE, 0x006D34DA, "d81d54fbc500", "d81d" + struct.pack("<I", cl[1]).hex(), "ZoomStyle 1 clamp compare"),
        (EXE, 0x006D34E7, "b8000088c1", "a1" + struct.pack("<I", cl[1]).hex(), "ZoomStyle 1 clamp value"),
        (EXE, 0x006D34F7, "d81d58fbc500", "d81d" + struct.pack("<I", cl[2]).hex(), "ZoomStyle 2 clamp compare"),
        (EXE, 0x006D3502, "b8cdcc1cc1", "a1" + struct.pack("<I", cl[2]).hex(), "ZoomStyle 2 clamp value"),
        (EXE, 0x006EB2F7, "e8c4c4ffff", rel32(0x6EB2F7, e["hook_load"]).hex(), "options load: read zoom"),
        (EXE, 0x006ECBA8, "e823afffff", rel32(0x6ECBA8, e["hook_save"]).hex(), "options save: write zoom"),
        (EXE, 0x008F4F4D, "c74424548c1cc700", (rel32(0x8F4F4D, e["hook_init"]) + b"\x90" * 3).hex(),
         "options page init: zoom slider"),
        (EXE, 0x008F61A8, "a308da0101", rel32(0x8F61A8, e["hook_apply"]).hex(), "options apply: zoom slider"),
    ]
    return P


def entries():
    return build_code()[1]


# ---------------------------------------------------------------- UI XML
def _control(value, idx, body, attrs=""):
    return (f'\t<XMLControl Value="{value}" FormIndex="{idx}" GroupID="3" {attrs}>\r\n{body}'
            f'\t</XMLControl>\r\n')


def _label(value, idx, string_id, offsets, align, small):
    font = ('<ControlFont StringID="2" Value="4" Quality="High" PointSize="14" ScaledFontHeight="-1" '
            'ScaleFontToFitControl="True"/>') if small else \
           ('<ControlFont StringID="2" Value="85" Quality="High" PointSize="24" Bold="True" Shadow="True" '
            'ScaledFontHeight="-1" ScaleFontToFitControl="True"/>')
    body = ('\t\t<ControlEvents NumOfEvents="0"/>\r\n'
            f'\t\t{font}\r\n'
            '\t\t<ControlBgColor Red="0" Green="0" Blue="0"/>\r\n'
            f'\t\t<ControlOffsets {offsets}/>\r\n'
            f'\t\t<SingleLineTextLabel StringTableStart="{string_id}">\r\n'
            '\t\t\t<StringColor Red="255" Green="255" Blue="255"/>\r\n'
            '\t\t</SingleLineTextLabel>\r\n')
    return _control(value, idx, body, f'TextAlignment="{align}" TextParser="Basic"')


def _offsets(l, r, t, b):
    return f'LeftOffset="{l}" RightOffset="{r}" TopOffset="{t}" BottomOffset="{b}"'


# Interface page: both columns (267-667, 934-1334) are full down to the bottom bar, so the
# zoom block sits in the gap between them, on the first row (Side Scroll Speed | Default Camera View).
LAYOUT = {"left": 687, "right": 914, "top": 299}

VIEW_DIST_OLD = '<HSlider WidthBorderThickness="8" HeightBorderThickness="8" EndRange="60" CurrentRange="40" PageSize="15"/>'
# View distance slider: stock range 0..60 = RearClipPlaneModifier 0.6..1.2. Pressing OK in the
# options cut any larger value (the patcher writes 1.07 x zoom) back to 1.2; 0..300 = up to 3.6.
VIEW_DIST_NEW = '<HSlider WidthBorderThickness="8" HeightBorderThickness="8" EndRange="300" CurrentRange="40" PageSize="15"/>'


def build_xml(src: bytes) -> bytes:
    text = src.decode("latin-1")
    if text.count(VIEW_DIST_OLD) != 1 or text.count("</XMLForm>") != 1:
        raise SystemExit("game settings screen.xml: not the v1.15 layout (view distance slider / form end)")
    for idx in (IDX_LABEL, IDX_SLIDER, IDX_MIN, IDX_MAX):
        if f'FormIndex="{idx}"' in text:
            raise SystemExit(f"game settings screen.xml: FormIndex {idx} already used")
    for v in range(VAL_BASE, VAL_BASE + 4):
        if f'Value="{v}"' in text:
            raise SystemExit(f"game settings screen.xml: control Value {v} already used")
    l, r, t = LAYOUT["left"], LAYOUT["right"], LAYOUT["top"]
    slider_body = ('\t\t<ControlEvents NumOfEvents="0"/>\r\n'
                   '\t\t<ControlBgColor Red="0" Green="0" Blue="0"/>\r\n'
                   f'\t\t<ControlOffsets {_offsets(l, r, t + 29, t + 83)}/>\r\n'
                   '\t\t<HSlider WidthBorderThickness="8" HeightBorderThickness="8" StartRange="0" '
                   f'EndRange="{SLIDER_STEPS}" CurrentRange="{round((FALLBACK_ZOOM - ZOOM_MIN) / ZOOM_STEP)}" PageSize="1"/>\r\n')
    block = ("\t<!--RAF Remaster Camera Distance Label-->\r\n"
             + _label(VAL_BASE, IDX_LABEL, STR_LABEL, _offsets(l, r, t, t + 29), "LeftJustify", False)
             + "\t<!--RAF Remaster Camera Distance Slider-->\r\n"
             + _control(VAL_BASE + 1, IDX_SLIDER, slider_body,
                        f'TextAlignment="TopLeftJustify" HelpStringID="{STR_HELP}" BackgroundID="13"')
             + "\t<!--RAF Remaster Camera Distance Min Label-->\r\n"
             + _label(VAL_BASE + 2, IDX_MIN, STR_MIN, _offsets(l, l + 110, t + 83, t + 111), "LeftJustify", True)
             + "\t<!--RAF Remaster Camera Distance Max Label-->\r\n"
             + _label(VAL_BASE + 3, IDX_MAX, STR_MAX, _offsets(r - 110, r, t + 83, t + 111), "RightJustify", True))
    text = text.replace(VIEW_DIST_OLD, VIEW_DIST_NEW).replace("</XMLForm>", block + "</XMLForm>")
    return text.encode("latin-1")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build(stock: Path, out: Path) -> None:
    src = (Path(stock) / UI_XML).read_bytes()
    dst = Path(out) / UI_XML
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = build_xml(src)
    dst.write_bytes(data)
    manifest = {"feature": "zoom-setting",
                "files": {UI_XML: {"stock_sha256": sha256(src), "output_sha256": sha256(data)}}}
    (Path(out) / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"zoom-setting: {UI_XML} ({len(src)} -> {len(data)} bytes, sha {sha256(data)[:12]})")


def string_repl(lang: str) -> dict:
    return dict(STRINGS["en" if lang == "en" else "ru"])


def listing() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work" / "tools" / "py"))
    import capstone

    code, e = build_code()
    names = {v: k for k, v in e.items()}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = []
    for i in md.disasm(code, a(CODE)):
        if i.address in names:
            out.append(f"{names[i.address]}:")
        out.append(f"  {i.address:08x}: {i.bytes.hex():<22} {i.mnemonic} {i.op_str}")
    return "\n".join(out)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "build":
        build(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:] == ["listing"]:
        print(listing())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
