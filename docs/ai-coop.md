# Computer-player attack targeting and ally coordination (RAF-8)

Status: reverse-engineering notes plus ranked patch candidates. Candidate A and the weight-unit fix
are implemented, see section 6.
Sources: `decomp/RiseAndFall.c` (line numbers below), and disassembly of the stock 1.15
`RiseAndFall.exe` (addresses below; read with the capstone/pefile copy in `work/tools/py`).
RTTI vtables come from the `.?AV...@@` type descriptors in the exe. Anything marked
**(hypothesis)** comes from reading the code and has not been checked in game.

## 1. Object map

| object | how to reach it | evidence |
|---|---|---|
| player array | `DAT_0101db18[i]`, count `DAT_0101db70`, index 0 = Gaia | loop in FUN_004ce870 (line 133897) |
| player index | `player+0x474` | used as the array index everywhere, e.g. line 133901 |
| computer player | `player+0xdf8` is non-zero only for AI players and is what the game treats as the `EEComputerPlayer` (vtable `0xc52054`). Code such as line 145377 and line 66779 uses `[player+0xdf8]` as "is AI / get CP". For an AI the player object and the CP are the same object (offsets like `+0x1238` and `+0xa74` are read on the same pointer, lines 133901 and 134067) **(hypothesis: `+0xdf8` points to the object itself)** | FUN_004138a0 (line 10940) returns it |
| combat manager `EECPCombatManager` (vtable `0xc5355c`) | `CP+0x10e8` | ctor FUN_004d1aa0 (line 135854); CP update calls `FUN_004d0510` with `ecx=[esi+0x10e8]` at `0x47d8f2..0x47d8f9` |
| attack commander `EECPAttackCommander` (vtable `0xc52570`) | `combat+0xc4` | ctor FUN_0048ff30 (line 92489) stored at `in_ECX[0x31]` (line 135947) |
| defense commander `EECPDefenseCommander` (vtable `0xc53610`) | `combat+0xc8` | ctor FUN_004dcbf0 (line 142791), stored at `in_ECX[0x32]` (line 135955) |
| intelligence (per-player files) | `combat+0xcc`, a map from player index to `EECPIntelligencePlayerFile` | FUN_0049b390 (line 100004), lookups in FUN_004ce870 at `0x4ceadd..0x4ceb16` |
| combat manager back pointer to CP | `combat+0xc0` | FUN_004d1aa0 `in_ECX[0x30] = param_1` |

### 1.1 "Is player X allied with me?"

- Diplomatic stance: `int stance[...]` at `player+0xe30`, indexed by the other player's index:
  `[me + 0xe30 + X->index*4]`. `0` = allied, non-zero = not allied (enemy is 1). The setter is
  `FUN_007c0a70(other, stance, mutual, notify)` (line 584036), which writes `in_ECX[idx + 0x38c]`
  (0x38c*4 = 0xe30) at lines 584130 and 584152. Stance is one-sided; mutual alliances also update
  the ally list below.
- Ally list: a vector of player pointers at `player+0xa74` (begin) / `+0xa78` (end), with the
  count cached at `+0xa80`. `FUN_007bbbc0` (line 580423) adds an ally, `FUN_007b89a0` (line 578465)
  removes one. `FUN_007c0a70` calls both only when both sides are allied (AddAlly at line 584089, RemoveAlly at line 584128). The out-of-sync dump prints the list: `FUN_007bcf60`, line 581509,
  "Allied Player %6d is player number". The list can contain the player itself; code that walks it
  skips self (line 132151).
- Defeated / resigned: `player+0x47f` and `player+0x107b` are non-zero for players to skip
  (FUN_004ce870 lines 133902-133903, FUN_004cbe70 line 132377) **(hypothesis: defeated and
  resigned)**.
- Human or AI: the virtual at `vtable+0x8c` returns false for `EEComputerPlayer` (`0x4773c0`:
  `xor al,al; ret`), so it is "is human". The same test is `[player+0xdf8] != 0` for AI.

