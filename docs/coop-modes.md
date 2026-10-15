# Co-op modes: Survival Endless, Boss Hunt, Co-op Roles, Co-op vs Hard AI

Status (2026-10-15): **built & unit-tested offline, not yet tested in game.** Feature `coop-modes`
in `tools/raf_patch.py` is **off** until the in-game tests in section 6 pass.

Build and check (both read the user's install, write only into the overlay):

```
python tools/build_coop.py "D:\Games\Rise and Fall" work\overlay-coop
python tools/check_coop.py "D:\Games\Rise and Fall" work\overlay-coop      # ALL CHECKS PASSED
python tools/build_coop.py "D:\Games\Rise and Fall" <scratch> --probe     # in-game test map
python tools/build_coop.py "D:\Games\Rise and Fall" <scratch> --test-schedule   # short clocks
```

| lobby name | file (`Data\scenarios`, + `.rmv` in `Data\map scripts`) | template | players |
|---|---|---|---|
| (4) Survival Endless | `(4) survival endless.scn` | (4) plains | 1-2 humans + exactly 1 computer |
| (4) Boss Hunt | `(4) boss hunt.scn` | (4) plains | 1-2 humans + exactly 1 computer |
| (4) Co-op Roles | `(4) co-op roles.scn` | (4) plains | 2 humans (slot 1, slot 2) + exactly 1 computer |
| (4) Co-op Roles vs AI | `(4) co-op roles vs ai.scn` | (4) plains | 2 humans (slot 1, slot 2) + 1-2 computers |
| (5) Co-op vs Hard AI | `(5) co-op vs hard ai.scn` | (5) babylon | 2 humans (slots 1-2) + 3 computers |

Texts (since 2026-10-15 evening): lobby names and help come from Language.dll string ids, in
Russian (English with `lang-en`); in-game chat and counters are Russian cp1251 by default,
English with `--lang en`. Every text lives in `tools/map_texts.py`. Lobby pictures are the
template's own preview with a badge. Evidence and rules: docs/survival.md section 8.

Multiplayer: every file lives in `Data\scenarios` / `Data\map scripts`, both are in
`GAMEPLAY_DIRS`, so they count into the fingerprint; both players need the same build.

## 1. What the trigger system offers (study)

Answer to "no loops or variables?": it has both. Evidence from the shipped scenarios
(`tools/raf_scn.py`, all 76 parse; counts over every shipped effect/condition):

| need | mechanism | evidence | source |
|---|---|---|---|
| repeat forever | trigger `looping` flag; fires again every `true_for` s while the conditions hold | runtime FUN_008d0d80 (docs/scenario-format.md 3.2); gaugamela gold cap loop; survival "keep enemy passive" loop (in game) | code |
| chain stages | category-3 Trigger effect: `trigger` 0 = on / 1 = off, `action` = trigger index | 1687 shipped uses, e.g. contested sands "Create WJ1 on" (0, 1) | files |
| counters | player variables Var0..Var9 = resource 11..20, set/add/sub by ChangeResourceLevel (`amount` 0/1/2), compared by PlayerHasResource | scendefault "SS Set P1 Var4 = Var4 + Civ Dev", 708 ChangeResourceLevel, 715 PlayerHasResource | files |
| show a number | text token `/#PA<id>` = current value of the PlayerHasResource condition with that id (the campaigns' "REF ..." conditions, `f50` = 2) | Cleopatra 10 chat "Carry-over: /#PA0125 ...", Cleopatra 01 counter "...: /#PA0399", 41 ChangeResourceLevel value texts | format from files, rendering in chat **not seen in game** |
| move units between players | ChangeOwner (`new_player` = player enum 7+) | 157 shipped uses | files |
| "only living" / "only finished" | object attribute filter `ubc`=1, `u98`=3 hit points, `u9c..ua0`, `bde`=1 percent | "Ramses HP" 0..100 %, "Glory Statue Built" 100..100 %, tutorial "P1 Barracks" full HP | files |
| compare op | PlayerHasResource `f50`: 0 "<", 1 "<=", 2 "=" / reference, 3 ">=" (">"?), 4 ">" | names of shipped conditions ("Glory < 5" 0, "Pop <= 40" 1, "Gold > 900" 3, "Glory >= 100" 3) | likely, from names; raf_scn calls the fields `f50`/`compare` (op/value) |
| restrict training per player | ModifyTechnology exists (gamersday "P1 to Level 2") but tech ids for single units are not mapped | not used | rejected for now (needs tech-tree RE) |

## 2. Rules per mode

### 2.1 Survival Endless

* Start, computer and diplomacy exactly as Survival (AI off, citizens removed, TC
  invulnerable, gold/wood 0 in a loop; humans allied by trigger at 1 s).
* **Explicit waves 1-50** (`--explicit-waves`): one trigger each, own text "Wave k is coming!",
  countdown to the next. Size `min(50, 3 + 1.25k + 0.03k^2)` (cap reached at wave 24), +50 % co-op
  bonus with two human TCs, level 1-5 (L5 from wave 17), elephants from 11. Bosses every 5th
  wave, `1 + k//20` heroes rotating through all 13 RTS heroes from the weakest (Cleopatra) to
  the strongest (Minotaur). Gaps 150/135/120/110 s, then 100 s, +30 s after boss waves. Wave 50
  at 1:39:45.
* **Endless phase** (looping triggers, from 1:41:25): every 100 s a capped wave plus
  co-op bonus, text "Wave /#PA.... is coming!" (P1 Var0); every 500 s Achilles + the Minotaur;
  every 1000 s another looping tier (10 tiers) adds 8-14 level-5 units to every wave. No
  victory. The game ends only when the town falls.
* **Wave counter**: P1 Var0 (resource 11) = 0 at 1 s, +1 at every wave (explicit and looped).
* **Defeat message**, to all humans (SendChatMessage to player group 3, shown on every client):
  one message trigger per time window. Window 0 (5 s .. wave 1): "The town has fallen before
  the first wave." Window k (wave k .. wave k+1): "The town has fallen in wave k. You survived
  k-1 waves." (static text, no token needed). Endless phase: "The town has fallen in wave
  /#PA.... You held out past wave 50." A gate (P1 Var1 < 1, set to 1 by the first message)
  makes sure only one message shows, although the defeat itself comes 3 s later (or after the
  30 s start guard). Defeat: no human TC for 3 s after 30 s, as Survival.

### 2.2 Boss Hunt

* Same start as Survival. 12 stages: Cleopatra, Octavian, Nebuchadnezzar, Aristander, Sargon,
  Ramses, Tiberius, Alexander, Achilles, Germanicus (G Caesar record), the Minotaur, finally
  Julius Caesar + Tor together. Hero HP in dbobjects rises 1000 -> 1680.
* Stage k spawns at the map centre: the hero(es) + an escort of `6 + 4k` Persian units (level
  `1 + (k-1)//2`, max 5), +50 % with two human TCs; hero bot AI switched on for the computer
  (as in Survival) so heroes use their powers; all attack-move to the human TCs (and again every
  15 s).
* Next stage: a watch trigger, switched on 10 s after the spawn, fires when no hero of the stage
  is alive (alive filter HP 1..100 %) for 2 s: "X has fallen!", countdown 45 s, then the next
  stage is switched on by a Trigger effect. Escorts do not need to be killed.
* Victory: the last stage's heroes dead. Defeat: no human TC.
* `--boss-buffs` (experimental, off): +10 % HP per stage on the boss class (ChangeUnitClassAttribute,
  unverified, see Survival).

### 2.3 Co-op Roles (and vs AI)

Lobby slot 1 (player enum 7) = **economist**, slot 2 (enum 8) = **commander**.

| rule | how | enforceable? |
|---|---|---|
| economist has all citizens | looping every 5 s: ChangeOwner of P2's citizens (4 citizen types) to P1 | yes, within 5 s; P2's own TC can still train citizens, they go to P1 (P2 pays) |
| commander gets every soldier and hero | looping every 5 s: ChangeOwner of P1's units of 110 military types (Inf/Arc/Cav level 1-5 of the four civs, from dbobjects names) and the 13 RTS heroes to P2 | yes, within 5 s; P1 can still give orders in that window |
| commander gets the military buildings | ChangeOwner of P1's barracks/stables/archery ranges (27 types) **only when finished and undamaged** (HP 100 %) | finished buildings yes; a damaged one waits for repair |
| commander builds no economy | P2 has no citizens, so he cannot build anything | yes |
| tithe | every 30 s while P1 holds >= 300 gold: 100 gold P1 -> P2; while >= 800: another 200; same for wood | yes (fixed amounts; percentage transfers would need expression maths that the stock files never use) |
| not covered | siege engines and ships (built as "buildings" by citizens or from docks) stay with P1; docks stay with P1; techs are per player (P2 must research in his buildings) | documented |

* `(4) Co-op Roles`: against the Survival classic waves (first wave at 6:00 instead of 4:00),
  win after wave 20, as Survival.
* `(4) Co-op Roles vs AI`: same roles, the computers keep their AI; humans allied, computers
  allied with each other, no own victory trigger (standard game end).

### 2.4 Co-op vs Hard AI

* Template `(5) babylon` (5 start positions; `--template` is not exposed, change `VSAI` to use
  `(5) crete` / `(5) gorges`). Only one trigger at 1 s: humans allied, humans vs computers,
  computers allied with each other, intro text. AI untouched, own triggers of the map kept
  (no-build zones). `--ai-bonus N` gives every computer N gold and wood at the start (default 0).
* **Civ choice cannot be fixed by the scenario.** The header has 16 player slots with a civ
  field, but the lobby copies its players over them at game start (start-game code
  FUN_006e4c40, docs/scenario-format.md section 2, likely). Lobby setup: humans slots 1-2
  team 1; computers slots 3-5 team 2 as **Greece, Egypt, Persia**; difficulty slider fully right
  (the ai-hard values apply only at slider >= 9, docs/formats.md 3.4). With `ai-personalities`
  on, each civ plays its own personality.

## 3. Lobby setup (all modes)

Skirmish (solo) or LAN lobby, map from the list above, humans in slots 1 and 2 on one team, the
stated number of computers on another team, everything else empty. Waves and bosses come from
"all computer players", so a second computer in Endless/Boss Hunt doubles every wave (as in
Survival). Roles needs the humans exactly in slots 1 and 2 (slot 1 = economist).

## 4. Attack-move first leg (open issue from Survival)

Not fixed. The TaskToObject execute function was not found in this pass (vtable 0xc70e3c of
`EESMEOTaskToObject`, load FUN_008c0170); a TaskToArea target needs the human start positions,
which live in undecoded chunks. The new maps use the Survival orders unchanged (waves did reach
the town in game). Next step: find the execute through the vtable in Ghidra, or let the probe map
place an area at each start corner and compare.

## 5. Limits

* Endless: waves on a fixed clock, unkilled enemies pile up; the computer's pop cap is not
  raised (creation may stop at the cap; not measured). The token text in the endless phase is
  the one unverified display path; if it shows literally, the explicit-wave messages still work.
* Boss Hunt: a hero that the computer revives would come back (the computer has no gold, so
  unlikely); a boss that is never killed stalls the hunt (escorts keep coming only once).
* Roles: hand-over is periodic, not instant; P1 can still click a new soldier for up to 5 s.
* vs Hard AI: the civs and difficulty depend on the lobby.

## 6. In-game tests

Install for a test: `python tools/raf_patch.py apply D:/Games/RAF-remaster --only <current
features>,coop-modes` (game closed). For the probe map copy `<scratch>/Data` from the `--probe`
build into a scratch install or add it by hand; do not ship it.

### 6a. Probe map "(4) Coop Probe" (solo + 1 computer, reveal map)

| time | reading that passes | failure means |
|---:|---|---|
| 5 s | "PROBE 5 s: Var0 = 7 / your gold = <your gold>" | literal "/#PA..." = tokens not expanded in chat -> endless phase message needs a static fallback (stop here) |
| 20, 30, 40 s ... | "PROBE loop ...: Var0 = 8, 9, 10" every ~10 s | no repeat = looping/true_for differs; same number = Var add broken |
| 30 s | enemy Cleopatra at the centre (minimap) | Create of a hero broken |
| after she dies | "boss-down trigger fired" within ~3 s | never = alive filter or Trigger-on chain broken (Boss Hunt stalls); fired before she died = alive filter wrong |
| 40-45 s | 2 L1 swordsmen of yours at the centre, then they change to slot 2's colour (solo: to the empty/absent slot 2 they may vanish or stay yours; note which) | stay yours with 2 humans = ChangeOwner broken |
| 60 s | two lines: P1 gold before/after (-100), P2 gold +100 | no change = ChangeResourceLevel sub/add broken |
| 180 s | victory | - |

### 6b. Per mode (build with `--test-schedule` into a scratch overlay for the long ones)

**Survival Endless** (test schedule: wave 1 at 0:30, 20 s apart, waves of 1-6 units, loop phase
after wave 50 at 17:35, first looped wave 17:55, loop every 20 s)
1. Lobby shows "(4) Survival Endless"; intro, countdown "Wave 1 in".
2. Waves 1, 2, 3 announced with their number, units at the centre walk to the TC.
3. Wave 5 "Cleopatra leads wave 5!", wave 10 Octavian, wave 20 two heroes.
4. Delete your TC during wave 3: exactly one line "The town has fallen in wave 3. You survived
   2 waves." on **both** screens (2 players), then defeat ~3 s later.
5. Let it run past wave 50 (test schedule ~18 min): "Wave 51 is coming!" with the number (token),
   countdown "Next wave in", every 5th loop Achilles + Minotaur.
6. Lose in the loop phase: "The town has fallen in wave 5x." Failure: literal "/#PA" text.

**Boss Hunt** (test schedule: boss 1 at 0:30, 10 s breather)
1. "Cleopatra is coming! Boss 1 of 12." + escort of 10 (15 with two TCs).
2. She uses powers (hero bot AI). Kill her: "Cleopatra has fallen!", countdown "Boss 2 in", then
   Octavian. Escort survivors do not block the next boss.
3. Wound a boss below 50 %: no "fallen" line until she dies.
4. After the last pair (Julius Caesar + Tor) dies: "Victory! Every hero has fallen." and the
   victory screen. Failure: no next boss after a kill = alive filter/chain (run 6a).

**Co-op Roles** (2 PCs, slots 1+2, 1 computer)
1. At 0:02-0:07 slot 2's citizens switch to slot 1.
2. Slot 1 builds a barracks: it stays slot 1's while under construction, turns slot 2's within
   5 s of completion. Slot 1 trains a soldier somewhere: it turns slot 2's within 5 s.
3. From 1:00, with slot 1 holding >= 300 gold for 30 s: slot 1 -100 gold, slot 2 +100 (both
   resource bars).
4. Waves from 6:00 as in Survival; victory after wave 20.
Failure: units/buildings not changing owner = ChangeOwner by type (or the HP-100 % filter) broken.

**Co-op Roles vs AI**: as above, computers build and attack on their own; no waves.

**Co-op vs Hard AI** (2 PCs or solo + 4 computers): computers Greece/Egypt/Persia, slider
right. At 0:01 diplomacy shows humans allied, computers allied with each other (diplomacy
window). The computers expand and attack together. 20+ minutes without out of sync.

## 7. Files

`tools/build_coop.py` (generator, all modes, `--probe`, `--test-schedule`),
`tools/check_coop.py` (one script: determinism, structure, refs, vocabulary, tokens, chains, stub
engine for every mode incl. failure paths, negative tests), `tools/build_survival.py`
(`build_mode(..., extra=)` hook used by Roles; survival output unchanged), this file.
