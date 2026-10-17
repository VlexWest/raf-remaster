# Rise and Fall data formats

Scope: the binary data in `D:\Games\Rise and Fall\Data` (2009 build, `RiseAndFall.exe` 13.5 MB).
Evidence is the bytes of the stock files plus a Ghidra 12.1.4 headless decompile of `RiseAndFall.exe`
(29,848 functions, kept outside git in `decomp\RiseAndFall.c`). Function names below (`FUN_xxxxxxxx`)
are Ghidra's default names = the function's address in the exe, so they can be found again in any
disassembler.

Unless noted, everything here is read from the bytes or the decompiled code; guesses are marked
"likely" (inferred, not checked in game). Nothing in this file was verified in the running game.

Tools:

- `tools/raf_data.py`: unpack / pack / round-trip for every `db\*.dat` (section 3).
- `tools/rafcodec.py`: the lossless binary <-> JSON field codec it uses.
- `tools/raf_cpnames.py`: names of the 143 AI parameters in `dbcpbehavior.dat` (generated).
- `tools/re/`: the scripts that produced the names from the decompile (`DecompAll.java` for Ghidra,
  `rx.py` capstone helper, `oosmap.py`, `aimap.py`, `objmap.py`, `cpuse.py`).

The engine is the Empire Earth lineage (Stainless Steel Studios): `dbtechtree.dat` has 14
epoch roots named `Epoch Paleo` ... `Epoch Nano`, the AI classes are `EEComputerPlayer`/`EECP*`, units
are `EEUnitClass`. Empire Earth 1 modding knowledge about the `db` files will likely partly transfer.

The exe has sections `.sforce3` and `.brick` (StarForce naming). The code decompiles cleanly where
I looked (AI, DB loaders, unit setup), so the protection does not hide the parts that matter here.

## 1. What each file type is

| Ext | Count | Magic / start | What it is | Gameplay? |
|---|---|---|---|---|
| `db\*.dat` | 51 | u32 count (mostly) | The game database: objects, tech tree, costs, AI parameters, civs, UI tables | **yes, all balance data** |
| `.udf` | 1891 | `USTR` + u32 version 0x42 | Unit/visual definition: model names (`..._MODEL`), animations, attachments. `db\string-graphic info.txt` maps each `.udf` to a `dbobjects` record name and a string id | no (visual) |
| `.sdf` | 919 | `SSTR` + u32 version 2 | Sound definition, one per sound (section 4.2) | no |
| `.edf` | 514 | `ESTR` + u32 version (0x1a..0x2f, per file) | Effect (particle) definition | no |
| `.sst` | 1664 | 15-byte header, then usually `DDS ` | Texture wrapper (section 4.3) | no |
| `.scn` | 54 | u32 payload length (file size - 4) | Scenario / multiplayer map: name, description, terrain, units, triggers (`ScenarioTriggers.scn`) | map content only |
| `.rmv` | 108 | text | Random map and map scripts (`#define`, `#if`, `DefineHerd`, `UseMapGenerator "Default"` = `Default.dll`) | starting units and resources per map (`random map scripts\common\common initial units.rmv`) |
| `.lcl` | 25 | text `{Version_0}` | Localized campaign text (cp1251 for the `-rus` files) with inline format codes (`/fp40#1200/ac/r225/g185/b35/f[...]`) | no |
| `.env` | 18 | `VNER` + u32 version 3 | Environment lighting (floats: colours, fog, HDR) | no |
| `.hdr` | 16 | `#?RADIANCE` | Radiance HDR sky maps | no |
| `.ssa` | 2 | `rass` + u32 1 | Campaign scenario list (`campaigns\Alexander.ssa`, `Cleopatra.ssa`) | no |
| `.tai` | 83 | text | Unit AI state machines (see `docs/ai.md`) | unit behaviour |

`string-graphic info.txt` in `db` is a tab-separated dev export: UDF file, object name, string id.

## 2. Where the balance data and the AI live

