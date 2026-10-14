# Optional 2x HD texture pass

Offline only. Reads `D:\Games\Rise and Fall\Data`, writes `work\overlay-hd\Data\textures\...` (gitignored). Nothing was installed into a game folder and the game was not launched. Code: `tools/build_textures.py` (HD section at the end; reuses `header`, `levels`, `full_chain`, `dxt_mean`, texconv from the mip step).

## Run

```
python tools/build_textures.py hd-terrain "D:/Games/Rise and Fall" work/overlay-hd
python tools/build_textures.py hd-units   "D:/Games/Rise and Fall" work/overlay-hd
python tools/build_textures.py hd-sheet   work/overlay-hd work/hd-samples.png    # before/after sheet, not for git
```

Each step writes `manifest-<step>.json` (per file: source and output sha256, sizes, method, plus skipped and failed lists). Both steps together take about 3 minutes on the RX 6800 XT. The process runs at below-normal CPU priority (children inherit it); GPU priority cannot be set, but a run is short.

## Tools (pinned)

- Real-ESRGAN ncnn-vulkan, `xinntao/Real-ESRGAN` release `v0.2.5.0`, asset `realesrgan-ncnn-vulkan-20220424-windows.zip` (45,474,481 bytes), SHA-256 `abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d`. Upstream publishes no checksum, so this is the hash of the download made on 2026-10-15 (trust on first use; size matches the GitHub API). The newer `Real-ESRGAN-ncnn-vulkan` v0.2.0 zip ships no models, so it was not used. Unpacked to `work\tools\esrgan\bin`, downloaded and verified by `ensure_esrgan()` if missing.
- texconv `may2026` (hash pinned by the mip step).

## Selection

Files in `textures/` only, DXT1/3/5, 2D, power of two, long side 128..512 px (so output is at most 1024). Skipped: anything already >= 1024 on its long side, names with thumb/test/shadow/_alpha/cube/envmap/sky/cloud, cube maps, UI and effects (never matched), uncompressed formats, SpeedTree.

| Step | Prefixes | Selected | Of which bump | Skipped by rule |
|---|---|---|---|---|
| hd-terrain | `trn_`, `sha_`, `grnd_` | 116 | 22 | 94 already >= 1024, 86 by name (thumbs), 21 under 128 px, 7 cube/other |
| hd-units | `men_ cav_ anml_ spc_ gun_ nav_ bld_ wall_ brg_` | 257 | 56 | 245 already >= 1024, 2 under 128 px, 2 by name |

Note the two steps skip most of the big art: 339 of the prefix-matched files are already 1024 px or larger. The pass lifts the small and medium textures to 256..1024.

## Method

1. Decode level 0 with texconv to RGBA8.
2. Diffuse RGB: pad 16 px (wrap for `trn_/sha_/grnd_` so tiling stays seamless, reflect otherwise), Real-ESRGAN 4x with `realesrgan-x4plus`, crop, downscale to 2x with Lanczos, blend 0.8 ESRGAN + 0.2 Lanczos-2x of the source (tames invented detail). DXT1 cut-out texels decode to black, so they are filled from the nearest opaque colour (iterative dilation) before upscaling to avoid dark halos.
3. Alpha is upscaled separately with Lanczos (it carries team colour masks and blend masks, so no network). DXT1: re-thresholded at 128 to a hard 1-bit edge. DXT3/DXT5: kept smooth. RGB and alpha are never premultiplied; the PNG handed to texconv is straight alpha.
4. Bump files (` bump`/`_bump`, RGB normal, alpha is specular per `unit functions.fx`): Lanczos 2x for all channels, no ESRGAN. RGB is renormalized only if the source is a genuine unit-vector map (mean length within 1.00 +- 0.07): 66 files. 12 bump files have z saturated at 255 (mean length 1.15-1.3), renormalizing them would shift the look, so they get Lanczos only.
5. Re-encode with `texconv -m 0 -sepalpha -f <orig format> -dx9` (full mip chain; bump files also `-bc u`, uniform weights). Default BC1-BC3 quality otherwise; no dithering.
6. Validation per file (`hd_validate`): header FourCC and format equal source, size exactly 2x, mip count equals the full chain, body size matches the format layout, mean RGB of level 0 within 18 and mean alpha within 10 of the source, mip 3 consistent with level 0. All 373 pass. A separate check re-read all headers: legacy 128-byte headers, 0 outputs above 1024 px, 373 unique paths.