So "is X my ally" is `[me+0xe30+X.idx*4] == 0` (one-sided) or "X is in `me.allies[]`" (mutual).

### 1.2 "What is ally Y currently attacking?"

Every attack wave is an `EECPAttackGroup` (vtable `0xc52718`, 0x70 bytes, ctor FUN_0049b4c0 at
line 100079). `FUN_00490020(task, kind)` (line 92556) is the attack commander's "create group":
it allocates the group, copies the task into `group+0x2c` (`lea ecx,[edi+0x2c]; call 0x47e2c0` at
`0x49007f`), and pushes the group into the commander's deque (`FUN_0048e330` on `commander+4`,
`0x490295..0x4902a1`). If the group got no units it is deleted instead (line 92684 pushes, line 92687 deletes).

Task `EECPAGTask` (vtable `0xc5219c`, ctor FUN_0047e0e0 at line 81166, copy FUN_0047e2c0 at line 81261):

| task offset | group offset | meaning |
|---|---|---|
| +0x04 | +0x30 | embedded `EECPILocation` (vtable `0xc52188`) |
| +0x1c | +0x48 | ref-counted target unit (counter-attack path, line 134198) |
| **+0x20** | **+0x4c** | **target player** |
| +0x28 / +0x2c | +0x54 / +0x58 | task kind: 0/0 normal wave (FUN_004ce870), 7/3 counter-attack (line 134205), 0xc/3 retaliation (FUN_004cb6a0 lines 132031-132032) |
| +0x30 | +0x5c | byte, 1 on counter-attack and retaliation |

