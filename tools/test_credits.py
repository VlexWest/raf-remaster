"""Offline tests for the visible credits (tools/raf_credits.py, patcher features credits + menu-credit).
Reads the base install only; writes into a temp folder (and previews into --preview DIR); never
touches the game folder, the registry or a running game.

    python tools/test_credits.py [stock_game_dir] [--preview DIR]   (default D:/Games/Rise and Fall)

1. main menu XML: well-formed, stock text unchanged except the appended control, free form index,
   no overlap with any stock control, inside the design space, AlwaysDirty + TextParser Default
2. Language.dll (ru stock, en lang-en overlay when built): menu line + credits roll added, nothing
   else changed, LoadStringW and LoadStringA (cp1251) read the line back, roll link escaped
3. loading screen: stock picture unchanged on top, bar below, deterministic
4. patcher build_credits with and without menu-credit (temp WORK), feature default off,
   files outside the gameplay fingerprint, expected fingerprint unchanged
"""
import contextlib
import hashlib
import io
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "work" / "tools" / "py"))  # pefile
import raf_credits as rc  # noqa: E402
import raf_patch as rp  # noqa: E402

args = [a for a in sys.argv[1:]]
PREVIEW = None
if "--preview" in args:
    i = args.index("--preview")
    PREVIEW = Path(args[i + 1])
    del args[i:i + 2]
GAME = Path(args[0] if args else "D:/Games/Rise and Fall")
LANG_EN = REPO / "work" / "overlay-lang-en" / "Language.dll"
FINGERPRINT = "40f38837c783"  # release set (tools/build_installer.py FEATURES)
FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def rects(text):
    """[(FormIndex, visible, (l, r, t, b))] of every control in a form."""
    out = []
    for m in re.finditer(r"<XMLControl[^>]*>.*?</XMLControl>", text, re.S):
        c = m.group(0)
        idx = int(re.search(r'FormIndex="(\d+)"', c).group(1))
        o = re.search(r'LeftOffset="(-?\d+)" RightOffset="(-?\d+)" TopOffset="(-?\d+)" BottomOffset="(-?\d+)"', c)
        out.append((idx, 'Visible="False"' not in c, tuple(int(x) for x in o.groups())))
    return out


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


