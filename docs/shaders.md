# Shader upgrade (units, terrain, water)

State: **built, compile-checked with the game's own compiler, pixel-tested on the D3D9 software rasterizer. Not installed, not seen in game.** Nothing was written into a game folder and the game was not launched.

The overlay is opt-in: it only takes effect once its `Data` folder is copied over the game's `Data`. Every new effect also has its own switch in `RAF Config.fx` (`--set NAME=0` at build time), so each one can be turned off on its own for an in-game A/B test.

## Build, check, install, revert

```
python tools/build_shaders.py "D:/Games/RAF-remaster" work/overlay-shaders            # all groups
python tools/build_shaders.py <game> <out> --only units --set RAF_UNIT_RIM=0           # subset / tuning
python tools/check_shaders.py "D:/Games/RAF-remaster" work/overlay-shaders --out work/shader-check
python tools/shader_cache.py "D:/Games/RAF-remaster/shader.cache"                      # what the engine compiled
```

- `build_shaders.py` reads the stock `.fx` files from `<game>/Data` and applies `shaders/edits.json`. It writes `<out>/Data/fx/...` and `<out>/shader-manifest.json`, which records the stock and output sha256 of every file. It refuses to write inside the game folder. Patch anchors must match an exact number of times. Replaced files must match the stock sha256 they were written for. Either failure stops the build (tested by changing a fake stock copy).
- `check_shaders.py` runs every offline test (details below). It needs a 32-bit Python because `d3dx9_27.dll` is 32-bit. It finds one through `uv python find cpython-3.12-windows-x86-none` (installed once with `uv python install cpython-3.12-windows-x86-none`) or the `RAF_PY32` variable. It exits 1 on any failure.
- **Install:** back up the 7 existing files listed under "patch/replace" in the manifest from `D:\Games\RAF-remaster\Data\fx`. Then copy `work/overlay-shaders/Data` over `D:\Games\RAF-remaster\Data`.
- **Revert:** restore those 7 files and delete the 3 added files: `fx/RAF Config.fx`, `fx/terrain/include/RAF Terrain.fx` and `fx/water/include/RAF Water.fx`. `shader.cache` stores only defines and a permutation list, not bytecode (see the engine facts below), so it most likely does not need to be touched.

The repo holds no stock shader. `shaders/src` holds only our own files: two replacements and three new files. `shaders/edits.json` holds short anchors such as `compile PS_VERSION `.

## Engine facts that shaped the design

| Finding | Evidence | Confidence |
|---|---|---|
| Effects are loaded with `D3DXCreateEffectFromFileA(device, file, defines, <engine include handler>, Flags = 0x20, pool NULL)`. 0x20 is `D3DXSHADER_PARTIALPRECISION`. | `DX9Rasterizer.dll` 0x10010f58-0x10010f79 (push 0x20, then call through the thunk at 0x10043fdc to the IAT entry 0x100498fc) | code |
| The stock water effect only compiles **with** flag 0x20: without it, `VS_DefaultWaterDiffuse` needs 153 slots, over the vs_1_1 limit of 128. Every offline check therefore uses 0x20. | check run, `d3dx9_27` CompileEffect with flags 0 vs 0x20 | checked |
| Unit permutations are `#define`s from a table of 33 flags (index, define name, minimum shader model). `k_IsNormalMapped`, `k_IsSpecularPerPixel` and `k_IsRimLightPerPixel` require PS 2.0 (0x20000); all other flags require 1.1. | `LowLevelEngine.dll` 0x1002d1b4-0x1002df0b; the arguments of each registration call | code (table); the version meaning of the argument is likely |
| `PS_VERSION`/`VS_VERSION` are formatted `ps_%d_%d`/`vs_%d_%d` from a version accumulated over the enabled flags and compared against caps. So stock compiles a unit without a normal map as **ps_1_1**. | `LowLevelEngine.dll` 0x100301d7-0x1003023c | likely, from disassembly; consistent with the two caches below |
| `shader.cache` = u32 version, 16-byte id, 9 defines, then permutation records (effect id, variant, flag indices). The stock install's cache (native D3D9, `PS_VERSION=ps_2_0`) lists 302 records: 271 for units (effect 20), of which 249 use `k_UseLightCube`, 123 `k_IsNormalMapped`, 132 `k_IsPlayerColor`, 21 `k_IsSpecularPerPixel`, 21 `k_IsRimLightPerPixel`. | `tools/shader_cache.py`; parser checks it consumes the file exactly | checked |
| The remaster's cache says `PS_VERSION=ps_1_1` with one record (menu only). This is the max over the permutations seen so far, not a caps limit. | same | likely |
| Units are lit by a 6-colour light cube (`k_LightingRegion`), not by N·L with the sun. `k_LightDirection` is only used for specular and rim. | `unit functions.fx` (stock) `ComputeLighting`, cache flag counts | code |
| Terrain has no sun N·L at all. Its lighting appears to be baked into the mask texture (`k_Texture1` rgb). | `terrain functions.fx` (stock) `PS_DefaultTerrainBumpmap` | code; "baked" is likely |