Other group fields: `+0x60` = owning attack commander (the commander's `+0x18` is the CP),
`+0x64` serial number, `+0x6e` byte set to 1 when the group is disbanded (FUN_0049b5e0, line 100183).
The target can change during the attack: FUN_0049d550 (line 101557) rewrites `group+0x4c`;
FUN_0049b5e0 (line 100158) disbands every group whose `+0x4c` matches a given player (called from
the commander via FUN_00490300).

Deque layout (VC6 `std::deque<EECPAttackGroup*>`, 1024 pointers per block), from the destructor
FUN_0048ff80 (line 92513): `commander+0x08` block map, `+0x0c` map size, `+0x10` first offset,
`+0x14` element count. Element `i`: `b = (off+i) >> 10; if (b >= mapsize) b -= mapsize;
group = map[b][(off+i) & 0x3ff]`.

So, for an ally `Y` with `cp = [Y+0xdf8] != 0`: `cmd = [[cp+0x10e8]+0xc4]`; for every group `g` in
the deque with `g != 0` and `byte [g+0x6e] == 0`, `[g+0x4c]` is a player Y is attacking right now.
Human allies have no such state (see section 5).

## 2. How the AI picks the player to attack

The attack decision is `FUN_004ce870` (`0x4ce870`, line 133768), a combat-manager method called
every AI tick from the combat-manager update `FUN_004d0510` (line 135079, call at line 135135),
which the CP update calls at `0x47d8f9`.

1. **Gate.** Returns unless the home position (`[[CP+0x10ec]+0x40]+0x144/0x148`) is set and
   either the attack timer is due, `FUN_00466270(now)` (line 67324: `CP+0x148c != 0 &&
   CP+0x1468 <= now`), or the counter-attack flag `combat+0xec` is set (lines 133893-133895,
   `0x4ce9ad..0x4ce9c4`). At the end `FUN_00469480(now)` (line 69085) schedules the next attack
   from AttackFrequency (line 134215).
2. **Enemy list.** For every player `1..count-1` that is not null, not the CP itself, has
   `stance != 0` towards it (`cmp [eax+edx*4+0xe30], 0` at `0x4ce9ff`), and is not defeated or
   resigned, the enemy goes into a human list or an AI list depending on `vtable+0x8c`
   (`0x4cea1a..0x4cea40`, lines 133897-133909).
3. **Human or AI target.** `p = AIvsAIPercentage / 100` (`CP+0x111c`, id 91, set at line 72030; read at
   line 133882). If both lists are non-empty, `r = URandom::Generate()` (lockstep RNG
   `DAT_0101cb8c+0x18`, value in `[0,1)`) picks the AI list when `r < p`, otherwise the human list.
   With only one list, that list is used (`0x4cea50..0x4cea92`, lines 133910-133917).
4. **Candidates.** For each enemy in the chosen list it gets (or creates) the enemy's
   `EECPIntelligencePlayerFile` and refreshes it (`FUN_004ea280(CP,1,0)`), building the candidate
   vector at `[esp+0x48]`, count `[esp+0x54]` (`0x4ceac0..0x4ceb48`). File fields used: `+0x40..+0x4c`
   building bounding box, `+0x50` the player, `+0x8c` a score used by the counter-attack branch,
   `+0xa0..+0xb0` five resource amounts **(hypothesis: resource amounts the AI has seen)**.
5. **Normal mode (`combat+0xec == 0`, line 133946 onward):** three candidates are computed.
   - *Close* `local_fc` (`[esp+0x1c]`): among candidates that share a region with the AI's own
     presence (`FUN_004c09a0` + `FUN_004ce620` count units of both owners, lines 133984-134008),
     the one with the largest bounding box (line 134007). If none qualifies, the candidate whose
     bounding-box centre is nearest to the AI's own (lines 133952-133971, test at line 133966). Because the fallback always takes
     the first candidate, **Close is never empty when there is any candidate.**
   - *Resource* (`ebp` at `0x4cf14d`, `local_d8`): candidates holding one of five resources that
     the AI needs (`[[CP+0x10ec]+0x3c]+0x164[k] > 0`) and has none of itself (lines 134017-134050).
     The exact tie-break was not decoded fully **(hypothesis: smallest positive amount)**.
   - *Revenge* (`esi`): the candidate with the largest `CP+0xf00[enemy.idx]` (read at line 134059,
     `0x4cf0f0..0x4cf11e`). `player+0xf00[i]` is increased by `FUN_007ab7b0(i, amount)` (line 569205),
     which the CP's "attacked by" virtual FUN_00469090 (line 68983, vtable slot `0xc520f4`) calls, so it is
     the damage or hostility received from player `i` **(hypothesis on the unit)**.
   - Weights: `C = CP+0x1238` (AttackChoiceProbabilityClose), `C+R` with `R = CP+0x123c`
     (Resource); Revenge (`CP+0x1240`) is stored and saved but never read here, it is the
     remainder. `r = URandom::Generate()`; `r <= C` -> Close, `C < r <= C+R` -> Resource,
     `r > C+R` -> Revenge, with fallbacks when a candidate is missing (lines 134067-134105,
     `0x4cf120..0x4cf1f4`).
   - The chosen player goes into the task: `mov [esp+0xec], eax` at `0x4cf1fb` (task at `esp+0xcc`,
     `+0x20`), then `FUN_00490020(&task, 0)` on `[combat+0xc4]` at `0x4cf202..0x4cf216` (line 134106).
6. **Counter-attack mode (`combat+0xec != 0`, lines 134108-134213):** set by FUN_004cbe70
   (line 132365, `in_ECX+0xec = 1` at line 132383) when the AI is attacked. Picks the candidate with
   the largest file `+0x8c` (line 134115), finds a target building near the AI's home position, and creates a
   group with task kind 7/3 (`0x4cee08..0x4cee35`), then clears the flag.

**Stock quirk (affects tuning, not this ticket):** the weights are stored as integers (stock 70 / 20 / 10,
formats.md 3.4) and compared with a float in `[0,1)` (`fild dword [esp+0x20]` vs `fld [esp+0x10]`
at `0x4cf15f..0x4cf171`; the same RNG is compared with 0.15, 0.7, 0.8 elsewhere, e.g. lines 82379
and 100337). `r <= 70` always holds, and Close always exists, so **stock AIs always attack the
"close" enemy**. Resource and Revenge are effectively dead unless Close is set to 0 in
`dbcpbehavior.dat`.

## 3. What AllyTimer does

`AllyTimerEasy/Medium/Hard` (dbcpbehavior id 4) are stored as minutes x 60000 at `CP+0x1224 /
+0x1228 / +0x122c` (FUN_004701a0 lines 71996-72006). The only getter is `FUN_00465a30` (line 66981):
it picks or interpolates by difficulty like the other timers. Its only caller is `FUN_004ed420`
(line 153689; call at line 153808).

`FUN_004ed420` belongs to `EECPMilitaryAidPackage` (vtable `0xc535f4`, ctor FUN_004ebdc0 at line 152697):
a defence package the defense commander creates for a threatened town. Fields: `+0x20` own CP,
`+0x24` the player who owns the town, `+0x2c` the town, `+0x30` state, `+0x38` earliest time of the
next dispatch. The state machine `FUN_004ed940` (line 153934) runs the per-state handlers
FUN_004ed710 / FUN_004ed7a0 / FUN_004ed830, which compare the town's jeopardy with
MinimumJeopardyLevelOfTown (`CP+0x1198`, id 69, line 72524) and call FUN_004ed420 to send troops.
After a dispatch, FUN_004ed420 sets `+0x38 = now + delay` (lines 153797-153811, AllyTimer call at line 153808), where

- `delay = AllyTimer` if the town owner `+0x24` is set and is **human** (`[owner+0xdf8] == 0`),
- `delay = TownGuardUpdateTime` (`FUN_00466970` / deathmatch `FUN_004669e0`, `CP+0x13fc..+0x1410`,
  id 114/115, lines 72728-72738) for its own towns and for AI allies' towns.

The packages for other players' towns come from the defense commander
(`FUN_004e0ac0` -> `FUN_004e03a0`, line 145336, called at line 145720): it copies the ally list
(`CP+0xa70`), shuffles it with the lockstep RNG, skips itself and AI allies whose DifficultySlider
(`allyCP+0x1114`, formats.md 3.4) is below 4, and creates an aid package for an ally's town when
the town's jeopardy is above the minimum or the owner is allied (always true for entries of the ally
list) and troops are available (`FUN_004dde50() > 0`) (condition at line 145403, package owner set at line 145413).

