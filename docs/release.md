# Releasing a remaster version

The installed remaster updates itself from GitHub Releases: the launcher `RaF Remaster.exe` (in the
game folder, target of every shortcut) asks
`https://api.github.com/repos/VlexWest/raf-remaster/releases/latest` and offers a newer `vX.Y.Z` to the
player. Nothing is installed without the player's click.

## 1. Bump the version

`tools/raf_version.py`:

```python
VERSION = "1.0.1"          # semantic version, no "v"
UPDATE_REPO = "VlexWest/raf-remaster"
```

That one constant ends up in REMASTER.txt, state.json, install.json, the credits / loading screen
line, the uninstall entry and the launcher's comparison. The release tag must be `v` + VERSION.

Bump the patch for fixes, the minor for new features. If the gameplay fingerprint changes (anything
in Data/db, scenarios, map scripts, random map scripts or unit AI), say so in the release notes:
all players of a network game need the new version.

## 2. Build

```
python tools/run_stub_tests.py          # all stub tests
python tools/build_installer.py         # dist/RaF-Remaster-Setup.exe + .sha256, content scan must say CLEAN
python tools/e2e_update.py              # optional, ~10 min: install + update a scratch copy offline
```

`dist/RaF-Remaster-Setup.exe.sha256` holds `<sha256>  RaF-Remaster-Setup.exe`. The launcher refuses
a download whose hash it cannot verify against this file (or a `sha256: <hex>` line in the release
text).

## 3. Publish

```
gh release create v1.0.1 dist/RaF-Remaster-Setup.exe dist/RaF-Remaster-Setup.exe.sha256 \
    --title "Rise and Fall Remaster 1.0.1" --notes-file notes.md
```

- The asset names must stay exactly `RaF-Remaster-Setup.exe` and `RaF-Remaster-Setup.exe.sha256`.
- The first ~900 characters of the notes appear in the update dialog (markdown marks are stripped);
  put the player-facing changes first, in plain words.
- Only full releases count: drafts and pre-releases are not returned by `releases/latest`.
- Stable download link for the newest setup (websites, other launchers):
  `https://github.com/VlexWest/raf-remaster/releases/latest/download/RaF-Remaster-Setup.exe`
  (and `.../RaF-Remaster-Setup.exe.sha256`).

**While the repository is private** the API answers 404 without authentication: every launcher
treats that as "no update" and starts the game silently. Updates only reach players once the
repository (or at least its releases) is public.

## What the player sees

- Launcher start: one API request on every start (3 s timeout), so "Update now" always gets the
  newest release. The result is recorded in `<game>/.raf-remaster/update-cache.json`. Offline,
  403/404 or any error: the game just starts.
- Newer release: dialog "Version X available (installed Y)", the release notes, installed version +
  gameplay fingerprint, buttons **Update now / Later / Skip this version** (Later = ask again after
  6 h, Skip = never for this version). Language from the install (ru/de/en).
- Update now: the setup downloads to `%TEMP%\RaF-Remaster-Update` with a progress window (https only,
  size checked against the release, sha256 checked), the launcher starts it with
  `--update "<game dir>"` and exits, the setup shows its own progress window and starts the game
  afterwards with the original arguments (Host/Join keep working).

## How the update works (and rolls back)

`RaF-Remaster-Setup.exe --update <dir>` (tools/raf_installer.py `run_update`):

1. waits for the launcher to exit; refuses while `RiseAndFall.exe` / `RaF Remaster.exe` from this
   folder runs (Retry / Cancel);
2. reads `<dir>/.raf-remaster/install.json` (original game folder, HD on/off, forced native D3D9,
   shortcut choices, language, the `Install Directory` value from before the first install, test
   marker); if the original game moved or fails the quick check it asks for the folder;
