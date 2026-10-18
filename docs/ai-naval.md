# Computer-player navy and troop ferrying (RAF-9)

Ticket RAF-9: "the AI does not handle ships well and sends either no ships or empty ships".
This note traces the naval code of `RiseAndFall.exe` (Russian 1.15) from the decompile
`decomp/RiseAndFall.c` and, where Ghidra did not produce a function, from a capstone disassembly of the
exe (`tools/re/disasm.py "<game>/RiseAndFall.exe" <start> <end>`). Status: static analysis only, nothing
patched, nothing tested in game.

Conventions:
- `L<n>` is a line in `decomp/RiseAndFall.c`. Addresses are VAs in the 1.15 exe.
- "disasm" means the function is missing from the decompile (Ghidra merged or skipped it) and was read
  from the machine code; the address range is given so it can be re-read.
- **Hypothesis** marks anything inferred from names or shapes rather than read directly.
- Strings in `decomp/exe_strings.txt` are listed at *file offset*; VA = offset + 0x400000
  (example: `856448 OUT OF SYNCH DUMP: EECPASGUMountSea -` is VA 0xc56448).

## 1. Classes and where their code is

Vtables found from RTTI with `tools/re/vtable.py`:

| class | vftable | constructor(s) | notes |
|---|---|---|---|
| `EECPASGLand` | 0xc5225c | FUN_00486700 (L85992), size 0x24c | owns an `EECPTransportWrapper` (vftable 0xc5224c, 0x2c bytes) at +0x238 (L86003-86022) |
| `EECPASGSea` | 0xc523b4 | FUN_004893a0 (L87589), size 0x224 | sea attack sub-group |
| `EECPASGTransport` | 0xc52504 | not found in the decompile | abstract-looking (purecall slots 0xc34836) |
| `EECPASGUMount` | 0xc52644 | FUN_0049b3e0 / FUN_0049b480, size 0xd8 | sub-group unit type 0x11 |
| `EECPASGUMountSea` | 0xc52744 | FUN_0049d340 (L101342) / FUN_0049d450, size 0x11c | sub-group unit type 0x12, i.e. one AI-controlled ship |
| `EECPUGatherNavalUnitsCount` | 0xc535ac | (stack object) | ship counter used by naval maintenance |
| `EEAIFOUnitsToKillForNavalMaintenance` | 0xc535d4 | FUN_004d49d0 (L137190) | frees population for ships |
| `EECPUGatherUnitsOnMount` | 0xc56438 | (stack object, L228022) | counts units on a ship |

Sub-group creation: `FUN_0049d550` (L101435, an `EECPAttackGroup` add-unit method) classifies the unit
with `FUN_004964a0(unit+0x88)` (movement class). Class 0 -> new `EECPASGLand` (L101561); class 1
or 7 -> new `EECPASGSea` (L101564-101566); any other class is dropped (`goto LAB_0049daa5`).
The per-unit wrapper comes from the factory `FUN_0049db50` (L101693): case 0x11 -> `EECPASGUMount`,
case 0x12 -> `EECPASGUMountSea` (0x11c bytes).

### `EECPASGUMountSea` field map

From its out-of-sync dump `FUN_00558620` (vftable +0x2c, disasm 0x558620-0x5586bf; each field is pushed
together with its format string):

| offset | field (exe string) | init in FUN_00558a80 (L227588) |
|---|---|---|
| +0xf4 | `mTechForRamming` | 100000 |
| +0xf8 | `mMeleeCrewCount` | 0 |
| +0xfc | `mArcherCrewCount` | 0 |
| +0x100 | `mGrapplersCount` | 0 |
| +0x104 | `mNextTimeCanDecideGrappling` | 0 |
| +0x108 | `mNextTimeCanDecideRamming` | 0 |
| +0x10c | `mNextTimeWeUnlockFromLand` | 0 |
| +0x110 | `mNextTimeWeBeginFerry` | now + rand(60 000..210 000) ms (L227610-227613) |
| +0x114 | `mNextTimeCanUnloadTroops` | 0 |

