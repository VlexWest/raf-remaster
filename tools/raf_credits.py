"""Remaster credits: menu line, credits roll section, loading screen, hidden signatures.

Used by raf_patch.py (features `credits` and `menu-credit`; tests: tools/test_credits.py). Everything is written into work/overlay-credits from the
files the install would otherwise get (stock or the English pack), so revert stays exact.
"""

import struct
import sys
from pathlib import Path

AUTHOR = "Alexander West"
LINK = "thewest.cc/raf"
SIGNATURE = "RAF Remaster by Alexander West, thewest.cc/raf"
DDS_SIG = b"RAF Remaster by Alexander West, thewest.cc"  # 42 bytes, fits dwReserved1[11] (44 bytes)

COPYRIGHT_ID = 7209      # main menu copyright line (main menu screen.xml, control 3356)
CREDITS_TIME_ID = 14012  # credits roll duration in ms (FUN_00b4e4e0 reads 14012..14240)
CREDITS_FIRST_ID = 14013
MENU_TITLE_ID = 7698     # free in stock + lang-en (block 482; zoom-setting uses 7696/7697/7709/7710)
MENU_SUB_ID = 7699
MENU_TITLE = "RISE AND FALL REMASTER"      # ROMIC.ttf (the menu button font): no '/' and no middle dot
MENU_SUB = f"BY {AUTHOR}  \u00b7  {LINK}".upper()  # Georgia Bold has both


def credit_line(version: str) -> str:
    """The loading screen bar line (the menu shows MENU_TITLE / MENU_SUB). Same in ru and en."""
    return f"Rise and Fall Remaster v{version} \u00b7 {LINK}"


def esc(text: str) -> str:
    """Escape for the Basic/Advanced text parser (LowLevelEngine UITOPGETextParser::ParseGEText):
    every '/' starts a format code (/r255, /fb ...), '//' is a literal slash."""
    return text.replace("/", "//")


def menu_line(version: str) -> str:
    # plain ASCII separators: the menu fonts are 8-bit and '|' renders everywhere
    return f"Remastered by {AUTHOR} | {LINK} | v{version}"


