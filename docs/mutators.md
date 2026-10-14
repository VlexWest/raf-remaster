# Mutatoren (Regelpakete)

## Zusammenfassung (Deutsch)

Mutatoren sind optionale Regelpakete, die beide Spieler vor einer Partie aktivieren. Jeder ist ein
reines Daten-Overlay (nur `db\dbobjects.dat` und `db\dbtechtree.dat`), wird aus deiner eigenen
Installation erzeugt, gilt für alle Spieler und die KI gleich und ist deterministisch. Es gibt
keinen Code im Spiel. Stand: **gebaut, offline geprüft, NICHT installiert, NICHT im Spiel getestet.**

| Mutator | Was passiert |
|---|---|
| Blitzkrieg | Epochen halb so teuer und halb so lang; Bürger sammeln ca. 67 % schneller (Sammelzeiten x0,6) |
| Poverty | Sammeln 20 % langsamer, Vorkommen (Bäume, Stein, MP-Gold, Futter, Wild) 40 % kleiner, Einheiten 15 % billiger; Felder und SP-Gold bleiben unendlich |
| Titans | Helden 2x Lebenspunkte, 1,5x Angriff, halbe Ausbildungszeit |
| Glass cannon | Alle Armee-Einheiten 1,6x Angriff, 0,6x Lebenspunkte |
| Naval war | Schiffe 30 % billiger, 20 % schneller gebaut, 1,5x Lebenspunkte, Marine-Onager 1,5x Angriff; Land-Militärgebäude 1,5x Kosten |

Gegenseitig ausschließend: Das Tool baut standardmäßig genau einen. `--combine` erlaubt Kombinationen,
verweigert sie aber, sobald zwei Mutatoren dasselbe Feld desselben Eintrags ändern (z. B. Blitzkrieg
+ Poverty beim Sammeltempo, Titans + Glass cannon bei den Helden-Lebenspunkten, Poverty + Naval bei
den Schiffskosten). Erlaubt sind u. a. Blitzkrieg + Titans, Blitzkrieg + Naval, Poverty + Glass cannon.

Bauen: `python tools\build_mutators.py "D:\Games\Rise and Fall" work\overlay-mutators all`
(oder ein Name). Prüfen: `python tools\test_mutators.py` (dauert einige Minuten, jedes Overlay wird
mehrfach gebaut). Installation geht NICHT über dieses Tool; man kopiert
`<mutator>\Data\db\*.dat` von Hand in die Arbeitsinstallation. **Beide Spieler brauchen identische Dateien**
(Lockstep). Zurück zum Original: die beiden Dateien aus der Basisinstallation zurückkopieren.

Nicht umgesetzt: Startressourcen (siehe unten, Feld nicht sicher gedeutet) und Heldenwiederbelebung als
eigenes Feld (nur die Ausbildungszeit im Techtree gefunden).

Ehrlich vorab: Die Richtung der Sammel-Felder (kleiner = schneller) ist aus den Spieldaten belegt,
die Zuordnung Feld -> Rohstoff ist es nicht (deshalb werden alle Sammelfelder gleich skaliert). Dass
die Epochen-Kosten wirklich an den "LEVEL xx (Epoch tech)"-Knoten hängen, ist eine Schlussfolgerung.
Das klären die Tests im Spiel unten.

---

# Mutators (English details)

Status: built, round trip proven, unit-tested offline. Not installed, not yet tested in game.

## How it works

`tools/build_mutators.py <game_dir> <overlay_root> <mutator|all|a+b> [--combine]` reads
`Data\db\dbobjects.dat` and `dbtechtree.dat` through `tools/raf_data.py` and writes
`<overlay_root>\<mutator>\Data\db\*.dat` plus `manifest.json` (generator hash, stock and output
sha256 of every file, every edit as table/record/field/old/new, grouped summary). Output is
deterministic (rational arithmetic, round half up, no randomness, tested by building twice).

Safety checks in the tool:

- stock tables must round-trip byte-identically through `raf_data` before anything is edited;
- every edit re-checks the stock value on the fresh copy, so a different game version fails loudly;
- records are addressed by name and id (`obj:998|A - Inf01 - Spear Infantry (Level 1 Rome)`,
  `tech:<epoch root>|<node name>|obj<index>|id<tech_id>`), never by position; tech node keys must be
  unique or the build stops; any dbobjects record with `object_id != index` (916 placeholders) is
  refused;
