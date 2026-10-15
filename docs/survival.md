# Survival (co-op) and Survival: Zombies

## Kurzfassung (Deutsch)

**Was es ist:** zwei neue Mehrspieler-Karten, „(4) Survival“ und „(4) Survival Zombies“. Ein
oder zwei Menschen verteidigen ihre Stadt gegen 20 Angriffswellen eines Computergegners. Die
Wellen kommen in festen Abständen (erste nach 4 Minuten, danach alle 2½ bis knapp 2 Minuten),
werden größer und steigen von Stufe 1 bis 5 auf. Jede 5. Welle führt ein feindlicher Held an
(Sargon, Nebukadnezar, Germanicus, zum Schluss Julius Caesar und Ramses). Ein Countdown oben
zeigt, wann die nächste Welle kommt. Gewonnen ist, wer nach der 20. Welle alle Feinde besiegt
hat; verloren ist, wenn kein Stadtzentrum der Menschen mehr steht. Zu zweit gibt es pro Welle
50 % mehr Gegner (solange beide ein Stadtzentrum haben), allein entsprechend weniger.

**Zombies (Halloween):** dieselbe Mechanik bei Nacht, nur Nahkämpfer, viel mehr Gegner,
der Minotaurus als Boss (1, 2, 3, dann 4 auf einmal). Optional (Schalter `--zombie-buffs`):
Zombies mit doppelten Lebenspunkten und 40 % langsamer.

**Wie es gebaut ist:** keine Programmänderung, nur Kartendaten. Ich habe das Trigger-Format der
Szenariodateien vollständig entschlüsselt (`docs/scenario-format.md`, alle 76 Original-Szenarien
lesen und schreiben sich bitgenau zurück) und schreibe unsere Trigger in eine Kopie der Karte
„(4) Plains“ aus deiner Installation. Trigger laufen in der synchronen Spielsimulation, also
für beide Rechner gleich.

**Starten:** beide Spieler brauchen dieselben Dateien. Im Lobby-Fenster Karte „(4) Survival“
wählen, Menschen auf Platz 1 und 2 (gleiches Team), **genau einen Computergegner** hinzufügen
(beliebiger Platz, anderes Team), Rest leer. Solo: du plus ein Computer.

**Stand (15.10. abends):** Im Spiel getestet: beide Karten erscheinen in der
Kartenauswahl und laden, Einleitungstext, Wellen-Countdown und Wellen-Meldungen laufen. Zwei
Fehler gefunden und offline behoben: (1) die Einheitengruppen-Nummern waren um 3 verschoben
(man verlor nach 30 s), jetzt fest auf den im Spiel bestätigten Wert; (2) die Wellen erschienen
nicht, weil sie „neben dem Stadtzentrum des Computers“ erzeugt wurden. Das nutzt keine
Originalkarte, und der Computer hatte zu dem Zeitpunkt nichts mehr. Jetzt erscheinen die Wellen
wie in den Originalkarten in einem festen Gebiet (Kartenmitte) und laufen zu euren
Stadtzentren; der Computer wird nur noch über genaue Einheitentypen angesprochen. **Diese
neue Fassung ist offline geprüft, aber noch nicht im Spiel getestet.** Dafür gibt es eine
Diagnosekarte „(4) Survival Probe“, die jede Trigger-Aktion einzeln vorführt (Abschnitt 5a).

---

## 1. Vehicle and why

| option | verdict |
|---|---|
| (a) multiplayer scenario `.scn` with triggers | **chosen.** MP maps are listed from `Data\map scripts\*.rmv` (scanned, unlike the 13 fixed random maps) and every shipped MP map already runs triggers in multiplayer (no-build zones, wine-jug respawn, gold caps, victory by hoarding). Triggers are part of the lockstep simulation. |
| (b) random map script + scripted AI | rejected: `.rmv` random maps have no logic (placement only), the 13 names are fixed in the exe, and the skirmish AI is C++ tuned by numbers only (no way to script timed waves). |
| (c) map scripts referenced by scenarios | not a thing: the scenario-map `.rmv` files only hold `UseMapGenerator` and string ids. |

