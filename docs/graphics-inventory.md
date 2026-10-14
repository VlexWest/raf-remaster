# Rise and Fall: graphics inventory (textures and shaders)

Read-only pass over `D:\Games\Rise and Fall\Data`. Nothing was written into the game folder and the game was not launched.
Tools (this batch): `tools/dds_inventory.py`, `tools/dds_stats.py`, `tools/fx_inventory.py`, `tools/texture_groups.py`.
Short hashes (sha256): dds_inventory `8675d0928bd1aaf5`, fx_inventory `b02f85764107e4b9`, dds_stats `8773a53fd85d14b7`, texture_groups `2ed5fc555282063c`.
Evidence is cited as file and line in the `fx/` folder. Everything comes from headers & source unless marked "likely".

## 1. DDS textures

Every DDS sits in `textures/` (1939 files, 526.8 MB) or `speedtree/textures/` (79 files, 18.3 MB). No other top-level folder holds DDS.

| Metric | Value |
|---|---|
| Total DDS | 2018 files, 545.1 MB |
| All header-valid | 2018 / 2018 |
| Mip chain stored (mipcount > 1) | 1500 |
| Header mipcount 0 (one level only) | 518 (mostly 64x64 and 32x32; not verified per file) |
| Cube maps | 17 |
| Non-square | 264 |
| Non-power-of-two | 1 (1024x768) |

Resolution histogram (w x h: files):

| Size | Files | | Size | Files |
|---|---|---|---|---|
| 64x64 | 545 | | 1024x512 | 137 |
| 512x512 | 397 | | 256x512 | 33 |
| 1024x1024 | 258 | | 32x32 | 118 |
| 256x256 | 226 | | 512x1024 | 18 |
| 128x128 | 196 | | 2048x2048 | 10 |

Others (2048x1024, 2048x512, 1024x768, 64x1024 and smaller sizes): 36 files in total.

Longest side: at least 256 px 1142 files (538.9 MB); at least 512 px 884 files (524.3 MB); at least 1024 px 436 files (402.4 MB); at least 2048 px 13 files (48.7 MB).

Compression (header FourCC):

| Format | Files |
|---|---|
| DXT3 (BC2) | 1032 |
| DXT1 (BC1) | 772 |
| DXT5 (BC3) | 162 |
| Uncompressed RGB32 | 46 |
| Uncompressed RGB16 | 5 |
| Uncompressed RGB24 | 1 |
| BC4/BC5/BC7, DX10 header | 0 |

Largest 15 files (MB, file, size, format, mips):

| MB | File | Size | Fmt | Mips |
|---|---|---|---|---|
| 5.33 | textures/3DU_yMain_Backdrop.dds | 2048x2048 | DXT3 | 12 |
| 5.33 | textures/men_ygheighttest_bump.dds | 2048x2048 | DXT5 | 12 |
| 5.33 | textures/trn_ybasedrygrasst_bump.dds | 2048x2048 | DXT3 | 12 |
| 5.33 | textures/trn_ybasegrassdirtt_bump.dds | 2048x2048 | DXT3 | 12 |
| 5.33 | textures/trn_ybasegrasst.dds | 2048x2048 | DXT3 | 12 |
| 5.33 | textures/trn_ybasegrasst_bump.dds | 2048x2048 | DXT3 | 12 |
| 5.33 | textures/sfx_yfiresequence_nocolor.dds | 1024x1024 | RGB32 | 11 |
| 3.00 | textures/clearskysunlp_cube_ldr.dds | 1024x1024 | DXT1 | 0 |
| 2.67 | textures/spc_yecleocoffin_0t_bump_cinematic.dds | 2048x1024 | DXT3 | 12 |
| 2.67 | textures/spc_yecleocoffin_0t_cinematic.dds | 2048x1024 | DXT3 | 12 |
| 2.67 | textures/men_ygheighttest.dds | 2048x2048 | DXT1 | 12 |
| 2.67 | textures/trn_ybasedesertt.dds | 2048x2048 | DXT1 | 12 |
| 2.67 | textures/trn_ybasedrygrasst.dds | 2048x2048 | DXT1 | 12 |
| 2.67 | textures/trn_ybasegrassdirtt.dds | 2048x2048 | DXT1 | 12 |
| 1.33 | textures/amb_yeshipwreck_0t.dds | 1024x1024 | DXT3 | 11 |

