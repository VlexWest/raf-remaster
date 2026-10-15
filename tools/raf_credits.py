"""Remaster credits: menu line, credits roll section, loading screen, hidden signatures.

Used by raf_patch.py (feature `credits`). Everything is written into work/overlay-credits from the
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


def menu_line(version: str) -> str:
    # plain ASCII separators: the menu fonts are 8-bit and '|' renders everywhere
    return f"Remastered by {AUTHOR} | {LINK} | v{version}"


def patch_language_dll(src: Path, dst: Path, version: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_language import Dll

    d = Dll(str(src))
    repl = {}
    cr = d.strings[COPYRIGHT_ID].rstrip()
    repl[COPYRIGHT_ID] = f"{cr}   {menu_line(version)}"
    first = d.strings[CREDITS_FIRST_ID]
    repl[CREDITS_FIRST_ID] = (f"/fs48/fb\n\n\n\nRise and Fall Remaster v{version}\n\n"
                              f"/fs28Remastered by\n/fs24  {AUTHOR}\n/fs24  {LINK}\n\n\n\n") + first
    try:
        repl[CREDITS_TIME_ID] = str(int(d.strings[CREDITS_TIME_ID]) + 15000)
    except ValueError:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    d.write(str(dst), repl)


MENU_XML = "Data/user interface/main menu screen.xml"
COPYRIGHT_OFFSETS_OLD = '<ControlOffsets LeftOffset="0" RightOffset="1600" TopOffset="995" BottomOffset="1050"/>'
# The stock copyright label sits behind the menu frame; move it just above the bottom bar.
COPYRIGHT_OFFSETS_NEW = '<ControlOffsets LeftOffset="0" RightOffset="1600" TopOffset="922" BottomOffset="962"/>'


def patch_menu_xml(src: Path, dst: Path) -> None:
    text = src.read_bytes().decode("latin-1")
    if text.count(COPYRIGHT_OFFSETS_OLD) != 1:
        raise SystemExit(f"{src}: copyright label offsets not found")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(text.replace(COPYRIGHT_OFFSETS_OLD, COPYRIGHT_OFFSETS_NEW).encode("latin-1"))


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