We do not write a map from scratch: the generator takes the user's own `(4) plains.scn`
(terrain, start positions, its no-build-zone trigger) and appends our trigger system. Only the
trigger chunk, the names and the map id change; every other chunk stays byte-identical
(checked).

## 2. Rules (both themes)

* **Players.** Trigger player groups: humans = "all humans" (enum 3), enemy = "all computer
  players" (enum 4). The mode does not care which lobby slot the computer gets.
* **Start (t = 1 s).** Humans allied with each other and enemies of the computers (mutual).
  The computer's own AI is switched off (AIToggleSetting 0; `--keep-ai` leaves it on), its
  citizens are removed (one object per citizen unit type), its town centre made invulnerable,
  its gold and wood set to 0. A looping trigger repeats this every 20 s. Intro text (20 s) and
  an on-screen countdown to wave 1.
* **Waves.** Wave k fires when the scenario clock passes its time (GameHasAttribute "game
  time > t", one non-looping trigger per wave). Units are created for "all computer players"
  inside a 10x10 area at the map centre (the same "inside area" encoding as all 211 Create
  effects in the shipped scenarios; the centre is equally far from every start corner of the
  symmetric Plains map), set to aggressive and ordered to attack-move to the human town
  centres. Enemy units are addressed by exact unit type, never by unit set. The countdown is
  reset to the next wave. Every 15 s all enemy units are sent again (`--spawn near` restores
  the old placement next to the computer's town centre, which failed in game).
* **Co-op bonus.** A second trigger per wave adds 50 % (separate units) when at least two human
  town centres exist. Solo play therefore gets 2/3 of the 2-player wave.
* **Bosses.** Waves 5/10/15/20 add hero units (RTS-mode hero records) and switch on the
  computer's hero bot AI so they use their powers. Optional `--boss-buffs`: +50/100/150/200 %
  hit points on the boss class.
* **Win.** 10 s after the last wave, when no unit of any wave unit type (roster and bosses) is
  left for 2 s: victory for all humans, then defeat for the computers.
* **Lose.** No human town centre for 3 s (after the first 30 s): defeat for all humans.
  (Not "heroes": hero death is not a lose condition, heroes can be revived.)
* **Unchanged:** economy, the humans' start, tech, standard diplomacy UI.

### Wave table, classic (generated, `python tools/build_survival.py <game> <out> --table`)

Enemy roster: Persian Sword/Spear Infantry, Archer, Sword/Spear Cavalry levels 1-5, War
Elephant (Archer) level 3. Level = 1 + (wave-1)/4. Size = 3 + 1.25k + 0.03k² (solo), x1.5 with
two town centres.

| wave | time | units (2 humans) | composition (level) | boss |
|---:|---:|---:|---|---|
| 1 | 4:00 | 6 (solo 4) | 2 sword, 2 spear (L1) | - |
| 2 | 6:30 | 9 (solo 6) | 4 sword, 2 spear (L1) | - |
| 3 | 9:00 | 11 (solo 7) | 3 sword, 2 spear, 2 archer (L1) | - |
| 4 | 11:30 | 12 (solo 8) | 3 sword, 2 spear, 3 archer (L1) | - |
| 5 | 14:00 | 15 (solo 10) | 4 sword, 3 spear, 3 archer (L2) | Sargon |
| 6 | 17:00 | 18 (solo 12) | 4 sword, 3 spear, 3 archer, 2 cavalry (L2) | - |
| 7 | 19:15 | 19 (solo 13) | 4 sword, 3 spear, 3 archer, 3 cavalry (L2) | - |
| 8 | 21:30 | 23 (solo 15) | 4 sword, 4 spear, 4 archer, 3 cavalry (L2) | - |
| 9 | 23:45 | 25 (solo 17) | 5 sword, 4 spear, 4 archer, 4 cavalry (L3) | - |
| 10 | 26:00 | 27 (solo 18) | 5 sword, 4 spear, 4 archer, 5 cavalry (L3) | Nebuchadnezzar |
| 11 | 28:45 | 30 (solo 20) | 5 sword, 5 archer, 4 spear, 4 cavalry, 2 elephant (L3) | - |
| 12 | 30:45 | 33 (solo 22) | 6 sword, 6 archer, 4 spear, 4 cavalry, 2 elephant (L3) | - |
| 13 | 32:45 | 36 (solo 24) | 6 sword, 6 archer, 5 spear, 5 cavalry, 2 elephant (L4) | - |
| 14 | 34:45 | 39 (solo 26) | 7 sword, 6 archer, 5 spear, 5 cavalry, 3 elephant (L4) | - |
| 15 | 36:45 | 42 (solo 28) | 7 sword, 7 archer, 6 spear, 6 cavalry, 2 elephant (L4) | Germanicus |
| 16 | 39:15 | 47 (solo 31) | 8 sword, 8 cavalry, 6 spear, 6 archer, 3 elephant (L4) | - |
| 17 | 41:05 | 49 (solo 33) | 8 sword, 8 cavalry, 7 spear, 7 archer, 3 elephant (L5) | - |
| 18 | 42:55 | 53 (solo 35) | 9 sword, 9 cavalry, 7 spear, 7 archer, 3 elephant (L5) | - |
| 19 | 44:45 | 57 (solo 38) | 10 sword, 10 cavalry, 8 spear, 8 archer, 2 elephant (L5) | - |
| 20 | 46:35 | 60 (solo 40) | 10 sword, 10 cavalry, 8 spear, 8 archer, 4 elephant (L5) | Julius Caesar and Ramses |

Breather: 150 s between waves 1-5, 135 s to 10, 120 s to 15, 110 s to 20, +30 s after each
boss wave. A full game is about 47 minutes. The final wave switches the sky to "hdri stormy
weather".

### Wave table, zombies

Night sky ("hdri grassland night") from the start, "hdri desert night ocean" for the last horde.
Sword and Spear Infantry only (melee), size x1.4 of classic, first horde at 3:00, breathers
120/110/100/95 s (+30 s after boss hordes), about 39 minutes.

| wave | time | units (2 humans) | composition (level) | boss |
|---:|---:|---:|---|---|
| 1 | 3:00 | 9 (solo 6) | 3 sword, 3 spear (L1) | - |
| 5 | 11:00 | 21 (solo 14) | 8 sword, 6 spear (L2) | The Minotaur |
| 10 | 20:50 | 39 (solo 26) | 14 sword, 12 spear (L3) | 2 x The Minotaur |
| 15 | 29:50 | 60 (solo 40) | 22 sword, 18 spear (L4) | 3 x The Minotaur |
| 20 | 38:20 | 84 (solo 56) | 31 sword, 25 spear (L5) | 4 x The Minotaur |

(Full table: `--table`.) In-game texts are Russian (cp1251, like the stock Russian scenarios) by
default and English with `--lang en`; see section 8.

## 3. Build, install, start

```
python tools/build_survival.py "D:\Games\Rise and Fall" work\overlay-survival [--table]
python tools/check_survival.py "D:\Games\Rise and Fall" work\overlay-survival
```

Writes `Data\scenarios\(4) survival.scn`, `Data\scenarios\(4) survival zombies.scn` and the two
matching `Data\map scripts\*.rmv`. Install = copy `work\overlay-survival\Data` over the working
install's `Data` (new files only, nothing is overwritten). Both players need identical files.
Flags: `--theme classic|zombie|all`, `--template "(4) plains"`, experimental `--boss-buffs`,
`--zombie-buffs` (both off by default until their in-game test passes); `--no-diplomacy` drops the start
diplomacy; `--unitset-base` (default 134, confirmed in game); `--spawn area|near`; `--keep-ai`;
`--test-schedule` and `--probe` (in-game testing only).

Lobby: in-game testing showed that the skirmish and LAN lobbies
only offer scenario maps from a .scn list, so both modes live where players already pick maps.
Map "(4) Survival" / "(4) Survival Zombies", humans in two slots on one team, exactly one
Computer player on another team, standard victory settings. Solo: skirmish with you plus one
computer. More computers = each gets every wave (harder, untested). The `.rmv` entry mirrors
the shipped maps (each scenario map has one); whether the list needs it is not known.

## 4. What a zombie theme needs and what is still missing

Built so far (in the zombie map): night environment, melee-only roster, more units, faster
pacing, Minotaur bosses, own texts, separate lobby entry for a Halloween release.

| need | how / status |
|---|---|
| slow, tanky zombies | `--zombie-buffs`: at 2 s one template unit of each zombie type is created for the computer, `ChangeUnitClassAttribute` hit points +100 % and speed -40 % is applied to its class, then the template is removed. **Unverified** that a class attribute change sticks to units created later; if it does not, the alternative is a per-wave `ChangeUnitAttribute` or a data overlay of dbobjects (global, would need its own records). |
| melee only, many | done (Sword/Spear Infantry L1-L5 of `PERSIAN`; any civ works, Persian keeps one look) |
| night / fog | `.env` files: `hdri grassland night`, `hdri desert night`, `hdri desert night ocean` (fog values live inside the .env). Also available: SetTime / SetDayNightCycle effects and the calamity "Q NightFall(1 shot)". |
| killed units "turn" | no trigger reacts to a single death. Candidates: the calamity **"A-Raise Dead"** (dbcalamity record 5, unit set "A-All Units Affected By Raise Dead") via StartCalamity on the battlefield after each wave; or a looping trigger that re-creates N zombies near the human town per X human losses (PlayerHasResource on the "units lost" counters the campaigns use via `/#PA` tokens). Both need RE of the calamity fields and an in-game test. |
| zombie look | missing: tinted/rotting textures (HD texture pipeline could produce a green/grey variant as new .sst + .udf), groans/footstep sounds (new .sdf/.wav), no new unit records yet |
| boss | Minotaur gladiator (RTS mode record). A bespoke zombie boss would need its own model/texture. |

## 5a. In-game results 2026-10-15 & the fix

| build | result | cause (offline analysis) |
|---|---|---|
| default (`--unitset-base 137`) | maps listed and load, intro and countdown OK, **defeat ~30 s** | "human town centres" selection empty: unit-set class offset is 134, not 137 (all campaign files use 134) |
| `--unitset-base 134` | no early defeat, countdown chains to wave 2, **no wave units**, computer has nothing on the revealed minimap | waves were placed "near the computer's town centre": no shipped scenario ever places units that way, and the unit-set based start clean-up ("A-All Units (Non-buildings...)") evidently also removed the town centre, so there was no anchor |
| current (`ced74ae8` classic, `1db03574` zombies) | probe passes (below); `--test-schedule` classic solo: waves 1-20 announced and chained, Sargon announced at wave 5 and later "defeated", red enemy units reached the town, town centre destroyed -> "Вы проиграли!" at ~6:40. Zombies (test schedule, 200 s): intro, hordes 1-14 chained, Gladiator boss defeated; **daylight, not night**. Win not reached solo without defending (only the probe's Victory(3) step seen) | spawn "inside area" at the map centre (shipped encoding), unit-set base 134, enemy addressed by exact unit types, start clean-up only removes the 4 citizen types |

Round 3 (03:30): win path `--test-schedule --waves 2` (new option) classic solo: both waves announced, town centre held, "Victory: The town stands." then "Вы победили!" ~75 s in -> classic PASSES end to end (waves, boss, lose, win). Zombies still daylight: neither the Environment effect nor replacing the environment name in the terrain chunk (`set_terrain_environment`, chunk 4 length-prefixed "hdri_clearsky_grasslands") changed the lighting; the lighting source for scenarios is still unknown. Attack-move: not changed; in the full test the waves did reach and destroy the town, the first leg went toward the computer corner (shipped TaskToObject targets are mostly placed-unit or area selections, player 7).

### Probe map

`python tools/build_survival.py <game> <scratch overlay> --probe` writes
`(4) survival probe.scn`: solo + 1 computer, watch chat and the map centre (reveal map).

| time | chat | pass reading | if it fails |
|---:|---|---|---|
| 5 s | P1 human: L1 sword at map centre | your own swordsman at the centre | Create/area encoding broken at all |
| 10 s | all computers: L1 spear | enemy spearman at the centre | player group 4 does not create |
| 15-25 s | slot 2/3/4: archer / cavalry / L3 spear | one of them appears = the computer's slot | (informational) |
| 30 s | all computers: L3 sword next to their TC | appears near the computer TC | near placement broken (known) |
| 35 s | 3 elephants at centre | 3 enemy elephants | counts broken |
| 40 s | enemy town centre selection FOUND / EMPTY | FOUND | unit set or TC removed |
| 45 s | computer owns type N (...) | one line per created type | type selections broken |
| 50 s | ordered to attack-move | enemy units walk to your TC | TaskToObject broken |
| 55-60 s | AI off; L5 swords at centre | 2 more enemy swordsmen | AI-off blocks creation |
| 120 s | victory in 3 s | victory screen | Victory(3) broken |

In-game result 2026-10-15 03:00 (solo + 1 computer, reveal map):
5 s PASS (chat line, own unit at centre on the minimap), 10 s PASS (red unit at centre on the minimap, my swordsman died there later: population 5 -> 4 at ~46 s), 15-25 s chat lines shown (slot 2/3/4), 30 s chat shown, 35 s PASS (chat, units at centre), 40 s FOUND, 45 s three type lines (2508 spear, 2414 sword, 61 war elephant), 50 s chat shown, units left the centre toward the top of the map (where the computer town is) rather than visibly toward my town in the first 25 s, 55 s "AI switched off", 60 s L5 swords line shown, 120 s PASS ("Вы победили!").

## 5. In-game tests for the full maps

Run each with the overlay installed in the working install. "Expect" is the pass reading; the
failure line says what it means.

1. **Map appears.** Open the skirmish lobby, map list. Expect "(4) Survival" and
   "(4) Survival Zombies" (name may show as the file name). Failure: not listed → the list is
   not a folder scan or needs a `StringTableID`; try copying our .scn/.rmv over `(4) plains`
   in a scratch install (same slot, our content).
2. **Map loads.** Start solo + 1 computer (Easy). Expect the Plains terrain, intro text after
   1 s, countdown "Wave 1 in : 3:58". Failure: crash/error 0x1bf1 at load → header or trigger
   chunk rejected (check with `python tools/raf_scn.py dump` on the overlay file).
3. **Computer neutralised.** At 0:10 look at the computer's start (reveal map or follow its
   colour). Expect: town centre only, no citizens, TC takes no damage. Failure: citizens remain
   → RemoveUnit/unit set wrong; AI keeps building → AIToggleSetting 0 is not "AI off".
4. **Wave 1 at 4:00** (0:30 with `--test-schedule`). Expect message "Wave 1 of 20 is
   coming!", warning bell, 4 Persian L1 infantry appear at the map centre and walk to your
   town centre. Failure: run the probe map (5a) to see which step breaks.
5. **Countdown chain.** After wave 1 the counter reads "Wave 2 in : 2:29". Pass if it counts
   down to the next wave.
6. **Co-op bonus.** With 2 humans (LAN), wave 1 brings 6 units (4 + 2). Solo brings 4.
7. **Boss wave 5 (14:00).** Expect Sargon (enemy colour) plus message and horn; he uses powers.
   With `--boss-buffs` his HP bar is 1.5x a normal Sargon.
8. **Idle re-attack.** Stand still away from the path; enemies that stopped resume within ~10 s.
9. **Lose.** Delete your town centre (or let it fall). Expect "The town has fallen." and
   defeat 3 s later. Failure: no defeat → the human TC selection never empties (unit set).
10. **Win (fast).** Build with `--test-schedule` into a scratch overlay (wave 1 at 0:30, 20 s
    apart, quarter size, bosses at 1:50/3:35/5:20/7:05, last wave 7:05). Kill everything;
    expect "Victory! The town stands." and the victory screen ~10-15 s after the last enemy dies,
    about 7-8 minutes in. Failure: no victory with no enemies visible → an enemy unit survives
    somewhere (check the computer's TC area) or the army/hero selections never empty. Do not
    ship a `--test-schedule` build (its lobby help text starts with "TEST SCHEDULE BUILD").
11. **Zombie map.** Night sky at 0:01; hordes melee only; with `--zombie-buffs` a zombie
    swordsman L1 has 2x the HP of a normal one and walks visibly slower.
12. **MP sync.** Two PCs, 20+ minutes, no out-of-sync message.

## 6. Limits of the design

* Waves are on a fixed clock, not "next wave when cleared": unkilled enemies stack up.
* The enemy spawns at the map centre (10x10 tiles, a fixed place); the computer's own corner
  stays empty. Terrain at the centre of Plains is not checked for passability (probe map).
* Pop cap of the computer is not raised; if creation hits a cap, waves shrink (probe 4/7).
* Two or more computers multiply every wave (each gets a copy).
* One language per build for the in-game texts (section 8).

More co-op maps built on the same trigger layer (Endless, Boss Hunt, Roles, vs Hard AI):
`docs/coop-modes.md`.

## 7. Files

`tools/raf_scn.py` (format), `tools/build_survival.py` (generator, themes), `tools/check_survival.py`
(all offline checks + stub engine + negative tests), `tools/map_texts.py` (every player-visible
text, ru + en), `tools/map_preview.py` (lobby picture + movie), `docs/scenario-format.md`, this file.
The overlay (`work/overlay-survival`) is generated and not committed.

## 8. Lobby texts, in-game language, lobby pictures (all seven maps)

Applies to the two survival maps and the five co-op maps (docs/coop-modes.md).

### Where the lobby gets name, help and picture (RiseAndFall.exe v1.15, decompile)

| what | source | evidence |
|---|---|---|
| map list | every `Data\map scripts\*.rmv`; keys `UseMapGenerator`, `TextureName`, `StringTableID`, `StringHelpID`, `DisplayHelp`, `DisplayName` | FUN_00bcd8f0 (strings 0xc921d4..0xc9221c, keyword table set up at 0xc41381) |
| name | `StringTableID` -> Language.dll string; else `DisplayName`; default = file name in title case. A missing id falls back to "<Name>.scn" | same function; stock `(4) plains.rmv`: `StringTableID 27032` = "(4) Равнины" |
| help (hover text) | `StringHelpID` -> Language.dll; else `DisplayHelp`. Shown as the map button's help string in the lobby help box (738x153 of 1600x1200, 18 pt) | FUN_00b9e000 -> FUN_00bc8150 (entry +0x60); stock 630 = "(4) /fbРавнины/fd - ..." (stock help texts: at most 311 chars, 2 line breaks) |
| still picture | `textures\<TextureName>` (default = the .rmv name), fallback `textures\DefaultRandomMap` (= `defaultrandommap.sst`, the "?" we saw) | FUN_00bc87d0, string "DefaultRandomMap" at 0xc91f84; stock files `Data\textures\(4) plains.tga` etc.: 256x256, 32 bit, uncompressed, bottom-up, picture in the top-left 212x160 (the lobby uses 2..213 x 2..161) |
| movie | `Movies\<Name>.bik`, fallback `Movies\Random Map Default.bik` | FUN_00bc7ab0 (stock `(4) Plains.bik` ...) |
| parser detail | lines split on blanks and `,`, grouping with `[]` only | FUN_00bcd8f0 tokenizer args `" \t\n,"`, `"[]"`: our old `DisplayHelp (Co-op survival: ...)` would only have shown "(Co-op" |

Text encoding: the game's strings are narrow. `UResourceFile::GetString` uses
`LoadStringA` (LowLevelEngine), i.e. the Windows ANSI code page; this PC runs code page 1251, and
the stock Russian scenarios store cp1251 trigger texts (`(2) gamersday.scn`, the three tutorials,
`scendefault.scn`), which the Russian game shows. So: Language.dll strings for the lobby (UTF-16
in the DLL, converted by Windows), cp1251 bytes for in-game texts. On a PC whose non-Unicode
language is not Russian the whole Russian install shows "?" anyway; not our problem to solve.

### What the builders write now

* `.rmv`: ` StringTableID 2704x` / ` StringHelpID 64x` (ids from `map_texts.string_ids`, names
  27040-27046, help 640-646; free in the stock and the lang-en Language.dll). Test builds
  (`--test-schedule`, `--waves`, probes) write `DisplayName [..]` / `DisplayHelp [..]` instead.
* Language.dll: `raf_patch.build_credits` adds the 14 strings (Russian, English when `lang-en` is on)
  to the generated Language.dll whenever `survival`, `survival-probe` or `coop-modes` is on (it
  generates that DLL even with `credits` off, as for `zoom-setting`). `build_language.Dll.write`
  learned to create the missing string blocks (before, ids outside existing blocks were dropped
  silently; output is unchanged when no new block is needed, test_build_language passes).
* In-game texts: Russian by default (`--lang ru`), English with `--lang en` (byte-identical
  trigger chunk to the earlier English builds, checked). Hero names as in Language2.dll
  (Навуходоносор, Аристандер, Ахиллес, ...), verb agreement (ведет/ведут, пал/пала/пали) and
  Russian plural (1 волну, 2 волны, 5 волн). Allowed bytes: ASCII, newline, Cyrillic 0xC0-0xFF
  (no ё, no typographic dashes/quotes), enforced by `map_texts.encode` and check_survival.
* Pictures: `Data\textures\<map>.tga` = the template's stock picture ((4) plains / (5) babylon) with
  a round badge (survival shield, zombies skull, endless infinity, boss hunt crown, roles two
  figures, roles vs AI the same in red, vs hard AI crossed swords), drawn in pure Python, so it is
  deterministic. Movies: `Data\movies\<Map>.bik` = the template's movie, unchanged (no Bink encoder).
  Both are built from the player's install; textures/movies are outside the fingerprint.

Why not per-language in-game texts: the `.scn` is a gameplay file (fingerprint), and the overlay
cache does not track a language, so `raf_patch` always builds Russian. A group that wants English
in-game texts builds with `--lang en` on every PC (fingerprint then differs from the Russian one).

### In-game tests

1. Apply with `survival,coop-modes` (+ current features). Expect `Language.dll: ...` / `credits:`
   lines and the overlay counts: survival 8 files, coop-modes 20.
2. Skirmish lobby, map list: the seven maps show Russian names ("(4) Выживание", "(4) Выживание:
   зомби", "(4) Бесконечное выживание", "(4) Охота на героев", "(4) Кооп: роли", "(4) Кооп: роли
   против ИИ", "(5) Кооп против сильного ИИ"). Failure "(4) Survival.scn" = the string ids are not in
   the installed Language.dll (check that `credits` overlay was installed).
3. Select each: picture = Plains (Babylon for the 5-player map) with the badge bottom right, not
   "?". Hover the map button: the help box shows the Russian text, bold names, three lines, nothing
   cut off. If the text is cut: shorten in map_texts (help limit 320 chars).
4. Start "(4) Выживание" solo + 1 computer: intro "ВЫЖИВАНИЕ  Удержите город 20 волн...", counter
   "До волны 1 : 3:58", Cyrillic readable in chat and counter (garbage = font has no Cyrillic in that
   place; then build `--lang en`).
5. With `lang-en` on: lobby names/help English, in-game Russian (documented).
6. Watch whether a movie plays anywhere for our maps (the stock maps' movies are used by a lobby
   background, FUN_00bc7ab0); if nothing, it is harmless.