**Meaning:** AllyTimer is the cooldown, in minutes, between two military-aid dispatches to the same
threatened town of a **human** ally. The AI already defends allies. It does not coordinate
**attacks**: nothing in FUN_004ce870 reads the ally list or another CP's attack groups.

## 4. Patch candidates (ranked)

All three share the rules of the target-priority patch (`tools/test_target_priority.py`): exe code
cave plus a 5-byte `jmp`, integer-only code, no RNG draws, no allocation, only simulation state.

Determinism notes for all candidates:
- They only read lockstep state (player array, stance array, ally vectors, other CPs' attack
  commanders), which every peer holds in the same order. The ally vector order comes from
  stance-change commands, so it is the same on every peer.
- They do not change the number of `URandom::Generate` calls (the draws at `0x4cea6b` and
  `0x4cf143` still happen), so the RNG stream after the decision stays the same as stock.
- They add no saved state, so save games stay compatible both ways.
- Risk: a patched and an unpatched peer in the same MP game will go out of sync as soon as the
  choice differs. The patcher must ship it like the other exe patches (all peers equal, part of the
  version check). Replays or saves recorded with the patch off and replayed with it on will diverge.

Cave: the `.RDATA` zero tail already holds click-fix (`0xCE3880..0xCE38AD`), zoom-setting
(`0xCE3980..0xCE3B92`) and target-priority (`0xCE3C00..0xCE3E53`). In the stock exe, raw dwords
point at `0xCE3934`, `0xCE3C8C`, `0xCE3E8C` and `0xCE3F81` (found by a scan of the whole image;
probably coincidental data). Proposed: **`0xCE3E90..0xCE3F7F` (240 bytes)**, which avoids all four.
The same "zero / RWX / unreferenced" static check as target-priority must confirm it.

### Candidate A (recommended): override the final target with an ally's current target

