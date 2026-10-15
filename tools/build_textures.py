"""Texture pass: append a full mip chain to DDS files that lack one. Offline, read-only on the game dir.

Usage: python build_textures.py <game_dir> <overlay_dir> [--jobs N]                       (mip step)
       python build_textures.py hd-terrain|hd-units <game_dir> <overlay_hd_dir> [--jobs N] [--limit N]
       python build_textures.py hd-sheet <overlay_hd_dir> <out.png>                           (before/after sheet)
The hd-* steps (2x upscale, see docs/textures-hd.md) live in the HD section at the end of this file.
Output: <overlay>/Data/<same relative path>.dds and <overlay>/manifest.json.
Level 0 (and any existing top level data) is copied byte for byte from the source; only the missing levels
are generated (DXT via texconv from the decoded top level, uncompressed via a 2x2 box filter in numpy).
The header is the source header with the mip count and flags patched. Alpha is never premultiplied.
"""
import hashlib, json, os, re, struct, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from raf_proc import NO_WINDOW  # no console window per texconv/ESRGAN call from the windowed setup

TAG = "may2026"
TEXCONV_SHA256 = "dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06"
URL = f"https://github.com/microsoft/DirectXTex/releases/download/{TAG}/texconv.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXCONV = os.path.join(ROOT, "work", "tools", "texconv.exe")
BS = {"DXT1": 8, "DXT3": 16, "DXT5": 16}

UI_NAME = re.compile(r"^(but_|act_|3dui_|3pui_|ub_|circle_|square_|cur_|ui_|frm_|alertt|chataltert|outpostaltert|"
                     r"glory|gold|wood|population|powerup|spbanner|uicontrols|se buttons|unit facing|tinysilver|"
                     r"miscicons|ypopup|debug)")
UI_ANY = re.compile(r"font|cursor|minimap|mini_|icon|border|button|banner|thumb|test")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def ensure_texconv():
    if not os.path.exists(TEXCONV):
        os.makedirs(os.path.dirname(TEXCONV), exist_ok=True)
        urllib.request.urlretrieve(URL, TEXCONV + ".part")
        os.replace(TEXCONV + ".part", TEXCONV)
    got = sha(open(TEXCONV, "rb").read())
    if got != TEXCONV_SHA256:
        sys.exit(f"texconv sha256 mismatch: {got}")


def header(b):
    """Parse a DDS header (legacy 128 bytes, DX10 extension noted); None if not a DDS."""
    if len(b) < 128 or b[:4] != b"DDS ":
        return None
    h, w, _, _, mips = struct.unpack_from("<5I", b, 12)
    pff, fcc, bpp, rm, gm, bm, am = struct.unpack_from("<7I", b, 80)
    caps2 = struct.unpack_from("<I", b, 112)[0]
    fcc = fcc.to_bytes(4, "little").decode("latin1")
    return dict(w=w, h=h, mips=mips, pff=pff, fcc=fcc, bpp=bpp, masks=(rm, gm, bm, am), caps2=caps2,
                fmt=fcc if pff & 4 else f"RAW{bpp}", faces=6 if caps2 & 0x200 else 1, off=148 if fcc == "DX10" else 128)


def full_chain(w, h):
    return max(w, h).bit_length()