# ---------------------------------------------------------------- 1. menu XML
def xml_checks(tmp: Path):
    src = GAME / rc.MENU_XML
    dst = tmp / "menu.xml"
    rc.patch_menu_xml(src, dst)
    stock, new = src.read_bytes().decode("latin-1"), dst.read_bytes().decode("latin-1")
    try:
        root = ET.fromstring(dst.read_bytes())
        check("menu XML well-formed", True)
    except ET.ParseError as e:
        check("menu XML well-formed", False, str(e))
        return
    ctls = root.findall("XMLControl")
    check("one control added", len(ctls) == len(ET.fromstring(src.read_bytes()).findall("XMLControl")) + 1)
    nl = "\r\n" if "\r\n" in stock else "\n"
    block = rc.menu_control_xml().replace("\n", nl)
    check("stock text unchanged apart from the appended control", new.replace(block, "", 1) == stock)
    check("line endings match the stock file", ("\r\n" in new) == ("\r\n" in stock) and new.count("\r\n") in (0, new.count("\n")))
    idx = [int(c.get("FormIndex")) for c in ctls]
    check("form indices unique", len(idx) == len(set(idx)), idx)
    check("new index below NumOfControls", rc.MENU_INDEX < int(root.get("NumOfControls")))
    check("form ID still 12, NumOfControls unchanged", root.get("ID") == "12" and root.get("NumOfControls") == "20")
    mine = next(c for c in ctls if c.get("FormIndex") == str(rc.MENU_INDEX))
    check("AlwaysDirty + TextParser Default + right aligned",
          mine.get("AlwaysDirty") == "True" and mine.get("TextParser") == "Default"
          and mine.get("TextAlignment") == "RightJustify")
    lbl = mine.find("SingleLineTextLabel")
    check("label reads the menu string id", lbl is not None and lbl.get("StringTableStart") == str(rc.MENU_LINE_ID))
    check("no events on the label", mine.find("ControlEvents").get("NumOfEvents") == "0")
    vals = [c.get("Value") for c in ctls]
    check("control value unique in the form", vals.count(str(rc.MENU_VALUE)) == 1)
    r = rc.MENU_RECT
    check("inside the 1600 x 1200 design space", 0 <= r[0] < r[1] <= 1600 and 0 <= r[2] < r[3] <= int(root.get("DesignedHeight")))
    clash = [(i, v, rr) for i, v, rr in rects(stock) if overlap(r, rr) and i != 6]  # 6 = tooltip popup, moves
    check("no overlap with any stock control (visible or hidden)", not clash, clash)
    bar = [rr for i, v, rr in rects(stock) if i in (11, 12, 13, 14, 15)]
    check("sits above the bottom button bar", all(r[3] <= rr[2] for rr in bar), (r, bar))
    # refusal paths
    taken = stock.replace('FormIndex="15"', f'FormIndex="{rc.MENU_INDEX}"', 1)
    (tmp / "taken.xml").write_bytes(taken.encode("latin-1"))
    for name, data in (("form index taken refused", taken),
                       ("other form refused", stock.replace('XMLForm ID="12"', 'XMLForm ID="13"')),
                       ("no room in NumOfControls refused", stock.replace('NumOfControls="20"', 'NumOfControls="16"'))):
        (tmp / "bad.xml").write_bytes(data.encode("latin-1"))
        try:
            rc.patch_menu_xml(tmp / "bad.xml", tmp / "bad-out.xml")
            check(name, False)
        except SystemExit:
            check(name, True)
    # every UI form names its controls by FormIndex; nothing in the exe asks form 12 for index 16
    dec = REPO / "decomp" / "RiseAndFall.c"
    if dec.exists():
        txt = dec.read_text(encoding="latin-1")
        check("decomp: string id 7698 (0x1e12) not used by the exe", not re.search(r"\b0x1e12\b|\b7698\b", txt))


