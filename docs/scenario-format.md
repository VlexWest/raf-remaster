# Scenario (.scn) format and the trigger system

Scope: `Data\scenarios\*.scn` (multiplayer maps), `Data\tutorials\*.scn`, and the campaign
scenarios inside `Data\campaigns\*.ssa`, of the 2009 build of `RiseAndFall.exe`. Tool:
`tools/raf_scn.py`. Generator that writes our own maps with it: `tools/build_survival.py`
(see `docs/survival.md`).

Unless noted, everything here is read from the decompile (function address given) or proven by a
byte-exact round trip of all 76 shipped scenarios; "likely" marks what fits the data but was not
checked in game. Apart from the unit-set test in section 3.5, nothing in this file was verified in
the running game.

Proof of the layout: `python tools/raf_scn.py stock "<game>"` parses every shipped scenario
(25 multiplayer maps x 2 identical language copies, `scendefault.scn`, 3 tutorials, 22 campaign
scenarios read from the two `.ssa` archives): header, all chunks, the complete trigger stream including its tail, and
writes them back. Result 2026-10-15: **76 of 76 byte-identical**.

## 1. Where triggers live (answer to "which vehicle")

* Triggers are **inside the .scn**, in chunk type 6 (the `EEScenarioManager` stream). There is
  no separate trigger text file. `Data\map scripts\*.rmv` only lists the multiplayer scenario
  maps for the lobby (`UseMapGenerator "Default"`, string ids); it holds no logic.
* Multiplayer maps ship with working triggers (from the files): every 2/4/5/6/8 player
  map has at least a "no build zone" trigger, `(4) contested sands` re-creates four wine jugs
  60 s after they are taken, `(2) gamersday` / `(2) corridor of blood` send chat text to P1/P2
  and research "Level 2" for both, `(6) gaugamela` caps the computer players' gold in a loop and
  gives victory to whoever hoards 5000 gold and wood. Trigger evaluation is part of the
  lockstep simulation (`OUT OF SYNCH DUMP: ... Test Triggers %d`, trigger timing uses the
  scenario clock in the manager, `FUN_008d0d80`).
* The editor can export a debug text dump of all triggers (`ScenarioTriggers.txt`,
  `FUN_008667d0`) and save/load "triggers only" (`EEUIESaveScenarioTriggersOnly`), but the game
  never reads a text format.

## 2. File layout

```
u32   payload length (= file size - 4)
header                       FUN_007246f0
chunk * 12                   FSChunk (LowLevelEngine): u32 ver_major (4), u32 ver_minor (0),
                             u32 type, u32 size, data[size]
u32   map id                 same value as header.map_id
```

Campaign scenarios inside `.ssa` are additionally compressed as a whole (one `ZL01` blob).

`.ssa` archive: `rass`, u32 1, u32 0, u32 header_end, then entries
`{u32 len, name (UWideString bytes), u32 start, u32 end, u32 size}`; the archive also carries
the campaign's own sounds (`raf_scn.iter_ssa`).

Chunk data is an `FSMemoryFile`: raw, or `ZL01` + u32 raw size + u32 0 + zlib stream
(`UDataCompression::Compress/Decompress`, LowLevelEngine 0x100a81b0 / 0x100a8250). The loader
accepts both (`FSMemoryFile::Decompress` falls back to raw).

Chunk order in every shipped map: 1, 2, 4, 3, 6, 12, 13, 5, 7, 8, 11, 14 (also listed in the
header). Types the loader insists on (`FUN_00728f40`): 1-7, 11, 14. Known contents: 4 = terrain
(starts with u32 width, u32 height in tiles), 6 = scenario manager (triggers), 7 = placed units,
5 = large terrain/vegetation data; the rest are small (not decoded, copied unchanged).

### Header (FUN_00723f70 + FUN_007245c0 + game setup FUN_006e0360)

```
uws name ("(4) Plains rus.scn"), uws description, u32 ver_major 4, u32 ver_minor 0,
uws (player-name text), uws date, u32,
16 x player slot  {u32 kind, uws name, f32, u32, u32 index, u32 team, u32, bool x3,
                   u32 civ, u32, u32, bool}                         FUN_006dedf0
game setup        {u32, u32 game_type (3 in MP maps), ... , uws map_name ("(4) Plains.scn"),
                   uws (encrypted), bool x3, uws, bool}             FUN_006e0360
u32, u32 n + n x u32 chunk types, 8 x uws + list (uws, uws, bool)  FUN_008c7bb0
u32 map id, u32 (0xffffffff)
```