Other members used below: +0x64 the ship unit, +0x70 the owning sub-group (its +0x1ac is the
`EEComputerPlayer`), +0x7c current state id, +0x60 current state handler, +0xa0 next crew check,
+0xbd crew buying enabled (init 1), +0xe4/+0xe8 pickup tile, +0xec/+0xf0 drop-off tile.

`MountSea` overrides of the `Mount` vftable (`EECPASGUMount` 0xc52644 vs 0xc52744): +0x1c SetState
0x55a150, +0x20 SelectStateHandler 0x55a0e0, +0x24 0x558710, +0x2c dump, +0x30 checksum 0x5586d0,
+0x3c 0x55aa90, +0x50 IsFerrying 0x49d400, +0x60/+0x7c Read/Write, +0xa8 0x558dd0, +0xbc BuyCrew
0x559510, +0xc0 Update 0x558be0.

## 2. Building ships: naval maintenance

`FUN_004db450` (L141891-142002), called once per update from `FUN_004e0ac0` (L145693, call at 0x4e0b4a).

Gates, in order:
1. `FUN_004e0ac0` only calls it when `EEComputerPlayer+0x1498 != 0` (L145715). That byte is set to 1 in
   the player init (L79558) and is one of the scenario-editor AI check boxes (L610268, L611289), so it is
   on in skirmish.
2. Timer: runs when `this+0x5c < now`; afterwards `this+0x5c = NavalMaintenanceTimer(+0x1220) * 60000 + now`
   (L141998). Stock `NavalMaintenanceTimer` = 4 minutes (docs/ai-personalities.md, Greece table).
3. `DAT_01020d78 > 0x32` (L141932, cmp at 0x4db46a). `DAT_01020d78` is only ever read in the decompile
   and is paired with `DAT_01020d7c` as a ratio (`1 - d7c/(d78+d7c)`, L192816). **Hypothesis:** it is a
   count of water regions/tiles from the map analysis; on maps with less than 51 of them the AI never
   maintains a fleet.

Body:
- Counts its ships with an `EECPUGatherNavalUnitsCount` functor (vtable 0xc535ac, L141939) through
  `FUN_0051f530`; the result is `local_cc + local_d0` (**hypothesis:** existing + queued).
- Target: `FUN_00468f00()` (L68906: `DAT_0101e230 == 1 && DAT_0101e255 == 0`) picks the death-match
  getter `FUN_00466760` (+0x1208/+0x120c/+0x1210), otherwise `FUN_004666f0` (L67491-67518):
  `ShipsToMaintainEasy/Medium/Hard` at +0x1214/+0x1218/+0x121c chosen by `DifficultyLevel` +0x1104, or
  interpolated by `FUN_00464180`/`FUN_004642f0` when `DifficultySlider` +0x1114 is non-zero. The fields
  are filled once in `FUN_004701a0` (L72707-72712). Stock values 1/3/4.
- If `count < target`: `deficit = target - count`. `FUN_004bcc80` (L121643, **hypothesis:** room for more military units;
  `ceil(n * (1 - x - in_use/n))`) is compared with the deficit; when the room is smaller an
  `EEAIFOUnitsToKillForNavalMaintenance` order (L141950-141954) removes `deficit - room` land units.
  Then a unit request is filled (fields 0x21 / 0x17, count `deficit`) and queued through `FUN_0048e410`
  twice and `FUN_0048f9c0` (L141960-141993). **Hypothesis:** 0x21 / 0x17 are the naval unit category and
  the naval-yard building class.

So ships are built only up to ShipsToMaintain (1 on Easy), only every 4 minutes, and only on maps that
pass the `DAT_01020d78` test.

## 3. One ship's life: `EECPASGUMountSea`