- **Unit stats** (hit points, attack, range, reload, speed-related, work rate, ammo): `dbobjects.dat`,
  one 2012-byte record per object (3079 records). `FUN_00a1dd00` copies record fields into the
  per-type unit object, and the unit out-of-sync dump (`OUT OF SYNCH DUMP:  Base Hit Points` etc.)
  names those object fields. Spear Infantry Rome L1/L3/L5 have `hit_points` 440/530/645 and
  `attack` 38/.../56 (record offsets 0x78 and 0xc4).
- **Costs and build/research items, epoch membership**: `dbtechtree.dat` (one node per buildable or
  researchable item, 2618 nodes under 14 epoch roots). Each node points to its `dbobjects` record
  (`object_index`) and holds the 7 cost fields.
- **Tech effects**: `dbevents.dat` (1500 slots, named events with a list of effect ids) and
  `dbeffects.dat` (2000 x 88-byte effect records, read as one block).
- **Upgrades / families / unit sets / calamities (powers)**: `dbupgrade`, `dbfamily` (81 families:
  `Anti Tank`, `Aircraft` ...), `dbunitset` (873 sets used by powers, AI and targeting), `dbcalamity`
  (147 powers: `Earthquake`, `Q Hurricane` ...), `dbcivpowers`, `dbspecialunittable`, `dbareaeffect`.
- **Damage table**: `dbweapontohit.dat` (6 rows `Shock`, `Arrow`, `Pierce`, `Gun`, `Laser`, `Missile`;
  percentages, all 100 in the stock file except the attacker type ids). Likely an attacker x defender
  multiplier table, currently neutral.
- **Starting resources per game type**: `dbstartingresources.dat` (`Normal`, `Death Match`,
  `Death Match (AI)`); per map: the `.rmv` scripts.
- **Civilizations**: `dbphoenixcivtable.dat` (12 slots: 0 Any, 3 Greece, 4 Persia, 5 Rome, 10 Egypt, the
  rest placeholders), `dbcivspecificunitdefines.dat`, `dbpremadecivs.dat`. `dbcivilization.dat` is
  empty (count 0).
- **Strategic / skirmish AI**: hard-coded C++ in `RiseAndFall.exe` (classes `EEComputerPlayer`,
  `EECPBuildManager`, `EECPResearchManager`, `EECPCombatManager`, `EECPAttackCommander`,
  `EECPDefenseCommander`, `EECPResourceManager`, `EECPExplorationManager`, `EECPDiplomacyManager`,
  `EECPWallManager`, `EECPSpecialPowersManager` ...). There is no build-order script. Every tunable
  number comes from `db\dbcpbehavior.dat` (section 3.4); `db\dbcivspecai.dat` can scale single
  records per civ (stock overrides are neutral, see 3.3 and `docs/ai-personalities.md`). `dbaiunittargeting.dat` (Melee / Short Range /
  Long Range) and `dbunitbehavior.dat` (Scout, Stand Ground, Guard, Harass, Cautious, Aggressive ...)
  hold unit-level AI settings. Not in `Default.dll`, `LowLevelEngine.dll` or any text file
  (searched for the parameter names: only the exe has them).

## 3. The `db\*.dat` database

### 3.1 Loading

`FUN_007182d0` registers every table: `UWideString(name)` then `FUN_00713200(table_id, FUN_005f8fd0)`.
`FUN_005f8fd0` switches on the table id and calls the table's loader. Loaders read through an
`FSFileSpec`: `Read(u32)` and a raw `Read(buffer, size)` (vtable +0x40). All little-endian.

Three things to know when editing:

1. Records are raw C struct dumps from the dev editor. Unused string bytes and some padding hold
   **uninitialised memory** (stack addresses like `0x0012d2..`, `0x77c...`). It is harmless, but a
   lossless tool must keep it (the codec stores it as `tail`/hex).
2. `dbrandommap.dat` says count 10 but holds 29 records (the exe reads 10). `dbeffects.dat` has no
   count. `dbterraingraytextures.dat` has no loader in the exe.
3. Strings inside records are fixed `char[N]`, cp1252/cp1251. `UWideString::Load` strings (used by
   `dbsounds`, `dbterrain`, `dbterraingraytextures`, and the `xSTR` files) are `u32 byte_length` +
   bytes, normally the text followed by two NUL bytes.

### 3.2 Layouts

