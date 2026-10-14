# English language pack

Offline only. Nothing here was run in the game. Built and checked offline (see "Verified / not verified").

## Where the text lives (from the Russian install, read only)

| Source | What | Format | Strings |
|---|---|---|---|
| `Language.dll` | pure resource DLL (i386, `.rsrc` + empty `.reloc`, no code). UI labels, key names, tooltips, options, errors, advisor and unit voice lines, hero/tech descriptions | RT_STRING tables, UTF-16, language id 1033 (label only, content is Russian) | 5632 non-empty, 3902 contain Cyrillic |
| `Language2.dll` | pure resource DLL. "Unit & Tech Names": object/unit/building/tech names, many scenario-editor object names, hotkey descriptions | RT_STRING, UTF-16 | 4632 non-empty, 2619 with Cyrillic |
| `Data\scenarios\*-rus.lcl` (25: alex01-12, cleo01-10, tutorial01-03) | campaign and tutorial text: objectives, help, cinematic lines, player names, score-screen labels | text `{Version_0}`, CP1251, CRLF, sections `{N_Kind[:label]}` + body, inline codes (`/r255/g0/b0`, `/fb`, `/fd`, `#PA0697`) | 1720 units (1297 bodies, 423 player/scenario name labels) |

Not text-bearing (checked): `Data\db\*.dat` (balance, internal English names only, no Russian), `Data\user interface\*.xml` (no Cyrillic),
`Language.dll` dialogs/RCDATA (one English dialog `IDD_AUTHENTICATE`, a 4-byte language marker).

Language selection: no registry value or file suffix selects the language. The exe loads `Language.dll` and `Language2.dll`
by fixed name (strings in the exe at 0xc6216c / 0xc617c0; `UResourceFile::GetString`). The `.lcl` runtime lookup was not found
in the decompile (the two `.lcl` references are in the scenario editor); the files are named `<scenario>-rus.lcl`. The pack therefore keeps
every file name identical to the install so it works as a drop-in overlay. Registry `Language Track ID` (=1) is a voice/track
setting, unrelated.

Counts: 3902 + 2619 + 1720 = 8241 translatable units, 6782 distinct Russian texts.

## Known gaps (not covered by this pack)

- `.scn` map headers (all 54 in `Data\scenarios`, 3 tutorials) hold Russian player and civilization names (e.g. "Игрок 2 - Компьютер") in a binary header; the tutorial `.scn` file names are Russian too. Not patched.
- Campaign metadata inside `Alexander.ssa`/`Cleopatra.ssa` (author/description defaults, cp1251).
- Voice-over (mp3 in the .ssa archives, Russian dub) and subtitle timing; textures/bitmaps with painted Russian text (not searched exhaustively; the lobby, load screen and tutorial image I looked at had none).
- `Manual.pdf`, `readme.txt`.
- Fonts: `ROMIC.ttf` lacks `# & + / < = > [ \ ] ^ _ ` { | } ~`; `RAFC.ttf` has full ASCII+Latin-1 but no Cyrillic. English only needs ASCII so coverage is fine, but those ROMIC characters would be blank wherever ROMIC is used. The translations avoid them where the Russian text did not use them.

## Catalog

`work/lang/en.json` (kept outside git, not part of the repo): `{"meta": ..., "strings": {key: english}}`. Key = source location + sha1[:8] of the Russian text, e.g. `Language.dll:24007:ab12cd34`
or `lcl:alex01-rus.lcl:12:body:ab12cd34`. No Russian text in the repo. If the install changes a string, its hash changes, the key
no longer matches, and the build reports it as missing (and, without `--allow-incomplete`, refuses to build).

## Rebuild

```
python tools/build_language.py "D:\Games\Rise and Fall" work\overlay-lang-en
python tools/build_language.py "D:\Games\Rise and Fall" work\overlay-lang-en --check-only
python tools/build_language.py "D:\Games\Rise and Fall" x --update-catalog --check-only --dump-source work\lang-src.json  # new keys for translators
python tools/test_build_language.py
```

The tool parses the resource tree itself, replaces string-table blocks, re-serialises `.rsrc` in the standard layout, moves `.reloc` behind it
and fixes SizeOfImage/data directories. After writing it re-parses every output, compares all non-string resources with the original,
and loads each DLL with `LoadLibraryEx(LOAD_LIBRARY_AS_DATAFILE)` + `LoadStringW` on every id (exact match required).
Validation per string: identical engine tokens in the same order (printf, colour/size/column codes, `/fb /fd /hk0[...]`, bullet textures,
`#PA..` variables), identical newline count, identical leading/trailing spaces, ASCII only, no stray `/`, `/hk` names exist in `dbuihotkey.dat`.

## Installing

Copy the overlay over a working install (never the base install): `Language.dll`, `Language2.dll`, `Data\scenarios\*.lcl`. Back up the originals first
(`tools/raf_patch.py` owns installs; this pack is not wired into it).

## In-game checklist

1. Main menu, options, skirmish setup, multiplayer lobby: text fits buttons, no blank glyphs, key names in the options list.
2. Hover tooltips: unit, building, tech (bullet icons, coloured headings, `/fb ... /fd` bold spans, hotkey brackets shown in green).
3. Train/build tooltips (`Train: /tech ... /res /pop /prereq`): resource and prerequisite lines still filled in.
4. Hero Mode text (hotkey `Toggle Hero Mode`), diplomacy/tribute window (`Alliances & Tribute screen`).
5. Campaign: Alexander 01 and Cleopatra 01 briefings, objectives list, victory/defeat popups, "After Math" score screen (column alignment: `/cw` codes, blank lines).
6. Tutorials 1 to 3: help text, objectives.
7. Scenario editor object palette (G_/R_/E_/P_ prefixed names), unit names on selection.
8. Text that is too long: wraps or overflows on small buttons. List them for a follow-up shortening pass.
9. Names glued to codes (`/fbName`): the engine must still colour them.

## Status

All 8241 units are translated (catalog `work/lang/en.json`, 0 missing, 0 validation errors); 0 Cyrillic left in the rebuilt DLLs and `.lcl` files.
Translation was done in 36 chunks by model translators with a shared guide and glossary, then machine-validated. Names that are only
known from the Russian transliteration (credits, minor captains, places) are best guesses. Official English terms are used where known with
confidence. Output is on average 8 % shorter than the Russian; 118 of 5344 short strings (<= 40 Russian chars) are more than 15 % longer
and are the first candidates if a button overflows.

Special cases found: `/hk0[...]` brackets must name a `dbuihotkey.dat` entry (two Russian ones were translated names, restored to the
English identifiers); one Russian string spells tokens in Cyrillic (`/боец /рес /нас`), restored to `/unit /res /pop`.
The campaign "After Math" screen, tooltips and train/build lines use blank lines for layout: newline counts are enforced.

## Verified / not verified

Verified offline: resource round trip (identity rebuild keeps every string and non-string resource), pefile re-parse of the output, `LoadLibraryEx(AS_DATAFILE)` +
`LoadString` returns exactly the new text for all ids of both DLLs, `.lcl` section count unchanged, unit tests `python tools/test_build_language.py`.
Not verified: that the running exe accepts the rebuilt DLLs (it should, same layout, CheckSum field left 0 as in the original), that it parses the English
`.lcl` text the same way, text fit, glyph coverage, and the `.lcl` file-name rule (see above). Built overlay: `work/overlay-lang-en` (not installed).