3. builds the new version from the original game into the sibling folder `<dir>.raf-update`, exactly
   like a fresh install (same builders, same fingerprint), with the old `registry.json` carried over
   and `keep_settings`: every registry value the remaster already manages keeps the player's value
   (graphics quality, resolution, vsync, zoom slider, view distance); only the network adapter is
   picked again and values new in this version are written;
4. swaps the folder contents: every entry of `<dir>` moves into a new `<dir>.raf-old`, then every
   entry of `<dir>.raf-update` moves into `<dir>`. `<dir>` itself is never renamed, so an open
   handle on it (an Explorer window, a shell, a scanner) does not block the update. A failing move
   puts back all entries moved so far. If a move fails, Explorer windows showing the folder are
   switched to its parent once and the swap is retried before the player is asked;
5. copies the player's files over from the old folder: everything the new build does not have
   (saves and profiles under `Users\`, own maps, logs) and game-written changes to files the remaster
   does not patch; never files the old version installed itself (managed overlay files), the old
   launcher, DXVK files or `shader.cache`; `update.json` and the update cache (skip setting) too;
6. writes shortcuts, `Uninstall.bat` and the uninstall entry for the final folder;
7. deletes `<dir>.raf-old` and starts the game through the new launcher.

Rollback: before step 4 a failure deletes `<dir>.raf-update` and puts back the registry values from
before the update (snapshot taken right before the apply); the old install was never touched. A
failure in steps 5-6 moves the new entries to `<dir>.raf-failed` and the old ones back, then
restores the registry. The journal `<dir>.raf-swap.json` (next to the folder) records the phase of
step 4 until step 6 is done; a crash in between is undone by the next update run, which moves the
old entries back from `<dir>.raf-old`. A half-done swap of 1.3.0 or older (`<dir>` missing,
`<dir>.raf-old` present) is renamed back as before.

Cost: an update needs the free space of a second install while it runs and takes as long as an
install (3-20 minutes with HD textures, which are rebuilt from scratch every time).

Limits: the launcher cannot update installs made before it existed (no `RaF Remaster.exe`); those
players run the new setup once with `--update "<remaster folder>"` or reinstall. A failure after the
uninstall entry was rewritten leaves its DisplayVersion at the new version (cosmetic).

## Per-install switches

`<game>/.raf-remaster/update.json`:

| key | effect |
|---|---|
| `"disabled": true` | never check |
| `"repo": "owner/name"` | check another GitHub repository (a fork) |
| `"api"`, `"test_answer"`, `"dry_run_game"`, `"download_dir"` | tests only, honoured only when `api` is a loopback URL (tools/e2e_update.py) |

`RaF Remaster.exe --check-updates` checks immediately and also reports "up to date";
`--skip-check` starts the game without a check. Launcher log: `%TEMP%\RaF-Remaster-Launcher.log`.

## Command line for other launchers

```
RaF-Remaster-Setup.exe --silent --source "<original game dir>" --target "<new empty dir>"
                       [--lang ru|de|en] [--no-hd] [--no-shortcuts] [--force-native] [--log <file>]
```

No window, real registry (game settings, uninstall entry under HKCU), shortcuts unless
`--no-shortcuts`. Exit codes: `0` installed with the release fingerprint, `1` failed (the target
folder is removed again, registry restored), `2` bad arguments, `3` installed but the fingerprint
differs from the release (the original has extra files in its gameplay folders). The log goes to
`--log` or `%TEMP%\RaF-Remaster-Setup.log`; the last line starting with `RESULT` is JSON with
`fingerprint`, `features`, `dxvk`, `uninstall`.

Updating such an install: `RaF-Remaster-Setup.exe --update "<dir>" --headless --log <file>
--no-launch` (exit `0` updated, `1` failed and rolled back, `2` refused: game running, original
missing, not a remaster folder). After an install the game is started with
`"<dir>\RaF Remaster.exe" [game args]` (update check) or
`"<dir>\RiseAndFall.exe" -datapath "Data\" -redistpath "Redist\" [game args]` (no check).