| File | Layout | Record | Records | Loader (table id) |
|---|---|---|---|---|
| dbobjects | count + fixed | 2012 | 3079 | FUN_005f8ef0 -> FUN_005fa9e0 (2) |
| dbtechtree | 14 x { u32 nchild; node; nchild x node } | node = 452 + list + list | 14 roots, 2618 children | FUN_008d8260 -> FUN_008dff40 (root) / FUN_008e5550 (child) (6) |
| dbevents | 1500 x { char[100] name; i32 id; u8 flag; u32 n; i32[n] effects } | var | 1500 (261 named) | FUN_008d2fc0 (8) |
| dbeffects | 2000 x fixed, no count | 88 | 2000 | FUN_008d2fc0 (8, read as 0x2af80 bytes) |
| dbsounds | count + { UWideString path; fixed } | 4+n+232 | 1362 | FUN_00602120 (4) |
| dbterrain | count + { UWideString texture; fixed } | 4+n+304 | 113 | FUN_00605ba0 (0x0c) |
| dbterraingraytextures | count + { UWideString; fixed } | 4+n+120 | 133 | none found |
| dbcpbehavior | count + fixed | 56 | 143 | FUN_005f74b0 (0x1a) |
| dbcivspecai | count + fixed | 196 | 2 | FUN_005f7380 (0x34) |
| dbupgrade | count + fixed | 240 | 69 | FUN_0060c5b0 (0x19) |
| dbunitset | count + fixed | 272 | 873 | FUN_006ef030 (0x16) |
| dbfamily | count + fixed | 412 | 81 | FUN_00606ac0 (9) |
| dbcalamity | count + fixed | 268 | 147 | FUN_00571e20 (0x15) |
| dbareaeffect | count + fixed | 200 | 79 | FUN_00baf8c0 (0x17) |
| dbweapontohit | count + fixed | 132 | 6 | FUN_0060d310 (0x14) |
| dbstartingresources | count + fixed | 136 | 3 | FUN_00602990 (0x1e) |
| dbaiunittargeting | count + fixed | 160 | 3 | FUN_005f2250 (0x0b) |
| dbunitbehavior | count + fixed | 124 | 9 | FUN_0060d1c0 (0x1d) |
| dbcivpowers | count + fixed | 56 | 65 | FUN_00bc5cb0 (0x22) |
| dbphoenixcivtable | count + fixed | 364 | 12 | FUN_005ff420 (0x27) |
| dbcivspecificunitdefines | count + fixed | 216 | 60 | FUN_005f60a0 (0x28) |
| dbpremadecivs | count + fixed | 124 | 21 | FUN_00bc5010 (0x20) |
| dbgamevariant | count + fixed | 332 | 3 | FUN_005fbee0 (0x1f) |
| dbrandommap | count + fixed (+19 unread records) | 132 | 10 (29 in file) | FUN_006000e0 (0x10) |
| dbgraphics, dbbuttons, dbanimals, dbcrewedunitdetails, dbflora, dbmusic, dbnewgfxeffecttable, dbambientsounds, dbsoundgroups, dbtpwalkeffects, dbtpmeleeattackeffects, dbterraintype, dbterrainsettable, dbcliffterrain, dbworld, dbuihotkey | count + fixed | 212, 232, 272, 144, 1792, 216, 208, 144, 156, 140, 128, 128, 148, 124, 32, 136 | see tool | ids 3, 5, 0x1c, 0x35, 0x3a, 1, 0x26, 0x1b, 0x37, 0x38, 0x39, 0x0e, 0x36, 0x21, 0x0f, 0x29 |
| dbactiontable, dbcolortable, dbmousepointer, dbspecialunittable, dbuiback, dbuifonts, dbuiformevents, dbuiforms | count + fixed | 48, 168, 224, 168, 564, 128, 116, 404 | see tool | loader not traced; size = (file-4)/count, exact for every file |
| dbcivilization, dbuicontrols, dbuicontrolevents | count 0 | 904 / - / - | 0 | |

Record sizes for traced loaders are the `Read(buffer, size)` constant in the loader; every one
matches the file size exactly.

### 3.3 Field names

