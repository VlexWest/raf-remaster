# Cross-civ training (feature `crossciv`)

Archers and spearmen of every civilization can be trained in the military buildings of the other
civilizations. Needed when a player owns a foreign building: Co-op Roles hands P1's barracks to P2,
captured buildings. Gameplay data (`Data/db/dbtechtree.dat`), so every network player needs it
(REMASTER.txt fingerprint). Built from the stock install by `tools/build_crossciv.py` into
`work/overlay-crossciv`; tests `tools/test_build_crossciv.py`.

## Where the game keeps it

dbtechtree child node loader `FUN_008e5550` (root: `FUN_008dff40`), raw 452-byte node + two lists:

| Raw offset | Meaning | Evidence |
|---|---|---|
| list_a | dbobjects ids of the buildings that produce the item | loader adds one cost entry per list_a element (`FUN_008def40`); entry 0 cost x1.0, entries 1..4 x the floats at 0xfc..0x108 (1.0 for every unit), later entries x1.0 |
| 0x140 + civ (byte) | item available to civ (3 Greece, 4 Persia, 5 Rome, 10 Egypt, 0 = any) | exactly one set per unit node, matches the name |
| 0x144 + 8 x civ (i32 pair) | first value: button slot for that civ (-1 = the button's default, dbbuttons +0x3c); second: not traced | loader turns slots 7..12 into the same row bit; per civ the barracks use 0-4 research, 7 sword, 8 spear, 9 archer (Greece/Rome) or ladder, 10/11 ladder/healer/centurion |

The slot belongs to the unit and the player's civ, not to the building: a Roman player sees the
Roman barracks layout in any barracks.

Stock: sword infantry lists all 8 barracks, every cavalry node all 11 stables. Archers and spearmen
list only their own civ's buildings (Rome Archer L1, tech 6152: 984, 486; Greek Archer L1, 6613:
2501, 193 plus town defense 2721, 339; Persian 6614: archery ranges 388, 2726; Egyptian 6047: 377,
2729).

## What the builder changes

- For each trainable unit node (dbobjects name matches `A - Inf|Arc|Cav0N - ... (Level N Civ)`, not
  Spawned or Building Defender, stock list_a holds one of the 27 military buildings), list_a gets the
  military buildings of all nodes with the same class, sub-type and level, appended in id order.
  Result: 40 nodes (archers and spearmen L1-5 of all four civs), +240 entries. Sword infantry and
  cavalry are unchanged; heroes, siege, ships, town defenses are not touched.
- Archers train where any civ trains archers: Greek and Roman barracks, Persian and Egyptian
  archery ranges. Persian/Egyptian barracks still have no archers (as in stock).
- Persian and Egyptian archers sat on slot 7, the sword slot of the barracks they now appear in.
  They move to the first slot of the same row no other unit line of that civ uses: Persia 7 -> 10,
  Egypt 7 -> 11 (also in their own archery range).
- Nothing else changes; the file grows by 960 bytes.

## Limits

- Upgrade researches (e.g. `A - UP - Archer 2 (Greek)`) still only run in the own civ's buildings.
- A mutator that ships its own `dbtechtree.dat` (blitzkrieg, naval, poverty, titans) is installed
  last and replaces this overlay.
- Not seen in game yet: the foreign unit buttons, their icons, the moved Persian/Egyptian archer
  button (work/TESTING.md).