- a mutator may not edit the same (table, record, field) twice, and `--combine` refuses overlaps
  between mutators;
- sanity limits: results >= 1, no int32 overflow, no single value changes by more than 3x;
- after packing, the output is unpacked again: it must round-trip, keep its size, and the field-level
  diff against stock must equal the edit list exactly (nothing else changed), and the changed byte
  count must be <= 4 per edit.

Build log (2026-10-15, base install). dbobjects.dat is 6,194,952 bytes, dbtechtree.dat 1,239,700; sizes unchanged.

| Mutator | dbobjects edits (records / bytes changed) | dbtechtree edits (nodes / bytes changed) |
|---|---|---|
| blitzkrieg | 138 (22 / 289) | 30 (15 / 74) |
| poverty | 245 (129 / 513) | 315 (223 / 329) |
| titans | 90 (45 / 156) | 44 (44 / 111) |
| glasscannon | 416 (208 / 625) | none |
| naval | 36 (32 / 72) | 113 (59 / 170) |

## What the values rest on

- **Gather fields are durations, smaller is faster (from game data).** `dbeffects` record 1658 is
  the effect of the tech "Q Wood Gather Rate +15%": value -0.12, i.e. it lowers the field by 12 %
  (same for stone +20 %, farm, fishing: -0.12). So a "+15 %" tech is a time reduction. The fields are
  dbobjects `work_rate` (0x134) and 0x138..0x150; the loader `FUN_00a1dd00` copies them to the unit
  type at +0x274..+0x290 (`decomp\RiseAndFall.c` line 928170). Which field is which resource is NOT
  established (likely the effect attribute ids 26..33 follow the field order: wood 26 -> 0x134, stone 27
  -> 0x138, fishing 31 -> 0x148, farm 33 -> 0x150). Mutators therefore scale all non-zero gather fields
  of a citizen record by the same factor. Edited: the 22 records with behavior `Citizen`/`Civilian`
  that have a non-zero field (`A - Cit - Citizen (Greek/Egypt/Rome/Persian)`, the Civilian variants,
  plus the legacy `Citizen`, `Female Citizen`, `Citizen (China)`). The generic `Citizen` record keeps
  one field in the raw column `x_0x13c` (a float, 2800.0); the tool decodes and writes it as float32.
- **Deposits**: dbobjects `f_0x1a0` is the amount (copied to the type at +0x2cc), `i_0x19c` the
  resource (3 trees, 4 stone, 5 gold, 2 food). Evidence: the five MP gold mines are named
  `(5000)`/`(7500)`/`(10000)`/`(15000)`/`(20000)` and hold exactly those amounts; trees 1250, stone
  2800, forage bush 2000, deer 275. Poverty edits 107 records: all 86 `Amb - Tree`, both
  `Stone Mine`, the five `Gold Mine (MP)`, and 14 `Res - ` food nodes (animals, forage bush).
  Left alone: farms and `Gold Mine (SP)` (both 90000 = effectively endless). Whether random maps use
  these exact objects (the map scripts only say `PlaceResourceInRing (Gold ...)`, the object choice is
  inside `Default.dll`) is not verified.
- **Costs**: `dbtechtree` node fields `cost_0x7c, 0x80, 0x84, 0x88, 0x8c`. `cost_0x74` is an event id
  (6 = "A-Hero Level 2 Research", 739 = "Q Hunting Gather Rate +15%"), and `cost_0x78` is -1/0 in
  the whole file, so neither is scaled. Only positive values are scaled. Which resource each slot
  is: still open (spear infantry 30/70 in 0x7c/0x84, galleys 220/110, epoch techs 500..3000 in 0x88).
- **Epochs**: `A - ACTION - LEVEL 02..10 (Epoch tech)` (nine nodes under the Middle .. WW2 roots, costs
  500, 750, 1000, 1250, 1500, 1800, 2000, 2500, 3000 in 0x88, time 60-90 s; their event ids 6-9 and
  909-913 are the "A-Hero Level N Research" events). These are the level/epoch advances (likely,
  from names and the unit "Level 1..5" scheme). Blitzkrieg also halves the six epoch root nodes
  Dark..WW2 (cost in 0x84 625..1150, time 140-170 s): they look like Empire Earth leftovers, and if the
  game ignores them the edit is harmless. Level 1 is free.
