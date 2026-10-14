"""Read-only .fx (HLSL effect) inventory: size, techniques, passes, shader profiles, globals.
Usage: python fx_inventory.py <DataDir> <out.txt>
"""
import os, re, sys

TECH = re.compile(r"^\s*technique\s+(\w+)", re.I)
PASS = re.compile(r"^\s*pass\s+(\w+)", re.I)
PROF = re.compile(r"(VertexShader|PixelShader|ps|vs)\s*=?\s*compile\s+(\w+)\s+(\w+)", re.I)
PROF2 = re.compile(r"\b(vs|ps)_\d_\d\w*|\b(vs|ps)_[1-9]_[0-9]\w*", re.I)
INC = re.compile(r'#include\s+"([^"]+)"', re.I)
GLOB = re.compile(r"^\s*(uniform\s+)?(float\d?x?\d?|int|bool|half\d?|texture\w*|sampler\w*|matrix|float4x4)\s+(\w+)", re.I)
STATE = re.compile(r"^\s*(\w+)\s*=\s*(\w+)", re.I)

def main():
    root, out = sys.argv[1], sys.argv[2]
    lines_out = []
    files = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".fx"):
                files.append(os.path.join(dp, fn))
    for p in sorted(files):
        rel = os.path.relpath(p, root).replace("\\", "/")
        txt = open(p, encoding="latin1", errors="replace").read()
        techs, passes, profiles, incs, globs = [], [], set(), set(), []
        for ln in txt.splitlines():
            m = TECH.match(ln)
            if m: techs.append(m.group(1))
            m = PASS.match(ln)
            if m: passes.append(m.group(1))
            for m in PROF.finditer(ln):
                profiles.add(f"{m.group(2)}")
            for m in INC.finditer(ln):
                incs.add(m.group(1).replace("\\", "/").split("/")[-1])
            m = GLOB.match(ln)
            if m and not ln.lstrip().startswith(("//", "float4 ", "{")) and "(" not in ln:
                globs.append(m.group(3))
        lines_out.append(f"FILE {rel} bytes={len(txt.encode('latin1',errors='replace'))}")
        lines_out.append(f"  techniques({len(techs)}): {', '.join(techs)}")
        lines_out.append(f"  passes({len(passes)})")
        lines_out.append(f"  shader_profiles: {', '.join(sorted(profiles)) or '-'}")
        lines_out.append(f"  includes: {', '.join(sorted(incs)) or '-'}")
        lines_out.append(f"  globals({len(globs)}): {', '.join(globs[:40])}")
    open(out, "w", encoding="utf-8").write("\n".join(lines_out) + "\n")
    print("fx files", len(files))

if __name__ == "__main__":
    main()
