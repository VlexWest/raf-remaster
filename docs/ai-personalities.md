# Civilization AI personalities

Data only. `python tools/build_ai_db.py <game> <overlay> --personalities` writes
`Data/db/dbcivspecai.dat` (plus the Hard `dbcpbehavior.dat` from the same script) into the overlay.
Default is off. Status: built & unit-tested offline, **not yet tested in game** (see section 5).

## 1. How the exe reads `dbcivspecai.dat` (decompile, `decomp/RiseAndFall.c`)

An earlier note in the format study ("does nothing with stock data, main setup passes civ slot 0") is half right.
Two of three call sites pass slot 0; the third passes the real civ.

**Load: `FUN_005f7380` (0x5f7380), table id 0x34.** Records are 196 bytes. For each record with
`0 < behavior_id < 0x95` (field at +0x6c, the loop test is `0 < id && id < 0x95`) it allocates a
0x68-byte object with `FUN_005f72b0` (0x5f72b0) and stores it in `DAT_00d2caa8[behavior_id]`
(a later record with the same id replaces an earlier one; ids -1 and >= 0x95 are dropped).
The object holds `mult[12]` at +0x00 (default 1.0) and `value[12]` at +0x30 (default -1.0), indexed by
civ slot. `FUN_005f72b0` fills them from the record pairs (mult at record offset, value at +4):