Update `FUN_00558be0` (vftable +0xc0, disasm 0x558be0-0x558c87), every second (`+0x9c = now + 1000`):
1. vfunc +0xa8 (`FUN_00558dd0`).
2. If `+0xbd` and `+0xa0 < now`: BuyCrew (vfunc +0xbc).
3. If `+0xb0 < now`: vfunc +0x24 `FUN_00558710` (refreshes the byte +0xbe "has melee crew or flag 6").
4. `FUN_00558b10(now)`: the ferry decision.
5. The current state handler (`call [esi+0x60]`).
6. Ship-specific fallback to state 0x321 when the ship cannot move (`def+0x150` test, 0x558c2b-0x558c76).

### 3.1 Crew: `FUN_00559510` (vftable +0xbc, L227970-228146)

Every 15 s (`+0xa0 = now + 15000`, L228144). Desired crew = `FUN_004bcc40` which always returns 15
(L121623: `return 0xf;`), replaced by 3 with 25 % chance (L228028-228031). It skips when the ship already
holds that many (`ship vfunc +0xc4`) or `ship+0x46c != 0`, and also when more than 2 units are already
on the mount unless flag bit 4 (L228041-228044). Otherwise it queues crew from the ship's own training
list with `FUN_00522060(type, 1, 0, 0, ship id)` (grapplers 2..5 when `mGrapplersCount < 4`, archer or
melee crew by random draw, L228059-228139). This crew is the deck crew, not cargo for an invasion.

### 3.2 Ferry decision: `FUN_00558b10` (L227618-227645)

Runs when `now > mNextTimeWeBeginFerry` and the state is not 0x321/0x322, and only if the ship is not
already ferrying (vfunc +0x50 = `FUN_0049d400`, disasm 0x49d400: true for states 0x1f5/0x1f6/0x1f7).
- `limit = round((1 - DifficultySlider/10) * 2 700 000)` ms (`FUN_004fe380` L164732 returns `+0x1114 / 10`).
  If `EEComputerPlayer+0x149d == 0` and `now <= limit`: retry in 60 s. With the slider unused (0) this is
  **45 minutes** of game time.
  `+0x149d` is written only at L69127 inside `FUN_00469480` (attack-timer setup) and only when
  `+0x148d` (first-update-done, set at L80560 in `FUN_0047d3a0`) is already set, i.e. when the attack
  timer is re-armed after the first update. **Hypothesis:** `+0x149d` = "the first attack has been
  launched"; before that the AI never ferries, on any map.
- Then 75 %: `SetState(0x1f5)`; 25 %: `mNextTimeWeBeginFerry = now + 120 000`.

### 3.3 Ferry states

`SetState` is `FUN_0055a150` (vftable +0x1c, disasm 0x55a150-0x55a3d7). It stores the id in +0x7c and
does per-state entry work; `FUN_0055a0e0` (L228432) maps the id to the handler.

| state | entry work in FUN_0055a150 | handler |
|---|---|---|
| 0x1f5 go to pickup | `+0x10c = 0`; `mNextTimeWeBeginFerry = now + rand(120 000..420 000)` (0x55a23f-0x55a296) | `FUN_005591a0` (L227822-227864) |
| 0x1f6 load at home shore | boarding request (below); `+0x10c = now + rand(60 000..180 000)` (0x55a19c-0x55a23a) | `LAB_00559280` (disasm 0x559280-0x5592f4) |
| 0x1f7 sail and unload | clears +0xe4..+0xf0, `FUN_00ab4030(ship, type, 1, 0, 0)`, `mNextTimeWeBeginFerry = now + rand(120 000..420 000)`, `+0x10c = -1`, `+0x114 = 0` (0x55a2c4-0x55a35a) | `FUN_00559b40` (L228200-228292) |

`FUN_00966ed0` (L814935) is the "ship is moored at land" test: `ship+0x924`, a non-empty attachment list
at +0x370/+0x37c, and the first attached object's type is 0x89 or 0xa0. **Hypothesis:** those are the
landing-plank objects a moored ship deploys.

- **0x1f5** (`FUN_005591a0`): if moored -> 0x1f6. Otherwise, if no pickup tile yet, it asks
  `FUN_0056a230` for a shore tile near the home town (`FUN_00466890(1)`) and moves there
  (`FUN_009e0240`). Either call failing -> state 0.
