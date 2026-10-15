"""Draw the Rise and Fall Remaster emblem (our own artwork, no game asset) with Pillow.

    python tools/make_icon.py OUT_DIR [--preview]

Writes OUT_DIR/raf.ico (16, 20, 24, 32, 40, 48, 64, 96, 128, 256 px) for the setup, the launcher,
window icons and shortcuts, OUT_DIR/raf-header.png + raf-header-40.png (the emblem for the window header
band), OUT_DIR/check-*.png (checkbox images of the dark theme) and with --preview OUT_DIR/preview-<size>.png plus a contact sheet.

The emblem: a gold-rimmed navy shield with a gold Ionic column, flanked by laurel branches. Small
sizes get their own simplified drawing (no laurel, heavier column, 1 px rim) instead of a blurry
downscale. build_installer.py calls this at build time; nothing is stored in the repo.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
NAVY_TOP, NAVY_BOT = (27, 46, 82), (9, 17, 34)
GOLD_HI, GOLD, GOLD_LO = (250, 222, 140), (214, 170, 74), (140, 98, 36)
RIM_DARK = (70, 48, 18)
SS = 4  # supersampling factor


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def shield_points(s, inset=0.0):
    """Heater shield in an s x s box: flat top with rounded shoulders, curved sides to a point."""
    left, right, top = 0.12 * s + inset, 0.88 * s - inset, 0.07 * s + inset
    bottom = 0.95 * s - inset * 1.5
    cx = s / 2
    pts = []
    r = 0.07 * s
    for i in range(9):  # top-left shoulder
        a = math.pi + i / 8 * math.pi / 2
        pts.append((left + r + r * math.cos(a), top + r + r * math.sin(a)))
    for i in range(9):  # top-right shoulder
        a = 1.5 * math.pi + i / 8 * math.pi / 2
        pts.append((right - r + r * math.cos(a), top + r + r * math.sin(a)))
    ys = top + 0.40 * s  # straight sides down to here, then a quadratic curve to the point
    h = bottom - ys
    for side in (1, -1):
        edge = right if side == 1 else left
        rng = range(0, 25) if side == 1 else range(24, -1, -1)
        for i in rng:
            t = i / 24
            # Bezier (edge, ys) -> control (edge, ys + 0.55 h) -> (cx, bottom): a pointed heater tip
            x = (1 - t) ** 2 * edge + 2 * (1 - t) * t * edge + t * t * cx
            y = (1 - t) ** 2 * ys + 2 * (1 - t) * t * (ys + 0.55 * h) + t * t * bottom
            pts.append((x, y))
    return pts


def gradient(s, top, bot):
    g = Image.new("RGB", (1, 256))
    for y in range(256):
        g.putpixel((0, y), lerp(top, bot, y / 255))
    return g.resize((s, s))


def gold_fill(s):
    """Vertical metallic gradient: light top, darker bottom with a bright band."""
    g = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        if t < 0.35:
            c = lerp(GOLD_HI, GOLD, t / 0.35)
        elif t < 0.55:
            c = lerp(GOLD, (232, 196, 104), (t - 0.35) / 0.2)
        else:
            c = lerp((232, 196, 104), GOLD_LO, (t - 0.55) / 0.45)
        g.putpixel((0, y), c)
    return g.resize((s, s))


def column_mask(s, small=False, laurel=False):
    """Ionic column centred in the shield, as a 1-bit-ish L mask (s x s)."""
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    cx = s / 2
    if small:
        top, bot = 0.24 * s, 0.76 * s
        shaft_w = 0.20 * s
        cap_w, cap_h = 0.46 * s, 0.11 * s
        base_w, base_h = 0.44 * s, 0.10 * s
    else:
        top, bot = (0.20 * s, 0.69 * s) if laurel else (0.23 * s, 0.76 * s)
        shaft_w = 0.15 * s
        cap_w, cap_h = 0.38 * s, 0.075 * s
        base_w, base_h = 0.34 * s, 0.08 * s
    # abacus (top slab) + volutes
    d.rectangle([cx - cap_w / 2, top, cx + cap_w / 2, top + cap_h * 0.45], fill=255)
    if small:
        d.rectangle([cx - cap_w / 2, top, cx + cap_w / 2, top + cap_h], fill=255)
    else:
        vr = cap_h * 0.62
        for sx in (-1, 1):
            vx = cx + sx * (cap_w / 2 - vr * 0.75)
            vy = top + cap_h * 0.55
            d.ellipse([vx - vr, vy - vr, vx + vr, vy + vr], fill=255)
            ir = vr * 0.42
            d.ellipse([vx - ir, vy - ir, vx + ir, vy + ir], fill=0)
            d.ellipse([vx - ir * 0.45, vy - ir * 0.45, vx + ir * 0.45, vy + ir * 0.45], fill=255)
        d.rectangle([cx - cap_w / 2 + vr * 1.2, top, cx + cap_w / 2 - vr * 1.2, top + cap_h * 1.05], fill=255)
    # shaft, slightly tapered (entasis)
    st = top + cap_h * (1.0 if small else 1.1)
    sb = bot - base_h
    taper = 0.0 if small else 0.012 * s
    d.polygon([(cx - shaft_w / 2 + taper, st), (cx + shaft_w / 2 - taper, st),
               (cx + shaft_w / 2, sb), (cx - shaft_w / 2, sb)], fill=255)
    if not small:  # fluting
        for i in (-1, 0, 1):
            fx = cx + i * shaft_w * 0.27
            d.rounded_rectangle([fx - s * 0.008, st + s * 0.02, fx + s * 0.008, sb - s * 0.02], radius=s * 0.008,
                                fill=0)
    # base: torus + plinth
    d.rectangle([cx - base_w / 2 * 0.8, sb, cx + base_w / 2 * 0.8, sb + base_h * 0.45], fill=255)
    d.rectangle([cx - base_w / 2, sb + base_h * 0.5, cx + base_w / 2, bot], fill=255)
    return m


def leaf(d, x, y, length, width, angle, fill):
    pts = []
    for i in range(21):
        t = i / 20
        u = length * t
        v = width * math.sin(math.pi * t) * (1 - 0.35 * t)
        pts.append((u, v))
    pts += [(u, -v) for u, v in reversed(pts[1:-1])]
    ca, sa = math.cos(angle), math.sin(angle)
    d.polygon([(x + u * ca - v * sa, y + u * sa + v * ca) for u, v in pts], fill=fill)


def laurel_mask(s):
    """Two laurel branches curving up along the shield sides, meeting under the column."""
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    cx = s / 2
    for side in (-1, 1):
        # stem: arc from the bottom centre up the side
        stem = []
        for i in range(31):
            t = i / 30
            a = math.radians(100 - 120 * t)  # from below centre round to the upper side
            r = 0.30 * s
            stem.append((cx + side * r * math.cos(a) * 0.95 - side * 0.0, 0.50 * s + r * math.sin(a) * 1.02))
        d.line(stem, fill=255, width=max(1, int(0.012 * s)))
        for k in range(1, 8):
            t = k / 8
            i = int(t * 30)
            x, y = stem[i]
            x2, y2 = stem[min(30, i + 1)]
            tang = math.atan2(y2 - y, x2 - x)
            ln = 0.075 * s * (1 - 0.25 * t)
            w = 0.024 * s * (1 - 0.2 * t)
            leaf(d, x, y, ln, w, tang - side * 0.75 * 1, 255)  # outer leaf
            leaf(d, x, y, ln * 0.85, w * 0.9, tang + side * 0.65, 255)  # inner leaf
        tx, ty = stem[-1]
        leaf(d, tx, ty, 0.07 * s, 0.022 * s, math.atan2(stem[-1][1] - stem[-2][1], stem[-1][0] - stem[-2][0]), 255)
    return m


def emblem(size: int) -> Image.Image:
    small = size <= 32
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    outer = Image.new("L", (s, s), 0)
    ImageDraw.Draw(outer).polygon(shield_points(s), fill=255)
    rim = max(SS * 1.0, s * (0.055 if small else 0.045))
    inner = Image.new("L", (s, s), 0)
    ImageDraw.Draw(inner).polygon(shield_points(s, inset=rim), fill=255)
    # shadow line just inside the rim (depth), skipped at tiny sizes
    if not small:
        dark = Image.new("L", (s, s), 0)
        ImageDraw.Draw(dark).polygon(shield_points(s, inset=rim * 0.72), fill=255)
        img.paste(Image.new("RGBA", (s, s), RIM_DARK + (255,)), (0, 0), outer)
        img.paste(gold_fill(s).convert("RGBA"), (0, 0), ImageChops.subtract(outer, dark))
        img.paste(Image.new("RGBA", (s, s), RIM_DARK + (255,)), (0, 0), ImageChops.subtract(dark, inner))
    else:
        img.paste(gold_fill(s).convert("RGBA"), (0, 0), outer)
    field = gradient(s, NAVY_TOP, NAVY_BOT).convert("RGBA")
    img.paste(field, (0, 0), inner)
    if not small:  # soft light from the top left on the field
        glow = Image.new("L", (s, s), 0)
        ImageDraw.Draw(glow).ellipse([-0.2 * s, -0.35 * s, 0.75 * s, 0.55 * s], fill=46)
        glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(s * 0.08)), inner)
        img.paste(Image.new("RGBA", (s, s), (120, 150, 210, 255)), (0, 0), glow)
    laurel = size >= 96
    col = column_mask(s, small, laurel)
    if laurel:
        col = ImageChops.lighter(col, laurel_mask(s))
    col = ImageChops.multiply(col, inner)
    if not small:  # engraved shadow under the gold
        sh = col.filter(ImageFilter.GaussianBlur(s * 0.012))
        sh = ImageChops.offset(sh, int(s * 0.008), int(s * 0.012))
        img.paste(Image.new("RGBA", (s, s), (0, 0, 0, 255)), (0, 0), ImageChops.multiply(sh, inner).point(
            lambda v: v * 0.6))
    img.paste(gold_fill(s).convert("RGBA"), (0, 0), col)
    out = img.resize((size, size), Image.LANCZOS)
    return out


def checkbox(on: bool, disabled=False, size=18) -> Image.Image:
    """Checkbox indicator images for the dark ttk theme (raf_ui): rounded box, gold when ticked."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [SS, SS, s - SS - 1, s - SS - 1]
    if on:
        fill = (120, 104, 70) if disabled else GOLD
        d.rounded_rectangle(box, radius=3 * SS, fill=fill + (255,))
        pts = [(0.27 * s, 0.52 * s), (0.44 * s, 0.68 * s), (0.75 * s, 0.33 * s)]
        d.line(pts, fill=(26, 20, 6, 255), width=int(2.2 * SS), joint="curve")
    else:
        d.rounded_rectangle(box, radius=3 * SS, fill=(12, 21, 40, 255),
                            outline=(43, 60, 94, 255) if not disabled else (30, 40, 60, 255), width=SS)
    return img.resize((size, size), Image.LANCZOS)