Special maps by name (flags are name-based; the shader confirms only the normal and team-color roles, see section 2):

| Kind | Files | MB | Evidence |
|---|---|---|---|
| Normal maps (`_bump`, or ` bump` with a space) | 263 (141 `_bump`, 91 ` bump`) | 163.3 | 229 of them have a same-name base texture. Formats: DXT1 148, DXT3 110, DXT5 4, RGB24 1. |
| Team color | no separate file | - | The unit shader adds the player color where the diffuse alpha is 0 (`fx/units/include/unit functions.fx` ~l.592-595). The team mask is the diffuse alpha channel. |
| Specular in normal map alpha | in the `_bump` files | - | `unit functions.fx` ~l.649-652: specular amount = (2 x normal.a)^2. |
| Shadow / alpha masks | 36 `_shadow`, 2 `_alpha` | - | Names only. |
| Thumbnails (`_thumb`) | 65 | 0.1 | Editor previews; the `trn_` rule claims them first in texture_groups.py, so they show as 0 there. |
| Test and debug | 28 with "test" in the name | 19.2 | e.g. mipmaptest, rdtest. Candidates to skip. |
| Neutral normal | `blanknormalmap.dds` | - | Name only. |
| Cube/env maps | 13 `_cube_ldr`, 7 `envmap` | 12.5 + 1.2 | Name plus header. |

Other image formats (not DDS):

| Format | Files | Size | Where | Notes |
|---|---|---|---|---|
| TGA | 75 | 55.3 MB | 70 in `textures/`, 5 in `speedtree/textures/` | 26 are 256x256 32-bit, 17 are 64x64, 6 are 1600x1200 24-bit, 1 is 1600x1200 32-bit. Names like `(2) corridor of blood.tga` suggest map preview images (likely). |
| HDR (Radiance RGBE) | 16 | ~10.3 MB | `textures/` | Sky and light probes, e.g. `clearskylp.hdr`, `stormylt.hdr`, `light_yclear.hdr`. |
| ENV | 18 | ~19 KB total | `environments/` | Binary (magic `VNER`), not an image. HDRI environment settings, e.g. `hdri desert day.env`. Keep as data. |

## 2. Shaders (`fx/`, 73 files)

Only 26 files define techniques (38 techniques in total). The other 47 are includes: constants, data structures, functions, render states and samplers, grouped per family. Every technique is a plain-text D3D9 effect.

Shader-model use (by file, from the `compile` lines):

| Stage | Profiles | Files | Notes |
|---|---|---|---|
| Vertex | vs_1_1 | 26 (every technique file) | Includes the z-only pass of normal unit.fx. |
| Vertex | vs_2_0 | 1 (water) | Only the water file. |
| Vertex | VS_VERSION macro | 1 (units/normal unit.fx) | Main unit passes. Chosen outside the Data folder. The macro is defined nowhere in `Data` (grep), so the engine supplies it, probably per caps. |
| Pixel | ps_1_1 | 11 | Fog of war (4), simple terrain, SpeedTree billboards, imposters, selection shapes and water (mixed profiles). |
| Pixel | ps_1_4 | 4 | Post: blur H/V, high pass, screen filter. |
| Pixel | ps_2_0 | 6 | Screen-distortion particles, post blur H/V, high pass, default terrain, default water. |
| Pixel | PS_VERSION macro | 1 (units/normal unit.fx) | Same as the VS macro. |

Shader table (judged by name and technique and pass names):