- **Site:** `0x4cf1fb  89 84 24 EC 00 00 00  mov [esp+0xec], eax`, the single store of the chosen
  player into the task in normal mode. The five branches to it (`0x4cf17b`, `0x4cf1ad`, `0x4cf1c5`,
  `0x4cf1e9`, `0x4cf1f2`) land on the first byte, and no branch targets `0x4cf1fc..0x4cf201`.
  Replace it with `jmp cave` plus 2 `nop`, and return to `0x4cf202` (`8B 44 24 34 mov eax,[esp+0x34]`).
- **Original logic:** `eax` = Close / Resource / Revenge pick (in stock practice always Close).
- **Proposed logic** (cave, `esp` unchanged by the jump):
  ```
  if byte [FLAG] == 0: goto store
  pushad                                  ; stack offsets +0x20 below
  me  = [[esp+0x20+0x34] + 0xc0]          ; combat manager -> CP
  for a in me.allies[ [me+0xa74] .. [me+0xa78] ):
      skip a == 0, a == me, byte[a+0x47f] != 0, byte[a+0x107b] != 0
      cp = [a+0xdf8];  skip cp == 0                    ; human ally: no attack state (v1)
      cmd = [[cp+0x10e8] + 0xc4];  skip cmd == 0
      for i in 0 .. [cmd+0x14]-1:
          k = [cmd+0x10] + i;  b = k >> 10;  if b >= [cmd+0x0c]: b -= [cmd+0x0c]
          g = [[ [cmd+0x08] + b*4 ] + (k & 0x3ff)*4]
          skip g == 0 or byte[g+0x6e] != 0
          t = [g+0x4c];  skip t == 0 or t == me
          skip [me + 0xe30 + [t+0x474]*4] == 0         ; must be my enemy too
          skip byte[t+0x47f] != 0 or byte[t+0x107b] != 0
          [esp+0x1c] = t ; goto done                   ; overwrite saved eax (first match wins)
  done: popad
  store: mov [esp+0xec], eax ; jmp 0x4cf202
  ```
  First match in (ally list order, deque order) keeps it deterministic and cheap. A later variant
  can count groups per target and take the most-attacked one (still integer-only).
- **Why here:** timing (AttackDelay / AttackFrequency), group size and composition are untouched;
  only the target player changes, and only when an AI ally has a live group. The counter-attack
  branch (`combat+0xec`) is not touched, so a directly attacked AI still hits back at its attacker.
  The target need not be in the candidate list (the AIvsAI split may have picked the other list),
  which is intended: joining the ally beats the human/AI coin flip. `FUN_00490020` only needs the
  player pointer in the task; the group then picks buildings itself (FUN_0049d550 / FUN_0049bfa0).
- **Size estimate:** about 130-170 bytes of code plus a 1-byte flag (fits the proposed cave).

### Candidate B: replace only the Close candidate

- **Site:** `0x4cf120  8B 4C 24 28 / 8B 81 38 12 00 00` (`mov ecx,[esp+0x28]; mov eax,[ecx+0x1238]`,
  10 bytes) just before the weight roll. The cave runs the same ally scan, but only accepts `t` if
  it is in the candidate vector (`[esp+0x48]`, count `[esp+0x54]`, file `+0x50 == t`), then writes the
  file into `[esp+0x1c]` (Close). Re-executes the two moved instructions and returns to `0x4cf12a`.
- **Difference to A:** keeps the AIvsAI split, the candidate filter and the C/R/Revenge structure. In
  stock data the roll always picks Close, so the visible result equals A whenever the ally target is
  in the chosen list, and does nothing otherwise. Better choice if the weight units are fixed later
  (section 2 quirk), because the ally preference then becomes part of the Close share.

### Candidate C (follow-up, not first version): treat an ally being attacked like being attacked

- **Site:** `FUN_004cbe70` (line 132365), which sets `combat+0xec` when the AI itself is attacked.
  A hook in the CP's "attacked by" virtual (FUN_00469090, line 68983, vtable `0xc520f4`) could also
  set `combat+0xec` on the AI allies of the attacked player. Wider effect (counter-attack groups,
  retaliation tasks, the `FUN_0050a5d0` alerts at lines 132152-132155), so more MP risk and harder to
  test offline. Listed for completeness.

