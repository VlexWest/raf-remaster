"""Pixel A/B tests of the unit effect on the D3D9 REF rasterizer (software, no GPU).

For a set of unit permutations taken from the engine's own shader.cache, render one
quad with identical inputs through
  stock          the game's files, engine-style VS/PS_VERSION per permutation,
  ours (base)    the overlay built with RAF_UNIT_SPEC=0 and RAF_UNIT_RIM=0,
  ours (full)    the overlay as shipped,
and check:
  - base equals stock within 2/255 on every pixel (lighting moved per pixel, team colour
    formula and alpha unchanged; the normal is constant over the quad, so per-vertex and
    per-pixel lighting must agree);
  - full never darkens a pixel by more than 2/255 vs base and is never NaN-black;
  - team-coloured texels keep their hue (red stays the strongest channel);
  - accurate opacity (z-only pass then ZFunc EQUAL) still draws: depth matches;
  - fixed-function fog is still applied with ps_2_b.
"""
import math
import os

import fxcompile as fc
import fxrender as fr

SIZE = 32


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _bones(count):
    """count float4x3 bone matrices: small rotations about z plus small offsets."""
    out = []
    for i in range(count):
        a = 0.05 * (i % 4)
        c, s = math.cos(a), math.sin(a)
        out += [c, s, 0, -s, c, 0, 0, 0, 1, 0.02 * (i % 4), -0.01 * (i % 4), 0.0]
    return tuple(out)


IDENT = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
PARAMS = {
    "k_LocalToClip": IDENT, "k_WorldToClip": IDENT, "k_LocalToWorld": IDENT,
    "k_MaterialColor": (1, 1, 1, 1), "k_UVScaleAndOffset": (1, 1, 0, 0),
    "k_CameraPosition": (0.0, 0.0, -3.0),
    "k_LightDirection": _norm((0.35, 0.3, -0.85)),
    "k_LightColor": (1.0, 0.95, 0.85), "k_SpecularColor": (1.0, 1.0, 1.0), "k_AmbientColor": (0.3, 0.3, 0.35),
    "k_FogAttributes": (0.0, 1000.0, 1.0, 0.0),
    "k_LightingRegion": (0.9, 0.5, 0.4, 1, 0.2, 0.3, 0.6, 1, 0.6, 0.8, 0.5, 1,
                         0.3, 0.25, 0.2, 1, 0.4, 0.45, 0.5, 1, 0.7, 0.65, 0.55, 1),
    "k_PlayerColor": (0.85, 0.1, 0.1), "k_HighlightIntensity": (0.5,),
    "k_RimLightColor": (0.4, 0.4, 0.5), "k_RimLightPower": (2.0,),
    "k_FogOfWarUVScaleAndOffset": (0.5, 0.5, 0.25, 0.25), "k_FogOfWarColorTop": (0.1, 0.1, 0.12),
    "k_AlphaReferenceValue": 128,
    "k_BoneMatrices": _bones(75),
}
NORMAL = _norm((0.3, 0.2, -0.93))


def quad(mirrored=False):
    # strip TL, BL, TR, BR: counter-clockwise on screen, survives CullMode = CW;
    # reflected permutations cull CCW, so they get the mirrored winding
    pts = [((-1, 1, 0.5), (0, 0)), ((-1, -1, 0.5), (0, 1)), ((1, 1, 0.5), (1, 0)), ((1, -1, 0.5), (1, 1))]
    if mirrored:
        pts = [pts[0], pts[2], pts[1], pts[3]]
    # 4 bone weights / indices 0..3 (BLENDINDICES as D3DCOLOR bytes); rigid permutations ignore them
    return [fr.unit_vertex(p, NORMAL, uv, binormal=(1, 0, 0), tangent=(0, 1, 0),
                           weights=(0.4, 0.3, 0.2, 0.0), indices=0x03020100) for p, uv in pts]



def make_textures(dev):
    return {
        # left half: team-colour area (alpha 0); right half: plain texel, alpha 255
        "k_Texture0": dev.texture(16, 16, lambda x, y: (200, 150, 100, 0) if x < 8 else (90, 120, 60, 255)),
        "k_TextureNormalMap": dev.texture(16, 16, lambda x, y: (128, 128, 255, 160)),
        "k_TextureFogOfWarMask": dev.texture(16, 16, lambda x, y: (0, 0, 64, 255)),
    }


