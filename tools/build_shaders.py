"""Build the remaster shader overlay from the user's own stock .fx files.

Usage:
  python tools/build_shaders.py <game_dir> <overlay_dir> [--only units,terrain,water]
                                [--set RAF_UNIT_RIM=0 ...]

Reads <game_dir>/Data/fx (never writes there), applies shaders/edits.json and our
sources in shaders/src, and writes <overlay_dir>/Data/fx/... plus
<overlay_dir>/shader-manifest.json. Installing = copying <overlay_dir>/Data over the
game's Data folder (back up the files listed in the manifest first).

Patch edits are exact-match and fail loudly when an anchor is missing or matches a
different number of times; replaced files are checked against the stock sha256 they
were written for.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADERS = os.path.join(REPO, "shaders")
GROUPS_ORDER = ["common", "units", "terrain", "water"]


class BuildError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def find_ci(root, rel):
    """Case-insensitive lookup of rel (forward slashes) under root; None if absent."""
    cur = root
    for part in rel.split("/"):
        if not os.path.isdir(cur):
            return None
        hit = [n for n in os.listdir(cur) if n.lower() == part.lower()]
        if not hit:
            return None
        cur = os.path.join(cur, hit[0])
    return cur


def to_text(data):
    txt = data.decode("latin1")  # stock files are cp1252/latin1; latin1 round-trips every byte
    crlf = "\r\n" in txt
    return txt.replace("\r\n", "\n"), crlf


def from_text(txt, crlf):
    if crlf:
        txt = txt.replace("\n", "\r\n")
    return txt.encode("latin1")


def read_config_defaults():
    path = os.path.join(SHADERS, "src", "fx", "RAF Config.fx")
    txt = open(path, encoding="latin1").read()
    block = txt.split("/* RAF-CONFIG-BEGIN */")[1].split("/* RAF-CONFIG-END */")[0]
    out = {}
    for m in re.finditer(r"^#define\s+(RAF_\w+)\s+(\S+)", block, re.M):
        out[m.group(1)] = m.group(2)
    return out


def render_config(overrides):
    path = os.path.join(SHADERS, "src", "fx", "RAF Config.fx")
    txt = open(path, encoding="latin1").read().replace("\r\n", "\n")
    head, rest = txt.split("/* RAF-CONFIG-BEGIN */")
    block, tail = rest.split("/* RAF-CONFIG-END */")
    known = read_config_defaults()
    for k in overrides:
        if k not in known:
            raise BuildError(f"--set {k}: unknown setting (known: {', '.join(sorted(known))})")

    def sub(m):
        k = m.group(1)
        if k in overrides:
            return f"#define {k:<24} {overrides[k]}"
        return m.group(0)

    block = re.sub(r"^#define\s+(RAF_\w+)\s+(\S+)", sub, block, flags=re.M)
    return head + "/* RAF-CONFIG-BEGIN */" + block + "/* RAF-CONFIG-END */" + tail


def line_hash(lines):
    return sha256("".join(lines).encode("latin1"))[:8]


def apply_lines(txt, script, rel):
    """Apply a line script (shaders/src/**/*.fxpatch, made by tools/make_shader_patch.py).

    Directive lines start with '@@ '; every other line is ours and is emitted verbatim.
      @@ keep N H     next N stock lines unchanged
      @@ drop N H     skip the next N stock lines
      @@ copy L N H   emit N stock lines starting at line L (1-based), cursor unchanged
      @@ copy L 1 H W emit stock line L with its words re-spaced: W lists the whitespace
                      before, between and after the words, ',' separated, t = tab,
                      s = space (e.g. 't,tt,s,' for TAB A TAB TAB B SPACE C)
      @@ noeol        the output ends without a final newline
      @@ # ...        comment
    H is the first 8 hex digits of the sha256 of the stock lines covered, so a different
    stock text fails the build instead of producing a mixed file. keep + drop must cover
    the whole stock file.
    """
    stock = txt.splitlines(keepends=True)
    out, pos, stats = [], 0, {"keep": 0, "drop": 0, "copy": 0, "add": 0}
    noeol = False

    def take(start, n, h, what):
        if start < 0 or start + n > len(stock):
            raise BuildError(f"{rel}: {what} {start + 1}+{n} is past the stock file ({len(stock)} lines)")
        chunk = stock[start:start + n]
        if line_hash(chunk) != h:
            raise BuildError(f"{rel}: {what} at stock line {start + 1} hash {line_hash(chunk)} != {h} "
                             "(stock file changed? regenerate with tools/make_shader_patch.py)")
        return chunk

    for line in script.splitlines(keepends=True):
        if not line.startswith("@@ "):
            out.append(line)
            stats["add"] += 1
            continue
        f = line.split()
        if len(f) < 2 or f[1].startswith("#"):
            continue
        if f[1] == "keep" and len(f) == 4:
            out += take(pos, int(f[2]), f[3], "keep")
            pos += int(f[2])
            stats["keep"] += int(f[2])
        elif f[1] == "drop" and len(f) == 4:
            take(pos, int(f[2]), f[3], "drop")
            pos += int(f[2])
            stats["drop"] += int(f[2])
        elif f[1] == "copy" and len(f) == 5:
            out += take(int(f[2]) - 1, int(f[3]), f[4], "copy")
            stats["copy"] += int(f[3])
        elif f[1] == "copy" and len(f) == 6 and f[3] == "1":
            words = take(int(f[2]) - 1, 1, f[4], "copy")[0].split()
            gaps = [g.replace("t", "\t").replace("s", " ") for g in f[5].split(",")]
            if len(gaps) != len(words) + 1 or set(f[5]) - set("ts,"):
                raise BuildError(f"{rel}: bad re-spacing {f[5]!r} for stock line {f[2]}")
            out.append("".join(g + w for g, w in zip(gaps, words + [""])) + "\n")
            stats["copy"] += 1
        elif f[1] == "noeol" and len(f) == 2:
            noeol = True
        else:
            raise BuildError(f"{rel}: bad line-script directive {line.strip()!r}")
    if pos != len(stock):
        raise BuildError(f"{rel}: line script covers {pos} of {len(stock)} stock lines (stock file changed?)")
    res = "".join(out)
    if noeol and res.endswith("\n"):
        res = res[:-1]
    return res, stats


def apply_edits(txt, edits, rel):
    applied = []
    for e in edits:
        if "lines" in e:
            script = open(os.path.join(SHADERS, "src", e["lines"]), encoding="latin1").read().replace("\r\n", "\n")
            txt, stats = apply_lines(txt, script, rel)
            applied.append({"lines": e["lines"], **stats})
            continue
        if "append" in e:
            if not txt.endswith("\n"):
                txt += "\n"
            txt += e["append"]
            applied.append({"append": len(e["append"])})
            continue
        n = txt.count(e["find"])
        if n != e["count"]:
            raise BuildError(f"{rel}: anchor {e['find']!r} found {n}x, expected {e['count']}x "
                             "(stock file changed? re-check the edit)")
        txt = txt.replace(e["find"], e["replace"])
        applied.append({"find": e["find"], "count": n})
    return txt, applied


def git_rev():
    try:
        rev = subprocess.check_output(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.call(["git", "-C", REPO, "diff", "--quiet", "--", "shaders", "tools/build_shaders.py"])
        return rev + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def build(game_dir, overlay_dir, groups, overrides):
    data_dir = os.path.join(game_dir, "Data")
    if not os.path.isdir(data_dir):
        raise BuildError(f"no Data folder in {game_dir}")
    g_abs = os.path.normcase(os.path.abspath(game_dir))
    o_abs = os.path.normcase(os.path.abspath(overlay_dir))
    if o_abs == g_abs or o_abs.startswith(g_abs + os.sep):
        raise BuildError("overlay_dir must not be inside the game folder")

    spec = json.load(open(os.path.join(SHADERS, "edits.json"), encoding="utf-8"))
    out_data = os.path.join(overlay_dir, "Data")
    if os.path.isdir(os.path.join(out_data, "fx")):
        shutil.rmtree(os.path.join(out_data, "fx"))
    manifest = {"tool": "tools/build_shaders.py", "repo_rev": git_rev(), "game_dir": game_dir,
                "groups": groups, "config": {**read_config_defaults(), **overrides}, "files": []}
    outputs = {}

    for g in ["common"] + [x for x in GROUPS_ORDER if x in groups and x != "common"]:
        for item in spec["groups"][g]:
            rel = item["path"]
            stock_path = find_ci(data_dir, rel)
            entry = {"group": g, "op": item["op"], "path": "Data/" + rel}
            if item["op"] == "add":
                if stock_path:
                    raise BuildError(f"{rel}: 'add' target already exists in stock Data")
                if rel == "fx/RAF Config.fx":
                    txt = render_config(overrides)
                elif "lines" in item:  # new file derived from a stock one: our lines + references
                    base_path = find_ci(data_dir, item["base"])
                    if not base_path:
                        raise BuildError(f"{rel}: stock base {item['base']} missing")
                    entry["base"] = "Data/" + item["base"]
                    entry["base_sha256"] = sha256(open(base_path, "rb").read())  # not stock_sha256: the path is new
                    txt, _ = to_text(open(base_path, "rb").read())
                    txt, entry["edits"] = apply_edits(txt, [{"lines": item["lines"]}], rel)
                else:
                    txt = open(os.path.join(SHADERS, "src", item["src"]), encoding="latin1").read().replace("\r\n", "\n")
                data = from_text(txt, True)
                out_rel = rel
            elif item["op"] == "replace":
                if not stock_path:
                    raise BuildError(f"{rel}: stock file missing")
                stock = open(stock_path, "rb").read()
                entry["stock_sha256"] = sha256(stock)
                if sha256(stock) != item["expect_sha256"]:
                    raise BuildError(f"{rel}: stock sha256 {sha256(stock)[:16]} != expected "
                                     f"{item['expect_sha256'][:16]}; our rewrite targets another version")
                txt = open(os.path.join(SHADERS, "src", item["src"]), encoding="latin1").read().replace("\r\n", "\n")
                data = from_text(txt, True)
                out_rel = os.path.relpath(stock_path, data_dir).replace("\\", "/")
            elif item["op"] == "patch":
                if not stock_path:
                    raise BuildError(f"{rel}: stock file missing")
                stock = open(stock_path, "rb").read()
                entry["stock_sha256"] = sha256(stock)
                if "expect_sha256" in item and sha256(stock) != item["expect_sha256"]:
                    raise BuildError(f"{rel}: stock sha256 {sha256(stock)[:16]} != expected "
                                     f"{item['expect_sha256'][:16]}; the patch targets another version")
                txt, crlf = to_text(stock)
                txt, entry["edits"] = apply_edits(txt, item["edits"], rel)
                data = from_text(txt, crlf)
                out_rel = os.path.relpath(stock_path, data_dir).replace("\\", "/")
            else:
                raise BuildError(f"unknown op {item['op']}")
            dst = os.path.join(out_data, *out_rel.split("/"))
            if dst in outputs:
                raise BuildError(f"{rel}: produced twice")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
            outputs[dst] = True
            entry["path"] = "Data/" + out_rel
            entry["out_sha256"] = sha256(data)
            entry["bytes"] = len(data)
            manifest["files"].append(entry)

    with open(os.path.join(overlay_dir, "shader-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir")
    ap.add_argument("overlay_dir")
    ap.add_argument("--only", default="units,terrain,water", help="comma list of groups: units,terrain,water")
    ap.add_argument("--set", action="append", default=[], metavar="RAF_X=V", help="override a RAF Config value")
    a = ap.parse_args(argv)
    groups = [g.strip() for g in a.only.split(",") if g.strip()]
    for g in groups:
        if g not in GROUPS_ORDER or g == "common":
            ap.error(f"unknown group {g}")
    overrides = {}
    for s in a.set:
        if "=" not in s:
            ap.error(f"--set needs NAME=VALUE: {s}")
        k, v = s.split("=", 1)
        overrides[k.strip()] = v.strip()
    try:
        m = build(a.game_dir, a.overlay_dir, groups, overrides)
    except BuildError as e:
        print("BUILD FAILED:", e, file=sys.stderr)
        return 1
    for f in m["files"]:
        print(f"{f['op']:8} {f['path']:55} {f['out_sha256'][:12]}")
    print(f"{len(m['files'])} files -> {os.path.join(a.overlay_dir, 'Data')}  (manifest: shader-manifest.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