`uws` = UWideString: u32 byte length + bytes (cp1251 text + two NUL). Field names in
`raf_scn.PLAYER_FIELDS` / `SETUP_FIELDS`. The stored player slots are the editor's test setup;
in a multiplayer game the lobby supplies the players (likely, from the start-game code
`FUN_006e4c40`, which copies lobby players over them).

## 3. The scenario manager stream (chunk 6, FUN_008a1c00)

```
u32 n, n x Trigger                                        (EESMTrigger, load 0x8d2760)
u32 n, n x {u32 type, Condition}                          factory FUN_008a9e30
u32 n, n x {u32 category, u32 type, Effect}               factory FUN_008b1550
u32 n, n x Object                                         (EESMObject, load 0x8cb780)
u32 n, n x {u32 type, Area}                               factory FUN_008a7570
u32 n, n x CameraPath                                     (load 0x8a7bd0)
u32 n, n x u32 ;  u32 n, n x {u32, u32, bool}
u32 n, n x {u32 category, u32 type, Effect}               (pending effects)
tail: 5 x u32 last used ids (trigger, condition, effect, object, area), f32 scenario time,
      f32, 8 uws + list, ..., 17 per-player string lists, optional on-screen counter,
      animation manager, 17 per-player lists, ...                     (raf_scn.parse_tail)
```

Every component ends with its base class: `u32 id, uws name, uws description` (conditions and
effects); subclass fields come **before** the base (that is the order of the Load functions).

### 3.1 References and index rules

`EEScenarioManager::Init` (0x89e360) creates defaults that are **not saved**:
3 conditions (AlwaysTrue "<NONE>", PlayingCameraScript, HaveDialogMessage), 1 effect
(DoNothing), 1 object, 2 areas. So, in the file:

| reference to | value |
|---|---|
| condition | 3 + index in the in-memory list (0 = AlwaysTrue) |
| effect | 1 + index (0 = nothing) |
| object | 1 + index |
| area | 2 + index |
| trigger | index (0-based) |

