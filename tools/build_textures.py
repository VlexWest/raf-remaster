"""Texture pass: append a full mip chain to DDS files that lack one. Offline, read-only on the game dir.

Usage: python build_textures.py <game_dir> <overlay_dir> [--jobs N]
Output: <overlay>/Data/<same relative path>.dds and <overlay>/manifest.json.
Level 0 (and any existing top level data) is copied byte for byte from the source; only the missing levels
are generated (DXT via texconv from the decoded top level, uncompressed via a 2x2 box filter in numpy).
The header is the source header with the mip count and flags patched. Alpha is never premultiplied.
"""
import hashlib, json, os, re, struct, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np

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
                           capture_output=True, text=True)
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


if __name__ == "__main__":
    main()