- **0x1f6 entry** (0x55a1d0-0x55a217): `edi = FUN_00960550(ship, 5)` (L812430; **hypothesis:** the land area of the
  shore the ship is on). The boarding request `FUN_004bbbd0(ship)` on `EEComputerPlayer+0x10ec` is made
  only when `edi == 0` or `edi` equals the home town's area (`FUN_00413ac0` on 0x1020bf0 with the home
  tile). On a foreign shore no troops are asked for, but the 60-180 s timer is still set.
- **Boarding request** `FUN_004bbbd0` (L121088-121160, gate L121112-121115, `FUN_007978d0(1,5)` L121125):
  - Gate (L121112-121115): ship moored **and** (`FUN_004662a0()` **or** `DifficultyLevel +0x1104 != 0`).
    `FUN_004662a0` (L67336) is true only when `EEComputerPlayer+0x1484` (the map id) is 0x697c, 0x6992,
    0x6994 or 0x699a. **Hypothesis:** those four are the island map types. So on Easy, on every other
    map, no unit is ever told to board.
  - Candidates: `FUN_005211a0` -> `FUN_00520780` list, filtered by `FUN_0051d930` (L187210): alive,
    valid position, `unit+0x28c == 0` and no current goal (or goal type 6), not garrisoned. That is
    idle, unassigned units only; units in a defence or attack group are not used.
  - Sorted by distance to the ship (`FUN_004bb9d0`), only those on the home continent
    (`FUN_0042ba40 == continent of home tile`), and at most `rand(1..5) + 1` of them
    (`while (... && param_1 <= iVar7)`, `iVar7 = FUN_007978d0(1,5)`).
  - Each gets a board order (`FUN_009ea6e0` goal, unit class vfunc +0xbc).
- **0x1f6 handler** (`LAB_00559280`):
  - moored: wait while `now <= +0x10c`; when the 60-180 s window ends -> **0x1f7, without checking cargo**
    (0x559290-0x5592a6).
  - not moored (left the shore): cargo count `(ship+0x34c - ship+0x348) / 4`; non-zero -> 0x1f7, zero ->
    state 0 (0x5592ae-0x5592ef).
- **0x1f7** (`FUN_00559b40`): if not moored, find/keep a drop-off tile (`FUN_0056a230` with
  `FUN_009607d0(3)`, `FUN_004c8f20`) and move there; failure -> state 0. When moored: wait 1-2.4 s
  (`+0x114`), then set `+0x10c = now + rand(12 000..18 000)` and unload every own unit in
  `ship+0x348` (`FUN_009de480` + `FUN_004b7670`). Ends (state 0) when `+0x10c` passed or the unload list
  is empty (`FUN_0042c200`).

## 4. Land attack groups that need a ship (`EECPASGLand` + `EECPTransportWrapper`)

A land sub-group owns a transport wrapper at +0x238 (created in `FUN_00486700`, L86004-86026):
+0x04/+0x08 pickup tile, +0x0c/+0x10 and +0x1c/+0x20 drop-off/route tiles, +0x24 the transport's
sub-group unit (an `EECPASGUMountSea`), +0x28 "transport acquired", +0x29 "unloading started".

- Acquire: `FUN_00481460` (L82490, vftable 0xc5225c slot at 0xc523a0) stores the pickup tile and calls
  `FUN_0049ef80` (L102752). That requires `DAT_01020d78 > 0` (some water) and then calls
  `FUN_0049e110` (L101973-102193). On success +0x28 = 1, on failure the sub-group clears +0x130 and
  calls `FUN_00569730` (gives up the crossing).