The loader moves conditions: every non-`ObjectExists` condition is inserted before the first
`ObjectExists` one, and `ObjectExists` conditions with object 0 are dropped (FUN_008a1c00,
dynamic_cast + vfunc 0x78). A writer must therefore store non-ObjectExists conditions first.
Checked on the arena scenario: with these rules every trigger reads sensibly ("PowerUp 1: if
NOT <P0 Wine Jug 1 Exists>").

### 3.2 Trigger record and runtime (load 0x8d2760, update FUN_008d0d80)

```
uws name, uws desc, bool on, bool looping, bool, u32, bool, u32 true_for (seconds),
u32, f32 next_check_ms, f32 check_interval_ms (500), u32 id,
u32 n, n x {bool not, u32 op, u32 condition}     op: 1 AND next, 2 OR next, 0 last
u32 n, n x {u32 delay, u32 op, u32 effect}       then-list; delay in 1/100 s
u32 n, n x {u32 delay, u32 op, u32 effect}       else-list (stock: one placeholder 0,0,0)
```

Runtime: every `check_interval` ms an "on" trigger evaluates its condition groups
(AND within a group, groups split by op 2). If true and `true_for` > 0, it remembers the time
and fires only after the conditions stayed true `true_for` seconds (reset when false). On fire
a non-looping trigger switches itself off; each then-entry is scheduled at
`now + delay * 10 ms` (`FUN_008a2950`). Effects are grouped by op 2 as well; the group that runs
is the one matching the condition group that was true. A trigger is turned on/off by the
Trigger effect.

### 3.3 Conditions (factory FUN_008a9e30)

| type | class | fields (file order, before the base) |
|---|---|---|
| 0 | AlwaysTrue | - |
| 1 | ObjectExists | object (true when the object's selection has >= min units) |
| 2 | PlayerHasResource | player, resource, u, compare, amount, u, bool |
| 3 | PlayerHasTechnology | player, tech |
| 4 | PlayerDefeated | player |
| 5 | TriggerHasAttribute | trigger, bool, bool |
| 6 | PlayerHasDiplomacy | other, stance, player |
| 7 | GameHasAttribute | bool difficulty?, bool time?, bool hour?, difficulty, time_max, time_min, hour |
| 8 | GameCounter | counter, value, bool |
| 9 | ChatMessageEquals | player, text |
| 10 | CanPath / 11 CanRam | object, area/target |
| 12 | PlayingCameraScript / 13 HaveDialogMessage | - |

GameHasAttribute (eval 0x8a9620): with the time flag it is true while
`time_min < scenario seconds <= time_max` (scenario time = manager+0x6c0 / 1000, saved in the
tail, 0 at start). Stock "Game Time = 60+" uses min 60, max 999999. The difficulty flag
compares the global difficulty, the hour flag the time of day.

### 3.4 Effects (factory FUN_008b1550; category, type)

Category 0: DoNothing. Category 1 (objects; base adds `u32 object`): 0 Create, 1/2
Freeze/Unfreeze, 3 KillUnit, 4 RemoveUnit, 5 TaskToObject (target, task, bool),
6 TaskToArea (area, task, bool), 7 SetStance (stance), 8 ChangeUnitAttribute,
9 ChangeOwner, 10 ChangeUnitClassName, 11 FaceObject, 12 ChangeUnitClassAttribute
(attr, op, value, bool percent, u32, i32), 13 ChangeUnitName, 14 ReplaceObjects, 15
ChangeAnimation, 16 SetMedal, 17 MountObject, 18/19 Make/BreakFormation, 20
CreateUnitSpawner (frequency, max units, unit schema, mutator effect ids, ...), 21
DeleteUnitSpawner, 22 ResearchTechnology, 23/24 physics update. Category 2 (players; base adds
`u32 player`): 0 Victory, 1 ScriptCamera, 2 Defeat, 3 ChangeDiplomaticStance (other, stance,
mutual), 4 ChangeResourceLevel (resource, op, value text), 5 ModifyTechnology, 6 NoBuildZone,
7/8 camera fades, 9 ChangeVisibility, 10 MiniMapFlare, 11 Objective, 12 RenameCiv, 15
ActivateHeroBotAI. Category 3: Trigger (0 = on / 1 = off, trigger index; the type id is
stored as 0xffffffff). Category 4 (media): 0 PlaySound, 1 ChangeScenarioText,
2 SendDialogueMessage, 3 SendChatMessage (text, players, seconds, bool), 4 QuestionBox,
5 PlayMusic, 6 StopMusic, 7/8 music levels. Category 5 (game): 0 SetTime, 1 SetDayNightCycle,
2 StartCalamity, 3 GraphicEffect, 4/5 cinematic mode, 6 Counter (on-screen countdown),
7 Environment (`.env` name, seconds, bool, bool), 8 LoadNextScenario, 9 SetSlowDeath,
10 SetGameSpeed, 11 hero swimming. Category 6 (computer player; base adds `u32 player`):
0 ModifyMilitaryTarget, 1 CreateMilitaryGroup, 2 BuildObject, 3 MaintainObject,
4 AIToggleSetting (setting, on), 5 SetAttribute, 6 SetFavoriteUnits.
Field lists for every class: `raf_scn.EFFECTS`.

### 3.5 Objects (EESMObject, load 0x8cb780): the selection/creation filter

An object is a unit filter used by conditions and effects (and as the template for Create).

| field (memory offset) | meaning (from the code unless marked) |
|---|---|
| unit list + 0xdc | fixed list of placed units; when 0xdc is 0 the filter below is used |
| 0x7c player | player enum (below) |
| 0x80 class | 0 any; 1-14 (unit class+1); 15-95 family; 96-136 (third category); unit sets above that. **In-game test: class = 134 + dbunitset table index** (note below) |
| 0x84 type | dbobjects record index |
| 0x38 / 0x50 | min / max count as decimal text (may hold expressions, FUN_008afc10); ObjectExists is true when >= min match; Create makes a random number in [min, max] |
| 0xdd | 1 = dynamic (otherwise the selection is frozen after the first match) |
| 0xb4, 0x88 | area mode (0 none, 1 inside, 2 outside), area ref |
| 0xb8, 0x90, 0x8c | near mode (0 none, 1 near, 2 not near), object ref, distance mode (0 = line of sight of that object's units, 1 = attack range, 2 = footprint) |
| 0xbc, 0x98, 0x9c, 0xa0, 0xde | attribute filter on/off, attribute, min, max, percent |
| 0xc4, 0xa8 | state filter on/off, state (1000 default, 5000 idle, 6002 rotting) |
| 0xdf | negate the type filter |
| 0xb0 | object id |

Unit-set class values: every campaign file stores `134 + table index` (auto-names like
`<Set: A-All Swordsman (Family)*>` match that), and the in-game test of 2026-10-15 agrees: with
134 the "human town centres" selection works, with 137 it is empty (game lost after 30 s).
My first reading of `FUN_008ce8f0` (`class - 0x89` into the array at 0xcef2e0) gave 137; the
array evidently holds three entries fewer than the table, which the decompile did not show.
**Confirmed in game: 134.** Creation placement: all 211 Create effects in the shipped scenarios use
"inside area" (0xb4 = 1); none uses "near object" (0xb8), and our near-object waves did not
appear in the in-game test.

### 3.6 Enums

Player (FUN_0089c6b0 / FUN_0089c9a0, used by every player effect, by objects and by
Create): 0 Gaia, 1 one random human, 2 one random computer, 3 all humans, 4 all computers,
5 random player, 6 all players, 7.. = player (value - 6), so P1 = 7, P2 = 8, P3 = 9.

| field | values (from shipped scenarios, names from their effect names) |
|---|---|
| TaskToObject/TaskToArea task | 0 move, 1 patrol, 2 attack-move, 7 escort, 8 attack ground, 9 panic, 10 run, 11 land, 125 ram, 126 grapple, 129 fire at, 130 trample |
| SetStance stance | 0 explore, 1 idle, 2/3 gate lock/unlock, 4 town patrol, 5 scout, 6 stand ground, 7 guard, 9 cautious, 10 aggressive, 11/12 pack/unpack, 13 vulnerable, 14 invulnerable |
| ChangeUnitClassAttribute attr | 39 reload, 40 attack, 41 work rate, 44 mana recharge, 46 hit points, 49 range, 50 line of sight, 51 speed, 52 max power; op 0 add / 1 subtract; bool = percent |
| ChangeResourceLevel resource | 2 recruitment points, 3 gold, 4 wood, 6 glory, 8 pop cap, 11-20 player variables Var0-Var9; op 0 set / 1 add / 2 subtract |
| ChangeDiplomaticStance stance | 0 allied, 1 enemy; bool mutual (FUN_008c36c0 resolves both sides as player groups) |
| AIToggleSetting setting | 0 computer player on/off (calls FUN_0046ae30, which Victory/Defeat also call to stop a defeated AI), 1-7 single AI managers (build = 4) |
| Counter (5,6) | title, seconds, count down, title only, mode (0 show, 1 pause, 2 resume, else remove), progress text, progress bar |

### 3.7 Resource compare & subtract (exe fixes)

PlayerHasResource is evaluated by `FUN_008aabc0` (vtable 0xc6eb10): value = `FUN_008aa9b0(player,
resource [cond+0x44])`, compared with the amount (or another player's value when the bool is set) by
`FUN_008a9c90(value, op [cond+0x50], amount)`, op 0 `<`, 1 `<=`, 2 `==`, 3 `>=`, 4 `>`. The helper
uses unsigned setb/setbe/setae/seta and has no other caller than the three calls in the evaluator.

ChangeResourceLevel ends in `FUN_00bfa1e0(player, resource, op, amount)`: op 2 negates the amount
and writes old + (-amount) through `FUN_007a7920` with no floor. Together this broke stock
Gaugamela: a trigger takes 250 gold from all computers when a random computer has >= 900, the
balance goes negative, the negative balance passes ">= 900 / 1000 / 5000" as a huge unsigned number,
so computers got 600 free gold every few seconds & could win the 5000 gold + wood hoard in debt.

Two patches in `tools/raf_patch.py`, both on by default & in the fingerprint, tested by
`tools/test_trigger_fixes.py` (static checks, unicorn emulation of the caves & of the whole
`FUN_00bfa1e0`, apply / revert):

| feature | change |
|---|---|
| `trigger-signed-compare` | the three helper calls (0x8aaca5, 0x8aacc4, 0x8aacf3) go to a cave at 0xCE3F88..0xCE3FDA: resource ids 0..6 (random, total, recruitment points, gold, wood, glory) compare signed (setl/setle/sete/setge/setg), all other ids jump to the stock helper |
| `trigger-resource-floor` | the `mov reg,[player+x]; add reg,edi` of resources 2, 3, 4, 6 (0xbfa2c2, 0xbfa2fc, 0xbfa334, 0xbfa36c) call caves at 0xCE3820..0xCE3867 that write 0 when op is 2 & the result is negative |

Resources above 6 stay unsigned on purpose: the campaign medal score Var4 (resource 15) is a
difference that can go negative, & the campaign tests it with a condition named "P1 Var4 < 0" that
is written as "Var4 > 100000", which only works unsigned. Variables, pop cap, set & add are not
clamped. Our co-op & survival maps only compare non-negative values (wave counter, flags, P1 gold >=
300 / 800 before a tithe), so they behave as before.

## 4. Writing scenarios

`raf_scn.ScnFile` (chunks, header, trailer) + `Manager.parse/serialize` round-trip losslessly.
`build_survival.Builder` appends components to a stock map while keeping the index rules,
reorders conditions, remaps the map's own trigger references, bumps the id counters in the
tail and gives the map its own name and map id (header and trailer).

## 5. Open questions

* In-game check of everything above (only the unit-set value has been checked in game).
* Meaning of the remaining header/tail fields and chunks 1-3, 5, 7, 8, 11-14.
* Whether the MP lobby offers a map from `Data\map scripts\` that is not in the shipped list
  and what it shows as its name when the `.rmv` has no `StringTableID`.
