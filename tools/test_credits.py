"""Offline tests for the visible credits (tools/raf_credits.py, patcher features credits + menu-credit).
Reads the base install only; writes into a temp folder (and previews into --preview DIR); never
touches the game folder, the registry or a running game.

    python tools/test_credits.py [stock_game_dir] [--preview DIR]   (default D:/Games/Rise and Fall)

1. main menu XML: well-formed, stock text unchanged except the appended control, free form index,
   no overlap with any stock control, inside the design space, AlwaysDirty + TextParser Default
2. Language.dll (ru stock, en lang-en overlay when built): menu line + credits roll added, nothing
   else changed, LoadStringW and LoadStringA (cp1251) read the line back, roll link escaped
3. loading screen: stock picture unchanged on top, bar below, deterministic
4. patcher build_credits with and without menu-credit (temp WORK), feature default on,
   files outside the gameplay fingerprint, expected fingerprint unchanged
"""
import contextlib
import logging
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
FINGERPRINT = "69654d23d483"  # release set (tools/build_installer.py FEATURES)
FAILED = []
logging.getLogger("fontTools").setLevel(logging.ERROR)


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
    nl = "\r\n" if "\r\n" in stock else "\n"
    block = rc.menu_control_xml().replace("\n", nl)
    check("stock text unchanged apart from the appended controls", new.replace(block, "", 1) == stock)
    check("line endings match the stock file", ("\r\n" in new) == ("\r\n" in stock) and new.count("\r\n") in (0, new.count("\n")))
    idx = [int(c.get("FormIndex")) for c in ctls]
    check("form indices unique", len(idx) == len(set(idx)), idx)
    check("form ID still 12, NumOfControls unchanged", root.get("ID") == "12" and root.get("NumOfControls") == "20")
    check("two labels added", len(ctls) - len(rects(stock)) == len(rc.MENU_LABELS) == 2)
    bar = [rr for i, v, rr in rects(stock) if i in (11, 12, 13, 14, 15)]
    vals = [c.get("Value") for c in ctls]
    mine_rects = []
    for n, (fi, value, r, fattr, col, sid) in enumerate(rc.MENU_LABELS, 1):
        mine = next(c for c in ctls if c.get("FormIndex") == str(fi))
        check(f"label {n}: index below NumOfControls", fi < int(root.get("NumOfControls")))
        check(f"label {n}: AlwaysDirty + TextParser Default + right aligned",
              mine.get("AlwaysDirty") == "True" and mine.get("TextParser") == "Default"
              and mine.get("TextAlignment") == "RightJustify")
        lbl = mine.find("SingleLineTextLabel")
        check(f"label {n}: reads string {sid}", lbl is not None and lbl.get("StringTableStart") == str(sid))
        check(f"label {n}: no events", mine.find("ControlEvents").get("NumOfEvents") == "0")
        check(f"label {n}: control value unique in the form", vals.count(str(value)) == 1)
        f = mine.find("ControlFont")
        # the font attributes copy a stock control of the same font (StringID + Value)
        same = re.search(r'<ControlFont StringID="%s" Value="%s"' % (f.get("StringID"), f.get("Value")),
                         "".join(x.read_text(encoding="latin-1") for x in (GAME / "Data/user interface").glob("*.xml")))
        check(f"label {n}: font StringID/Value pair used by a stock control", bool(same))
        check(f"label {n}: scales to the control, shadow on", f.get("ScaleFontToFitControl") == "True" and f.get("Shadow") == "True")
        check(f"label {n}: inside the 1600 x 1200 design space",
              0 <= r[0] < r[1] <= 1600 and 0 <= r[2] < r[3] <= int(root.get("DesignedHeight")))
        clash = [(i, v, rr) for i, v, rr in rects(stock) if overlap(r, rr) and i not in (6, 8)]
        # 6 = tooltip popup (moves); 8 = stock copyright label, drawn once and covered (not AlwaysDirty)
        check(f"label {n}: no overlap with any stock control (visible or hidden)", not clash, clash)
        check(f"label {n}: inside the stone band of the frame texture (988-1046)", 988 <= r[2] and r[3] <= 1046, r)
        check(f"label {n}: above the bottom button bar", all(r[3] <= rr[2] for rr in bar), (r, bar))
        mine_rects.append(r)
    check("the two labels do not overlap each other", not overlap(*mine_rects))
    check("labels centred in the band (centre 1017 +- 3)",
          abs((mine_rects[0][2] + mine_rects[-1][3]) / 2 - 1017) <= 3, mine_rects)
    check("overlapped control 8 is the non-AlwaysDirty copyright label",
          'AlwaysDirty' not in re.search(r'<XMLControl[^>]*FormIndex="8"[^>]*>', stock).group(0))
    # refusal paths
    taken = stock.replace('FormIndex="15"', f'FormIndex="{rc.MENU_LABELS[1][0]}"', 1)
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
    menu_ids = {rc.MENU_TITLE_ID: rc.MENU_TITLE, rc.MENU_SUB_ID: rc.MENU_SUB}
    check("menu string ids not used by zoom-setting or map texts", not set(menu_ids) & others)
    check("menu texts", rc.MENU_TITLE == "RISE AND FALL REMASTER"
          and rc.MENU_SUB == "BY ALEXANDER WEST  \u00b7  thewest.cc/raf", (rc.MENU_TITLE, rc.MENU_SUB))
    from fontTools.ttLib import TTFont
    for sid, path in ((rc.MENU_TITLE_ID, GAME / "ROMIC.ttf"), (rc.MENU_SUB_ID, Path("C:/Windows/Fonts/georgiab.ttf"))):
        if path.exists():
            cmap = TTFont(str(path)).getBestCmap()
            miss = [ch for ch in menu_ids[sid] if ord(ch) not in cmap]
            check(f"every glyph of string {sid} in {path.name}", not miss, miss)
    acp = ctypes.windll.kernel32.GetACP() if sys.platform == "win32" else 0
    for lang, src in (("ru", GAME / "Language.dll"), ("en", LANG_EN)):
        if not src.exists():
            print(f"skip Language.dll {lang}: {src} not built")
            continue
        d0 = Dll(str(src))
        check(f"{lang}: menu ids free in the source DLL", not set(menu_ids) & set(d0.strings))
        extra = {**zs.string_repl(lang), **map_texts.string_repl(lang)}
        for menu in (False, True):
            dst = tmp / f"Language-{lang}-{menu}.dll"
            quiet(rc.patch_language_dll, src, dst, "1.2.3", extra=extra, credits=True, menu=menu)
            d1 = Dll(str(dst))
            want = {**d0.strings, **extra}
            if menu:
                want.update(menu_ids)
            skip = (rc.COPYRIGHT_ID, rc.CREDITS_FIRST_ID, rc.CREDITS_TIME_ID)
            got = {k: v for k, v in d1.strings.items() if k not in skip}
            want = {k: v for k, v in want.items() if k not in skip}
            check(f"{lang} menu={menu}: only the expected strings changed", got == want,
                  sorted(set(got.items()) ^ set(want.items()))[:3])
            check(f"{lang} menu={menu}: menu line present only with menu-credit", all((i in d1.strings) == menu for i in menu_ids))
            check(f"{lang} menu={menu}: copyright line stock with menu-credit, extended without",
                  (d1.strings[rc.COPYRIGHT_ID] == d0.strings[rc.COPYRIGHT_ID]) == menu)
            roll = d1.strings[rc.CREDITS_FIRST_ID]
            check(f"{lang} menu={menu}: roll link escaped for the parser", "thewest.cc//raf" in roll
                  and not re.search(r"(?<!/)/raf", roll), roll[:120])
            check(f"{lang} menu={menu}: roll keeps the stock credits after ours", roll.endswith(d0.strings[rc.CREDITS_FIRST_ID]))
            if sys.platform == "win32":
                check(f"{lang} menu={menu}: LoadStringW matches every string", verify_dll_loads(str(dst), d1.strings) == 0)
                if menu:
                    a = load_a(dst, list(menu_ids))
                    if acp == 1251:
                        check(f"{lang}: LoadStringA (cp1251) reads the menu lines back",
                              all(a[i] == s.encode("cp1251") for i, s in menu_ids.items()), a)
                    else:
                        check(f"{lang}: LoadStringA reads the menu lines back (ACP {acp})",
                              all(a[i].decode(f"cp{acp}", "replace") == s for i, s in menu_ids.items()), a)


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
    check("menu-credit registered, default on", rp.FEATURES.get("menu-credit") is True)
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
                      files == ["Language.dll"] and rc.MENU_TITLE_ID not in __import__("build_language").Dll(str(out / "Language.dll")).strings, files)
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
    """Preview of the corner at 3440x1440: the stock frame texture (1600x1200 of it = the design
    space) stretched like the game stretches the menu, the bar captions and our labels in the real
    fonts (ROMIC.ttf from the install, Georgia), GDI cell height = control height. Not a screenshot."""
    if not PREVIEW:
        return
    from fontTools.ttLib import TTFont
    from PIL import Image, ImageDraw, ImageFont
    from build_language import Dll

    W, H = 3440, 1440
    sx, sy = W / 1600, H / 1200
    tex = Image.open(GAME / "Data/textures/3DU_yMain_Backdrop.dds").convert("RGB").crop((0, 0, 1600, 1200))
    bg = tex.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(bg)
    paths = {"6": GAME / "ROMIC.ttf", "5": Path("C:/Windows/Fonts/georgiab.ttf")}  # both labels bold

    def font(sid, units):
        t = TTFont(str(paths[sid]))
        k = t["head"].unitsPerEm / (t["OS/2"].usWinAscent + t["OS/2"].usWinDescent)
        return ImageFont.truetype(str(paths[sid]), max(6, round(units * sy * k)))

    text = (GAME / rc.MENU_XML).read_bytes().decode("latin-1")
    strings = Dll(str(GAME / "Language.dll")).strings
    for i, vis, (l, r, t, b) in rects(text):
        sid = re.search(rf'FormIndex="{i}".*?StringTableStart="(\d+)"', text, re.S)
        if vis and i in (11, 12, 13, 14, 15) and sid:
            d.text(((l + r) / 2 * sx, (t + b) / 2 * sy), strings.get(int(sid.group(1)), "?"),
                   font=font("6", (b - t) * 0.72), fill=(10, 8, 6), anchor="mm")
    for (fi, value, (l, r, t, b), fattr, col, sid) in rc.MENU_LABELS:
        fs = re.search(r'StringID="(\d+)"', fattr).group(1)
        f = font(fs, b - t)
        sw = 1 if 'Bold="True"' in fattr and fs == "6" else 0  # ROMIC has no bold face: GDI emboldens
        x, y = r * sx, (t + b) / 2 * sy
        s = {rc.MENU_TITLE_ID: rc.MENU_TITLE, rc.MENU_SUB_ID: rc.MENU_SUB}[sid]
        d.text((x + 2, y + 2), s, font=f, fill=(0, 0, 0), anchor="rm", stroke_width=sw, stroke_fill=(0, 0, 0))
        d.text((x, y), s, font=f, fill=col, anchor="rm", stroke_width=sw, stroke_fill=col)
    bg.crop((W - 1500, H - 330, W, H)).save(PREVIEW / "menu_preview_corner.png")
    bg.save(PREVIEW / "menu_preview_3440x1440.png")


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