`raf_data.py` names a field only where the exe or a value cross-check names it. All other bytes are
typed columns by offset: `i_0xNN` (int32), `f_0xNN` (float32), `s_0xNN` (char[], detected by content),
`x_0xNN` (raw hex: mixed or garbage). Column types are picked from the data at unpack time and
written into the JSON `schema`, so packing never guesses.

**dbobjects (2012 bytes)**. Source column: `copy` = `FUN_00a1dd00` copies it to the unit type object,
whose field the unit out-of-sync dump `FUN_0095cab0` (strings `OUT OF SYNCH DUMP:  Base ...`) names;
`value` = checked against other tables.

| Off | Name | Type | Source | Note |
|---|---|---|---|---|
| 0x000 | name | char[100] | value | object name, unique key used by `string-graphic info.txt` |
| 0x074 | object_id | i32 | copy (Object Type) | equals the record index |
| 0x078 | hit_points | i32 | copy (Base Hit Points) | |
| 0x080 | min_range | f32 | copy (Min Range) | |
| 0x084 | range | f32 | copy (Base Range) | |
| 0x08c | reload_time_s | f32 | copy (Base Reload Time, x1000 to ms) | |
| 0x090 | area_effect | f32 | copy (Base Area Effect) | |
| 0x098 | acceleration | f32 | copy (Base Accel) | |
| 0x0a4 | turret_max_ang_vel | f32 | copy (Base Turret MaxAV) | |
| 0x0b0 | flight_time_s | i32 | copy (Base Flight Time, x1000) | projectiles |
| 0x0c4 | attack | i32 | copy (Base Attack) | |
| 0x0e4 | ammo_type | i32 | copy (Ammo Type) | |
| 0x0f0 | behavior | char[52] | value | name of the `.tai` unit AI script (`Land Patrolling` ...); 52 = gap to the next used field (exact size likely, not checked) |
| 0x134 | work_rate | f32 | copy (Base Work Rate, rounded) | 0x134..0x150 are 8 such rates, likely per task / resource |
| 0x16c | repair_rate | i32 | copy (Base Repair Rate) | |
| 0x1e4 | healing_points | i32 | copy (Base Healing Pts) | |
| 0x1f4 | fire_while_moving | u8 | copy | |
| 0x214 | missile_delay_s | f32 | copy (Missle Delay Time, x1000) | |
| 0x21c | ammunition | i32 | copy (Ammunition) | |
| 0x223 | shoots_high | u8 | copy | |
| 0x320 | carry_amount | f32 | copy (Base Carry Ammt, rounded) | |
| 0x328 | max_objects_carried | i32 | copy (Base Max Obj Carry) | |
| 0x32e | build_on_elevation | u8 | copy | |
| 0x390 | tech_id | i32 | value | equals `dbtechtree.tech_id` of the node that builds it |

`FUN_00a1dd00` copies about 190 record fields in total (`tools/re/objmap.py` prints the full
record -> object offset map, `decomp\dbobjects_map.json`). Speed and line of sight are not among the
named ones (they come from a physics sub-object and a virtual getter); open.

**dbtechtree node (452 bytes + two lists)**

| Off | Name | Note |
|---|---|---|
| 0x00 | name | char[100] |
| 0x68 | tech_id | copied to node+0xf0, used as `%s_%d` key; equals `dbobjects.tech_id` |
| 0x74..0x8c | cost_0x74 ... cost_0x8c | these 7 ints become the node's cost array (node+0x6c..0x84), which the loader scales per resource. Which resource each slot is: open (Spear Infantry L1 Rome has 30 in 0x7c and 70 in 0x84) |
| 0x90 | time_ms | likely build / research time (33000 for Spear Infantry L1, 45000 Town Center) |
| 0xa4 | object_index | by value: index of the `dbobjects` record (998 for Spear Infantry L1 Rome) |
| 0xb0 | string_id | by value: matches `Bad String(n)` in `string-graphic info.txt` |
| list_a | u32 n + i32[n] | stored at node+0x10. dbobjects ids of the buildings that produce the item (one cost entry each); see `docs/crossciv.md` |
| list_b | u32 n + i32[n] | stored at node+0x38 |

Root node layout = child layout; the root is preceded by its child count.