def levels(w, h, n, fmt, bpp):
    out = []
    for _ in range(n):
        out.append(max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BS[fmt] if fmt in BS else w * h * bpp // 8)
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def skip_reason(rel, hd):
    low = rel.lower().replace("\\", "/")
    base = os.path.basename(low)
    if hd is None or hd["fcc"] == "DX10":
        return "unsupported header"
    if "user interface" in low:
        return "ui folder"
    if UI_NAME.match(base) or UI_ANY.search(base):
        return "ui/font/cursor/test by name"
    w, h = hd["w"], hd["h"]
    if w & (w - 1) or h & (h - 1):
        return "non power of two"
    if hd["caps2"] & 0x200000:
        return "volume texture"
    if hd["faces"] == 6 and hd["caps2"] & 0xFC00 != 0xFC00:
        return "partial cube map"
    if hd["fmt"] not in BS and not (hd["pff"] & 0x40 and hd["bpp"] in (16, 24, 32)):
        return "unsupported pixel format"
    if max(1, hd["mips"]) >= full_chain(w, h):
        return "already full chain"
    return None


def box_mips(top, w, h, hd, n):
    """Uncompressed: levels 1..n-1 from raw level 0 bytes of one face (2x2 box per channel, no premultiply)."""
    bpp, masks = hd["bpp"], hd["masks"]
    px = np.frombuffer(top, np.uint8).reshape(h * w, bpp // 8).astype(np.uint32)
    v = sum(px[:, i] << (8 * i) for i in range(bpp // 8))
    ch = []
    for m in masks:
        if m:
            sh = (m & -m).bit_length() - 1
            ch.append((m, sh, ((v & m) >> sh).astype(np.float64).reshape(h, w)))
    out = []
    for _ in range(n - 1):
        nw, nh = max(1, w // 2), max(1, h // 2)
        ch = [(m, sh, a.reshape(nh, h // nh, nw, w // nw).mean(axis=(1, 3))) for m, sh, a in ch]
        w, h = nw, nh
        v = np.zeros((h, w), np.uint32)
        for m, sh, a in ch:
            v |= (np.floor(a + 0.5).astype(np.uint32) << sh) & m
        if bpp == 24:
            out.append(b"".join(int(x).to_bytes(3, "little") for x in v.ravel()))
        else:
            out.append(v.astype("<u%d" % (bpp // 8)).tobytes())
    return out


def process(rel, hd, src, tmp):
    w, h, f = hd["w"], hd["h"], hd["faces"]
    n_old, n_new = max(1, hd["mips"]), full_chain(w, h)
    old, new = levels(w, h, n_old, hd["fmt"], hd["bpp"]), levels(w, h, n_new, hd["fmt"], hd["bpp"])
    body = src[hd["off"]:]
    if len(body) != f * sum(old):
        raise ValueError(f"size mismatch: body {len(body)} != {f * sum(old)}")
    gen = []  # per face: generated levels 1..n_new-1 as one bytes object
    if hd["fmt"] in BS:
        inp = os.path.join(tmp, "in", rel)
        outd = os.path.join(tmp, "out", os.path.dirname(rel))
        os.makedirs(os.path.dirname(inp), exist_ok=True)
        os.makedirs(outd, exist_ok=True)
        h0 = bytearray(src[:128])  # level 0 only, so texconv regenerates the whole chain
        struct.pack_into("<I", h0, 28, 1)
        open(inp, "wb").write(bytes(h0) + b"".join(body[i * sum(old):i * sum(old) + old[0]] for i in range(f)))
        r = subprocess.run([TEXCONV, "-nologo", "-y", "-m", "0", "-sepalpha", "-f", hd["fmt"], "-dx9", "-o", outd, inp],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        gb = open(os.path.join(outd, os.path.basename(rel)), "rb").read()
        gh = header(gb)
        if gh is None or gh["fmt"] != hd["fmt"] or gh["mips"] != n_new or (gh["w"], gh["h"]) != (w, h):
            raise ValueError("texconv output mismatch: " + r.stdout[-200:] + r.stderr[-200:])
        gb = gb[gh["off"]:]
        if len(gb) != f * sum(new):
            raise ValueError("texconv size mismatch")
        gen = [gb[i * sum(new) + new[0]:(i + 1) * sum(new)] for i in range(f)]
    else:
        for i in range(f):
            gen.append(b"".join(box_mips(body[i * sum(old):i * sum(old) + old[0]], w, h, hd, n_new)))
    parts = [body[i * sum(old):i * sum(old) + old[0]] + gen[i] for i in range(f)]
    if any(len(p) != sum(new) for p in parts):
        raise ValueError("level size mismatch")
    hb = bytearray(src[:128])
    struct.pack_into("<I", hb, 8, struct.unpack_from("<I", hb, 8)[0] | 0x20000)       # DDSD_MIPMAPCOUNT
    struct.pack_into("<I", hb, 28, n_new)
    struct.pack_into("<I", hb, 108, struct.unpack_from("<I", hb, 108)[0] | 0x400008)  # MIPMAP | COMPLEX
    return bytes(hb) + b"".join(parts)


def dxt_mean(data, hd, level):
    """Mean RGB (opaque texels) and mean alpha of one level (face 0) of a DXT file, decoded with numpy."""
    fmt = hd["fmt"]
    sizes = levels(hd["w"], hd["h"], hd["mips"], fmt, 0)
    w, h = max(1, hd["w"] >> level), max(1, hd["h"] >> level)
    o = hd["off"] + sum(sizes[:level])
    n = max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
    b = np.frombuffer(data, np.uint8, n * BS[fmt], o).reshape(-1, BS[fmt])
    c = b[:, -8:]
    c0 = c[:, 0].astype(np.uint32) | c[:, 1].astype(np.uint32) << 8
    c1 = c[:, 2].astype(np.uint32) | c[:, 3].astype(np.uint32) << 8

    def rgb(x):
        return np.stack([(x >> 11 & 31) * 255 / 31, (x >> 5 & 63) * 255 / 63, (x & 31) * 255 / 31], -1)
    p0, p1 = rgb(c0), rgb(c1)
    four = ((c0 > c1) | (fmt != "DXT1"))[:, None]
    pal = np.stack([p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0)], 1)
    bits = np.ascontiguousarray(c[:, 4:8]).view("<u4")[:, 0]
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    col = pal[np.arange(len(b))[:, None], idx]
    al = np.full(idx.shape, 255.0)
    if fmt == "DXT1":
        al = np.where((~four) & (idx == 3), 0.0, 255.0)
        col = np.where(al[..., None] == 0, np.nan, col)
    elif fmt == "DXT3":
        a = np.ascontiguousarray(b[:, :8]).view("<u8")[:, 0]
        al = ((a[:, None] >> (4 * np.arange(16, dtype=np.uint64))) & np.uint64(15)).astype(float) * 17.0
    else:
        a0, a1 = b[:, 0].astype(float), b[:, 1].astype(float)
        s = b[:, 2:8].astype(np.uint64)
        bits = sum(s[:, i] << np.uint64(8 * i) for i in range(6))
        ai = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(int)
        t = np.zeros((len(b), 8))
        t[:, 0], t[:, 1] = a0, a1
        for k in range(1, 7):
            t[:, k + 1] = np.where(a0 > a1, ((7 - k) * a0 + k * a1) / 7, ((6 - k) * a0 + k * a1) / 5 if k < 5 else 0)
        t[:, 7] = np.where(a0 > a1, t[:, 7], 255)
        al = t[np.arange(len(b))[:, None], ai]
    return np.nanmean(col.reshape(-1, 3), 0) if not np.isnan(col).all() else np.zeros(3), al.mean()


def validate(src, out, sh):
    ok = header(out)
    if ok is None:
        return ["bad header"]
    errs = [f"{k} changed" for k in ("w", "h", "fmt", "pff", "bpp", "masks", "faces", "caps2") if sh[k] != ok[k]]
    if ok["mips"] != full_chain(sh["w"], sh["h"]):
        errs.append("mip count")
    old = levels(sh["w"], sh["h"], max(1, sh["mips"]), sh["fmt"], sh["bpp"])
    new = levels(sh["w"], sh["h"], ok["mips"], sh["fmt"], sh["bpp"])
    sb, ob = src[128:], out[128:]
    if len(ob) != sh["faces"] * sum(new):
        errs.append("body size")
    else:
        for i in range(sh["faces"]):
            if sb[i * sum(old):i * sum(old) + old[0]] != ob[i * sum(new):i * sum(new) + new[0]]:
                errs.append(f"mip0 face{i} differs")
    if not errs and sh["fmt"] in BS and sh["w"] >= 8 and sh["h"] >= 8:
        (c0, a0), (c1, a1) = dxt_mean(out, ok, 0), dxt_mean(out, ok, 1)
        if abs(a0 - a1) > 8 or np.abs(c0 - c1).max() > 10:
            errs.append(f"mean drift mip1 rgb {np.abs(c0 - c1).max():.1f} a {abs(a0 - a1):.1f}")
    return errs


def main():
    a = sys.argv[1:]
    if a and a[0] in HD_STEPS:
        return hd_main(a)
    if a and a[0] == "hd-sheet":
        return hd_sheet(a[1], a[2])
    jobs = os.cpu_count() or 4
    if "--jobs" in a:
        i = a.index("--jobs")
        jobs = int(a[i + 1])
        del a[i:i + 2]
    game, overlay = a
    ensure_texconv()
    data = os.path.join(game, "Data")
    todo, skipped = [], []
    for d, _, fs in os.walk(data):
        for f in sorted(fs):
            if f.lower().endswith(".dds"):
                p = os.path.join(d, f)
                rel = os.path.relpath(p, data)
                src = open(p, "rb").read()
                hd = header(src)
                r = skip_reason(rel, hd)
                if r:
                    skipped.append({"file": rel.replace("\\", "/"), "reason": r})
                else:
                    todo.append((rel, hd, src))
    res, fails = [], []
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(jobs) as ex:
        def run(t):
            rel, hd, src = t
            try:
                out = process(rel, hd, src, tmp)
                return out, validate(src, out, hd)
            except Exception as exn:
                return None, [repr(exn)]
        for (rel, hd, src), (out, e) in zip(todo, ex.map(run, todo)):
            if e:
                fails.append({"file": rel, "errors": e})
                continue
            dst = os.path.join(overlay, "Data", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(out)
            res.append({"file": "Data/" + rel.replace("\\", "/"), "source_sha256": sha(src), "sha256": sha(out),
                        "format": hd["fmt"], "w": hd["w"], "h": hd["h"], "mips_before": hd["mips"],
                        "mips_after": header(out)["mips"], "src_bytes": len(src), "out_bytes": len(out)})
    reasons = {}
    for s in skipped:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    json.dump({"tool": "build_textures.py", "step": "mips", "texconv_tag": TAG, "texconv_sha256": TEXCONV_SHA256,
               "files": res, "skipped": skipped, "failed": fails},
              open(os.path.join(overlay, "manifest.json"), "w"), indent=1)
    d = sum(r["out_bytes"] - r["src_bytes"] for r in res)
    print(f"processed {len(res)}, skipped {len(skipped)} {reasons}, failed {len(fails)}, size change {d / 1e6:+.2f} MB")
    for f in fails[:20]:
        print("FAIL", f)
    sys.exit(1 if fails else 0)

# ---------------------------------------------------------------------------------------------------------
# HD section: optional 2x upscale of terrain / unit / building diffuse maps (Real-ESRGAN) and bump maps (Lanczos).
# Level 0 is upscaled 2x, the full mip chain is regenerated by texconv. Only DXT1/3/5 2D textures with a long
# side of 128..512 px are touched (nothing >= 1024, no UI, cube maps, thumbnails, shadow/alpha/test files).
# ---------------------------------------------------------------------------------------------------------
ESRGAN_TAG = "v0.2.5.0"
ESRGAN_ZIP = "realesrgan-ncnn-vulkan-20220424-windows.zip"
ESRGAN_URL = f"https://github.com/xinntao/Real-ESRGAN/releases/download/{ESRGAN_TAG}/{ESRGAN_ZIP}"
# upstream publishes no digest; this is the hash of the release asset as downloaded 2026-10-15 (size 45474481)
ESRGAN_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
ESRGAN_DIR = os.path.join(ROOT, "work", "tools", "esrgan")
ESRGAN_EXE = os.path.join(ESRGAN_DIR, "bin", "realesrgan-ncnn-vulkan.exe")
ESRGAN_MODEL = "realesrgan-x4plus"
BLEND = 0.8      # weight of the ESRGAN result; the rest is a Lanczos 2x of the source (tames hallucinated detail)
PAD = 16         # source pixels of wrap/reflect padding so the network sees no border (tiling terrain stays seamless)
HD_STEPS = {
    "hd-terrain": re.compile(r"^(trn_|sha_|grnd_)"),
    "hd-units": re.compile(r"^(men_|cav_|anml_|spc_|gun_|nav_|bld_|wall_|brg_)"),
}
HD_EXCLUDE = re.compile(r"thumb|test|shadow|_alpha|cube|envmap|sky|cloud")
BELOW_NORMAL = 0x4000


def lower_priority():
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
    except Exception:
        pass


def ensure_esrgan():
    if os.path.exists(ESRGAN_EXE):
        return
    z = os.path.join(ESRGAN_DIR, "dl.zip")
    os.makedirs(ESRGAN_DIR, exist_ok=True)
    if not os.path.exists(z):
        urllib.request.urlretrieve(ESRGAN_URL, z + ".part")
        os.replace(z + ".part", z)
    got = sha(open(z, "rb").read())
    if got != ESRGAN_SHA256:
        sys.exit(f"realesrgan zip sha256 mismatch: {got}")
    import zipfile
    zipfile.ZipFile(z).extractall(os.path.join(ESRGAN_DIR, "bin"))


def hd_select(step, rel, hd):
    """None if the file does not belong to this step; "" if it is selected; else the reason it is skipped."""
    base = os.path.basename(rel).lower()
    if os.path.dirname(rel).lower() != "textures" or not HD_STEPS[step].match(base):
        return None
    if HD_EXCLUDE.search(base):
        return "excluded by name"
    if hd is None or hd["fmt"] not in BS or hd["faces"] != 1 or hd["caps2"] & 0x200000:
        return "not a plain DXT 2D texture"
    w, h = hd["w"], hd["h"]
    if w & (w - 1) or h & (h - 1):
        return "non power of two"
    if max(w, h) >= 1024:
        return "already >= 1024"
    if max(w, h) < 128:
        return "long side < 128"
    return ""


def dilate_fill(rgb, opaque, iters=24):
    """Fill texels where opaque is False with the mean of opaque neighbours, growing outwards."""
    rgb = rgb.astype(np.float32).copy()
    op = opaque.copy()
    for _ in range(iters):
        if op.all():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(op.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    o = np.roll(op, (dy, dx), (0, 1))
                    acc += np.roll(rgb, (dy, dx), (0, 1)) * o[..., None]
                    cnt += o
        new = (~op) & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        op = op | new
    if not op.all() and op.any():
        rgb[~op] = rgb[op].mean(0)
    return rgb


def lanczos2x(arr):
    """float32 HxWxC (0..255) -> float32 2Hx2WxC using PIL Lanczos per channel."""
    from PIL import Image
    h, w = arr.shape[:2]
    ch = [np.asarray(Image.fromarray(np.ascontiguousarray(arr[..., i]), "F").resize((w * 2, h * 2), Image.LANCZOS))
          for i in range(arr.shape[2])]
    return np.stack(ch, -1)


def renormalize(rgb):
    """Bump map RGB (0..255 float): unpack to [-1,1], normalize, repack. Returns (rgb, mean length before)."""
    v = rgb / 255.0 * 2 - 1
    ln = np.sqrt((v ** 2).sum(-1, keepdims=True))
    v = np.where(ln > 1e-3, v / np.maximum(ln, 1e-3), np.array([0, 0, 1.0], np.float32))
    return (v * 0.5 + 0.5) * 255.0, float(ln.mean())


def hd_prepare(item, tmp):
    """Decode level 0 to RGBA, save padded RGB for ESRGAN (diffuse only). Returns (rgb, alpha) float arrays."""
    from PIL import Image
    rel, hd, src, idx, tiled, bump = item
    d = os.path.join(tmp, "dec")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"{idx}.dds")
    h0 = bytearray(src[:128])
    struct.pack_into("<I", h0, 28, 1)
    w, h = hd["w"], hd["h"]
    open(f, "wb").write(bytes(h0) + src[hd["off"]:hd["off"] + levels(w, h, 1, hd["fmt"], 0)[0]])
    r = subprocess.run([TEXCONV, "-nologo", "-y", "-ft", "png", "-f", "R8G8B8A8_UNORM", "-o", d, f],
                       capture_output=True, text=True, creationflags=BELOW_NORMAL | NO_WINDOW)
    im = np.asarray(Image.open(os.path.join(d, f"{idx}.png")).convert("RGBA"))
    if im.shape[:2] != (h, w):
        raise ValueError("decode size mismatch " + r.stdout[-150:])
    rgb, a = im[..., :3].astype(np.float32), im[..., 3].astype(np.float32)
    if hd["fmt"] == "DXT1" and (a < 128).any() and not bump:
        rgb = dilate_fill(rgb, a >= 128)     # DXT1 cut-out texels decode to black; do not let that bleed into edges
    if not bump:
        pad = np.pad(rgb, ((PAD, PAD), (PAD, PAD), (0, 0)), mode="wrap" if tiled else "reflect")
        os.makedirs(os.path.join(tmp, "in"), exist_ok=True)
        Image.fromarray(np.clip(pad + 0.5, 0, 255).astype(np.uint8), "RGB").save(os.path.join(tmp, "in", f"{idx}.png"))
    return rgb, a


def hd_finish(item, rgb, a, tmp):
    """Upscale one texture 2x, write the RGBA PNG, encode with texconv. Returns (dds bytes, note)."""
    from PIL import Image
    rel, hd, src, idx, tiled, bump = item
    w, h = hd["w"], hd["h"]
    base2 = lanczos2x(rgb)
    if bump:
        ml = float(np.sqrt(((rgb / 255.0 * 2 - 1) ** 2).sum(-1)).mean())
        if abs(ml - 1) <= 0.07:     # genuine unit-vector map: renormalize after filtering
            out = renormalize(base2)[0]
            note = f"bump lanczos+renorm (source mean |n| {ml:.2f})"
        else:                       # z saturated / not unit length (e.g. 1.2-1.3): renormalizing would shift the look
            out = base2
            note = f"bump lanczos only, not unit length (source mean |n| {ml:.2f})"
    else:
        big = Image.open(os.path.join(tmp, "out", f"{idx}.png")).convert("RGB")
        big = big.resize(((w + 2 * PAD) * 2, (h + 2 * PAD) * 2), Image.LANCZOS)
        big = np.asarray(big).astype(np.float32)[PAD * 2:-PAD * 2, PAD * 2:-PAD * 2]
        out = BLEND * big + (1 - BLEND) * base2
        note = f"esrgan {ESRGAN_MODEL} x{BLEND} + lanczos"
    a2 = lanczos2x(a[..., None])[..., 0]
    a2 = np.where(a2 >= 127.5, 255.0, 0.0) if hd["fmt"] == "DXT1" else a2   # DXT1: hard 1-bit edge, DXT3/5: smooth
    rgba = np.dstack([np.clip(out + 0.5, 0, 255), np.clip(a2 + 0.5, 0, 255)]).astype(np.uint8)  # straight alpha
    pdir = os.path.join(tmp, "enc_in")
    odir = os.path.join(tmp, "enc_out")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(odir, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(os.path.join(pdir, f"{idx}.png"))
    cmd = [TEXCONV, "-nologo", "-y", "-m", "0", "-sepalpha", "-f", hd["fmt"], "-dx9"]
    if bump:
        cmd += ["-bc", "u"]            # uniform weighting; perceptual weights are wrong for vectors
    r = subprocess.run(cmd + ["-o", odir, os.path.join(pdir, f"{idx}.png")], capture_output=True, text=True,
                       creationflags=BELOW_NORMAL | NO_WINDOW)
    p = os.path.join(odir, f"{idx}.dds")
    if not os.path.exists(p):
        raise ValueError("texconv failed " + r.stdout[-200:] + r.stderr[-200:])
    return open(p, "rb").read(), note


def hd_validate(src, out, sh):
    oh = header(out)
    if oh is None:
        return ["bad header"]
    errs = []
    if oh["fcc"] != sh["fcc"] or oh["fmt"] != sh["fmt"]:
        errs.append(f"format {oh['fmt']} != {sh['fmt']}")
    if (oh["w"], oh["h"]) != (sh["w"] * 2, sh["h"] * 2):
        errs.append("size not 2x")
    if oh["mips"] != full_chain(oh["w"], oh["h"]):
        errs.append(f"mip count {oh['mips']}")
    if oh["faces"] != 1 or oh["caps2"] & 0x200000:
        errs.append("faces/volume")
    if errs:
        return errs
    if len(out) - oh["off"] != sum(levels(oh["w"], oh["h"], oh["mips"], oh["fmt"], 0)):
        errs.append("body size")
    elif sh["w"] >= 8 and sh["h"] >= 8:
        (c0, a0), (c1, a1) = dxt_mean(src, sh, 0), dxt_mean(out, oh, 0)
        c3 = dxt_mean(out, oh, 3)[0]
        if np.abs(c0 - c1).max() > 18 or abs(a0 - a1) > 10:
            errs.append(f"mean drift rgb {np.abs(c0 - c1).max():.1f} a {abs(a0 - a1):.1f}")
        if np.abs(c1 - c3).max() > 14:
            errs.append("mip3 drift")
    return errs


def hd_main(a):
    step, a = a[0], a[1:]
    jobs, limit = 4, None
    for flag in ("--jobs", "--limit"):
        if flag in a:
            i = a.index(flag)
            v = int(a[i + 1])
            del a[i:i + 2]
            jobs, limit = (v, limit) if flag == "--jobs" else (jobs, v)
    game, overlay = a
    lower_priority()
    ensure_texconv()
    ensure_esrgan()
    data = os.path.join(game, "Data")
    todo, skipped = [], []
    for d, _, fs in os.walk(data):
        for f in sorted(fs):
            if not f.lower().endswith(".dds"):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, data)
            src = open(p, "rb").read()
            hd = header(src)
            r = hd_select(step, rel, hd)
            if r is None:
                continue
            if r:
                skipped.append({"file": rel.replace("\\", "/"), "reason": r})
                continue
            low = f.lower()
            todo.append([rel, hd, src, len(todo), bool(re.match(r"^(trn_|sha_|grnd_)", low)), "bump" in low])
    if limit:
        todo = todo[:limit]
    tmp = os.path.join(ROOT, "work", "cache", "hd-" + step)
    if os.path.isdir(tmp):
        import shutil
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, "out"))
    print(f"{step}: {len(todo)} textures ({sum(1 for t in todo if t[5])} bump)", flush=True)
    pre, fails = {}, []

    def prep(t):
        try:
            return hd_prepare(t, tmp)
        except Exception as e:
            return repr(e)
    with ThreadPoolExecutor(jobs) as ex:
        for t, r in zip(todo, ex.map(prep, todo)):
            if isinstance(r, str):
                fails.append({"file": t[0], "errors": [r]})
            else:
                pre[t[3]] = r
    work = [t for t in todo if t[3] in pre]
    if any(not t[5] for t in work):
        print("prepared, running ESRGAN", flush=True)
        r = subprocess.run([ESRGAN_EXE, "-i", os.path.join(tmp, "in"), "-o", os.path.join(tmp, "out"), "-n", ESRGAN_MODEL,
                            "-s", "4", "-f", "png", "-m", os.path.join(ESRGAN_DIR, "bin", "models")],
                           capture_output=True, text=True, creationflags=BELOW_NORMAL | NO_WINDOW)
        if r.returncode:
            sys.exit("esrgan failed: " + r.stderr[-300:])
    print("upscaled, encoding", flush=True)
    res = []

    def fin(t):
        try:
            out, note = hd_finish(t, *pre[t[3]], tmp)
            return out, note, hd_validate(t[2], out, t[1])
        except Exception as e:
            return None, "", [repr(e)]
    with ThreadPoolExecutor(jobs) as ex:
        for t, (out, note, e) in zip(work, ex.map(fin, work)):
            rel, hd, src = t[:3]
            if e:
                fails.append({"file": rel, "errors": e})
                continue
            dst = os.path.join(overlay, "Data", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(out)
            oh = header(out)
            res.append({"file": "Data/" + rel.replace("\\", "/"), "source_sha256": sha(src), "sha256": sha(out),
                        "format": hd["fmt"], "w": hd["w"], "h": hd["h"], "out_w": oh["w"], "out_h": oh["h"],
                        "mips_before": hd["mips"], "mips_after": oh["mips"], "src_bytes": len(src),
                        "out_bytes": len(out), "method": note})
    os.makedirs(overlay, exist_ok=True)
    json.dump({"tool": "build_textures.py", "step": step, "model": ESRGAN_MODEL, "esrgan_release": ESRGAN_TAG,
               "esrgan_zip_sha256": ESRGAN_SHA256, "blend": BLEND, "texconv_tag": TAG, "files": res,
               "skipped": skipped, "failed": fails},
              open(os.path.join(overlay, f"manifest-{step}.json"), "w"), indent=1)
    d = sum(r["out_bytes"] - r["src_bytes"] for r in res)
    print(f"{step}: wrote {len(res)}, failed {len(fails)}, skipped-by-rule {len(skipped)}, "
          f"size {sum(r['src_bytes'] for r in res) / 1e6:.1f} MB -> {sum(r['out_bytes'] for r in res) / 1e6:.1f} MB "
          f"(delta {d / 1e6:+.1f} MB)")
    for f in fails[:20]:
        print("FAIL", f)
    sys.exit(1 if fails else 0)


def hd_sheet(overlay, outpng, game=r"D:\Games\Rise and Fall"):
    """Before/after sheet (derived game art: keep it out of git). Six textures, 128 px source crop, before | after."""
    from PIL import Image
    files = []
    for st in HD_STEPS:
        mp = os.path.join(overlay, f"manifest-{st}.json")
        if not os.path.exists(mp):
            continue
        m = json.load(open(mp))["files"]
        m = [f for f in m if "bump" not in f["file"].lower()]
        files += m[len(m) // 7::max(1, len(m) // 3)][:3]
    tmp = os.path.join(ROOT, "work", "cache", "hd-sheet")
    os.makedirs(tmp, exist_ok=True)
    rows = []
    for e in files[:6]:
        pair = []
        for k, p in enumerate((os.path.join(game, e["file"]), os.path.join(overlay, e["file"]))):
            d = os.path.join(tmp, str(k))
            os.makedirs(d, exist_ok=True)
            subprocess.run([TEXCONV, "-nologo", "-y", "-ft", "png", "-f", "R8G8B8A8_UNORM", "-m", "1", "-o", d, p],
                           capture_output=True, creationflags=NO_WINDOW)
            im = Image.open(os.path.join(d, os.path.splitext(os.path.basename(p))[0] + ".png")).convert("RGB")
            s = im.width // e["w"]
            c = 128 * s
            box = ((im.width - c) // 2, (im.height - c) // 2, (im.width + c) // 2, (im.height + c) // 2)
            pair.append(im.crop(box).resize((256, 256), Image.NEAREST if s == 1 else Image.LANCZOS))
        rows.append(pair)
    sheet = Image.new("RGB", (3 * 520, 2 * 260), (60, 60, 60))
    for i, (b, h) in enumerate(rows):
        x, y = (i % 3) * 520, (i // 3) * 260
        sheet.paste(b, (x, y))
        sheet.paste(h, (x + 260, y))
    sheet.save(outpng)
    print("wrote", outpng, [e["file"] for e in files[:6]])


if __name__ == "__main__":
    main()