### Offline test plan (pattern of `tools/test_target_priority.py`)

1. Static: stock bytes at `0x4cf1fb` (`89 84 24 EC 00 00 00`) and `0x4cf202` (`8B 44 24 34`), no
   branch into the hook tail, whole instructions, cave zero / RWX / unreferenced, generated bytes
   equal to the `raf_patch` tuple, cave disassembles completely.
2. Unicorn emulation of the cave with fake memory: stack with `[esp+0x34]` -> combat -> CP, player
   objects with `+0x474`, `+0x47f`, `+0x107b`, `+0xe30[]`, `+0xa74/+0xa78`, `+0xdf8`, CP `+0x10e8` ->
   combat `+0xc4` -> commander deque with groups. Cases: flag off; no allies; human ally only;
   ally group targeting my enemy (replaced); target allied to me (kept); target defeated (kept);
   group with `+0x6e = 1` (skipped); deque with offset near 1024 and map wraparound; two allies (first
   wins); empty deque; all registers except `eax` preserved and `esp` unchanged on return.
3. Apply / re-apply / revert byte-exact on an exe copy together with click-fix, zoom-setting and
   target-priority.
4. In game (later): 2v2 skirmish (AI+AI vs two enemies far apart). Read each AI's groups through
   the offsets above (players at `0x101db18`) and check that the second AI's new groups take the
   first AI's target. Also a 2-player MP game with both peers patched (no OOS), and one with a
   mismatch (expect OOS, confirming the version check matters).

## 5. Open points

- Human allies: they have no attack groups. A rough proxy is the enemy's `+0xf00[ally.idx]`
  (damage the enemy took from the ally), but it is cumulative, not "current" **(hypothesis)**.
  Not part of the first version.
- `player+0xdf8 == player` for AIs is assumed, not proven; the patch uses `[a+0xdf8]` the same way
  the game does, so it does not depend on it.
- The exact Resource tie-break and the meaning of intelligence file `+0x8c` are not decoded.
- Whether a group stays in the deque while it walks home after the fight (it then still counts as an
  "attack" on `+0x4c`). The `+0x6e` test removes disbanded ones only.
- The weight-unit quirk (section 2) is a separate tuning bug. It is fixed by its own feature
  `attack-choice-fix` (section 6), which changes stock AI behaviour on purpose.

## 6. Implemented

Two exe features in `tools/raf_patch.py`, both default on, both on the simulation path, so each
mixes its own mark into the gameplay fingerprint while installed (`ALLY_ATTACK_MARK`,
`ATTACK_CHOICE_FIX_MARK`; `tools/build_installer.py` adds them to the expected release fingerprint).
Generated and tested offline by `tools/test_ai_coop.py` (static checks, unicorn emulation of both
caves, apply / re-apply / revert with click-fix, zoom-setting, target-priority and naval-ai).
Cave region `0xCE3E90..0xCE3F7F` was confirmed zero, in the RWX `.RDATA` tail and unreferenced by
any raw dword of the stock image (the stray values sit at `0x10d1add` -> `0xCE3E8C` and
`0xd08816` -> `0xCE3F81`).

### `ally-attack` (candidate A)

- Hook `0x4cf1fb`: `89 84 24 EC 00 00 00` -> `E9 90 4C 81 00 90 90` (`jmp 0xCE3E90`).
- Cave `0xCE3E90..0xCE3F69` (218 bytes), the logic of section 4 candidate A. It ends with the
  original `mov [esp+0xec],eax` and `jmp 0x4cf202`.
- Differences to the pseudocode in section 4:
  - No runtime flag byte: the feature toggle is the patch itself.
  - The ally vector is walked from begin to end (`+0xa74..+0xa78`); the cached count `+0xa80` is
    not used.
  - A group must also have units (`[g+8] != 0` and `[g+8] != [g+0xc]`), the same liveness test the
    commander uses before it erases a group from the deque (FUN_0048fa70, line 92280). That cleanup
    runs only every 45 s, so a group that lost all its units would otherwise still attract allies.
  - Defeated / resigned allies are skipped, as in the pseudocode.