**dbcivspecai (196 bytes)**: 0x6c `behavior_id` = which `dbcpbehavior` record it overrides; 0x70..0xac
eight (multiplier, value) float pairs for Greece, Persia, Rome, Egypt and placeholders, loaded by
`FUN_005f72b0` into civ slots 3, 4, 5, 10 (and 6-9, 11); slots 0-2 are never filled. Combine
(`FUN_0046bd20` float, `FUN_00468130` int): value -1 -> base * multiplier, else the value replaces the
base; one pair scales every field of that id (Easy/Medium/Hard alike). `FUN_004701a0` is called with
slot 0 from the constructor and from the save/network read, but with the real civ from the computer
player's set-civilization virtual method (0x472310) when `DAT_0101e255 == 0`, so overrides are live
for the ~100 parameters set up there. Full write-up, the personalities built on it and the
in-game tests: `docs/ai-personalities.md`. The two stock records (behavior_id -1 and 44) are
neutral (all multipliers 1, all values -1).

### 3.4 dbcpbehavior.dat: the skirmish AI parameters

Record (56 bytes, 14 x 4): `row`, `id`, `a_flag`, `a_limit`, **`v4`** (i32), `b_flag`, `b_limit`,
**`v7`** (i32), `u_32`, `c_flag`, `c_limit`, `c_scale`, **`v12`** (f32), `u_52`.

`FUN_005f74b0`: record `id` is copied to a global array at `0x00d2cd00 + id*0x38`.
`FUN_004701a0` (called when a computer player is set up) copies fields 4, 7 and 12 into the
`EEComputerPlayer` object; the out-of-sync dump `FUN_004642f0` names the object fields. Pattern:
`v4` = Easy (or Minimum), `v7` = Medium (or Maximum), `v12` = Hard (float). The other fields
(`*_flag`, `*_limit`: 0/1 and 999/500/100) are not read by the game code I found; likely editor
metadata (allowed range). Ids 21, 24, 58, 92-94, 117, 124-127 are not mapped to a name (92-94 are
read by `FUN_004773f0`/`FUN_004b83b0`; 21, 24, 117, 124-127 are not read anywhere).

How difficulty is applied (`FUN_00465xxx` getters, object offsets 0x1104 / 0x1114):
- `DifficultyLevel` 0/1/2 picks the Easy/Medium/Hard value directly when `DifficultySlider` is 0.
- If `DifficultySlider` (1..12) is set, the value is interpolated: slider 1-3 scales the Easy value by
  `1 - (3 - s) * 0.2` (0.6x..1.0x), 3-6 blends Easy -> Medium, 6-9 blends Medium -> Hard, 9-12
  extrapolates Hard by `1 + (s - 9) * 0.25` (up to 1.75x). `FUN_00464060` is the increasing form,
  `FUN_004641d0` the decreasing one.