| File | Size (B) | Techniques | What it does (likely, from names) | Models |
|---|---|---|---|---|
| fx/default/constants.fx | 557 | - | Global constants: world/clip matrices, fog, light, time. | include |
| fx/default/functions.fx | 5394 | - | Shared math: lighting, rim, normal helpers. | include |
| fx/flora/flora.fx | 2905 | DeformableFloraWithWind, FloraWithWind, BasicFlora | Grass and small plants with wind and hero-bend deformation. | vs_1_1 |
| fx/fog of war/fog of war billboards.fx | 866 | FogOfWarBillboards | Fog-of-war cloud sprites. | ps_1_1, vs_1_1 |
| fx/fog of war/fog of war edge.fx | 986 | FogOfWarEdge | Fog edge transition, 2 passes. | ps_1_1, vs_1_1 |
| fx/fog of war/fog of war plane.fx | 836 | FogOfWarPlane | Fog plane over the map. | ps_1_1, vs_1_1 |
| fx/fog of war/fog of war water.fx | 841 | FogOfWarWater | Fog applied to water. | ps_1_1, vs_1_1 |
| fx/particles/oriented particles.fx | 1090 | ParticlesOriented | Camera-facing particles. | vs_1_1 |
| fx/particles/screen distortion particles.fx | 894 | ScreenDistortionParticles | Heat or shock distortion, reads back buffer. | ps_2_0, vs_1_1 |
| fx/particles/tile mapped particles.fx | 1720 | ParticlesTileMapped, ParticlesTileMappedAnisotropic | Sprite-sheet particles (fire, smoke). | vs_1_1 |
| fx/post/post blur horizontal.fx | 1103 | PostBlurHorizontal, ...Advanced | Gaussian blur, horizontal pass. | ps_1_4, ps_2_0 |
| fx/post/post blur vertical.fx | 1089 | PostBlurVertical, ...Advanced | Gaussian blur, vertical pass. | ps_1_4, ps_2_0 |
| fx/post/post high pass.fx | 1118 | PostHighPass, PostHighPassClamped | Bloom bright-pass. | ps_1_4, ps_2_0 |
| fx/post/post screen filter.fx | 1219 | PostScreenFilter | Full-screen color filter. | ps_1_4, vs_1_1 |
| fx/post/shadow mask.fx | 1029 | ShadowMask | Shadow mask for post. | vs_1_1 |
| fx/sky/sky box.fx | 2626 | SkyBox | Sky cube. | vs_1_1 |
| fx/terrain/debug terrain.fx | 1032 | DebugTerrain | Debug terrain view. | vs_1_1 |
| fx/terrain/default terrain.fx | 3044 | DefaultTerrainBumpmapAlpha, ...BumpmapNoStretch, ...Bumpmap, ...WithShadows | Main terrain: 4 tiled layers with mask, bump, rim light, shadow map. Three bump variants. | ps_2_0, vs_1_1 |
| fx/terrain/simple terrain.fx | 993 | SimpleTerrain | Low-end terrain path. | ps_1_1, vs_1_1 |
| fx/trees/speedtree/billboards.fx | 864 | DefaultSpeedTreeBillboards | Tree billboards for distance. | ps_1_1, vs_1_1 |
| fx/trees/speedtree/branches.fx | 1080 | DefaultSpeedTreeBranches | Tree trunks and branches, 2 passes. | ps_1_1, vs_1_1 |
| fx/trees/speedtree/fronds.fx | 1080 | DefaultSpeedTreeFronds | Palm and frond geometry, 2 passes. | ps_1_1, vs_1_1 |
| fx/trees/speedtree/leaves.fx | 1081 | DefaultSpeedTreeLeaves | Leaf cards, 2 passes. | ps_1_1, vs_1_1 |
| fx/units/imposters.fx | 3406 | Imposters | Far-LOD unit imposters (billboard sprites). | ps_1_1, vs_1_1 |
| fx/units/normal unit.fx | 2444 | NormalModel | Main unit shader, 6 passes: z-only, normal, highlight, shadow map, accurate opacity. Driven by #if permutations (`k_AccurateOpacity`, `k_ShouldHighlight`, `k_IsShadowMapObject`). | VS/PS macros, vs_1_1 (z-only) |
| fx/units/selection shapes.fx | 1126 | BasicSelectionShapes | Selection rings and shapes. | vs_1_1 |
| fx/units/shadow billboard.fx | 2221 | ShadowBillboard | Blob shadow under units. | vs_1_1 |
| fx/water/default water.fx | 3394 | AdvancedWaterPerPixelSpecular, AdvancedWater, DefaultWaterWithGlossMap, DefaultWater | Water: reflection, bump, Fresnel, shore falloff, gloss map. 4 techniques, 6 passes. | ps_1_1, ps_2_0, vs_1_1, vs_2_0 |

Include-only families (no techniques, so they are not separate effects): `flora/include`, `fog of war/include`, `particles/include`, `post/include`, `terrain/include`, `trees/include/speedtree`, `units/include` (unit constants 2482 B, functions 17476 B, render states 4056 B), `units/include/selection`, `water/include` (functions 12971 B), `default` (constants, functions).

