# Unit AI (.tai) analysis and improvements

Scope: the 83 plain-text `.tai` files in `Data\unit ai scripts` of the base install. Offline only, nothing installed, game folder untouched.
Line numbers refer to the stock files in `D:\Games\Rise and Fall\Data\unit ai scripts` (all CRLF, 104 KB total).

Unless noted, everything here is read from the files or the exe's string table; guesses are marked "likely".

## 1. The .tai language

### 1.1 Grammar (derived from all 83 files, then checked by a linter)

```
file      := (include | block | comment)*
include   := #include("Other File.tai")          // case-insensitive name, resolved in the same folder
block     := StateName "{" entry* "}"
entry     := cond action* | "Flush()" | cond "remove()"
cond      := Trigger | allof(T1,T2,..) | anyof(T1,T2,..)      // no nesting, no negation
action    := true(NextState) | false(NextState)               // one or both, true first
comment   := // to end of line   |   /* ... */
```

- A *state* (`Idle`, `CheckRange`, `FaceEnemyUnit`...) is a block of ordered entries. Entries are evaluated top to bottom. The first entry whose condition produces a matching `true(..)`/`false(..)` action transitions the unit. An entry with only `true(X)` falls through when the condition is false; an entry with `false(X)` fires when it is false (`UnitInWeaponRange false(CheckRange)` = "if not in range, go re-check").
- A *trigger* is a boolean the engine evaluates (`UnitInWeaponRange`, `Reloaded`, `CanFlee`, `GoalIsUnit`, `AlwaysTrue`...). Triggers and state names are not defined in the scripts. They are compiled into `RiseAndFall.exe`: its string table holds one contiguous list of all 400+ trigger names (starting at `IsAtBuildingEntrance`, ending at `AbandonEnemy`, bracketed by the `allof(`, `anyof(` and `) true(%s) false(%s)` format strings) followed by all ~230 state names (`KnockDownRecover` ... `Airport`). The "action" in `true(X)` is therefore a state to move to; the state's actual behaviour (path, turn, shoot, flee) is C++ (`EEUnitClass`, `EEUCAirplane`, ...).
- Same state name in several places (and across includes) is **merged**: the entries accumulate in include/file order. Evidence for the merge: `Generic Attack.tai` defines `Idle`, `Healer.tai` defines `Idle` again and both must apply to `Land Healer Patrolling.tai`; `Formation.tai:203` clears it again with `Flush()`.
- `Trigger remove()` deletes an earlier entry for that trigger (`Land No Pursuit.tai:17`, `Aircraft Carrier.tai` `ShouldStopAdvancing remove()`). `Flush()` deletes every earlier entry of the state (`Formation.tai`, `Land Animal No Attack.tai` uses `remove()` x4 instead).
- Order matters twice: the include order (the comment block of `Generic Attack.tai` says it must come before `Generic Movement.tai` or "your unit will look stupid"), and the entry order inside a state.
- Code-side hooks: comments say "DO NOT ADD ANYTHING HERE, add it to `EEUnitClass::TestTriggerShouldStopAdvancing`" (`Generic Movement.tai:44`, `Generic Attack.tai:181-188`) and `EEUCAirplane::ShouldStopFlying` (`Generic Air Attack.tai`). `Advance`, `WaitForReload` and `Fly` are therefore partly hard-coded; editing them in the script does less than it looks.

Not in the language: variables, numbers, arithmetic, timers (only fixed engine triggers such as `OneSecondElapsed`), randomness, group or squad addressing, negation, nested boolean expressions, targeting parameters, user-defined triggers, user-defined actions. A script can only re-wire the engine's own triggers and states.

Linter: `tools/build_ai.py lint` checks block structure and that every state, trigger and action target exists in the exe's string table. All 83 stock files pass with 0 issues, which is decent evidence that the grammar above is complete.

### 1.2 What each top-level file controls

Which object uses which script comes from `Data\db\dbobjects.dat`, where the script name sits as a NUL-terminated string in each object record (counts below; the remaining scripts are not named there and are presumably selected by object class in code: air, hero, priest, aatank, ...).

