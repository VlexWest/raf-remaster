"""Offline compile + interface check for the shader overlay (runs every shader test).

Usage:
  python tools/check_shaders.py <game_dir> <overlay_dir> [--out <report_dir>] [--no-stock-all]

Needs a 32-bit Python for d3dx9_27.dll; re-runs itself under one found by
`uv python find cpython-3.12-windows-x86-none` (or RAF_PY32).

What it does:
 1. Compiles every stock .fx under Data with the game's own compiler (d3dx9_27,
    D3DXCreateEffectCompiler + CompileEffect) using the engine defines recorded in
    <game_dir>/shader.cache, to prove the toolchain handles the stock files.
 2. For every effect the overlay touches, compiles stock and overlay for each
    permutation the engine used (normal unit.fx: every unit record in shader.cache;
    terrain/water: with and without k_UseLightCube / k_IsBeingReflected), with
    d3dx9_27 and with d3dcompiler_47 (fx_2_0).
 3. Compares the effect interface stock vs overlay: parameter names, semantics,
    types, sizes, annotations; technique names, annotations and pass names; and
    the vertex input semantics each vertex shader reads.
 4. Writes report.json + report.txt; exit code 1 on any overlay failure or diff.
Nothing is written into the game folder.
"""
import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fxcompile as fc  # noqa: E402

FLAG_NAMES = {
    0: "k_IsSpecular", 1: "k_IsSpecularPerPixel", 2: "k_IsNormalMapped", 3: "k_IsPlayerColor",
    4: "k_HasVertexColor", 5: "k_UseAlternateUV", 6: "k_IsRimLightPerPixel", 7: "k_BlendModeAlpha",
    8: "k_BlendModeAdditive", 9: "k_BlendModeMultiply", 10: "k_BlendModeZero", 11: "k_HasCappedAxis",
    12: "k_IsShadowMapObjectAlpha", 13: "k_IsShadowMapObjectNoAlpha", 14: "k_IsMorphedToTerrain",
    15: "k_IsBeingImpostered", 16: "k_IsBeingReflected", 17: "k_UseRigidAnimation",
    18: "k_UseBone2Weight", 19: "k_UseBone3Weight", 20: "k_UseBone4Weight",
    21: "k_UseBoneReducedArraySize", 22: "k_UseLightAmbient", 23: "k_UseLightHemisphere",
    24: "k_UseLightCube", 25: "k_UseCliffTexturing", 26: "k_UsePerPixelAlpha",
    27: "k_UseImposterFiltering", 28: "k_UseAlphaTest", 29: "k_AccurateOpacity",
    30: "k_ShouldHighlight", 31: "k_ApplyFogOfWar", 32: "k_BlackAndWhite",
}
# flags whose registration in LowLevelEngine.dll asks for pixel shader 2.0 (0x20000)
PS20_FLAGS = {"k_IsSpecularPerPixel", "k_IsNormalMapped", "k_IsRimLightPerPixel"}
UNIT_EFFECT_ID = 20

FALLBACK_DEFINES = {
    "PS_VERSION": "ps_2_0", "VS_VERSION": "vs_1_1", "k_MaxBillBoardArraySize": "236",
    "k_MaxBoneArraySize": "77", "k_MaxNumberImposters": "62", "k_MaxOrientedParticleArraySize": "49",
    "k_MaxSelectionShapeLineSegmentsArraySize": "246", "k_MaxTileMappedParticleArraySize": "30",
    "k_ReducedBoneArraySize": "75",
}


