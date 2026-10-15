"""Offline tests for the shader line scripts (tools/make_shader_patch.py + build_shaders.apply_lines).

    python tools/test_shader_patch.py [stock_game_dir]      (default D:/Games/Rise and Fall)

1. synthetic round trips: keep, drop, copy (exact and re-spaced), added lines, no final newline
2. failure paths: changed stock line, shorter or longer stock file, bad directive, bad re-spacing,
   our line starting with '@@ '
3. on the player's install (skipped if absent): every 'lines' script in shaders/edits.json applies
   to the stock file and a one-character change to that stock file fails the build
Writes nothing.
"""
import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import build_shaders as bs  # noqa: E402
import make_shader_patch as mp  # noqa: E402

GAME = sys.argv[1] if len(sys.argv) > 1 else "D:/Games/Rise and Fall"
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def raises(fn):
    try:
        fn()
    except (bs.BuildError, ValueError):
        return True
    return False


STOCK = ("/* header */\n"
         "float4 ComputeSomething(float3 inNormal, float3 inLight)\n"
         "{\n"
         "\treturn float4(dot(inNormal, inLight), 0.0F, 0.0F, 1.0F);\n"
         "}\n"
         "\n"
         "\ttheOutput.mSpecular  = float4(0.0F, 0.0F, 0.0F, 1.0F);\n"
         "static const float k_UnusedStockConstant = 1.0F;\n"
         "};")
OURS = ("/* ours */\n"
        "float4 ComputeSomething(float3 inNormal, float3 inLight)\n"
        "{\n"
        "\ttheOutput.mSpecular\t\t= float4(0.0F, 0.0F, 0.0F, 1.0F);\n"
        "\treturn float4(dot(inNormal, inLight), 0.0F, 0.0F, 1.0F);\n"
        "\treturn float4(dot(inNormal, inLight), 0.0F, 0.0F, 1.0F);\n"
        "}\n"
        "\n"
        "};")

script = mp.make(STOCK, OURS, header=["test"])
out, stats = bs.apply_lines(STOCK, script, "t")
check("round trip", out == OURS)
check("uses keep, drop, copy and add", all(stats[k] > 0 for k in ("keep", "drop", "copy", "add")))
check("re-spaced copy used", any(len(x.split()) == 6 for x in script.splitlines() if x.startswith("@@ copy")))
check("no stock line of >= 20 chars in the script",
      not any(mp.norm(x) == mp.norm(y) for x in script.splitlines() if not x.startswith("@@ ")
              for y in STOCK.splitlines() if len(mp.norm(y)) >= mp.MIN_COPY))
check("no final newline kept", out.endswith("};") and "@@ noeol" in script)
check("final newline kept", bs.apply_lines(STOCK, mp.make(STOCK, OURS + "\n"), "t")[0] == OURS + "\n")
check("identical file", bs.apply_lines(STOCK, mp.make(STOCK, STOCK), "t")[0] == STOCK)
check("empty ours", bs.apply_lines(STOCK, mp.make(STOCK, ""), "t")[0] == "")

check("changed stock line fails", raises(lambda: bs.apply_lines(STOCK.replace("dot(", "dot2("), script, "t")))
check("changed copied line fails", raises(lambda: bs.apply_lines(STOCK.replace("k_Unused", "k_Unusex"),
                                                                 mp.make(STOCK, OURS + "\nstatic const float k_UnusedStockConstant = 1.0F;\n"), "t")))
check("longer stock fails", raises(lambda: bs.apply_lines(STOCK + "\nextra line\n", script, "t")))
check("shorter stock fails", raises(lambda: bs.apply_lines(STOCK.rsplit("\n", 2)[0], script, "t")))
check("bad directive fails", raises(lambda: bs.apply_lines(STOCK, "@@ move 1 2\n", "t")))
bad = "\n".join(x if not (x.startswith("@@ copy") and len(x.split()) == 6) else x.rsplit(" ", 1)[0] + " t,x"
                for x in script.splitlines()) + "\n"
check("bad re-spacing fails", raises(lambda: bs.apply_lines(STOCK, bad, "t")))
check("our line starting with '@@ ' refused", raises(lambda: mp.make(STOCK, "@@ keep 1 x\n")))

spec = json.load(open(os.path.join(bs.SHADERS, "edits.json"), encoding="utf-8"))
data = os.path.join(GAME, "Data")
if not os.path.isdir(data):
    print(f"skip install checks: no {data}")
else:
    n = 0
    for items in spec["groups"].values():
        for item in items:
            scripts = [e["lines"] for e in item.get("edits", []) if "lines" in e]
            target = item["path"] if item["op"] == "patch" else item.get("base")
            if "lines" in item:
                scripts.append(item["lines"])
            for sc in scripts:
                n += 1
                stock, _ = bs.to_text(open(bs.find_ci(data, target), "rb").read())
                text = open(os.path.join(bs.SHADERS, "src", sc), encoding="latin1").read().replace("\r\n", "\n")
                check(f"{sc} applies", not raises(lambda: bs.apply_lines(stock, text, sc)))
                lines = stock.splitlines(keepends=True)
                mid = len(lines) // 2
                lines[mid] = lines[mid].replace(";", ":", 1) if ";" in lines[mid] else "x" + lines[mid]
                check(f"{sc} fails on a changed stock file", raises(lambda: bs.apply_lines("".join(lines), text, sc)))
    check("found the line scripts", n == 4)

print(f"{'FAILED ' + str(len(fails)) if fails else 'ALL PASSED'}")
sys.exit(1 if fails else 0)