| File | Role | Used by (dbobjects.dat count) |
|---|---|---|
| `Land Patrolling.tai` | `Generic Attack` + `Generic Movement` + `Patrol` + `Generic Death`. This is the default infantry / archer / cavalry / siege / ground-unit brain. | 357 |
| `Sea Patrolling.tai`, `Sea.tai` | identical stack for ships | 50, 4 |
| `Land.tai` | same without `Patrol` | 13 |
| `Simple Building.tai`, `Gate`, `Town Defense`, `Land Garrison` | death only / gate state machine / loading | 1276, 74, 23, 23 |
| `Defending Building.tai` -> `Stationary Target Tracking.tai` | towers and tower-like buildings: `Idle -> EnemyUnitSpotted -> TrackEnemyUnit -> AttackEnemyUnit` | 34 |
| `Tower Catapult.tai` | like tracking, but with `EnemyWithinMinimumRange -> LostEnemyUnit` | 5 |
| `Naval Onager.tai` | private copy of the whole attack file with animation waits | 4 |
| `Generic Attack.tai` | the core combat state machine (see 1.3) | included by ~25 files |
| `Generic Movement.tai` | path following, waypoints, container loading, explore | included by ~25 files |
| `Generic Death.tai`, `Projectile.tai`, `3P Arrow.tai`, `Axe.tai`, `Torpedo.tai`, `Nuke Missile.tai` | death sequences, projectiles | all |
| `Formation.tai` | army formation object; includes Generic Attack, then `Flush()`es most of it | 1 |
| `Generic Air Attack.tai`, `Generic Air Movement.tai`, `Air.tai`, `Bomber.tai`, `Eagle.tai`, `Falcon.tai`, `Helicopter.tai`, `Airport.tai`, `Aircraft Carrier.tai` | aircraft: takeoff, taxi, fly, strafe, bomb, landing queue | air / bomber / airport 1 each |
| `Healer.tai`, `Land/Sea Healer Patrolling`, `Medic Surgeon`, `Military Trainer` | heal and train goals | 1 to 4 |
| `Priest.tai`, `Land Priest`, `Naval Priest`, `Prophet`, `Priest Prophet`, `Military Prophet`, `Missionary`, `Priest Tower` | conversion and calamity (spell) casting | 1 to 3 |
| `Hero.tai` | `Land No Pursuit` + `Healer` + `Patrol`; re-adds `AmIUnderAttack` | not named in dbobjects |
| `Land/Sea No Pursuit.tai`, `AATank.tai` | attack stack with pursuit disabled by overriding `CheckRange`, `FaceEnemyUnit`, `AttackEnemyUnit` | not named |
| `Citizen`, `Gather`, `BuildRepair`, `Sailor`, `Engineer`, `Civilian`, `Fishing Boat`, `Farm`, `Mining Building` | economy units | 4 to 31 |
| `Transport`, `Sea Transport`, `Helicopter Transport`, `Bombing Helicopter Transport`, `Attacking Transport`, `Load Container` | boarding and unloading | 12 for `Transport` |
| `Avoid`, `Land Animal`, `Land Animal No Attack`, `Booby Trap`, `Land Sapper`, `Sea Sapper`, `Volcano`, `Hurricane`, `Anti Matter Storm`, `Coliseum`, `Grappling Hook`, `Missile Base`, `Mobile Weapons Platform`, `Active Group` (unused, says so) | specials | small |

### 1.3 The combat loop in `Generic Attack.tai` (what every ground unit does)

```
Idle --CanISeeEnemy--> CheckRange
CheckRange --in range / facing needed--> FaceEnemyUnit --Reloaded+in arc--> AttackEnemyUnit --> WaitForReload --> (engine) Idle/ReacquireGoal
CheckRange --not in range--> ShouldIFollowEnemyUnit --> PrepareToMove -> (Generic Movement) LookForEnemies -> Advance -> ... -> CheckRange
AttackEnemyUnit --ShouldIRun--> RunFromAttacker -> PrepareToMove          (flee decision is engine code: ShouldIRun / CanFlee)
AttackEnemyUnit --ShouldIRetaliate--> RetaliateAgainstAttacker -> CheckRange   (switches target to the attacker)
target gone --> ShouldIReturnToInitialContactLocation --> CanISeeEnemy -> CheckRange (rescan), else return to where the fight started
UnderAttack --CanFlee--> RunFromAttacker ; else if attacker reachable and we are idle -> RetaliateAgainstAttacker
```