def parse_shader_cache(path):
    """shader.cache: u32 version, 16-byte id, u32 n, n x (len+str name, len+str value),
    u32 m, m x (u32 effect, u32 variant, u32 k, k x u32 flag)."""
    d = open(path, "rb").read()
    o = 20
    n = struct.unpack_from("<I", d, o)[0]
    o += 4
    defines = {}
    for _ in range(n):
        vals = []
        for _ in range(2):
            ln = struct.unpack_from("<I", d, o)[0]
            o += 4
            vals.append(d[o:o + ln].rstrip(b"\0").decode("latin1"))
            o += ln
        defines[vals[0]] = vals[1]
    m = struct.unpack_from("<I", d, o)[0]
    o += 4
    records = []
    for _ in range(m):
        eff, var, k = struct.unpack_from("<III", d, o)
        o += 12
        flags = struct.unpack_from(f"<{k}I", d, o)
        o += 4 * k
        records.append((eff, var, [FLAG_NAMES.get(f, f"flag{f}") for f in flags]))
    if o != len(d):
        raise ValueError(f"shader.cache parse ended at {o} of {len(d)}")
    return defines, records


def engine_versions(flags):
    """Per-permutation profiles as the engine picks them (likely, see docs/shaders.md)."""
    return ("ps_2_0" if PS20_FLAGS & set(flags) else "ps_1_1"), "vs_1_1"