Design consequences:
- Pixel shaders are pinned to **ps_2_b**, not the engine's `PS_VERSION`. Per-pixel lighting does not fit ps_1_1, and the stock normal-mapped unit PS already uses 63 of the 64 ps_2_0 slots. ps_3_0 is not used: D3D9 applies fixed-function fog (the `FOG` output) only for pixel shaders below 3.0, and every effect here relies on it. ps_2_a is the drop-in fallback (`--set RAF_PS_PROFILE=ps_2_a`, compiles clean).
- Unit vertex shaders, including the z-only pass, are pinned to vs_2_0. They share one position function, so the z-only pass and the `ZFunc EQUAL` colour pass of "accurate opacity" produce the same depth.
- No new effect parameters. All tuning is preprocessor constants. Parameter names, semantics, types, annotations, techniques, passes and vertex inputs are checked identical to stock for every permutation.

## What changed, per shader

### Units: `fx/units/normal unit.fx` (patched), `units/include/unit functions.fx` + `unit data structures.fx` (replaced by ours)

| | Stock | Now |
|---|---|---|
| Lighting | Light cube (or half-lambert fallback) **per vertex** for units without a normal map; per pixel only when normal-mapped | Per pixel for every unit: the interpolated world normal is renormalised and the cube is evaluated per pixel (`RAF_UNIT_PERPIXEL`) |
| Normal maps | Tangent and binormal are not skinned (stock comment: "TODO skin this") | Tangent and binormal are skinned with the same bones as the normal (`RAF_UNIT_SKIN_TBN`) |
| Specular | Per vertex, only with `k_IsSpecular` and only without player colour, masked by (2·(1−tex.a))²; per pixel with `k_IsSpecularPerPixel`, masked by (2·normal.a)² | Blinn-Phong per pixel for every unit, times N·L, power max(`k_Shininess`, 16). Same stock masks where the material has one, otherwise 0.08 (`RAF_UNIT_SPEC`, `RAF_UNIT_SPEC_DEFAULT`) |
| Rim | Only for `k_IsRimLightPerPixel` materials | Those keep the stock formula and colour. All others get a gentle Fresnel rim tinted by the cube light, stronger against the sun (`RAF_UNIT_RIM`) |
| Blending | Everything in gamma space | Base colour exactly as stock (texture + team colour, ×light×2). Specular and rim are added in linear light (`sqrt(base² + add)`), so they brighten rather than wash out, and add nothing when zero |
| Team colour | `tex.rgb += k_PlayerColor * (1 − tex.a)` | Same line, same place; alpha output logic is identical |
| Fog of war, highlight, accurate opacity, shadow-map pass, z-only pass, reflections | as stock | Same math. Spec and rim are applied before fog of war, so units under fog do not glint, and are off in reflections. The highlight pass is lit like the base pass |
| Profiles | `VS_VERSION`/`PS_VERSION` (per permutation), z-only vs_1_1 | vs_2_0 / ps_2_b (max 112 VS / 67 PS slots over all 271 permutations) |

### Terrain: `terrain/include/terrain functions.fx` (stock PS renamed `_Stock`, ours appended via `RAF Terrain.fx`), `terrain/default terrain.fx` (ps_2_0 → `RAF_PS_PROFILE`)

| | Stock | Now |
|---|---|---|
| Diffuse | tile × mask × multiplier; the bump map is only used for rim, specular mask and glow | Adds relief: N·L of the bump normal (tangent-space light the VS already passes), taken as a ratio to the flat surface. Baked lighting is kept on average, and bumps catch light and shade per pixel (`RAF_TERRAIN_RELIEF`, amount 0.55) |
| Tiling | one sample | A second sample of the same tile texture, rotated 37° at 0.173 scale, modulates brightness against the texture's mean (lowest mip) to break up repetition (`RAF_TERRAIN_DETAIL`, amount 0.4). No new texture |
| Shadow map, layer alpha, rim, specular, glow, fog | | unchanged (identical code) |
| Low-quality techniques (`DefaultTerrainWithShadows`, fixed function; `simple terrain.fx`) | | unchanged |