- `FUN_0049e110` (the only other reader of ShipsToMaintain, L102083-102092):
  - counts transports with an `EECPUGatherTransportUnitsCount` functor (`FUN_00455580` L56748, vftable 0xc4eafc;
    call at L102081) -> `local_110 + local_114`;
  - if `transports < ShipsToMaintain` (1/3/4) and no candidate list was found (`FUN_007c8750`) it looks up
    the civ's transport type with `FUN_004b7ab0(1,0)` -> `FUN_007afc90(0x13)`; if there is one with
    capacity (`def+0x328 > 0`) it queues `clamp(ShipsToMaintain - n, 1, 4)` of them (request fields
    0x21 / 0x17 / 3, L102108-102117) and, if ships are already there (`local_a8 != 0`), makes a new
    `EECPASGSea` (`FUN_004893a0(this,1)`, L102126) with the naval ones (`def+0x3a0 & 2`);
  - if the transport count is already `>= ShipsToMaintain` it returns success without doing anything
    (`else local_1a5 = 1`, L102171).
  - If the civ has no transport type in the current epoch (`FUN_007afc90(0x13) == 0`) or none can be
    trained yet, it returns 0 and the crossing is abandoned.
- `FUN_00482420` (L82956) hands the tiles to the ship: `ship+0xe4/+0xe8 = pickup`,
  `+0xec/+0xf0 = drop-off`, and `mNextTimeWeBeginFerry = 0`. The ship still goes through the ferry
  decision of 3.2, so the 45-minute / first-attack gate and the 25 % "wait 2 minutes" roll apply here too.
- Load: `FUN_00484d50` (L84924) calls `FUN_004844f0` (L84527-84624). It returns "loaded" when the
  ship is full (`def+0x328 - ship+0x354 < 1`) or when every member has `unit+0x5d0 != 0` (inside *any*
  container, a tower counts as well). Otherwise it orders the members still outside to board
  (`FUN_009de480(list, ship, 1)`). The ship's own 0x1f6 timer keeps running meanwhile.
- Unload: `FUN_00484bb0` (L84839-84922): if the ship is moored and not in 0x1f7 and not ferrying, it
  re-hands the tiles and forces `SetState(0x1f7)`; in 0x1f7 with `+0x114` set it unloads the members
  that are in a container.

Who writes wrapper +0x24 (which ship serves the group) was not found in the decompile; it is likely in the
`EECPASGTransport` code around 0x48bxxx that Ghidra did not split into functions (open question).

## 5. Why "no ships" and "empty ships"

Symptom (ticket): the AI either sends no ships or sends empty ships.

### 5.1 Empty ships (confidence: high for the mechanism, medium that it is the main cause)

Ship-initiated ferry (section 3.3), all branches read directly:
1. **The 0x1f6 handler sails when the timer ends, cargo or not.** `LAB_00559280`, 0x559290-0x5592a6:
   moored and `now > mNextTimeWeUnlockFromLand` -> `SetState(0x1f7)`. The cargo test exists in the same
   function (0x5592ae-0x5592ef) but only on the "not moored" branch.
2. **Often nobody was asked to board:**
   - Easy difficulty on any map whose id is not one of the four in `FUN_004662a0` (0x4bbc00-0x4bbc0c):
     `FUN_004bbbd0` returns before collecting units.
   - Ship moored on a shore whose area is not the home area (0x55a1dd-0x55a202): the request is skipped.
   - Only idle, unassigned units on the home continent qualify (`FUN_0051d930`, L187210-187232), and at
     most `rand(1..5)+1` are picked. An AI whose army sits in defence or attack groups has none.
3. Result: 60-180 s later the ship sails to the drop-off (0x1f7) with 0 to 6 units, finds nothing to
   unload, and returns to state 0 after `+0x10c` expires; 2-7 minutes later (`mNextTimeWeBeginFerry`
   reset on 0x1f5/0x1f7 entry) it repeats. That is the "empty ship" loop.

Land-group path: the ship's 60-180 s window does not wait for the group either; `FUN_004844f0` only
stops the group from sailing its own way, it cannot hold the ship in 0x1f6. **Hypothesis:** a slow group
therefore also produces an empty or half-empty ship.

Alternative reading of "empty": warships without deck crew. Crew is bought by `FUN_00559510` every 15 s
only while the ship is in a sub-group and resources allow; nothing found forces a crew before sailing.
Not analysed further.