Key knobs, stock values from the user's install (full table: `python tools/raf_data.py cpbehavior
<db>\dbcpbehavior.dat`, all 143 rows with names):

| id | v4 / v7 / v12 | Meaning (names from the exe) |
|---|---|---|
| 1 | 15 / 25 / - | AttackDelayStarting Min / Max |
| 2 | 200 / 15 / - | AttackDelay LevelOfDifficulty Easy / Hard modifier (percent) |
| 6 | 10 / 14 / - | AttackFrequencyStarting Min / Max |
| 7 | 120 / 30 / - | AttackFrequency LevelOfDifficulty Easy / Hard modifier |
| 19 | 0 / 299 / - | AttackFrequencyOverall and AttackDelayOverall Min / Max (same record feeds both) |
| 11 | 40 / 100 / 200 | AttackGroupSize LevelOfDifficulty Easy / Medium / Hard |
| 13 | 90 / 90 / - | AttackForce Min / Max |
| 25-27 | 70, 20, 10 | AttackChoiceProbability Close / Resource / Revenge |
| 28 / 29 | 50 / 70; 120 / 60 | EpochAdvanceFrequency Min / Max; LevelOfDifficulty Easy / Hard |
| 67 | - / - / 1.0 | AICostPercentage (cost multiplier for the AI) |
| 96 | 1 / 1 / 0 | CostDiscount LevelOfDifficulty Easy / Hard |
| 97 | 1200 / 600 / 100 | ExpansionInterval Easy / Medium / Hard |
| 98 | 80 / 100 / 160 | PopLimitAdjust LevelOfDifficulty Easy / Medium / Hard |
| 88 | 45 / 20 / 4 | DefenseTimer Easy / Medium / Hard (minutes -> ms) |
| 114 | 45 / 20 / 4 | TownGuardUpdateTime Easy / Medium / Hard (minutes -> ms) |
| 103/106/104 | 2,2; 2,3; 2,5 | MilitaryBuildingBonus Easy / Medium / Hard (normal, DeathMatch) |
| 107 | 150 / 70 / 40 | EpochCatchUpModifier Easy / Hard / DeathMatch (percent) |
| 122, 123 | 24/16/4, 17/13/8 | DeathMatch AttackFrequency / InitialAttack modifier E/M/H (percent) |
| 142 | 1 / 1 / 1 | ResignationPercent Easy / Medium / Hard |
| 30-42, 95, 108, 109, 134, 135 | v4 target, v12 maximum | Target/Maximum building counts per type (barracks, archery range, stable, dock, ...). The exe labels 37/42 crosswise (Mining vs Food camp); check before tuning |
| 55-66 | v4 | SpendingLevel* and spending timers |
| 49-52, 119, 128-130, 136-141 | v4 / v7 / v12 | AI spending model, 14 categories of 5 floats at `EEComputerPlayer+0x10d8`; categories have no names in the exe |

Units of the time values (seconds, minutes, AI ticks) are not settled except where the exe
multiplies by 60000 (minutes -> ms).

## 4. Other binary formats (structure only, no tool)

### 4.1 `xSTR` streams (`.udf`, `.sdf`, `.edf`)

u32 magic (`USTR`, `SSTR`, `ESTR` read as little-endian dwords `0x52545355` etc.), u32 version,
then fields in a version-dependent order, strings as `UWideString` (u32 length + bytes + 2 NULs).
Loaders (each checks the magic dword): `.edf` `FUN_0067d160`, `.udf` `FUN_00a4cad0` and
`FUN_00a5f410`, `.sdf` `FUN_0071b670`.

### 4.2 `.sdf` (sound definition), versions 0..2 (loader above)

`SSTR`, u32 version, UWideString wav name, f32 (1.0 in samples; likely volume), u32, u32, u32,
bool, bool, then for version >= 2 two f32 (3.0 and 30.0 in samples; likely 3D min / max distance).
Version 1 drops the two floats, version 0 also drops the last bool.

### 4.3 `.sst` (texture)

15-byte header: u8 has_dds (1 = DDS follows), u8 mip_count (10 for 512x512), u32 (1), u32 width,
u32 height, u8 format code; then a complete `DDS ` file when has_dds = 1 (742 files). The other 922
files (has_dds = 0, mostly UI icons) carry raw pixel data after the header; their size fits an
uncompressed 32-bit mip chain (likely). Header layout is confirmed for all 1664 files; the format code
meaning is open.

### 4.4 `.scn` (scenario)

u32 payload length (= file size - 4), UWideString file name, UWideString description, then map data
(not decoded). The `rus` variants differ only in text (likely, from sizes).

## 5. Round-trip result

`python tools/raf_data.py roundtrip "D:\Games\Rise and Fall\Data\db"` unpacks each table to JSON,
serialises the JSON to text, parses it back and packs it. Result on the stock install
(2026-10-15): **51 of 51 `.dat` files byte-identical, 0 failures** (10.2 MB, 17,379 table records plus
2,632 tech-tree nodes). `string-graphic info.txt` is text and is skipped. Edit checks in
`tools/test_raf_data.py`: changing one field changes only that field's bytes, adding a record bumps
the count.

## 6. Open questions

- Which resource each of the 7 tech-tree cost slots is.
- Units of the AI timers that the exe does not convert.
- Names of the 14 AI spending categories.
- Where speed and line of sight per unit come from (physics sub-object, `EEUnitClass` +0x98).
- Does anything read the 19 extra records in `dbrandommap.dat` and `dbterraingraytextures.dat`?
- All of section 3.4 is from the code; an in-game test (change `dbcpbehavior` id 11 v12 from 200 to
  400 and watch Hard AI attack group size) would confirm the table is really what the game uses.