## Model choice

Compared on three samples (terrain cobblestone, unit diffuse with team alpha, building wall) as a 2x crop side by side with a Lanczos baseline (`work\hdtest\cmp.png`, not committed):

- `realesrgan-x4plus`: removes DXT blocking and gives crisp, natural stone and skin, colours stay put. Chosen.
- `realesrgan-x4plus-anime`: shifts colour and contrast (washed, plastic stone). Rejected.
- `realesr-animevideov3-x4`: faithful but soft, close to the Lanczos baseline, little gain. Rejected (kept as a fallback if x4plus looks too busy in game).

The model only does 4x, so the output is Lanczos-downscaled to 2x (the 4x step recovers detail, the downscale averages out noise).

## Size delta (against the source files of the same names)

| Step | Files | Source | Output | Delta |
|---|---|---|---|---|
| hd-terrain | 116 | 22.7 MB | 94.8 MB | +72.1 MB |
| hd-units (units + buildings) | 257 | 54.4 MB | 217.6 MB | +163.2 MB |
| Total | 373 | 77.1 MB | 312.4 MB | +235.3 MB |

Budget was +700 MB, so there is headroom; it is not used because the 1024 px cut-off and 2x limit exclude the larger files. Every texture is exactly 4x its old texel count and about 4x its old bytes.

Memory view: the same 235 MB is the worst-case increase in system-memory copies if D3D9 keeps managed copies and the engine loads everything (probably; not measured). The loaded set at any moment is smaller. Under DXVK the managed copy lives on the Wine side too, so the 32-bit process (LAA, 4 GB) is the limit to watch.

## Samples

`work\hd-samples.png` (not committed, derived art): six textures, three terrain-group (`sha_pathable_rock10`, `sha_ypmarketstand15_02`, `trn_ydesertgrass_0t`) and three unit/building (`bld_yethrough_statuet`, `gun_ymcatapult_02t`, `men_ypinfantry_l1_02t`), 128 px source crop, before (nearest) left, after right. Looked at it: blocking and noise are gone, edges are cleaner, colours and the cut-out/mask regions match. The market stand sample is a black texture (shadow-like), so it shows nothing. Tiling check: terrain edge-to-edge difference relative to inner gradient rises by about 1.3x, which is what halving the pixel pitch alone explains; no seam was introduced (numeric, not seen in game).

## Install and precedence

The overlay holds the same relative paths as `work\overlay` (mip pass) for these files, with a full chain already included. If both are installed, the HD overlay must win for the 373 paths. Enable terrain and units independently by copying only that step's files (the per-step manifests list them).

## Risks

- Not verified in the game: no render, no FPS, no memory number. Needs the in-game tests below.
- 4 GB address space: +235 MB of textures; VRAM and managed-pool copies both grow. If the game works near the limit on big maps, enable `hd-terrain` first (+72 MB, tiled across the whole map) and watch committed memory.
- Terrain layers are blended by the DXT3/5 alpha mask; the mask is only bicubic-upscaled, so splat edges stay as soft as before.
- Mixed sharpness: the large 1024/2048 textures are untouched, so some objects will look sharper than their neighbours. Intended (stock sizes already high there).
- The network can invent detail (painted textures like animal fur look more realistic than painted). The 0.2 Lanczos blend reduces it; `BLEND` in the script is the knob.
- Team colour uses diffuse alpha 0; alpha is Lanczos then kept soft for DXT3/5, so the mask edge is slightly wider than before and may tint borders. Check one unit in a non-default team colour.
- The 12 non-unit-length bump maps are not renormalized; a lit surface test should confirm they look the same as before.
- ESRGAN hash is first-use, not upstream-signed.

## In-game tests

1. Install `overlay-hd` hd-terrain only; load a skirmish map, screenshot the same camera before/after: terrain sharper, no seams at tile borders, no black or pink textures. Record process commit memory (32-bit exe) at map start and after 5 minutes.
2. Add hd-units; check one unit in two team colours (team colour area must stay correct, no coloured fringe), one building, one normal-mapped unit under a low sun (bump lighting unchanged in tone).
3. FPS on one large map with 1v1 AI: compare mip overlay only versus plus hd-terrain versus plus both. Failure means a crash on load, texture streaming hitches, or > ~300 MB growth in process memory.