### 5.2 No ships (confidence: medium; several independent gates)

1. **Ferry gate** (`FUN_00558b10`, 0x558b4a-0x558b94): until `EEComputerPlayer+0x149d` is set
   (hypothesis: first attack launched) or `(1 - slider/10) * 45 min` have passed, every ship postpones
   its ferry by 60 s. With the difficulty slider unused (0) that is 45 minutes. Even land groups that
   requested a transport (`FUN_00482420` zeroes `mNextTimeWeBeginFerry`) wait for it.
2. **25 % roll** (0x558b97-0x558bcb): a quarter of the decisions wait another 2 minutes.
3. **Fleet size = ShipsToMaintain** (1/3/4) for both naval maintenance (section 2) and transports
   (section 4). On Easy one ship total. Both counts share the same cap, so warships may already fill it.
   **Hypothesis**, depends on what the two gather functors count.
4. **`DAT_01020d78 > 50`** for naval maintenance (0x4db469) and `> 0` for transports (`FUN_0049ef80`).
   **Hypothesis:** a water measure from map analysis; small lakes or narrow straits may fail it.
5. **No transport type** in the civ/epoch (`FUN_007afc90(0x13) == 0`) -> `FUN_0049e110` fails and the
   land group abandons the crossing (`FUN_00481460` -> `FUN_00569730`).
6. Movement classes other than 0 (land) and 1/7 (sea) are dropped from attack groups
   (`FUN_0049d550`, L101564); not naval-specific but explains missing amphibious units if any use
   another class.

## 6. Patch candidates (ranked)

All addresses are 1.15 VAs; bytes were read from the stock exe at `D:/Games/Rise and Fall/RiseAndFall.exe`.

**Implemented:** P1, P2 and P3 ship as the exe feature `naval-ai` (default on): `raf_patch.NAVAL_AI`, applied
by `byte_patches` next to `target-priority`, with `NAVAL_AI_MARK` mixed into the gameplay fingerprint while
installed (all players need the same exe). P3 uses 900 000.0 = `00 ba 5b 49`; `00 b8 5b 49` is 899 968.0.
Offline test: `python tools/test_naval_ai.py` (stock bytes, jump targets, floats, apply / re-apply / revert next to
the other exe patches, fingerprint). The emulation tests listed per patch below were not written; the static
checks and the byte-level apply / revert are what is covered. Nothing is tested in game yet.

### P1. Do not sail with an empty hold (0x55929c, 2 bytes) - recommended first

- Original at 0x55929c: `8b 16 50 68 f7 01 00 00` (`mov edx,[esi]; push eax; push 0x1f7 ...`), the
  "timer expired, sail" branch of `LAB_00559280`.
- Change: `8b 16` -> `eb 10` (`jmp 0x5592ae`). The timer-expired case then runs the existing cargo test
  at 0x5592ae: cargo > 0 -> `SetState(0x1f7)`, cargo == 0 -> `SetState(0)`. Stack and registers match
  (same function, nothing pushed between 0x559290 and 0x55929c; `[esp+0xc]` is still `now`).
- Effect: empty ships abort the ferry and retry after `mNextTimeWeBeginFerry` (2-7 min, set on 0x1f5
  entry); partially loaded ships still sail. Land groups waiting on that ship re-request it through
  `FUN_004844f0` -> `FUN_00482420`.
- Risk: low. Ships that fail to get troops every time now stay home instead of sailing pointlessly (fewer
  naval "visits", which is what an empty ship achieves anyway). Bytes after 0x55929e become dead code.
- Offline test (pattern of `tools/test_target_priority.py`): (1) static: stock bytes at 0x55929c, the
  `jmp` target 0x5592ae is an instruction start, no other code jumps into 0x55929e-0x5592ad;
  (2) unicorn emulation of 0x559280 with a fake `this` (vtable whose +0x1c slot is a stub recording its
  arguments), ship object with +0x924/+0x370/+0x37c set so the stub for `FUN_00966ed0` returns 1 (or hook
  0x966ed0 to return 1), `+0x10c < now`, and ship+0x348/+0x34c describing 0 and 3 cargo entries: expect
  `SetState(0)` and `SetState(0x1f7)` respectively; stock bytes give 0x1f7 in both;
  (3) apply / re-apply / revert on a temp exe copy.

