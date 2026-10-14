"""Read-only DDS header inventory for Rise and Fall Data folder.

Usage: python dds_inventory.py <DataDir> <out.csv>
Parses the 128-byte DDS header (plus DX10 extension if present). Never writes into DataDir.
"""
import csv, os, struct, sys
from collections import Counter

DX10_FORMATS = {71: "BC1", 74: "BC2", 77: "BC3", 80: "BC4", 83: "BC5", 98: "BC7", 28: "RGBA8", 87: "BGRA8"}

def parse(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        hdr = f.read(128)
    if len(hdr) < 128 or hdr[:4] != b"DDS ":
        return {"ok": False, "size": size}
    h, w = struct.unpack_from("<II", hdr, 12)[0], struct.unpack_from("<I", hdr, 16)[0]
    mips = struct.unpack_from("<I", hdr, 28)[0]
    pf_flags, fourcc = struct.unpack_from("<II", hdr, 80)
    rgb_bits = struct.unpack_from("<I", hdr, 88)[0]
    caps2 = struct.unpack_from("<I", hdr, 112)[0]
    fcc = fourcc.to_bytes(4, "little").decode("latin1", "replace")
    dxgi = None
    if fcc == "DX10":
        with open(path, "rb") as f:
            f.seek(128)
            ext = f.read(20)
        dxgi = struct.unpack_from("<I", ext, 0)[0]
        fmt = DX10_FORMATS.get(dxgi, f"DXGI{dxgi}")
    elif pf_flags & 0x4:
        fmt = fcc.strip()  # DXT1/DXT3/DXT5 etc.
    elif pf_flags & 0x40:
        fmt = f"RGB{rgb_bits}"
    elif pf_flags & 0x20000:
        fmt = f"other-fourcc:{fcc}"
    else:
        fmt = f"other-flags:{pf_flags:#x}"
    return {"ok": True, "size": size, "w": w, "h": h, "mips": mips, "fmt": fmt,
            "cube": bool(caps2 & 0x200), "dxgi": dxgi}

def main():
    root, out = sys.argv[1], sys.argv[2]
    rows = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".dds"):
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root).replace("\\", "/")
                top = rel.split("/")[0] if "/" in rel else "(root)"
                info = parse(p)
                info.update({"rel": rel, "top": top, "name": fn})
                rows.append(info)
    with open(out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["rel", "top", "name", "ok", "w", "h", "mips", "fmt", "cube", "dxgi", "size"])
        for r in rows:
            wr.writerow([r.get("rel"), r["top"], r["name"], r["ok"], r.get("w"), r.get("h"),
                         r.get("mips"), r.get("fmt"), r.get("cube"), r.get("dxgi"), r["size"]])
    bad = sum(1 for r in rows if not r["ok"])
    print("files", len(rows), "bad_header", bad)

if __name__ == "__main__":
    main()