def patch_language_dll(src: Path, dst: Path, version: str, extra=None, credits=True, menu=False) -> None:
    """Credits strings (credits=True), the main menu lines (menu=True, MENU_TITLE_ID + MENU_SUB_ID) plus `extra`
    {string id: text} (zoom-setting labels, map texts)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_language import Dll

    d = Dll(str(src))
    repl = {}
    if credits:
        if not menu:  # with menu-credit the stock label (drawn once, under our line) stays stock
            cr = d.strings[COPYRIGHT_ID].rstrip()
            repl[COPYRIGHT_ID] = f"{cr}   {menu_line(version)}"
        first = d.strings[CREDITS_FIRST_ID]
        # the roll is parsed (TextParser Advanced): a single slash made "/raf" a format code
        repl[CREDITS_FIRST_ID] = (f"/fs48/fb\n\n\n\nRise and Fall Remaster v{version}\n\n"
                                  f"/fs28Remastered by\n/fs24  {AUTHOR}\n/fs24  {esc(LINK)}\n\n\n\n") + first
        try:
            repl[CREDITS_TIME_ID] = str(int(d.strings[CREDITS_TIME_ID]) + 15000)
        except ValueError:
            pass
    if menu:
        extra = {**(extra or {}), MENU_TITLE_ID: MENU_TITLE, MENU_SUB_ID: MENU_SUB}
    for sid, text in (extra or {}).items():
        if d.strings.get(sid, text) != text:
            raise SystemExit(f"{src}: string {sid} is already used ({d.strings[sid]!r})")
        repl[sid] = text
    dst.parent.mkdir(parents=True, exist_ok=True)
    d.write(str(dst), repl)


MENU_XML = "Data/user interface/main menu screen.xml"
# Two right-aligned lines centred in the dark stone band of the menu frame, above the gold meander
# strip and the bottom button bar (1100-1150). The frame texture 3DU_yMain_Backdrop.dds maps 1:1
# onto the form's 1600 x 1200 design space (its parchment bar = button rects 1100-1150): stone band
# 988-1046, meander 1052-1100. Live 2026-10-15 at 3440x1440: the first try (1066-1092) sat on the
# meander strip. Title in the bar buttons' font (ROMIC, StringID 6, as their Value 47 / Bold /
# Shadow), sub line in Georgia Bold capitals (StringID 5, Value 80 as the stock civ transition
# labels; live: regular Georgia in mixed case looked thin next to the ROMIC title).
# Both overlap the stock copyright label (FormIndex 8, 995-1050), which is never kept on screen
# (not AlwaysDirty) and keeps its stock text when menu-credit is on.
GOLD = (228, 194, 128)    # meander gold of the frame texture, a little darker
GOLD_DIM = (206, 176, 118)  # sub line: same gold, a little dimmer
MENU_LABELS = [  # FormIndex, control Value, (left, right, top, bottom), ControlFont attributes, colour, string id
    (16, 3390, (1100, 1555, 993, 1015),
     'StringID="6" Value="47" Quality="High" PointSize="36" Bold="True" Shadow="True"', GOLD, MENU_TITLE_ID),
    (17, 3391, (1100, 1555, 1018, 1039),
     'StringID="5" Value="80" Quality="High" PointSize="26" Bold="True" Shadow="True"', GOLD_DIM, MENU_SUB_ID),
]
# Why the stock copyright label (FormIndex 8) never showed, even when moved: LowLevelEngine
# UIControl::CopyData (0x100b8820) clears a control's dirty flag after one draw unless it is
# AlwaysDirty (XMLControl attribute -> UIControl+0xda). The menu redraws its 3D scene and movie
# every frame, so a label drawn once is gone the next frame. The visible bar buttons get the flag
# from ListBoxAlwaysDirtly (UIButton ctor), the in-game HUD sets AlwaysDirty on 315 controls.
# TextParser Default = no format codes, so the slash in the link stays one slash.
MENU_CONTROL = """\t<!--Rise and Fall Remaster credit {n} (raf-remaster)-->
\t<XMLControl Value="{value}" FormIndex="{index}" TextAlignment="RightJustify" TextParser="Default" AlwaysDirty="True">
\t\t<ControlEvents NumOfEvents="0"/>
\t\t<ControlFont {font} ScaledFontHeight="-1" ScaleFontToFitControl="True"/>
\t\t<ControlBgColor Red="0" Green="0" Blue="0"/>
\t\t<ControlOffsets LeftOffset="{l}" RightOffset="{r}" TopOffset="{t}" BottomOffset="{b}"/>
\t\t<SingleLineTextLabel StringTableStart="{sid}">
\t\t\t<StringColor Red="{c[0]}" Green="{c[1]}" Blue="{c[2]}"/>
\t\t</SingleLineTextLabel>
\t</XMLControl>
"""


def menu_control_xml() -> str:
    return "".join(MENU_CONTROL.format(n=n, value=v, index=i, l=r[0], r=r[1], t=r[2], b=r[3], font=f, c=c, sid=s)
                   for n, (i, v, r, f, c, s) in enumerate(MENU_LABELS, 1))


def patch_menu_xml(src: Path, dst: Path) -> None:
    """Append the credit labels to the main menu form (the file the install would otherwise get)."""
    import re

    text = src.read_bytes().decode("latin-1")
    m = re.search(r'<XMLForm ID="12" NumOfControls="(\d+)"', text)
    if not m or text.count("</XMLForm>") != 1:
        raise SystemExit(f"{src}: not the main menu form")
    used = {int(i) for i in re.findall(r'FormIndex="(\d+)"', text)}
    for idx, value, *_ in MENU_LABELS:
        if idx in used or idx >= int(m.group(1)):
            raise SystemExit(f"{src}: form index {idx} is not free (used {sorted(used)}, "
                             f"NumOfControls {m.group(1)})")
        if f'Value="{value}"' in text:
            raise SystemExit(f"{src}: control value {value} already used")
    nl = "\r\n" if "\r\n" in text else "\n"
    i = text.index("</XMLForm>")
    out = text[:i] + menu_control_xml().replace("\n", nl) + text[i:]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out.encode("latin-1"))


def stamp_loadscreen(src: Path, dst: Path, version: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(im)
    lines = [f"Remaster v{version} by {AUTHOR}", LINK]
    font = None
    for name in ("georgia.ttf", "times.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, max(9, im.height // 44))
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    # bottom right, two short lines in the light band right of the Midway logo (stock 640x480)
    y = im.height - 12
    for line in reversed(lines):
        w, h = draw.textbbox((0, 0), line, font=font)[2:]
        y -= h + 1
        draw.text((im.width - w - 14, y), line, font=font, fill=(96, 56, 24))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "BMP")


BAR_H = 30                 # px added below the stock 640 x 480 picture
BAR_BG = (16, 11, 6)
BAR_LINE = (176, 136, 64)  # thin gold rule, the colour of the picture's meander border
BAR_TEXT = (236, 214, 160)


def loadscreen_bar(src: Path, dst: Path, version: str) -> None:
    """Startup splash with a dark bar below the stock picture carrying credit_line().

    The splash is a popup the size of the bitmap (FUN_00709xxx: LoadImageA("loadscreen.bmp"),
    CreateWindowExA with the bitmap's width/height, WndProc 0x709680 paints with one BitBlt);
    nothing else is drawn on it, so a taller bitmap makes the window taller and covers no stock art."""
    from PIL import Image, ImageDraw, ImageFont

    pic = Image.open(src).convert("RGB")
    w, h = pic.size
    im = Image.new("RGB", (w, h + BAR_H), BAR_BG)
    im.paste(pic, (0, 0))
    draw = ImageDraw.Draw(im)
    draw.line([(0, h), (w - 1, h)], fill=BAR_LINE, width=1)
    text = credit_line(version)
    font = None
    for name in ("georgia.ttf", "times.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, 16)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - (x1 - x0)) // 2 - x0, h + 1 + (BAR_H - 1 - (y1 - y0)) // 2 - y0), text,
              font=font, fill=BAR_TEXT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "BMP")


def stamp_dds(path: Path) -> bool:
    """Write the signature into DDS_HEADER.dwReserved1 (file offset 32..75). Returns True if changed."""
    data = bytearray(path.read_bytes())
    if data[:4] != b"DDS " or len(data) < 128:
        return False
    if bytes(data[32:32 + len(DDS_SIG)]) == DDS_SIG:
        return False
    data[32:76] = DDS_SIG.ljust(44, b"\0")
    path.write_bytes(data)
    return True


def stamp_text(path: Path, comment: str) -> bool:
    """Append a // comment line (shaders, unit AI) once."""
    raw = path.read_bytes()
    if SIGNATURE.encode() in raw:
        return False
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    path.write_bytes(raw.rstrip(b"\r\n") + nl + f"// {comment}".encode("ascii") + nl)
    return True
