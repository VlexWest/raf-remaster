# Changelog

All notable changes to Rise and Fall Remaster. Newest first.

Updating: start the game from the RaF Remaster shortcut & click "Update now", or run the new `RaF-Remaster-Setup.exe`. Your saves & settings stay.

Multiplayer: where a version says "fingerprint changes", every player of a network game needs that version.

## 1.3.0 - 2026-10-18

### Added

- The AI attacks together with its allies (feature "ally-attack", on by default). An AI player joins the enemy that one of its AI allies is attacking right now. Human allies are not followed yet.
- The AI only sends ships with cargo (feature "naval-ai", on by default). Ferries no longer sail empty when the loading time runs out, the AI asks idle units to board on Easy too, & ferries are allowed after 15 instead of 45 minutes.

### Fixed

- The AI picks its attack target by the intended weights (feature "attack-choice-fix", on by default): 70 % the closest enemy, 20 % a resource target, 10 % revenge. Before, it always attacked the closest enemy.

Fingerprint changes.

## 1.2.0 - 2026-10-17

### Added

- Smarter archer targeting (feature "target-priority", on by default). Ranged units prefer siege engines first, then archers, then heroes, & do not leave targets in range.
- Guard stance is now an anti-siege mode: siege engines in range always come first, so wall defenders deal with rams & catapults.

Fingerprint changes.

## 1.1.0 - 2026-10-17

### Added

- Archers & spearmen of every civ can be trained in the barracks & archery ranges of other civs (feature "training in foreign barracks"). Persian & Egyptian archers moved to a free button slot.

### Changed

- Co-op Roles: the commander's population limit follows the economist's (granary, market, altar...).
- Co-op Roles: finished Glory Statues go to the commander.
- Co-op Roles: the economist starts with hero level 10 & unlimited glory, so he can hire all advisors.
- Co-op Roles: a warning shows when the two players picked different civilizations. Play the same civ for both.

Fingerprint changes.

## 1.0.6 - 2026-10-16

### Changed

- Siege waves bring small catapults instead of the heavy Persian onagers. The onager hit more than twice as hard & flattened towns in seconds.
- Onagers are rare now: at most 1 per wave (2 from wave 20 on Hard), from wave 11 on Hard, wave 16 on Normal & wave 30 on Easy.
- Rams stay as before.

Fingerprint changes.

## 1.0.5 - 2026-10-15

### Added

- Survival comes in three difficulties, pick the map in the lobby:
  - **Easy**: half-size waves, first wave after 6 minutes, rams & onagers only from wave 8, more time between waves
  - **Normal**: smaller waves, first wave after 5 minutes, siege from wave 4
  - **Hard**: the Survival from 1.0.3, first wave after 4 minutes, siege from wave 2

Fingerprint changes.

## 1.0.4 - 2026-10-15

### Changed

- Updates no longer upscale the HD textures again when nothing about them changed. The setup takes them over from your current install, so an update takes about a minute instead of up to 20.
- This works from the next update on: the update to 1.0.4 itself still upscales once.

Fingerprint does not change.

## 1.0.3 - 2026-10-15

### Changed

- Walls alone no longer hold the waves: rams & onagers come with every wave from wave 2, about a third of each wave. In the endless phase more of them join over time. This affects Survival Endless, Boss Hunt & Co-op Roles.
- The 20-wave Survival maps (classic & zombie) are gone for now. Survival Endless stays.

Fingerprint changes.

## 1.0.2 - 2026-10-15

### Added

- Other language versions of 1.15: if your game exe matches, the setup now installs instead of stopping at the language files. The new texts (co-op maps, menus) are then English. If your exe does not match, the setup says so. Please open an issue with your version.

### Fixed

- Graphics options you change in game are no longer set back to Ultra when the remaster is applied again.

Fingerprint does not change on the Russian version. English & Russian installs get different fingerprints & cannot play together.

## 1.0.1 - 2026-10-15

### Changed

- Own icon for the setup, the launcher, the shortcuts & the uninstall entry.
- Cleaner setup & update windows in dark blue & gold. The raw log sits behind "Show details", the last screen shows the fingerprint big & has a Play button.

### Fixed

- No more console windows flashing during the install. The HD texture step opened one window per texture, hundreds in total. Every tool the setup, the launcher & the updater start now runs hidden.

Fingerprint does not change.

## 1.0.0 - 2026-10-15

First release.

- Borderless fullscreen at your desktop resolution, smooth camera scrolling
- Camera zoom with a slider in the options
- HD textures, mipmaps & new shaders
- Harder Hard AI with a personality per civilization
- Unit limit up to 10000
- Co-op maps: Survival, Survival Zombies, Survival Endless, Boss Hunt, Co-op Roles & Co-op vs Hard AI
- Russian, German & English setup, auto update for new versions
- Fix for dead mouse clicks right after launch
- Supported: Russian v1.15 of the game