| slot | civ (dbphoenixcivtable row) | record pair |
|---|---|---|
| 0, 1, 2 | Any Civilization, Placeholder 6, 7 | never filled, always neutral |
| 3 | Greece | 0x70 / 0x74 |
| 4 | Persia | 0x78 / 0x7c |
| 5 | Rome | 0x80 / 0x84 |
| 6, 7, 8 | Placeholder 1, 2, 3 | 0x90, 0x98, 0xa0 |
| 9 | Placeholder 4 | 0x80 / 0x84 (the exe reads **Rome's** pair again; harmless, nobody picks it) |
| 10 | Egypt | 0x88 / 0x8c |
| 11 | Placeholder 5 | 0xa8 / 0xac |

The playable civs are only the four named ones; their slot is the row index of `dbphoenixcivtable`
(`FUN_005ff420`, array `DAT_00d2eeac`, 12 rows).

**Combine: the getters.** For one stored dbcpbehavior value the exe asks the table for
`(behavior id, civ slot)`:
- float values: `FUN_0046bd20` (0x46bd20): neutral pair -> base; `value == -1.0` -> `base * mult`;
  otherwise `value` (absolute, replaces the base).
- integer values: `FUN_00468130` (0x468130): the same, rounded: `ROUND(base * mult)` or `ROUND(value)`.
- The units are those of the stored value after the exe's own conversion: percentages are divided by
  100 *before* the override (so a `value` for a percent field is a fraction), minute fields are
  overridden *before* the `* 60000` (so `value` is in minutes).
- So it is **multiplier (default) or override (if value != -1)**, never additive. One pair applies to
  **every** field of that id that the exe reads (Easy, Medium and Hard at once, Min and Max at once).
  An absolute `value` therefore flattens an Easy/Medium/Hard triplet; we only use it where it is harmless.

**Which values go through it.** `FUN_004701a0` (0x4701a0, "set up the computer player") copies about
140 dbcpbehavior fields into the `EEComputerPlayer` object (offsets +0x10d8 sub-object, +0x1124 ..
+0x1414) and routes each through the table with the civ slot it was given. The per-difficulty
getters (`FUN_0046e5b0`, `FUN_0046f310`, `FUN_0046d3b0` ...) do the same. Difficulty is *not* part of
the override: all three stored values are scaled alike and the existing difficulty logic (formats.md
3.4) then picks Easy/Medium/Hard or interpolates the slider. So every difficulty is affected the same way.

**Who passes which slot.** Only three call sites reach `FUN_004701a0` (found by scanning the exe for
`call 0x4701a0`):
1. 0x47bb62 inside `FUN_0047ba30` (the constructor path): `push 0`, slot 0 (neutral).
2. 0x47abf6 in `FUN_00478f50` (end of the save-game/network `Read`, only when the player is not yet initialised): `push 0`.
3. **0x47233b in the virtual method at 0x472310**, vtable `0xc52054` + 0xdc (`PTR_FUN_00c52130`), which is
   the computer player's "set civilization" override: it calls the base `FUN_007b4120(civ, ...)` and then,
   if `DAT_0101e255 == 0`, `FUN_004701a0(civ)`. `civ` is the first argument. Callers seen: the lobby
   (decomp line 467772, `(**(code **)(*piVar19 + 0xdc))(civ,1,0,0)`) and the default-slot creation
   (line 484798, civ 3 = Greece). So **in a normal new game the AI is set up with slot 0 first and
   then re-set up with its real civ**, and the overrides are live for every parameter listed below.

One more consumer, `FUN_0047d3a0` (0x47d3a0, first update): for id 17 `CitizenTargetCountMaximum`. It halves
the value when `DAT_0101db78 < 201` *only if* the civ-adjusted value equals the stored one, so any real
override on id 17 *suppresses* that halving instead of scaling the value. Id 17 is therefore not used.

**Skirmish?** The path goes through the player setup that skirmish uses (lobby civ selection, default slot,
`EEComputerPlayer`). I did not find any skirmish-only gate. The one condition is `DAT_0101e255 == 0`
(unresolved global; written outside the decompiled code; it is also tested together with `DAT_0101e230`,
the game-variant index, in several "is this a normal game" checks). If it is non-zero for skirmish the
overrides stay neutral: this is the first thing the in-game test decides. Multiplayer: the AI runs in the
lockstep simulation, so all players need identical `dbcivspecai.dat` and `dbcpbehavior.dat`.

## 2. Design

Options considered:
- A. Edit `dbcpbehavior.dat` per civ: impossible, the rows have no civ dimension.
- B. Patch the exe to pass the civ slot at the two slot-0 sites: not needed, the virtual-method path already does it, and exe patches belong to the patcher.
- C. **Fill `dbcivspecai.dat` with multipliers** (chosen). Reuses a mechanism the exe already runs, no exe change, rebuildable from the user's install, stock records untouched.

Rules the generator enforces (`tools/build_ai_db.py`, checked in `tools/test_ai_personalities.py`):
- No resource or cost cheats. `AICostPercentage`, `CostDiscount*`, `ResourceBonus` are not touched. Only timing, group size, defence, building counts and spending weights.
- Multipliers only (one `set`, on a non-difficulty count that stays inside its stock Target..Max span).
- A multiplier stays within 0.75..1.25. Rounding ties (x.5 after multiplying) are refused.
- Easy/Medium/Hard parameters (ships to maintain, defence timer) may only get **weaker** than stock for a civ, by at most 25 %, and keep Easy <= Medium <= Hard. Strong-side boosts use the non-difficulty parameters. Because of this, "inside the stock Easy..Hard span" holds on the strong end of every triplet. **Deviation from the brief:** weakened triplet values can leave the stock span at the weak end (for example Persia defence timer Easy 45 -> 54 minutes), since any multiplier on a monotone triplet must. The non-triplet parameters have no Easy/Medium/Hard span; they move by at most 25 % (counts by at most 1).
- Every edit is checked against the stock files first (stock records must be ids -1 and 44 and neutral).

## 3. The personalities

Stock -> new, per civ. "Min/Max" and "target/max" mean both fields are scaled. Weights named SpendingLevel*
are integer priorities the exe stores per spending category (names from the exe; the exact formula
using them was not read, direction inferred from the name).

**Persia: early aggression, big waves, thin defence and navy.**

| id | parameter | x | stock -> new | note |
|---|---|---|---|---|
| 1 | AttackDelayStarting min/max | 0.8 | 15/25 -> 12/20 | first attack sooner |
| 6 | AttackFrequencyStarting min/max | 0.8 | 10/14 -> 8/11 | attacks closer together |
| 45 | AttackGroupSizePercentage | 1.25 | 0.5 -> 0.625 | bigger waves |
| 60 | SpendingLevelStandingArmy | 1.15 | 120 -> 138 | |
| 57 | SpendingLevelTechResearch | 0.85 | 200 -> 170 | |
| 32 | Stable target/max | 1.2 | 5/4 -> 6/5 | cavalry |
| 87 | DefenseForce min/max | 0.8 | 25/50 -> 20/40 | |
| 20 | MaxMilitaryUnitsOnDefensePercent | 0.8 | 0.4 -> 0.32 | |
| 88 | DefenseTimer E/M/H (min) | 1.2 | 45/20/4 -> 54/24/5 | slower reaction (weaker) |
| 33 | Dock target/max | 0.8 | 2/3 -> 2/2 | |
| 5 | ShipsToMaintain E/M/H | 0.8 | 1/3/4 -> 1/2/3 | |

**Egypt: late attacker with economy and defence.**

| id | parameter | x | stock -> new | note |
|---|---|---|---|---|
| 1 | AttackDelayStarting min/max | 1.2 | 15/25 -> 18/30 | first attack later |
| 45 | AttackGroupSizePercentage | 1.1 | 0.5 -> 0.55 | |
| 87 | DefenseForce min/max | 1.2 | 25/50 -> 30/60 | |
| 20 | MaxMilitaryUnitsOnDefensePercent | 1.25 | 0.4 -> 0.5 | |
| 61 | SpendingLevelGuardTroops | 1.2 | 80 -> 96 | |
| 38 | University target/max | 1.15 | 25/2 -> 29/2 | |
| 39 | Temple target/max | 1.2 | 25/3 -> 30/4 | |
| 59 | SpendingLevelPopulationBuildings | 1.1 | 300 -> 330 | economy |
| 57 | SpendingLevelTechResearch | 1.15 | 200 -> 230 | |
| 60 | SpendingLevelStandingArmy | 0.9 | 120 -> 108 | |

**Greece: naval focus, Spartan Academy, research.**

| id | parameter | x | stock -> new | note |
|---|---|---|---|---|
| 33 | Dock target/max | 1.2 | 2/3 -> 2/4 | |
| 35 | NavalYard target/max | 1.2 | 1/7 -> 1/8 | |
| 118 | NavalMaintenanceTimer | 0.75 | 4 -> 3 | |
| 40 | AICivSpecialBuildings target/max | set 2 | 1/2 -> 2/2 | the Spartan Academy shares its define with this slot |
| 30 | Barracks target/max | 1.15 | 7/5 -> 8/6 | hoplites |
| 57 | SpendingLevelTechResearch | 1.1 | 200 -> 220 | |
| 38 | University target/max | 1.15 | 25/2 -> 29/2 | |
| 45 | AttackGroupSizePercentage | 0.9 | 0.5 -> 0.45 | |

Greece also keeps the full stock fleet (ships to maintain 1/3/4) while Persia and Rome get less, so on the
sea Greece is the strongest civ by comparison.

**Rome: steady military build-up.**

| id | parameter | x | stock -> new | note |
|---|---|---|---|---|
| 30 | Barracks target/max | 1.2 | 7/5 -> 8/6 | |
| 31 | ArcheryRange target/max | 1.15 | 7/4 -> 8/5 | |
| 108 | TankFactory target/max | 1.2 | 5/6 -> 6/7 | late epochs |
| 60 | SpendingLevelStandingArmy | 1.1 | 120 -> 132 | |
| 63 | SpendingLevelTroopImprovements | 1.2 | 120 -> 144 | |
| 99 | SettlementUpgradeInterval | 0.8 | 30 -> 24 | |
| 100 | TownCenterUpgradeInterval | 0.8 | 60 -> 48 | |
| 5 | ShipsToMaintain E/M/H | 0.85 | 1/3/4 -> 1/3/3 | |

Attack timing and group size stay stock for Rome (steady). Values shown are before the Hard edits; the
two scripts combine (personalities scale the Hard-tuned numbers). With the Hard edits the Hard defence
timer is 2, so Persia's slower reaction rounds back to 2 on Hard (it still shows on Easy and Medium).

What this cannot do: single-digit counts only move by whole numbers (a x1.2 on a count of 2 changes
nothing), everything changes all difficulties alike, and any civ-specific *unit mix* (RPS, air/sea unit
choice) is not touched because the exact meaning of those percentages is unconfirmed. Egypt's "late
power" is an approximation (late first strike, larger waves, economy and tech weights), since there is no
time-based growth parameter with a civ slot.

## 4. Build and checks

```
python tools/build_ai_db.py "D:\Games\Rise and Fall" work\overlay-ai --personalities
python tools/test_ai_personalities.py
```

Checks (all passing): stock file neutral for every id/slot; the stub loader of the exe logic reproduces
all 60 reported values; slot 0 and every unlisted id/slot stay neutral; `dbcpbehavior` differs from stock
only in the six Hard edits (6 bytes); Easy <= Medium <= Hard for every civ; wrong/short stock, multiplier
1.6, stronger ships, faster defence timer, rounding tie, duplicate id, id 17, id 44 all stop the build;
two builds are byte-identical; the game directory is not written.

Byte diff (`dbcivspecai.dat`): 396 -> 5100 bytes; count 2 -> 26 (4 bytes); the two stock records are
byte-identical; 24 new records (one per id) differ from the clean stock record 44 only in `behavior_id`
and the four civ pairs (128 bytes in 0x6c..0xb0). Round trip through `raf_data` is byte-identical.

The patcher currently builds the `ai-hard` overlay without the flag. To ship the personalities the
patcher needs a toggle that calls the script with `--personalities`; the manifest then lists both files.
A build without the flag deletes a stale `dbcivspecai.dat` from the overlay.

## 5. Verifying in the game (not done yet)

Setup: skirmish, one computer player per civ (any difficulty; all three stored values are scaled), the
overlay installed. Read the `EEComputerPlayer` object (players are in the array at `0x101db18`, count
at `0x101db70`; confirm an entry is the AI by `[obj+0xe14]+0x211c` = civ row 3/4/5/10). Offsets below
are in the object; values are what `FUN_004701a0` stores:

| what | offset(s) | neutral | Persia | Egypt | Greece | Rome |
|---|---|---|---|---|---|---|
| AttackDelayStarting (max, min) | +0x1288, +0x128c | 25, 15 | 20, 12 | 30, 18 | 25, 15 | 25, 15 |
| AttackGroupSizePercentage (float) | +0x1124 | 0.5 | 0.625 | 0.55 | 0.45 | 0.5 |
| MaxMilitaryUnitsOnDefensePercent (float) | +0x118c | 0.4 | 0.32 | 0.5 | 0.4 | 0.4 |
| DefenseForce | +0x12b0, +0x12b4 | 50/25 | 40/20 | 60/30 | 50/25 | 50/25 |
| standing-army spending level | +0x13a0 | 120 | 138 | 108 | 120 | 132 |
| tech-research spending level | +0x13a4 | 200 | 170 | 230 | 220 | 200 |
| dock target / max | +0x13c0, +0x1308 | 2 / 3 | 2 / 2 | 2 / 3 | 2 / 4 | 2 / 3 |

Expected: the four AIs differ as shown, and the same AI civ in two games gives the same numbers. Failure
signs and meaning:
- All four equal to neutral: the override path is not reached in skirmish (`DAT_0101e255 != 0`, or the
  setter is not called). Then personalities need an exe patch (pass the civ at the slot-0 sites); stop
  and report, do not tune.
- Only some civs differ: check slot numbers (civ rows 3/4/5/10).
- Game crash or desync at game start: remove `dbcivspecai.dat` from the overlay (the stock file works).

Then play a few minutes per civ at Hard and watch for: Persia's first attack arriving earlier and larger than
Greece's; Egypt launching later but holding more defenders and building temples/universities; Greece's
docks and naval yards appearing early and a second civ-special building (the Spartan Academy slot, unconfirmed) being built; Rome's barracks and archery range
counts growing steadily. These are direction checks only; the spending-level weights are inferred from
their names and have not been confirmed.