- Offsets checked against the disassembly: `[esp+0x34]` is the combat manager at the store
  (`0x4ce87c..0x4ce889` saves `this` there; `0x4cf202` and `0x4cf21b` read it), `combat+0xc0` is
  the CP and the CP is the player object (the stance test at `0x4ce9ff` reads `[CP+0xe30+idx*4]`),
  `cp+0x10e8` is the combat manager (`0x47d8f2`), the deque layout matches the destructor
  FUN_0048ff80, the cleanup FUN_0048fa70 and push_back FUN_0048e330 (called with `ecx =
  commander+4`), and `[esp+0x28]` must not be used for the CP at the store because `0x4cf132`
  overwrites it with Close+Resource.

#### Object lifetime (use-after-free review)

Question: can the cave read a CP, combat manager, attack commander or group that was freed because
an ally was defeated, resigned, left the game or lost its AI? Result: no. None of these objects is
freed on those events. The cave needed no change for this. Evidence (stores found by a capstone
sweep of the whole code range `0x401000..0xC4A000`, deletes by decomp search and by a disassembly
scan for "load `[reg+off]`, `push 1`, `call [reg]`"):

| object | created / pointer written | freed | freed on defeat / resign / leave? |
|---|---|---|---|
| CP = player object, `+0xdf8` | `+0xdf8` is written only by the constructors: `0x47c423` / `0x47c4a7` (EEComputerPlayer ctors FUN_0047c3a0 / FUN_0047c430, lines 79863 / 79894: `= this`) and `0x7c9ca6` / `0x7ca30a` (base player ctors FUN_007c9640 / FUN_007c9cd0, lines 590476 / 590751: `= 0`). The only other store, the setter at `0x4685a0`, has no call, jump or pointer referencing it. The other hits (`0x704f0c`, `0x7092b7`, `0xb20...`) are other classes. | scalar dtor `0x478600` -> FUN_00477240 (line 77049), referenced only from vtable `0xc52054` slot 0 | no. `+0xdf8` never changes after construction, so there is no AI takeover by swapping the CP pointer and no "AI off" by clearing it |
| combat manager `cp+0x10e8` | `0x47bc96` (CP init FUN_0047ba30, line 79591) and `0x477d0e` (CP reset FUN_00477c80, vtable `0xc52054` slot 8, line 77584) | only FUN_00477240 (CP dtor, line 77093) and FUN_00477c80 (line 77575). The reset deletes the old manager and stores the new one in the same function, and the new manager starts with an empty commander | no |
| attack commander `combat+0xc4` | only the combat ctor FUN_004d1aa0 (line 135947) | only the combat dtor FUN_004d1890 (line 135792). The other `[reg+0xc4]` deletes (`0x7e572c`, `0x83c645`, `0x85724a`, `0x86ba54`) are destructors of unrelated classes | no |
| attack group (deque element) | pushed by FUN_0048e330 (FUN_0048f740 line 92197, FUN_0048f9c0 line 92242, FUN_00490020 line 92684) | FUN_0048fa70 (line 92294) erases the element from the deque before the delete. FUN_00490370 (line 92757) moves the deque into a local copy and sets the count to 0 before deleting. FUN_0048f740 / FUN_0048f9c0 / FUN_00490020 (lines 92212 / 92246 / 92687) delete only groups they never pushed. The commander dtor FUN_0048ff80 (line 92534) deletes the groups, then sets the count to 0 and frees the map | no. A disbanded group only gets `+0x6e = 1` (FUN_0049b5e0, line 100183) |

- Defeat and resign only write flags. `+0x47f`: setter FUN_006e13b0 (`0x6e13b4`, line 464779),
  FUN_007d5bf0 (`0x7d5c39`, init), game setup FUN_006e4c40 (`0x6e5b21`, closed slots). `+0x107b`:
  `0x6e1524`, `0x6e6670`, `0x7c2c45`, `0x7e9e83`. None of these frees anything.