- **Heroes**: dbobjects records `A - Inf00 - ...` and `A - Arc00 - ...` that sit in the tech tree
  (45 records: melee RTS/3rd person modes and archer modes of Alexander, Achilles, Caesar(s), Octavian,
  Cleopatra, Ramses, Tor, Tiberius, Sargon, Nebuchadnezzar, Aristander and the Minotaur gladiator).
  Chariots, camels and Darius (not in the tree) are not touched. Their tech tree `time_ms`
  (80000 / 60000 / 28000) is the only time field found for training a hero; a separate
  death/revive timer was not found in dbobjects, so "revive faster" = faster re-training.
- **Army units** (Glass cannon): tree-referenced records named `A - Inf00-05`, `Arc00-05`, `Cav00-05`,
  `Siege00-03` with behavior `Land Patrolling`, `Horse Archer` or `Naval Onager`, hit points > 0 and
  attack > 0, minus cinematic/test/scenario/worker/general/prisoner records (208 records, heroes
  included). Buildings, citizens, animals and projectiles are untouched. In `dbobjects` the unit's
  own `attack` is the damage for melee units (spear L1 Rome 38); for archers it is assumed that the
  unit value is what the projectile carries (the arrow projectile records all say 25), see test G2.
- **Ships**: 28 records `A - s0x` with behavior `Sea Patrolling` (galley, bireme, trireme, siege ship,
  Greek fire ship, both packed and unpacked) plus the four `Naval Onager`. 47 of 50 `Sea Patrolling`
  records have `attack` 0: the ship's damage is not in the ship record (crew/rams are resolved
  elsewhere, not found). So "stronger ships" means hit points (and onager attack) only.
- **Land military buildings**: tree nodes `A - b  Barracks | Archery Range | Stable | Assyrian Stable |
  Spartan Academy | Gladiator Coliseum | Building Siege...` (59 nodes incl. SP and MP variants).
  Docks, town centres, government centres are not included.
- **Starting resources: not done.** `dbstartingresources.dat` has 3 records (Normal, Death Match,
  Death Match (AI)) with 6 numbers each (Normal: 7147, 500, 3, 100, 150; DM: 15000, 1000, 3, 2000,
  150), but none of them could be tied to a resource in the decompile (the loader `FUN_00602990` copies
  them to an object, the consumer was not found; the in-game option is a checkbox). Editing unknown
  numbers could break the lobby option, so Blitzkrieg leaves them alone. Random-map scripts also set
  starting units but are text, not db.

## Mutators in detail

### blitzkrieg
| What | Table.field | Stock -> new | Why |
|---|---|---|---|
| 9 epoch techs, cost | dbtechtree cost_0x88 | e.g. 500 -> 250, 3000 -> 1500 | half price |
| 9 epoch techs, time | dbtechtree time_ms | 60-90 s -> 30-45 s | half time |
| 6 epoch roots Dark..WW2 | dbtechtree cost_0x84, time_ms | 625 -> 313 (half, rounded up), 140 s -> 70 s | same, in case the roots are what the game uses |
| citizen gather times | dbobjects work_rate, f_0x138, x_0x13c, f_0x140, f_0x144, f_0x148, f_0x14c, f_0x150 | x0.6 (Citizen 2500 -> 1500, 2000 -> 1200) | about +67 % speed; AI gets it too |

Risk: with epochs at half cost the AI advances quickly (the AI picks its own pace through
`dbcpbehavior`, unchanged). Not changed: unit training times, carry capacity.

### poverty
| What | Table.field | Change |
|---|---|---|
| citizen gather times | same eight fields | x1.25 (-20 % speed) |
| deposits (107 records) | dbobjects f_0x1a0 | x0.6 (tree 1250 -> 750, MP gold 5000 -> 3000, stone 2800 -> 1680) |
| unit costs (nodes of army, citizen, ship and onager records with a build time) | dbtechtree cost_0x7c/0x84 | x0.85 (spear L1 30/70 -> 26/60) |

Farms stay endless, so food never runs out completely; wood, stone and gold do. The cheaper units
(15 %) keep pace with the slower income only roughly: expect a slower, smaller game.

### titans
| What | Table.field | Change |
|---|---|---|
| 45 hero records | dbobjects hit_points | x2 (Alexander melee 1200 -> 2400) |
| 45 hero records | dbobjects attack | x1.5 (Alexander archer 800 -> 1200) |
| 44 hero tree nodes | dbtechtree time_ms | x0.5 (80 s -> 40 s) |