# ---------------------------------------------------------------- 2. Language.dll
def load_a(path, ids):
    """LoadStringA through the system ANSI code page (what the game does)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.LoadStringA.argtypes = [wintypes.HMODULE, wintypes.UINT, ctypes.c_char_p, ctypes.c_int]
    h = k.LoadLibraryExW(str(Path(path).resolve()), None, 0x2)
    buf = ctypes.create_string_buffer(8192)
    out = {}
    for sid in ids:
        n = u.LoadStringA(h, sid, buf, 8192)
        out[sid] = buf.raw[:n]
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    k.FreeLibrary(h)
    return out


def language_checks(tmp: Path):
    from build_language import Dll, verify_dll_loads
    import ctypes
    import map_texts
    import zoom_setting as zs

    line = rc.credit_line("1.2.3")
    check("credit line text", line == "Rise and Fall Remaster v1.2.3 \u00b7 thewest.cc/raf", line)
    check("credit line encodable in cp1251", line.encode("cp1251") is not None)
    others = set(zs.string_repl("ru")) | set(map_texts.string_repl("ru"))
    check("menu string id not used by zoom-setting or map texts", rc.MENU_LINE_ID not in others)
    acp = ctypes.windll.kernel32.GetACP() if sys.platform == "win32" else 0
    for lang, src in (("ru", GAME / "Language.dll"), ("en", LANG_EN)):
        if not src.exists():
            print(f"skip Language.dll {lang}: {src} not built")
            continue
        d0 = Dll(str(src))
        check(f"{lang}: id {rc.MENU_LINE_ID} free in the source DLL", rc.MENU_LINE_ID not in d0.strings)
        extra = {**zs.string_repl(lang), **map_texts.string_repl(lang)}
        for menu in (False, True):
            dst = tmp / f"Language-{lang}-{menu}.dll"
            quiet(rc.patch_language_dll, src, dst, "1.2.3", extra=extra, credits=True, menu=menu)
            d1 = Dll(str(dst))
            want = {**d0.strings, **extra}
            if menu:
                want[rc.MENU_LINE_ID] = line
            skip = (rc.COPYRIGHT_ID, rc.CREDITS_FIRST_ID, rc.CREDITS_TIME_ID)
            got = {k: v for k, v in d1.strings.items() if k not in skip}
            want = {k: v for k, v in want.items() if k not in skip}
            check(f"{lang} menu={menu}: only the expected strings changed", got == want,
                  sorted(set(got.items()) ^ set(want.items()))[:3])
            check(f"{lang} menu={menu}: menu line present only with menu-credit", (rc.MENU_LINE_ID in d1.strings) == menu)
            roll = d1.strings[rc.CREDITS_FIRST_ID]
            check(f"{lang} menu={menu}: roll link escaped for the parser", "thewest.cc//raf" in roll
                  and not re.search(r"(?<!/)/raf", roll), roll[:120])
            check(f"{lang} menu={menu}: roll keeps the stock credits after ours", roll.endswith(d0.strings[rc.CREDITS_FIRST_ID]))
            if sys.platform == "win32":
                check(f"{lang} menu={menu}: LoadStringW matches every string", verify_dll_loads(str(dst), d1.strings) == 0)
                if menu:
                    a = load_a(dst, [rc.MENU_LINE_ID])[rc.MENU_LINE_ID]
                    if acp == 1251:
                        check(f"{lang}: LoadStringA (cp1251) reads the menu line back", a == line.encode("cp1251"), a)
                    else:
                        check(f"{lang}: LoadStringA reads the menu line back (ACP {acp})",
                              a.decode(f"cp{acp}", "replace") == line, a)


# ---------------------------------------------------------------- 3. loading screen
def loadscreen_checks(tmp: Path):
    from PIL import Image

    src = GAME / "loadscreen.bmp"
    a, b = tmp / "ls1.bmp", tmp / "ls2.bmp"
    rc.loadscreen_bar(src, a, "1.0.0")
    rc.loadscreen_bar(src, b, "1.0.0")
    check("loading screen deterministic", a.read_bytes() == b.read_bytes())
    st, im = Image.open(src).convert("RGB"), Image.open(a)
    check("BMP 24-bit, uncompressed", im.format == "BMP" and im.mode == "RGB" and a.read_bytes()[30:34] == b"\0\0\0\0")
    check("size = stock + bar", im.size == (st.width, st.height + rc.BAR_H), im.size)
    check("stock picture unchanged", im.crop((0, 0, st.width, st.height)).tobytes() == st.tobytes())
    bar = im.crop((0, st.height + 1, st.width, st.height + rc.BAR_H))
    px = list(zip(*[iter(bar.tobytes())] * 3))
    lit = [p for p in px if sum(p) > 300]
    xs = [i % bar.width for i, p in enumerate(px) if sum(p) > 300]
    check("bar carries text", len(lit) > 400, len(lit))
    check("text centred and inside the bar", xs and min(xs) > 40 and max(xs) < bar.width - 40
          and abs((min(xs) + max(xs)) / 2 - bar.width / 2) < 6, (min(xs or [0]), max(xs or [0])))
    check("bar background dark", sum(1 for p in px if p == rc.BAR_BG) > len(px) * 0.7)
    if PREVIEW:
        PREVIEW.mkdir(parents=True, exist_ok=True)
        im.save(PREVIEW / "loadscreen_preview.png")
        im.resize((im.width * 2, im.height * 2), Image.NEAREST).crop((0, 860, 1280, im.height * 2)).save(
            PREVIEW / "loadscreen_bar_zoom.png")


# ---------------------------------------------------------------- 4. patcher
def patcher_checks(tmp: Path):
    check("menu-credit registered, default off", rp.FEATURES.get("menu-credit") is False)
    check("credits overlay files outside the gameplay fingerprint",
          not any(p.lower().startswith(d.lower() + "/") for p in (rc.MENU_XML, "Language.dll", "loadscreen.bmp")
                  for d in rp.GAMEPLAY_DIRS))
    old_work = rp.WORK
    rp.WORK = tmp / "work"
    try:
        for feats, menu in ((["credits"], False), (["credits", "menu-credit"], True), (["menu-credit"], False)):
            quiet(rp.build_credits, feats, GAME)
            out = rp.WORK / "overlay-credits"
            files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
            if "credits" not in feats:
                check("menu-credit without credits: Language.dll only, no menu line",
                      files == ["Language.dll"] and rc.MENU_LINE_ID not in __import__("build_language").Dll(str(out / "Language.dll")).strings, files)
                continue
            want = sorted(["Language.dll", "loadscreen.bmp"] + ([rc.MENU_XML] if menu else []))
            check(f"build_credits {feats}: files {want}", files == want, files)
            from PIL import Image
            h = Image.open(out / "loadscreen.bmp").height
            check(f"build_credits {feats}: loading screen {'bar' if menu else 'stamp'}", h == (480 + rc.BAR_H if menu else 480), h)
            if menu:
                names = (rc.MENU_XML, "Language.dll", "loadscreen.bmp")
                h1 = [hashlib.sha256((out / f).read_bytes()).hexdigest() for f in names]
                quiet(rp.build_credits, feats, GAME)
                check("build_credits deterministic (menu XML, DLL, BMP)",
                      h1 == [hashlib.sha256((out / f).read_bytes()).hexdigest() for f in names])
    finally:
        rp.WORK = old_work
    try:
        import build_installer as bi
        fp = bi.expected_fingerprint(GAME)
        check(f"expected release fingerprint unchanged ({FINGERPRINT})", fp == FINGERPRINT, fp)
    except Exception as e:  # noqa: BLE001
        print(f"skip fingerprint: {e}")


# ---------------------------------------------------------------- mock of the menu (preview only)
def menu_mock():
    """Where the line lands on a 3440x1440 screen: menu background movie frame stretched, control
    rects of the stock form, our label in Tahoma bold at the control height. A mock, not the game."""
    if not PREVIEW:
        return
    import subprocess
    from PIL import Image, ImageDraw, ImageFont
    from build_language import Dll

    W, H = 3440, 1440
    frame = PREVIEW / "menu_frame.png"
    if not frame.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "3", "-i", str(GAME / "Data/movies/Bink Main Menu.bik"),
                        "-frames:v", "1", str(frame)], check=False)
    bg = Image.open(frame).convert("RGB").resize((W, H)) if frame.exists() else Image.new("RGB", (W, H), (40, 50, 30))
    d = ImageDraw.Draw(bg)
    sx, sy = W / 1600, H / 1200
    text = (GAME / rc.MENU_XML).read_bytes().decode("latin-1")
    strings = Dll(str(GAME / "Language.dll")).strings
    for i, vis, (l, r, t, b) in rects(text):
        if not vis or i == 6:
            continue
        box = (l * sx, t * sy, r * sx, b * sy)
        d.rectangle(box, outline=(255, 80, 80), width=2)
        sid = re.search(rf'FormIndex="{i}".*?StringTableStart="(\d+)"', text, re.S)
        if i in (11, 12, 13, 14, 15) and sid:
            f = ImageFont.truetype("tahomabd.ttf", int((b - t) * sy * 0.6))
            d.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), strings.get(int(sid.group(1)), "?"),
                   font=f, fill=(20, 20, 20), anchor="mm")
    l, r, t, b = rc.MENU_RECT
    box = (l * sx, t * sy, r * sx, b * sy)
    f = ImageFont.truetype("tahoma.ttf", int((b - t) * sy * 0.85))
    line = rc.credit_line("1.0.0")
    d.text((box[2] + 2, (box[1] + box[3]) / 2 + 2), line, font=f, fill=(0, 0, 0), anchor="rm")
    d.text((box[2], (box[1] + box[3]) / 2), line, font=f, fill=(236, 222, 186), anchor="rm")
    d.rectangle(box, outline=(80, 200, 255), width=1)
    bg.save(PREVIEW / "menu_mock_3440x1440.png")
    bg.crop((W - 1400, H - 300, W, H)).save(PREVIEW / "menu_mock_corner.png")


def main():
    print(f"stock: {GAME}")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        xml_checks(t)
        language_checks(t)
        loadscreen_checks(t)
        patcher_checks(t)
    menu_mock()
    print()
    print("ALL CHECKS PASSED" if not FAILED else f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