Shader findings that matter for a remaster:
- Unit shading (`unit functions.fx`): the diffuse is `texture.rgb * diffuse * 2` (~l.555, 667). This uses a fixed multiplier, so a physically based path would be a new shader, not a tweak.
- Normal-mapped units exist via `k_IsNormalMapped` (~l.314, 507, 599-620). Terrain has bump variants (`default terrain.fx`).
- Specular: per-pixel from normal alpha (units), and a gloss-map water technique exists.
- Permutation switches (`#if k_...`) mean each technique is a family of compiled variants. The engine defines them; the Data folder does not (likely, from the `k_` names and the absent defines).

## 3. Visual priority for a remaster

Counts from `tools/texture_groups.py` (each file counted once, in the first group it matches; bump maps and thumbnails are counted with their owner group):

| Group | Files | MB | Priority | Why |
|---|---|---|---|---|
| Terrain (trn_) | 236 | 170.7 | Very high | Most of the screen. Seen at 2048 px in 6 files. |
| Terrain-adjacent (sha_, grnd_) | 88 | 5.2 | Medium | Pathable rock and ground decals. |
| Buildings (bld_, wall_, brg_) | 282 | 127.1 | Very high | Large, close, many. |
| Units, animals, ships, siege (men_, cav_, anml_, spc_, gun_, nav_) | 224 | 104.9 | Very high | The player's main view. Normal maps present. |
| Vegetation (amb_, flo_, res_, SpeedTree) | 248 | 48.7 | High | Tree bark, leaves and grass. Many small files. |
| Sky and env cubes (cube, envmap, sky, cloud, light_) | 46 | 24.0 | High | Lighting mood; the largest single cube is 3 MB. |
| Effects (sfx_, fx_) | 295 | 36.5 | Medium | Fire, smoke, and so on. Many small files. One 5.33 MB sprite sheet. |
| UI (but_, cur_, 3dui_, ui_, frm_, sel_, scenfull and others) | 482 | 16.0 | Low to medium | Mostly small. Keep the layout; upscale or re-do only if the HUD is in scope. |
| Test/debug | 6 | 2.1 | Skip | Not gameplay art. |
| Other (single-word and unprefixed names, misc) | 111 | 10.1 | Check | Includes the 37 unprefixed files such as `americansequoia.dds` and `oceanmist.dds`. |

Resolution budget: 884 files have a side of at least 512 px. Those hold 524 MB, so an upscale or re-encode pass on them is the bulk of the work. The 436 files at 1024 px and up hold 402 MB.

Recommendation (likely the best order): first a texture-only pass (AI upscale of the `trn_`, `bld_`, `men_` diffuse and normal maps, re-encoded to the same formats), then shaders. The terrain (ps_2_0 path) and water (ps_2_0) techniques are the only ones with a real pixel-shader-2.0 variant. A unit normal-map upgrade means editing `unit functions.fx` and its PS macro path, which is more work and needs the engine's permutation defines first.

## 4. Not verified

- Nothing was rendered. Visual importance above is by file count, size and role, not by seeing the game.
- The 518 DDS with mipcount 0 are one-level textures. Whether the engine generates mips at load is not checked.
- Shader-model behaviour under the current DXVK route is not checked. DXVK was reported to boot, but the vs_1_1 and ps_1_x paths were not confirmed to render correctly.
- The `VS_VERSION`/`PS_VERSION` macro values and the `k_` permutation defines live in the engine, not in Data. Not found in Data.
- Water texture roles (which DDS feed `DefaultWaterBumpSampler` and reflection) are not mapped. Names did not show them.
- Thumbnail counts are approximate (65 by name; grouping hides them).
- Team color is inferred from the shader code path at ~l.592-595; not checked with a rendered unit in a second team.

## 5. Reproduce

```
python tools/dds_inventory.py "D:/Games/Rise and Fall/Data" out/dds.csv
python tools/dds_stats.py out/dds.csv
python tools/texture_groups.py out/dds.csv
python tools/fx_inventory.py "D:/Games/Rise and Fall/Data" out/fx.txt
```

Scripts only read the Data folder. Write output outside the game folder.