Target selection (who `CanISeeEnemy` / `EnemyUnitSpotted` picks) is **not** in the scripts. It is engine code driven by `Data\db\dbaiunittargeting.dat` (section 1.4), and `dbunitbehavior.dat` holds the stances (`Scout, Stand Ground, Guard, Harass, Cautious, Aggressive, Healing Hero, Morale Hero, No Fight No Flee`) that drive `CanFlee` / `CanIMoveFreely` / `ShouldIRun` (likely, from names and from `Guard*`/`Defend*` states in the exe).

### 1.4 How a unit picks its target (engine, read from the decompiled exe)

- `dbaiunittargeting.dat` has three 160-byte records, one per *class*: 0 Melee, 1 Short Range, 2 Long Range. The loader `FUN_005f2250` keeps record bytes 0x6c..0x8c and 0x9c as a 0x28-byte row, `DAT_00d2c960[class]`. A unit is Melee when its def flag +0x3f8 is set, else Long when its weapon range (+0x6f4) is above the radius of its vtable+0xf0 (likely sight), else Short (`FUN_00a84e10`).
- Row (offset: meaning, Melee / Short / Long): +0x00 candidate is attacking me 2/15/10, +0x04 not used by the scorers 1/20/15, +0x08 candidate in weapon range 50/30/50, +0x0c candidate +0x6f0 (attack) below mine 1/6/4, +0x10 candidate vtable+0x6c (likely health) below mine 1/6/4, +0x14 preferred object type (0 = none; a match takes the target at once), +0x18 weight of the family damage multiplier 1/1/1, +0x1c weight of 1/dist² 50/2/0, +0x20 candidate +0x6f0 == 0: -500, +0x24 stop threshold 50/15/15.
- Scorer: `FUN_00a8c8c0` (unit scan; context built by `FUN_00a84e10`: ctx+0x24 attacker, +0x58 class, +0x70 best score, +0x75 stop flag). Each enemy around the unit gets the sum above (integers; the two float terms rounded by `FUN_004067e0`); the best score is kept and the scan stops when a score reaches +0x24. With 15 that is the first enemy in weapon range, so for ranged units the "priority" is in practice "first one in range". The same formula is in `FUN_00a92810` (scan over the map grid; loops while score < +0x24) and the formation chooser `FUN_00935fa0` (no stop). `FUN_004a27d0` re-scores a unit goal with the same row; `FUN_00557450` (a goal weight) uses 3 x the threshold, so the threshold must not be raised in the .dat.
- Families (`dbobjects` record 0x68 = def +0x220, `dbfamily.dat` index): siege 30 Ram, 31 Siege 333 (ballista, palintonos, onager, tower catapult, ladder unit), 57 Ladder Team, 62 Siege Tower, 63 Siege Building (siege under construction), 65 Naval Siege, 68 Entrenched Siege (unpacked siege towers); archers 29 Human Archer, 14 Mounted Archer (chariots, horse archers), 54 Cavalry Archer (no objects); hero 8.
- Stance: unit +0x624 points into the `dbunitbehavior` vector `[0xD2F004]` (set by the EEMSetUnitBehavior handler `FUN_005d63e0`); index 2 is Guard (UI button control 0xe9, `FUN_00b77490`).

**Feature `target-priority`** (exe patch, default on since 1.2.0, tested live; `tools/raf_patch.py` `TARGET_PRIORITY`, generated and tested by `tools/test_target_priority.py`). For classes Short/Long only, all three scorers add a family tier bonus:

| | all candidates | in weapon range (total) | in range, attacker in Guard |
|---|---|---|---|
| Short: siege / archers / hero | 8 / 6 / 3 | 25 / 18 / 10 (< +30) | siege 75 |
| Long: siege / archers / hero | 12 / 8 / 5 | 40 / 25 / 15 (< +50) | siege 75 |