### Water: `water/include/water functions.fx` (stock PS renamed, ours appended via `RAF Water.fx`), `water/default water.fx` (ps_2_0 → `RAF_PS_PROFILE`)

| | Stock | Now (`RAF_WATER`) |
|---|---|---|
| Wave normal | average of two bump samples | "whiteout" normal blend of the two samples (less flattening), normalised in both techniques |
| Fresnel | reflection fixed at `k_AmountEnvMap` (0.3), plus a tint of `pow(1−N·V, 4)` | Schlick (F0 0.02) raises the reflection toward 0.72 at grazing angles and reduces the water body colour accordingly. The stock tint and its opacity rise stay |
| Specular | broad vertex spec + `k_Shininess` per-pixel term | the same, plus a tight sun glint (power 220) in linear light that also raises alpha so it is not lost in the transparency |
| Medium/Low techniques (fixed function + `texbem` asm) | | unchanged |

## Offline verification (2026-10-15)

Run `python tools/check_shaders.py "D:/Games/Rise and Fall" work/overlay-shaders --out work/shader-check`. The reports are `work/shader-check/report.txt` and `report.json`.

- **Toolchain on stock:** all 26 technique files compile with `d3dx9_27` (the engine's compiler, engine flags and defines from `shader.cache`). All 26 also create on a D3D9 NULLREF device with `D3DXCreateEffect`, and all 26 compile with `d3dcompiler_47` `fx_2_0`. The 47 include-only files do not compile on their own, as expected. `normal unit.fx` is compiled with `k_UseRigidAnimation`, because the engine always sets a skinning flag.
- **Overlay:** `normal unit.fx` covers all 271 unit permutations from the stock cache. Terrain and water (default, simple and debug) cover 4 permutations each: ±`k_UseLightCube` and ±`k_IsBeingReflected`. Results:
  - `d3dx9_27` compile OK 287/287, NULLREF device create OK 287/287, `d3dcompiler_47` OK 287/287;
  - interface diffs 0: parameters, semantics, types, annotations, techniques, passes, and the vertex input semantics read by each VS.
- **Negative controls:**
  - a renamed technique plus one added parameter makes all 271 checks fail;
  - a z-only VS that reads `NORMAL` is caught as a vertex-input diff in the 91 accurate-opacity permutations;
  - team colour scaled by 0.8 fails 10 of 12 pixel tests.
- **Variants:** `RAF_LIGHT_SIGN=-1`, `RAF_UNIT_PERPIXEL=0`, `RAF_UNIT_SKIN_TBN=0`, `RAF_TERRAIN_BUMP_YSIGN=-1` and `RAF_PS_PROFILE=ps_2_a` all compile clean with 0 diffs.
- **Pixel tests on the REF rasterizer** (`d3dref9.dll`, software, no GPU), stock against our build with all new terms off:
  - **15 unit permutations:** rigid, 2/3/4 bones, normal-mapped, fog of war, accurate opacity, highlight, reflected, alpha blend, half-lambert fallback, and FF fog on/off. Our build with the new terms off matches stock within **≤1/255** on every pixel. The exceptions are the 2 cases where stock itself adds specular, which are sanity-checked only. The full build never darkens a pixel. Team-colour texels keep red dominant: stock (255,226,134) → full (255,236,152). Accurate opacity draws, so depth matches between passes. Fixed-function fog is still applied under ps_2_b.
  - **Terrain (4 techniques) and water (3 cases):** our build with features off matches stock at **0/255**. With features on, terrain mean brightness moves −1.3 % and water +16 % to +30 % (glint and fresnel), with no black or NaN output.

## Risks

1. **ps_2_b under DXVK.** It compiles to bytecode version 2.1 (ps_2_x). DXVK reports SM3, so it should accept it, but that is not verified. If units, terrain or water turn invisible, black or pink, rebuild with `--set RAF_PS_PROFILE=ps_2_a`. If that also fails, use `--only` to isolate the group.
2. **Light direction sign.** All the code agrees that `k_LightDirection` points toward the sun: stock lighting, specular and rim, and the water lighting. This is still not verified in game. If highlights sit on the shadow side, rebuild with `--set RAF_LIGHT_SIGN=-1.0F`. Terrain relief also depends on the bump map's green-channel convention (`RAF_TERRAIN_BUMP_YSIGN`).
3. **`k_SpecularColor` / `k_LightDirection` unset.** If the engine leaves them at zero, specular, rim tint and glint silently vanish. A zero light switches the terms off rather than producing NaN. The in-game test shows which.
4. **Look changes.** The default specular of 0.08 on every unit material can make matte cloth look slightly sheeny; tune with `RAF_UNIT_SPEC_DEFAULT`. Terrain detail on textures without a mip chain falls back to comparing against the base sample, so it is noisier there.
5. **Normal maps can be dropped by the engine.** Normal-map flags probably require PS 2.0 caps. Under DXVK the caps are 3.0, so they should be on. If `tools/shader_cache.py` shows no `k_IsNormalMapped` after a match, units get the vertex-normal per-pixel path only.
6. **Performance:** pixel shaders roughly double in length (unit PS up to 67 slots, terrain 85, water 108). This is negligible on modern GPUs but not measured.

## In-game test checklist

Before installing: take screenshots of the stock look for the same scenes, at the same camera and time of day. Use a skirmish with at least 2 AI players with clearly different team colours (red vs blue) on a map with water, and set the in-game terrain and water detail to the highest level (the Ultra techniques).

| # | Where / what | Expect | Broken looks like |
|---|---|---|---|
| 1 | Load the skirmish | Loads as stock; DXVK log (`*_d3d9.log` next to the exe) has no new shader errors | Crash or error dialog on load; units, terrain or water missing; pink or black geometry → rebuild with `RAF_PS_PROFILE=ps_2_a`, then bisect with `--only` |
| 2 | Zoom fully in on own infantry and cavalry next to enemy units | Team-colour areas (shields, tunics, banners) keep exactly the stock hue on both teams; smoother shading on round shapes; a highlight on the sun side; a faint rim on silhouettes | Team colour missing, grey or wrong hue; units uniformly too bright or too dark; highlight on the side away from the sun → `RAF_LIGHT_SIGN=-1.0F` |
| 3 | Select units, hover enemies | Selection highlight pulses as stock | Highlight missing or the whole unit white |
| 4 | Units at the edge of the fog of war | Darkened like stock, no glints inside the fog | Glinting units in black fog |
| 5 | A unit dying or fading, a building placement ghost, units behind buildings | Fade-in and fade-out as stock, no holes | Parts missing or flickering (depth mismatch between the z-only and colour passes) |
| 6 | Large buildings and ships (normal-mapped, often specular) | Normal-map detail under the per-pixel light, no seams on animated parts | Shading jumps at bone boundaries; inverted bumps |
| 7 | Terrain close and far, sun low and high | Bumpy ground shows relief toward the sun; less visible tiling at mid distance; shadows and distance fog as stock | Terrain darker overall, banding, a striped detail pattern, or relief lit from the wrong side (`RAF_TERRAIN_BUMP_YSIGN` / `RAF_LIGHT_SIGN`) |
| 8 | Water: look toward the sun, then a low grazing camera | Sharp sun glints; reflections stronger at grazing angles; shoreline transparency as stock; ships still reflected | Water opaque white, or black, or the glint on the opposite side |
| 9 | Big battle, FPS before and after | Within a few % | Large FPS drop |
| 10 | `python tools/shader_cache.py D:/Games/RAF-remaster/shader.cache` after the match | Effect 20 lists `k_IsNormalMapped` (normal maps active under DXVK) | No `k_IsNormalMapped`: risk 5 |

For A/B testing, rebuild with one feature off (for example `--set RAF_UNIT_RIM=0` or `--set RAF_WATER=0`) and reinstall. Each `RAF_*` switch is independent.

## Not verified

- No change has been seen in the real game or under DXVK. The pixel tests run on Microsoft's REF rasterizer with synthetic inputs, not the game's meshes and textures.
- That the engine sets `k_LightDirection`, `k_SpecularColor` and `k_Shininess` for unit effects. Stock unit specular uses them, so this is likely.
- Whether the engine supplies `k_LightingRegion` for all units: 249/271 stock permutations use it, and the rest use the half-lambert fallback, which is also tested.
- Skinned animation in game. The bone math is tested only with a synthetic bone palette.
- Performance.