- RemoveAlly FUN_007b89a0 (line 578465) only erases the pointer from `+0xa74..+0xa78` (and
  `+0xa10`). It frees nothing. The cave walks the vector as it is at the moment of the call.
- The stock game itself trusts the same lifetimes. The defense commander FUN_004e03a0 (lines
  145362-145377) walks a copy of the ally list and reads `[ally+0xdf8]+0x1114` without any defeat
  check. The retaliation code FUN_004cb6a0 (lines 132148-132152) walks the ally list. The CP
  scheduler FUN_00463630 (lines 66777-66783) dereferences every player slot `0..count-1` with no
  null check. If a player object were freed mid-game, stock code would already fault.
- Order inside the cave: ally null / self / `+0x47f` / `+0x107b` are tested before `+0xdf8` is read;
  `+0xdf8`, `+0x10e8` and `+0xc4` are null-checked; the deque is indexed only below its count; a
  group's unit vector is compared and never dereferenced; the target player is read only for
  `+0x47f`, `+0x107b`, `+0x474` (player objects live as long as the game).
- Threading: the cave runs inside the CP update (`0x47d8f9`) on the lockstep simulation thread, the
  same thread that runs the reset, RemoveAlly, defeat and group cleanup, so it never sees the
  state between a delete and the store that follows it (e.g. inside FUN_00477c80).
- `tools/test_ai_coop.py` covers these paths with an unmapped address standing in for freed
  memory: defeated / resigned ally with a freed CP pointer, human ally with garbage behind
  `+0x10e8`, ally erased from the vector (also from the front), CP reset with a fresh combat
  manager, commander with count 0 and a freed map, freed group in a slot past the count, and a
  control case that shows a real read of that address faults.
- Not proven statically: who calls the player scalar dtor (the player array `0x101db18` is filled
  by code the sweep did not find, probably a member of the global at `0x101daa8`, array at
  `+0x70`, count at `+0xc8`), and whether the StarForce-wrapped sections hide more code. The stock
  ally-list readers above would fault on the same paths.
- Behaviour, not memory: `CP+0x149b` marks a CP-class player in a human slot (set only in game setup
  FUN_006e4c40, line 468209; cleared in CP init, line 79563). FUN_00463630 then leaves it out of the
  AI updates. The cave does not test it. Such a player's deque is normally empty. If it held groups
  from a save, their targets would be stale but still valid memory.

### `attack-choice-fix`

- Hook `0x4cf143`: `FF 15 C0 A3 C4 00` (`call [URandom::Generate]`) -> `E8 28 4E 81 00 90`
  (`call 0xCE3F70; nop`).
- Cave `0xCE3F6C`: `00 00 C8 42` (float 100.0), then `FF 15 C0 A3 C4 00` (`call [0xc4a3c0]`),
  `D8 0D 6C 3F CE 00` (`fmul dword [0xCE3F6C]`), `C3` (17 bytes, ends `0xCE3F7C`).
- `r` becomes `100 * Generate()` in `[0,100)` before the stock `fstp [esp+0x10]`, so the stock
  compares `r <= C` and `r <= C+R` work in percent: with stock 70 / 20 / 10, Close 70 %, Resource
  20 %, Revenge 10 % when all three candidates exist. The stock fallbacks stay (no Resource
  candidate: Close up to C+R, then Revenge; no Close: Resource; none: `[esp+0x90]`). Revenge
  (`CP+0x1240`) is still not read; it stays the remainder.
- Same single RNG draw (`0x4cf143`), so the RNG stream is unchanged. `r` (`[esp+0x10]`) is only read
  by the weight compares `0x4cf169..0x4cf1d7`. Wrapping the call instead of hooking `0x4cf149` keeps
  the hook to one whole instruction and leaves the `test ebp,ebp` flags at `0x4cf14d` alone.
- Determinism: one extra x87 multiply on lockstep state; the stock code already compares the same
  RNG value in x87, so peers with the same exe and FPU mode get the same result.

Not tested in game yet (section 4 offline test plan step 4 is still open).