# permutations (engine flag names) chosen from the unit records in shader.cache
CASES = [
    ["k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube"],
    ["k_IsSpecularPerPixel", "k_IsNormalMapped", "k_IsPlayerColor", "k_IsRimLightPerPixel",
     "k_UseRigidAnimation", "k_UseLightCube"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube", "k_ApplyFogOfWar"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube", "k_AccurateOpacity"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube", "k_ShouldHighlight"],
    ["k_IsPlayerColor", "k_UseRigidAnimation", "k_UseLightCube", "k_ShouldHighlight"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_IsBeingReflected", "k_UseRigidAnimation", "k_UseLightCube"],
    ["k_BlendModeAlpha", "k_UseRigidAnimation"],
    ["k_IsSpecular", "k_IsNormalMapped", "k_UseRigidAnimation", "k_UseLightCube"],   # stock spec differs: sanity only
    ["k_IsPlayerColor", "k_UseRigidAnimation"],                                     # half-lambert fallback path
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseBone4Weight", "k_UseBoneReducedArraySize", "k_UseLightCube"],
    ["k_IsPlayerColor", "k_UseBone2Weight", "k_UseBoneReducedArraySize", "k_UseLightCube", "k_AccurateOpacity"],
    ["k_IsNormalMapped", "k_IsPlayerColor", "k_UseBone3Weight", "k_UseBoneReducedArraySize", "k_UseLightCube",
     "k_IsBeingReflected"],
]
# stock adds its own specular here, so "ours without spec" cannot equal stock
SANITY_ONLY = {"k_IsSpecular", "k_IsSpecularPerPixel"}


def run(game_dir, base_overlay, full_overlay, base_defines):
    from check_shaders import engine_versions  # noqa: PLC0415 (avoid import cycle at load)
    game_data = os.path.join(game_dir, "Data")
    dev = fr.RefDevice(os.path.join(game_dir, "d3dx9_27.dll"), SIZE)
    tex = make_textures(dev)
    roots = {"stock": fc.DataRoots([game_data]),
             "base": fc.DataRoots([os.path.join(base_overlay, "Data"), game_data]),
             "full": fc.DataRoots([os.path.join(full_overlay, "Data"), game_data])}
    unit_rel = "fx/units/normal unit.fx"
    results, failures = [], []
    for fog in (None, 0xFF00FF00):
        for flags in CASES:
            if fog is not None and flags != CASES[1]:
                continue
            d = dict(base_defines)
            d["PS_VERSION"], d["VS_VERSION"] = engine_versions(flags)
            for f in flags:
                d[f] = "1"
            params = dict(PARAMS)
            if fog is not None:
                params["k_FogAttributes"] = (0.0, 1.0, 1.0, 0.5)   # static fog factor 0.5
            imgs, passes = {}, {}
            for key in ("stock", "base", "full"):
                path = roots[key].find(unit_rel)
                eff = dev.effect(path, d, roots[key])
                imgs[key], passes[key] = dev.render(eff, "NormalModel", params, tex,
                                                     quad("k_IsBeingReflected" in flags), fog=fog)
                fc._release(eff)
            px = lambda k, x, y: fr.RefDevice.pixel(imgs[k], SIZE, x, y)  # noqa: E731
            max_base = max(abs(a - b) for a, b in zip(imgs["stock"], imgs["base"]))
            darker = max(max(0, b - f) for b, f in zip(imgs["base"], imgs["full"]))
            team_s, team_f = px("stock", 8, 16), px("full", 8, 16)
            plain_s, plain_f = px("stock", 24, 16), px("full", 24, 16)
            drawn = any(imgs["full"][i] or imgs["full"][i + 1] or imgs["full"][i + 2] for i in range(0, len(imgs["full"]), 4))
            entry = {"flags": flags, "fog": fog is not None, "passes": passes,
                     "max_abs_diff_stock_vs_base": max_base, "max_darkening_full_vs_base": darker,
                     "team_px_stock": team_s, "team_px_full": team_f,
                     "plain_px_stock": plain_s, "plain_px_full": plain_f, "drawn": drawn}
            problems = []
            sanity = bool(SANITY_ONLY & set(flags))
            if not sanity and max_base > 2:
                problems.append(f"base differs from stock by {max_base}/255")
            if darker > 2:
                problems.append(f"full darker than base by {darker}/255")
            if not drawn:
                problems.append("nothing drawn (depth mismatch or NaN)")
            if "k_IsPlayerColor" in flags and "k_ApplyFogOfWar" not in flags and fog is None \
                    and not (team_f[0] >= team_f[1] and team_f[0] >= team_f[2]):
                problems.append(f"team colour hue lost: {team_f}")
            if passes["stock"] != passes["full"]:
                problems.append(f"pass count {passes['stock']} -> {passes['full']}")
            entry["problems"] = problems
            results.append(entry)
            if problems:
                failures.append(entry)
    return results, failures


# ---------------------------------------------------------------- terrain and water
WORLD_PARAMS = {
    "k_WorldToClip": IDENT, "k_LocalToClip": IDENT, "k_LocalToWorld": IDENT,
    "k_LevelOfDetail": (0.5, 0, 0, 0) + (0, 0, 0, 0) * 4,
    "k_UVScaleAndOffset0": (8.0, 1.0, 0.0, 0.0), "k_UVScaleAndOffset1": (6.0, 6.0, 0.1, 0.2),
    "k_ShadowMapCoords": (-1.0, -1.0, 0.5, 0.5),
    "k_TextureMultiplier": (2.0,), "k_CameraPosition": (0.2, -0.5, 3.0),   # z is height in the world
    "k_LightDirection": _norm((0.4, 0.3, 0.85)), "k_LightColor": (1.0, 0.95, 0.85),
    "k_SpecularColor": (1.0, 0.95, 0.9), "k_AmbientColor": (0.3, 0.3, 0.35),
    "k_RimLightColor": (0.3, 0.3, 0.35), "k_RimLightPower": (2.0,),
    "k_FogAttributes": (0.0, 1000.0, 1.0, 0.0),
    "k_WaterLevel": (0.5,), "k_WaveAmplitude": (0.05,), "k_GameWorldTime": (1.0,), "k_FallOffDepth": (-3.0,),
}


def world_quad(normal=(0.0, 0.0, 1.0)):
    pts = [((-1, 1), (0, 0)), ((-1, -1), (0, 1)), ((1, 1), (1, 0)), ((1, -1), (1, 1))]
    return [fr.terrain_vertex(p, normal, uv) for p, uv in pts]


def world_textures(dev):
    def bump(x, y):
        return (int(128 + 70 * math.sin(x * 0.8)), int(128 + 70 * math.cos(y * 0.7)), 220, 110)
    return {
        "k_Texture0": dev.texture(16, 16, lambda x, y: ((60 + 9 * x) % 256, (90 + 7 * y) % 256, 50, 220)),
        "k_Texture1": dev.texture(16, 16, lambda x, y: (170, 160, 150, 128)),
        "k_Texture2": dev.texture(16, 16, bump),
        "k_Texture3": dev.texture(16, 16, lambda x, y: (128, 128, 255, 255)),
        "k_ShadowMapTexture": dev.texture(16, 16, lambda x, y: (255, 255, 255, 255) if x < 12 else (90, 90, 90, 255)),
    }


def world_water_textures(dev, base):
    t = dict(base)
    t["k_Texture0"] = dev.cube_texture(8, lambda f, x, y: (80 + 20 * f, 120 + 10 * y, 200, 255))
    t["k_Texture1"] = dev.texture(16, 16, lambda x, y: (200, 200, 200, 255))
    return t


WORLD_CASES = [
    ("fx/terrain/default terrain.fx", "DefaultTerrainBumpmapAlpha", ["k_UseLightCube"]),
    ("fx/terrain/default terrain.fx", "DefaultTerrainBumpmapNoStretch", ["k_UseLightCube"]),
    ("fx/terrain/default terrain.fx", "DefaultTerrainBumpmap", []),
    ("fx/terrain/default terrain.fx", "DefaultTerrainWithShadows", []),
    ("fx/water/default water.fx", "AdvancedWaterPerPixelSpecular", []),
    ("fx/water/default water.fx", "AdvancedWater", []),
    ("fx/water/default water.fx", "AdvancedWaterPerPixelSpecular", ["k_IsBeingReflected"]),
]


def _lum(img):
    px = [img[i:i + 3] for i in range(0, len(img), 4)]
    return sum(0.3 * p[0] + 0.59 * p[1] + 0.11 * p[2] for p in px) / len(px)


def run_world(game_dir, base_overlay, full_overlay, base_defines):
    game_data = os.path.join(game_dir, "Data")
    dev = fr.RefDevice(os.path.join(game_dir, "d3dx9_27.dll"), SIZE)
    tex = world_textures(dev)
    wtex = world_water_textures(dev, tex)
    refl = dev.texture(16, 16, lambda x, y: (220, 180, 140, 120))
    roots = {"stock": fc.DataRoots([game_data]),
             "base": fc.DataRoots([os.path.join(base_overlay, "Data"), game_data]),
             "full": fc.DataRoots([os.path.join(full_overlay, "Data"), game_data])}
    results, failures = [], []
    for rel, tech, flags in WORLD_CASES:
        d = dict(base_defines)
        for f in flags:
            d[f] = "1"
        textures = dict(wtex if "water" in rel else tex)
        if "k_IsBeingReflected" in flags:
            textures["k_TextureReflectionMap"] = refl
        imgs = {}
        for key in ("stock", "base", "full"):
            eff = dev.effect(roots[key].find(rel), d, roots[key])
            imgs[key], _ = dev.render(eff, tech, WORLD_PARAMS, textures, world_quad(), layout="terrain")
            fc._release(eff)
        max_base = max(abs(a - b) for a, b in zip(imgs["stock"], imgs["base"]))
        max_full = max(abs(a - b) for a, b in zip(imgs["stock"], imgs["full"]))
        ls, lf = _lum(imgs["stock"]), _lum(imgs["full"])
        drawn = lf > 0.5
        problems = []
        if max_base > 2:
            problems.append(f"features-off build differs from stock by {max_base}/255")
        if not drawn:
            problems.append("full build drew nothing / black")
        if ls > 1 and not (0.6 <= lf / ls <= 1.6):
            problems.append(f"mean luminance moved too far: {ls:.1f} -> {lf:.1f}")
        entry = {"file": rel, "technique": tech, "flags": flags, "max_abs_diff_stock_vs_base": max_base,
                 "max_abs_diff_stock_vs_full": max_full, "mean_luma_stock": round(ls, 1),
                 "mean_luma_full": round(lf, 1), "problems": problems}
        results.append(entry)
        if problems:
            failures.append(entry)
    return results, failures