### P2. Always ask for troops when the ship is moored at home (0x4bbc00, 2 bytes)

- Original at 0x4bbc00: `74 10` (`je 0x4bbc12`, taken when `FUN_004662a0()` is true; otherwise the
  `DifficultyLevel >= 1` test at 0x4bbc05 decides).
- Change: `eb 10` (`jmp 0x4bbc12`). Easy AIs on non-island maps then also send idle units to the ship.
- Risk: low to medium. This is a deliberate designer choice (Easy and non-island maps skip it); the
  change makes the Easy AI stronger at sea. Units it takes are idle and unassigned only.
- Optional companion: the boarder count `FUN_007978d0(1,5)` (call inside `FUN_004bbbd0`, L121125) could
  be raised to fill more of the hold; exact push bytes not yet located.
- Offline test: static bytes plus emulation of 0x4bbbd0..0x4bbc12 with `[edi+0x50]+0x1104 = 0` and
  `FUN_004662a0` hooked to return 0: stock exits to 0x4bbddf, patched reaches 0x4bbc12.

### P3. Shorten the early ferry gate (data 0xc56428, 4 bytes)

- Original float at 0xc56428: `80 cb 24 4a` = 2 700 000.0 (45 min), referenced only by
  `fmul dword ptr [0xc56428]` at 0x558b5f (`refs` scan: single reference).
- Change: e.g. 900 000.0 (`00 ba 5b 49`, 15 min) or 0.0 (`00 00 00 00`, gate off). Do **not** touch the
  0.75 at 0xc56424, it is shared with the crew code at 0x559558.
- Risk: medium. The gate stops early island rushes; removing it makes the AI ferry before its first
  attack. Lockstep: all players in a multiplayer game need the same exe.
- Offline test: static (single reference, value), emulation of 0x558b10 with slider 0, `+0x149d = 0`,
  now = 20 min: stock writes `+0x110 = now + 60000`, patched (15 min) calls `SetState(0x1f5)` or
  `+0x110 = now + 120000` depending on the stubbed random value.

Not recommended without in-game data: changing the `DAT_01020d78 > 0x32` test at 0x4db469
(`83 3d 78 0d 02 01 32`), because the meaning of `DAT_01020d78` is unproven, and raising ShipsToMaintain,
which is data (`dbcpbehavior.dat` id 5/44) and belongs to `tools/build_ai_db.py`, not to an exe patch.

## 7. In-game checks to confirm

1. Skirmish on an island map, AI Medium, watch a transport: after it moors at home, count units boarding
   in the 1-3 minutes before it leaves. Stock expectation: 0-6 units, often 0; with P1 an empty ship
   stays.
2. Same on a continental map with a lake, AI Easy: stock expectation: no unit boards at all (P2 gate).
3. Note the game time of the first ferry: stock expectation: not before the AI's first attack wave or
   45 minutes.

## 8. Open questions

- What `DAT_01020d78` / `DAT_01020d7c` measure (no direct writer found by byte scan; written through a
  pointer or in code Ghidra skipped).
- Meaning of `EEComputerPlayer+0x149d` (set in `FUN_00469480` L69127 only after the first update) and of
  the map ids 0x697c/0x6992/0x6994/0x699a in `FUN_004662a0` (written from the lobby at L467959/L468233).
- Who fills `EECPTransportWrapper+0x24` (which ship serves a land group) and how `EECPASGSea` sub-groups
  are dispatched against targets; the `EECPASGTransport` vtable (0xc52504) has no constructor in the
  decompile.
- What `EECPUGatherNavalUnitsCount` vs `EECPUGatherTransportUnitsCount` count (whether warships use up
  the transport cap).
- Request fields 0x21 / 0x17 / 3 in the unit requests (`FUN_0048e410`).