def find_fx(root):
    out = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".fx"):
                out.append(os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/"))
    return sorted(out)


def has_technique(path):
    import re
    return bool(re.search(r"^\s*technique\s+\w+", open(path, encoding="latin1").read(), re.M | re.I))


def summarize_shaders(shaders):
    return [f"{s['profile']}:{s['slots']}" for s in shaders]


def main():
    fc.ensure_py32()
    ap = argparse.ArgumentParser()
    ap.add_argument("game_dir")
    ap.add_argument("overlay_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-stock-all", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="skip the REF-rasterizer pixel tests")
    a = ap.parse_args()

    game_data = os.path.join(a.game_dir, "Data")
    ov_data = os.path.join(a.overlay_dir, "Data")
    out_dir = a.out or os.path.join(a.overlay_dir, "check")
    os.makedirs(out_dir, exist_ok=True)

    cache = os.path.join(a.game_dir, "shader.cache")
    try:
        base_defines, records = parse_shader_cache(cache)
        src = cache
    except Exception as e:  # noqa: BLE001
        base_defines, records, src = dict(FALLBACK_DEFINES), [], f"fallback ({e})"
    dx = fc.D3DX27(os.path.join(a.game_dir, "d3dx9_27.dll"))
    c47 = fc.D3DCompiler47()
    dev = fc.create_nullref_device()
    stock_roots = fc.DataRoots([game_data])
    ov_roots = fc.DataRoots([ov_data, game_data])
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "defines_from": src, "base_defines": base_defines,
              "cache_records": len(records), "stock_all": [], "overlay": [], "failures": []}
    lines = [f"defines from {src}: " + ", ".join(f"{k}={v}" for k, v in base_defines.items())]

    # 1. all stock files
    if not a.no_stock_all:
        ok = tech_ok = tech_n = 0
        for rel in find_fx(game_data):
            path = os.path.join(game_data, *rel.split("/"))
            tech = has_technique(path)
            d = dict(base_defines)
            if rel.lower().endswith("units/normal unit.fx"):
                d["k_UseRigidAnimation"] = "1"  # the engine always sets a skinning flag
            r = dx.compile_effect(path, d, stock_roots)
            r47 = c47.compile_effect(path, d, stock_roots)
            dev_ok, dev_err = dx.create_effect(dev, path, d, stock_roots) if dev else (None, "no device")
            ok += r["ok"]
            if tech:
                tech_n += 1
                tech_ok += r["ok"]
            report["stock_all"].append({"file": rel, "has_technique": tech, "d3dx9_27_ok": r["ok"],
                                        "d3dx9_27_errors": r["errors"], "device_ok": dev_ok,
                                        "device_errors": dev_err, "d3dc47_ok": r47["ok"],
                                        "d3dc47_errors": r47["errors"][:2000],
                                        "techniques": [t["name"] for t in (r["interface"] or {}).get("techniques", [])],
                                        "shaders": summarize_shaders(r["shaders"])})
        lines.append(f"stock, all files, base defines: d3dx9_27 ok {ok}/{len(report['stock_all'])}, "
                     f"technique files ok {tech_ok}/{tech_n}; D3DXCreateEffect on NULLREF device: technique files ok "
                     f"{sum(bool(x['device_ok']) for x in report['stock_all'] if x['has_technique'])}/{tech_n}; "
                     f"d3dcompiler_47 fx_2_0 technique files ok "
                     f"{sum(x['d3dc47_ok'] for x in report['stock_all'] if x['has_technique'])}/{tech_n}")
        for x in report["stock_all"]:
            if x["has_technique"] and not (x["d3dx9_27_ok"] and x["device_ok"]):
                lines.append(f"  stock fails: {x['file']}: {x['d3dx9_27_errors'][:200]!r}")

    # 2./3. overlay effects x permutations
    changed = set()
    for dp, _, fns in os.walk(ov_data):
        for fn in fns:
            changed.add(os.path.relpath(os.path.join(dp, fn), ov_data).replace("\\", "/").lower())
    targets = {}
    for rel in find_fx(game_data):
        path = os.path.join(game_data, *rel.split("/"))
        if not has_technique(path):
            continue
        r = dx.compile_effect(path, base_defines, ov_roots)
        used = {os.path.relpath(u, ov_data).replace("\\", "/").lower() for u in r["includes"]
                if os.path.abspath(u).lower().startswith(os.path.abspath(ov_data).lower())}
        if rel.lower() in changed or used:
            targets[rel] = sorted(used | ({rel.lower()} if rel.lower() in changed else set()))

    unit_sets = [flags for eff, var, flags in records if eff == UNIT_EFFECT_ID] or [["k_UseRigidAnimation"]]
    world_sets = [[], ["k_UseLightCube"], ["k_IsBeingReflected"], ["k_UseLightCube", "k_IsBeingReflected"]]
    for rel, via in sorted(targets.items()):
        path_stock = os.path.join(game_data, *rel.split("/"))
        ov_path = fc.DataRoots([ov_data]).find(rel)
        path_ov = ov_path or path_stock
        sets = unit_sets if rel.lower().endswith("units/normal unit.fx") else world_sets
        n_ok = n_diff = n_dev = 0
        worst = {}
        for flags in sets:
            d = dict(base_defines)
            if rel.lower().endswith("units/normal unit.fx"):
                d["PS_VERSION"], d["VS_VERSION"] = engine_versions(flags)
            for f in flags:
                d[f] = "1"
            rs = dx.compile_effect(path_stock, d, stock_roots)
            ro = dx.compile_effect(path_ov, d, ov_roots)
            r47 = c47.compile_effect(path_ov, d, ov_roots)
            r47s = c47.compile_effect(path_stock, d, stock_roots)
            dev_ok, dev_err = dx.create_effect(dev, path_ov, d, ov_roots) if dev else (None, "no device")
            diffs = []
            if rs["ok"] and ro["ok"]:
                diffs = fc.diff_interface(rs["interface"], ro["interface"])
                vs_s = sorted({tuple(s["inputs"]) for s in rs["shaders"] if s["inputs"] is not None})
                vs_o = sorted({tuple(s["inputs"]) for s in ro["shaders"] if s["inputs"] is not None})
                if vs_s != vs_o:
                    diffs.append(f"vertex inputs differ: stock {vs_s} ours {vs_o}")
            entry = {"file": rel, "via": via, "flags": flags, "stock_ok": rs["ok"], "stock_errors": rs["errors"],
                     "ours_ok": ro["ok"], "ours_errors": ro["errors"], "ours_device_ok": dev_ok,
                     "ours_device_errors": dev_err, "d3dc47_ok": r47["ok"],
                     "d3dc47_stock_ok": r47s["ok"], "d3dc47_errors": r47["errors"][:2000], "interface_diffs": diffs,
                     "stock_shaders": summarize_shaders(rs["shaders"]),
                     "ours_shaders": summarize_shaders(ro["shaders"])}
            report["overlay"].append(entry)
            if ro["ok"]:
                n_ok += 1
            if dev_ok:
                n_dev += 1
            # d3dcompiler_47 is a second opinion only: it must not fail where it passes stock
            if not ro["ok"] or diffs or (r47s["ok"] and not r47["ok"]) or dev_ok is False:
                report["failures"].append(entry)
            if diffs:
                n_diff += 1
            for s in ro["shaders"]:
                k = s["profile"]
                worst[k] = max(worst.get(k, 0), s["slots"] or 0)
        lines.append(f"{rel}: {len(sets)} permutations, ours compile ok {n_ok}/{len(sets)}, device create ok {n_dev}/{len(sets)}, interface diffs {n_diff}, "
                     f"max slots {worst}  (overlay files: {', '.join(via)})")

    # 5. pixel A/B tests on the REF rasterizer
    if not a.no_render:
        import build_shaders  # noqa: PLC0415
        import shader_render_tests  # noqa: PLC0415
        base_dir = os.path.join(out_dir, "overlay-base")
        build_shaders.build(a.game_dir, base_dir, ["units", "terrain", "water"],
                            {"RAF_UNIT_SPEC": "0", "RAF_UNIT_RIM": "0", "RAF_TERRAIN_RELIEF": "0",
                             "RAF_TERRAIN_DETAIL": "0", "RAF_WATER": "0"})
        try:
            res, fails = shader_render_tests.run(a.game_dir, base_dir, a.overlay_dir, base_defines)
        except Exception as e:  # noqa: BLE001
            res, fails = [], [{"flags": ["render harness"], "problems": [repr(e)]}]
        report["render"] = res
        lines.append(f"REF pixel tests (units): {len(res) - len(fails)}/{len(res)} ok")
        for r in res:
            lines.append(f"  {'+'.join(f[2:] for f in r['flags'])}{' fog' if r.get('fog') else ''}: "
                         f"stock-vs-base max {r['max_abs_diff_stock_vs_base']}/255, passes {r['passes']['full']}, "
                         f"team px stock {r['team_px_stock'][:3]} full {r['team_px_full'][:3]}, "
                         f"plain px stock {r['plain_px_stock'][:3]} full {r['plain_px_full'][:3]}"
                         + (f"  PROBLEMS {r['problems']}" if r['problems'] else ""))
        for f in fails:
            report["failures"].append({**f, "kind": "render"})
        try:
            wres, wfails = shader_render_tests.run_world(a.game_dir, base_dir, a.overlay_dir, base_defines)
        except Exception as e:  # noqa: BLE001
            wres, wfails = [], [{"flags": ["world render harness"], "problems": [repr(e)]}]
        report["render_world"] = wres
        lines.append(f"REF pixel tests (terrain/water): {len(wres) - len(wfails)}/{len(wres)} ok")
        for r in wres:
            lines.append(f"  {r['technique']} {'+'.join(f[2:] for f in r['flags'])}: features-off vs stock max "
                         f"{r['max_abs_diff_stock_vs_base']}/255, full vs stock max {r['max_abs_diff_stock_vs_full']}/255, "
                         f"mean luma {r['mean_luma_stock']} -> {r['mean_luma_full']}"
                         + (f"  PROBLEMS {r['problems']}" if r['problems'] else ""))
        for f in wfails:
            report["failures"].append({**f, "kind": "render"})

    if report["failures"]:
        lines.append(f"FAILURES: {len(report['failures'])} (see report.json)")
        for f in report["failures"][:10]:
            if f.get("kind") == "render":
                lines.append(f"  render {f.get('file', '')} {f.get('technique', '')} {f['flags']}: {f['problems']}")
                continue
            lines.append(f"  {f['file']} {f['flags']}: ours_ok={f['ours_ok']} d3dc47_ok={f['d3dc47_ok']} "
                         f"diffs={f['interface_diffs'][:3]} err={(f['ours_errors'] or f['d3dc47_errors'])[:300]!r}")
    else:
        lines.append("ALL OVERLAY CHECKS PASSED")
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8"), indent=1)
    open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