The in-range bonus stays below the in-range term, so a unit does not leave enemies in range for a far siege engine; out of range it only breaks ties. In Guard an in-range siege engine beats every other in-range target (wall defenders shoot rams and towers first).

Fire spreading (RAF-10, "archers on a wall do not attack spearmen"): stock stops its scan at the first in-range enemy that fewer than 3 goals aim at (`[unit+0x858]`, raised by `FUN_009d6940` and lowered by `FUN_009d5990` when a goal takes or drops its target; test at 0xA8CD82). Scoring every candidate dropped that rule, so all archers on a wall shot the one best enemy archer and the spearmen at the wall got nothing. Every in-range Short/Long candidate now gets **+50 unless it is saturated**: 3 or more goals aim at it, not counting the attacker's own goal (`[attacker+0x608]` cast EEUnitGoal -> EEUGAttackUnit through the same `__RTDynamicCast` call the stock "targets me" test uses, then `[[goal+0x40]+0x94]` like `FUN_004a19d0`). Siege is never saturated. 50 is more than the largest gap a saturated target can open over a free one in range (Short: archer tier 18 + targets me 15 + weaker attack 6 + weaker health 6 = 45; Long 25 + 10 + 4 + 4 = 43), so a free spearman in range (80) beats a saturated enemy archer that shoots me (63). Out-of-range scores do not change, so a saturated target in range still beats every target out of range, and when everything is saturated the old order holds. The two scans stop at Short 155 / Long 175 (Guard siege in range: 30/50 + 75 + 50) instead of 15, so they look at every candidate (more work per scan); a Guard unit still stops at the first in-range siege. Melee is unchanged. Integer adds only, deterministic. Hooks: in-range blocks 0xA8CC6E / 0xA92CE1 / 0x936294, end of the sums 0xA8CD25 / 0xA92D86 / 0x936350, stop tests 0xA8CD90 / 0xA92DA5; tables 0xCE3C00..0xCE3C87, code 0xCE3C90..0xCE3E85 (.RDATA zero tail, limit 0xCE3E8C). The Guard test only compares the attacker's +0x624 (null attacker = no Guard); every scanned attacker is a unit object of at least 0x940 bytes (`FUN_00a84e10` reads its +0x93e), towers/buildings hold 0 or a stance pointer there. Simulation path: `fingerprint()` mixes in `TARGET_PRIORITY_MARK` (name + hash of the patch bytes) while the patch is installed; off, the fingerprint is unchanged.

## 2. Weaknesses a player would notice

Confidence key: A = clear from the file, B = clear intent but the behaviour depends on engine code I cannot read here, C = suspicion.