def write_all(out: Path, preview=False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    imgs = {n: emblem(n) for n in ICO_SIZES}
    ico = out / "raf.ico"
    imgs[256].save(ico, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=[imgs[n] for n in ICO_SIZES])
    emblem(80).save(out / "raf-header.png")
    emblem(40).save(out / "raf-header-40.png")
    checkbox(True).save(out / "check-on.png")
    checkbox(False).save(out / "check-off.png")
    checkbox(True, disabled=True).save(out / "check-on-dis.png")
    checkbox(False, disabled=True).save(out / "check-off-dis.png")
    files = {"ico": ico, "header": out / "raf-header.png"}
    if preview:
        sheet = Image.new("RGB", (16 + sum(n + 16 for n in ICO_SIZES), 300), (40, 40, 44))
        light = Image.new("RGB", sheet.size, (236, 236, 236))
        x = 16
        for n in ICO_SIZES:
            imgs[n].save(out / f"preview-{n}.png")
            sheet.paste(imgs[n], (x, 280 - n), imgs[n])
            light.paste(imgs[n], (x, 280 - n), imgs[n])
            x += n + 16
        both = Image.new("RGB", (sheet.width, 600))
        both.paste(sheet, (0, 0))
        both.paste(light, (0, 300))
        both.save(out / "preview-sheet.png")
        zoom = Image.new("RGB", (16 * 12 + 32 * 8 + 48, 16 * 12 + 16), (40, 40, 44))
        zoom.paste(imgs[16].resize((192, 192), Image.NEAREST), (8, 8), imgs[16].resize((192, 192), Image.NEAREST))
        zoom.paste(imgs[32].resize((256, 256), Image.NEAREST).crop((0, 0, 256, 192)), (216, 8))
        zoom.save(out / "preview-zoom.png")
    return files


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    files = write_all(Path(sys.argv[1]), preview="--preview" in sys.argv)
    print(f"icon: {files['ico']} ({', '.join(map(str, ICO_SIZES))} px)")


if __name__ == "__main__":
    main()