### glasscannon
208 army records: `hit_points` x0.6 (spear L1 Rome 440 -> 264), `attack` x1.6 (38 -> 61). Net damage
race about 2.7x faster against equal units. Heroes are included, so it cannot be combined with Titans.

### naval
| What | Table.field | Change |
|---|---|---|
| 32 ship records (28 ships + 4 naval onagers) | dbobjects hit_points | x1.5 (trireme 5650 -> 8475) |
| 4 naval onagers | dbobjects attack | x1.5 (350 -> 525) |
| 18 ship tree nodes | dbtechtree cost_0x7c, cost_0x84 | x0.7 (galley 220/110 -> 154/77) |
| 18 ship tree nodes | dbtechtree time_ms | x0.8 (54 s -> 43.2 s) |
| 59 land military building nodes | dbtechtree cost | x1.5 (Barracks MP 325 -> 488) |

## In-game test checklist (nothing here has been run yet)

Setup for all: copy only the two `.dat` files of ONE mutator over the working install's `Data\db`
(keep the originals; `revert` = copy the base files back), skirmish vs. 1 AI, same files on both
machines in multiplayer. Record the stock reading first from an unmodified run (same map, same
civ, same seed if possible).

Common: game starts, no "out of sync", no crash on opening the build menus; an AI game reaches 10 minutes.

- **B1 (Blitzkrieg epochs)**: as Rome, click the advance to Level 2 (the `LEVEL 02` research).
  Stock reading: cost 500, time 60 s. Expect 250 / 30 s. If the stock cost/time is unchanged, the game
  reads the epoch cost somewhere else (the six root nodes or the exe); note the numbers shown and
  report. Check Level 3 = 375 / 35 s, Level 4 = 500 / 40 s, Level 5 = 625 / 45 s.
- **B2 (gather speed)**: select 10 citizens each on wood, stone, gold, a farm, and a fishing boat,
  time the resources gained over 60 s against the stock run. Expect about 1.6x on every gatherer type.
  Any resource that does not speed up tells which field belongs to which resource (report it, then the
  generator can be narrowed). If it gets slower, the direction is wrong: do NOT use, report.
- **P1 (deposits)**: place a tree line / mine and read the amount in the selection panel or run a
  gatherer until it dries up. Expect tree 750 (stock 1250), stone mine 1680, MP gold 3000/4500/6000/9000/12000,
  forage 1200. On random maps note whether gold mines show these sizes (proves the objects are used).
- **P2 (income, cost)**: spear infantry L1 Rome costs 26 and 60 (stock 30 and 70); gather speed about 0.8x stock.
- **T1 (heroes)**: train a hero (any civ, RTS mode). Expect train time 40 s (stock 80 s), hit points
  2x stock (Alexander melee 2400), kill count against a stock-strength squad about 1.5x damage.
  Check the 3rd-person archer hero deals 1.5x damage per shot (also settles G2).
- **G1 (glass cannon)**: spear L1 Rome shows 264 hp / attack 61 in the unit panel; two equal squads
  fight about 2.7x quicker than stock (time to wipe a squad of ten).
- **G2 (archer damage)**: archers carry their own `attack` (17 -> 27 for Archer L1 Rome). Verify the
  damage dealt per arrow goes up (kill 10 spearmen with 10 archers, compare time). If archers do
  not change, damage for ranged units comes from the projectile record and this mutator only changes
  melee and siege.
- **N1 (naval)**: galley cost 154 / 77, build time 43 s (stock 220/110, 54 s); trireme 8475 hp;
  barracks 488 (stock 325), archery range (MP, Greek) second cost slot 113 (stock 75). Sink a stock ship
  with ships for a rough 1.5x durability check; note that ships do not show an attack value.
- **Combos**: only if wanted, `build_mutators.py ... blitzkrieg+titans --combine` (allowed). The
  refused pairs are tested in `tools\test_mutators.py`.

## Not verified

- Everything above in the running game (see the checklist). The numbers are consistent with the data but
  were never loaded by the game.
- The meaning of each gather field and cost slot (which resource), the epoch node assumption, the
  object choice of random maps, archer damage source, ship damage source, hero revive timer, starting
  resources.
- Multiplayer: lockstep requires identical files on both sides; not tried.

## Files

`tools\build_mutators.py` (generator + proof), `tools\test_mutators.py` (all offline tests: determinism,
exclusivity, conflict refusal, stock check, proof rejects an unlisted change). Overlays are built into
`work\overlay-mutators\<mutator>\` (gitignored, not committed).