1. **Siege does not back off from enemies inside its minimum range unless the player gave the order (A).** `Generic Attack.tai:62,126` and `Naval Onager.tai:41,105,173` gate `MoveOutOfMinimumRange` behind `GoalIsPlayerInitiated`. For an auto-acquired target the next line (`Generic Attack.tai:63`, `anyof(AbandonEnemy,EnemyWithinMinimumRange) true(ShouldIReturnToInitialContactLocation)`) sends the catapult to `ShouldIReturn..` which immediately re-enters `CheckRange` (`Generic Attack.tai:278-283`, comment "instead of going idle (and fidgeting) try checking range once more"). That is a state ping-pong with no movement, so an onager that auto-engages an enemy that closed in just stands there (likely the engine's per-tick transition cap breaks the loop). The author's comment in `Tower Catapult.tai` (enemy inside min range -> `LostEnemyUnit`) shows towers have the same blind spot, but a tower cannot move. **Fixed (Fix 1).**
2. **Transports never react to being attacked (B).** `Transport.tai`, `Sea Transport.tai`, `Helicopter Transport.tai` define no `Idle`, `UnderAttack` or `RunFromAttacker`, unlike every other mobile script (`Citizen.tai:47`, `Priest.tai:17`, `Generic Attack.tai:244`). A loaded troop ship that is shot while idle just sits. **Fixed (Fix 2)**, with the caveat that the engine may already poll `AmIUnderAttack` for all units (see section 5).
3. **No health-based retreat anywhere (A).** `grep -i "health|hurt|wound|hitpoint|morale|retreat"` over all scripts returns only `Farm.tai` and `Generic Death.tai` (no hit in an AI condition). The only flee triggers are `CanFlee`, `ShouldIRun`, `CitizenShouldFlee`, `TakingLightDamage` (`Avoid.tai:19`, `Sailor.tai`). The exe knows `TakingHeavyDamage`, `NoLongerUnderAttack`, `GuardedUnitTakingHeavyDamage` but no shipped script uses them. Retreat when hurt is impossible without engine support or an unshipped trigger (section 4).
4. **No kiting for ranged units (A).** Nothing between `AttackEnemyUnit` and `RunFromAttacker` tests who is in melee. The exe has `AttackerIsMeleeUnit` and `AttackerIsRangedUnit`; only `AttackerIsRangedUnit` is used (`Generic Attack.tai:77`, `Land Priest.tai`), only for mounts and priests. Horse archers (`Horse Archer.tai`) are the stock Generic Attack stack, so they stand and shoot like infantry.
5. **Aircraft abort attack runs as soon as they are hit (B).** `Generic Air Attack.tai:87,97,105,117,131` and `Bomber.tai:31,76,128,138` put `allof(AmIUnderAttack,GoalIsNotPlayerInitiated,CanFlee) true(RunFromAttacker)` first in the face/attack/reload states, before the shoot/drop entry. Whether it matters depends on `CanFlee` for planes (engine). Not changed, because turning it off could just get planes shot down.
6. **Medic Surgeon stops healing when an enemy is visible (A).** `Medic Surgeon.tai:19` `HealUnit { CanISeeEnemy true(CheckRange) }` is evaluated after the stock heal exits, but any time those fall through the medic switches to combat and drops the patient. 4 objects. Not changed (cannot tell whether the unit is meant to fight).
7. **AA Tank pursues when retaliating (B).** `AATank.tai:15` says "Override these three transitions to inhibit pursuit" but overrides only two (`CheckRange`, `FaceEnemyUnit`); `Land No Pursuit.tai` and `Sea No Pursuit.tai` override three (`AttackEnemyUnit` too, line 33). `RetaliateAgainstAttacker` (`Generic Attack.tai:234`) ends in `false(PrepareToMove)`, i.e. a move. The file does not appear by name in dbobjects.dat. Not changed (unused or class-selected).
8. **Group focus fire does not exist at script level (A).** Every unit runs its own copy of the state machine; the only coupling is `GroupFinalRepath`, `HasGroupFlee`/`HasGroupAttack` (animals only, `Land Animal.tai:20-21`) and the `Formation*` states. After each volley units pass through `WaitingForStateTransition -> Idle -> CanISeeEnemy` (`Generic Movement.tai:50-53`, `Generic Attack.tai:181-188`), so targets are re-picked by engine code (likely nearest/priority table), not held. Fixing this needs the engine or `dbaiunittargeting.dat`.
9. **Towers retarget through a full `Idle` round trip (B).** `Stationary Target Tracking.tai:11-19` goes `TrackEnemyUnit -> WaitForReload -> Idle -> EnemyUnitSpotted` for every volley; `Tower Catapult.tai` uses `LostEnemyUnit` so it keeps the target until the animation ends. Tower target choice is again engine code (`ComputerBuildingShouldPickEnemyTarget` is the only visible hook, `Priest Tower.tai`).
10. **Ships and aircraft idle (B).** Idle ships use the same `Idle -> CanISeeEnemy` as land units; there is no separate "hunt" behaviour. `Hurricane.tai` deliberately neutralises it (`Idle { EnemyUnitSpotted true(Idle) }`). Aircraft only scan from `Circle` (`Generic Air Attack.tai:46-51`), so a plane on the ground (`Idle` in an airport) launches only through `Airport.tai:12` (`EnemyUnitSpotted` -> `AirportOpen`).
11. **Possible typo (C, not changed).** `Bomber.tai:15` tests `UnitDestroyed`; every other script (44 uses) tests `EnemyUnitDestroyed`. Both names exist in the exe, so it may be a real, different trigger. If it is a typo, bombers never pick a secondary target after killing their primary. To settle it, watch a bomber with a unit goal after the target dies.
12. **Minor:** `Generic Air Attack.tai` `FaceEnemyUnit` / `FaceLocation` omit `CeaseFire` that `AttackEnemyUnit` / `AttackLocation` handle, so a stop order is honoured one state late (A, cosmetic).

## 3. Changes shipped (all behind "not installed")

Everything is generated by `tools/build_ai.py build` from the user's install. Each edit is an exact-match replacement that must hit exactly once; output goes to `ai/unit ai scripts/` (mirrors `Data\unit ai scripts`). Nothing is written to the game folder. The default state is "not installed": the working install `D:\Games\RAF-remaster` only changes if the files are copied there by hand (suggested `--flag`: install step off by default until the in-game tests in section 6 pass).

### Fix 1: Artillery steps out of minimum range on auto-targets (`Generic Attack.tai`, `Naval Onager.tai`)
Removes `GoalIsPlayerInitiated` from the `MoveOutOfMinimumRange` entries in `CheckRange`, `FaceEnemyUnit` (and naval `WaitForReload`). Adds `AmmoExhausted` ahead of it in `FaceEnemyUnit` so an empty catapult does not walk away. Affects every unit whose `UnitIsArtillery` is true and that uses `Land Patrolling`/`Land`/`Sea`/... (357+ objects, but the trigger limits it to artillery). Does not touch `FaceLocation` (ground targets are always player-ordered) or the `Formation.tai` copy.

### Fix 2: Transports react to attacks (`Sea Transport.tai`, `Helicopter Transport.tai`)
Adds `Idle { AmIUnderAttack true(UnderAttack) }`, `UnderAttack { CanFlee true(RunFromAttacker) false(Idle) }`, `RunFromAttacker { AlwaysTrue true(PrepareToMove) }`. Uses the `remove()`-then-add pair `Hero.tai` uses so the entry cannot be duplicated if the engine already has a default. Not applied to `Transport.tai` itself because `Bombing Helicopter Transport` and `Attacking Transport` include it after `Generic Attack` (which already defines these states).

### Diffs

Only the changed lines are shown: `-` is the line in the stock script (file:line), `+` is ours. The surrounding lines are in your own install.

```diff
# Generic Attack.tai:62 (CheckRange) & :126 (FaceEnemyUnit); Naval Onager.tai:41, :105 & :173 (WaitForReload)
-	allof(GoalIsPlayerInitiated,UnitIsArtillery,EnemyWithinMinimumRange) true(MoveOutOfMinimumRange)
+	allof(UnitIsArtillery,EnemyWithinMinimumRange) true(MoveOutOfMinimumRange)

# added before that line in FaceEnemyUnit: Generic Attack.tai:126 & Naval Onager.tai:105
+	AmmoExhausted true(ShouldIReturnToInitialContactLocation)   (Generic Attack)
+	AmmoExhausted true(LostEnemyUnit)                           (Naval Onager)

# added after the #include of Transport.tai: Sea Transport.tai:19 & Helicopter Transport.tai:14
+// loaded transports run from attackers instead of sitting idle
+Idle
+{
+	AmIUnderAttack remove()
+}
+Idle
+{
+	AmIUnderAttack true(UnderAttack)
+}
+UnderAttack
+{
+	CanFlee true(RunFromAttacker) false(Idle)
+}
+RunFromAttacker
+{
+	AlwaysTrue true(PrepareToMove)
+}
```

Four files, 3 stock-state families changed. Build/lint: `python tools/build_ai.py build && python tools/build_ai.py lint` -> 0 stock issues, 0 patched issues.

### Considered and rejected
- Bomber: finish the drop before fleeing. The flee entry is only checked while loading, so the gain is negligible.
- Aircraft: add `UnitNotInWeaponRange` to the flee entries so planes commit once in range (precedent: `Tower Catapult.tai:29`). The state in which the entry is checked, `AttackEnemyUnit`, lasts one tick, so it would change almost nothing; the useful place (`FaceEnemyUnit`) is where fleeing is correct.
- `Idle { AmIUnderAttack true(UnderAttack) }` in `Generic Attack.tai`: probably already built in (section 5).
- Anything using unused triggers (`AttackerIsMeleeUnit`, `TakingHeavyDamage`, ...): outside "constructs used by shipped scripts". See section 4.

## 4. Experiments that need in-game testing (not shipped)

These use engine triggers that exist in the exe's string table but are never used in a shipped script. Semantics are guessed from the names, so they must be tried in game first:

- Ranged kiting: in `Generic Attack.tai` `AttackEnemyUnit` (before `ShouldIRetaliate`) add `allof(AttackerIsMeleeUnit,AttackerIsRangedUnit,CanFlee) true(RunFromAttacker)`. Unclear: `AttackerIsRangedUnit` appears to describe *the attacker* of this unit, so a self-test of "I am ranged" may not exist.
- Retreat when hurt: `TakingHeavyDamage true(RunFromAttacker)` in `AttackEnemyUnit`/`WaitForReload`; `NoLongerUnderAttack` to resume.
- `ShouldRepositionForCombat` (air only today) for ground ranged units.
- `EnemyUnitMoving`, `EnemyUnitInLOS`, `GoalIsNotAttack`, `TargetIsNotDefensiveBuilding` could give better target switching (unused).
- States never mentioned in scripts but present in the exe: `Engage`, `CheckSafety`, `MoveToSafeLocation`, `GuardUnit`, `GuardBuilding`, `DefendUnit`, `DefendLocation`, `DefendBuilding`, `Decelerate`, `Climb`.

## 5. Risks and unknowns (parser/engine)

- The parser is not available. The grammar was reconstructed from usage and validated structurally plus against the exe string table, not against the loader. Whether a duplicate `Idle` block in one file, or a trigger repeated in one state, is accepted or overridden is inferred only from shipped patterns (`Idle` blocks in `Hero.tai:16` after the included `Land No Pursuit.tai:15`; `Advance` twice in `Bombing Helicopter Transport.tai:12,18`).
- Merge/override semantics for the same trigger in the same state are not proven. The shipped `AA Tank`/`Land No Pursuit` overrides after `#include("Generic Attack.tai")` (`UnitInWeaponRange true(FaceEnemyUnit) false(Idle)` in `CheckRange`) only work if later entries win or replace earlier ones. All shipped edits here avoid depending on it: they edit the existing lines in place, or use `remove()` + add.
- `AmIUnderAttack` in `Idle`: `Land No Pursuit.tai:17` removes it although `Generic Attack.tai`'s `Idle` (line 35-38) has only `CanISeeEnemy`. This implies the engine seeds a default `Idle` entry; Fix 2 is safe either way but might do nothing.
- Fix 1 changes behaviour from "stand still" to "walk out of min range". It could, in principle, pull siege out of cover or oscillate if the engine's destination is inside the min range. The player-ordered path has shipped the same behaviour since release, so path computation is proven; the auto path is not.
- Scripts are read at start-up from the data folder (`Unit AI Scripts\` string in the exe, `*.tai` glob); I did not check whether a checksum/pack validation exists for multiplayer (the game uses an OOS dump, `OUT OF SYNCH DUMP` strings). **Both peers must run identical scripts or an MP game will desync.** Single-player only until tested.

## 6. In-game tests

All on a copy of the install with the four files copied into `Data\unit ai scripts`. Keep the original files for A/B. Scenario editor (`scenarioeditor` arg) or skirmish, windowed.

1. **Fix 1.** Skirmish, player A: 3 catapults (stance Aggressive, no orders) at a fixed spot; player B: 1 swordsman walking from 15 tiles toward them. Stock expectation: catapults fire while it approaches, then stop firing once it is adjacent and stay in place. With patch: catapults back away until the target is outside min range (positions change, then shots resume). Failure: catapults oscillate/jitter in place, drift away without firing, or walk out of range of a stationary target. Repeat with a player-issued attack order (must be unchanged) and with the catapult at 0 ammo if available (must not move).
2. **Fix 2.** Troop ship loaded with 5 soldiers, idle at sea; enemy warship fires on it from range. Stock: ship sits. Patch: ship moves away. Failure: ship moves while player-ordered to unload, or shakes in place. Same for a helicopter transport vs. an AA unit.
3. **Smoke test.** Game starts, loads a skirmish, no new messages in the game's log file about unknown triggers/states/parse errors. If the game ignores a bad script file silently, compare unit behaviour against the stock copy.
4. **MP.** Do not test until one host + one client with identical files complete 5 minutes without an OOS dump.

## 7. What is not in the .tai files (strategic AI) and leads

Not in any script: economy, build orders, army composition, attack waves, defence, research, diplomacy, difficulty. The scripts only drive a single unit or building once it has a goal (`Active Group.tai` is a stub that says "this file is unused").

Leads for further work (all from the exe's string table or file names):

- `Data\db\dbcpbehavior.dat` (8,012 bytes, binary, no strings): referenced by the exe as `db\dbcpbehavior.dat` and class `EEComputerPlayerBehaviorTable` / `DBComputerPlayerBehaviorTable`. Probably the per-difficulty/per-civ numeric table.
- The exe's out-of-sync dump lists the tunables: `AttackDelay`, `AttackFrequency`, `AttackGroupSize`, `CostDiscount`, `DefenseFrequency`, `EpochAdvanceFrequency`, `PopLimitAdjust`, `RandomResearch`, `TownGuardUpdateTime`, each with `LevelOfDifficulty{Easy,Medium,Hard}Modifier` (Medium only for `AttackGroupSize` and `PopLimitAdjust`). A struct with these fields is very likely what `dbcpbehavior.dat` holds.
- `Data\db\dbcivspecai.dat` (396 bytes, "Civ Specific AI"), `dbaiunittargeting.dat` (Melee / Short Range / Long Range), `dbunitbehavior.dat` (stances, BIFF-like header), `dbgamevariant.dat` (Scenarios / Tournament / Standard), `dbactiontable.dat`, `dbspecialunittable.dat`, `dbfamily.dat`.
- `EECP*` classes in the exe (computer player): `EEComputerPlayer`, `EECPCivilizationManager` (log strings: epoch advance time, settlement upgrade check, building counts), `EECPBuildManager`, `EECPResearchManager`, `EECPResourceManager`, `EECPSpecialPowersManager`, `EECPWallManager`, `EECPExplorationManager`, `EECPDiplomacyManager`, `EECPCombatManager`, `EECPCombatStrategy`, `EECPAttackCommander`, `EECPDefenseCommander`, `EECPAttackGroup`/`SubGroup`/`Formation`, `EECPASG*` (unit-type attack-group specialisations: Land, Sea, Transport, Hero, Prophet and one analyser per calamity, e.g. `EECPASGUProphetCalamityAnalyzerFamine`), `EECPUGather*` (unit counting), `EECPIntelligence` and `EECPIntelligencePlayerFile`.
- `EECPIntelligencePlayerFile` suggests the AI reads a per-player intelligence file (name not found as a string; likely a data file in `Data\scenarios` or `Data\db`), worth a search of `scenarios\*` & the `.sdf`/`.edf` formats (see `docs/formats.md`).
- `EEAIAStar*` / `EEAIContinent` / `EEAIPathSubSector`: pathfinding and continental analysis (not strategy).
- `Data\map scripts\*.rmv` and `Data\random map scripts\*.rmv` (binary) are map generation, not AI. `Data\scenarios\*.scn` (e.g. `(2) wide open.scn`) and `Data\campaigns\*.ssa` (`Alexander.ssa`, `Cleopatra.ssa`) are binary and may hold per-scenario AI triggers (`EESMC*` scenario conditions in the exe: `EESMCPlayerHasResource`, `...Technology`, `...PlayerDefeated`).
- No `.xml` outside `Data\user interface` (103 files, UI).
