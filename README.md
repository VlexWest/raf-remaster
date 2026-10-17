**English** | [Русский](README.ru.md)

# Rise and Fall Remaster

An unofficial remaster patch for Rise and Fall: Civilization at War.

It is tested with the Russian version 1.15 of the game. Other language versions of 1.15 may work if they use the same game exe. The installer checks this first & tells you if yours does not match. In that case please open an issue so I can add your version.

On a non-Russian install the new texts (co-op maps, menus) are English.

See the [changelog](CHANGELOG.md) for what changed in each version.

## Features

### 🖥️ Graphics & display

- Borderless fullscreen at your desktop resolution
- Smooth camera scrolling & a wider zoom (slider in Options > Interface)
- Ultra graphics settings, full mipmaps & reworked unit, terrain & water shaders
- Optional HD textures, upscaled on your own graphics card
- DXVK (Direct3D 9 on Vulkan) on GPUs that support it

### ⚔️ Gameplay & AI

- A harder Hard AI with its own personality per civilization
- Smarter unit AI for artillery & transports
- Smarter archer targeting: ranged units prefer siege engines, then archers, then heroes. Guard stance is an anti-siege mode
- Archers & spearmen can be trained in the barracks & archery ranges of other civilizations
- Unit limit raised to 10000

### 🏰 Co-op & maps

- Survival: an endless mode with siege waves in three difficulties
- Boss Hunt, Co-op Roles & Co-op vs Hard AI
- Co-op Roles fixes: shared population limit, glory statues for the commander, a strong start for the economist

### 🌐 Multiplayer & install

- The installer builds a new game folder from your own files. Your original install is never changed
- LAN & direct IP games with a fingerprint check against desyncs
- Updates from the launcher with "Update now". Setup in Russian, German & English
- Works with other language versions of 1.15 if the exe matches

### 🔧 Fixes

- Dead mouse clicks right after launch
- Graphics options you change in game are kept
- No console windows flashing during the install

## Install

Download `RaF-Remaster-Setup.exe` from [Releases](../../releases) & run it.

The installer finds your game & copies it into a new folder. Your original install is only read, never changed.

Everything is built on your PC from your own game files. The installer contains no game files.

When it is done you get shortcuts to play, host or join a network game & uninstall.

## Multiplayer

At the end the installer shows a gameplay fingerprint. You can also find it in `REMASTER.txt` in the game folder.

All players need the same fingerprint. If it differs, the game will go out of sync.

Use "Host network game" & "Join network game" for LAN or direct IP games.

## Co-op maps

The remaster adds maps you play together against the computer:

- **Survival** (Easy, Normal, Hard): endless waves until you fall, with rams & catapults so walls alone will not hold
- **Boss Hunt**: hunt down heroes stage by stage
- **Co-op Roles**: one player runs the economy, the other leads the army
- **Co-op vs Hard AI**: two players against three computer players

Pick them in the skirmish or LAN lobby like any other map.

In Co-op Roles the commander's population limit follows the economist's (granary, market, altar...) & finished glory statues go to the commander. The economist starts with hero level 10 & unlimited glory, so he can hire all advisors. A warning shows when the two players pick different civilizations, so play the same civ for both.

## Smarter archer targeting

Ranged units pick targets in this order: siege engines, then archers, then heroes. They do not leave targets in range. The feature is called "target-priority" & is on by default.

Guard stance is an anti-siege mode: siege engines in range always come first. Use it for wall defenders.

## Linux & Steam Deck

Not tested. The game & the installer are Windows programs, so Proton or Wine is the way to try.

If you get it running, please open an issue & tell me how.

## Problems

The installer writes a log to `%TEMP%\RaF-Remaster-Setup.log`. Please attach it when you open an issue.

To remove the remaster, use the uninstall shortcut. Your original game stays as it was.

## Building from source

You need Windows, [uv](https://docs.astral.sh/uv/) & the python.org build of Python 3.14.

Other Python builds compress the map files differently. The game still works, but your fingerprint will not match other players.

```
python tools/build_installer.py
```

This downloads the pinned third-party tools, checks their hashes & writes `dist/RaF-Remaster-Setup.exe`.

The offline tests need a few extra Python packages:

```
python -m pip install unicorn capstone pefile numpy pillow fonttools
python tools/run_stub_tests.py
```

## Credits

Remastered by [Alexander West](https://thewest.cc/raf).

Built with help from Claude (Anthropic) as a coding assistant. All features were tested in the real game.

Third-party tools shipped with the installer:

- [DXVK](https://github.com/doitsujin/dxvk) (zlib license)
- [texconv / DirectXTex](https://github.com/microsoft/DirectXTex) (MIT)
- [Real-ESRGAN ncnn Vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) & the [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) model (MIT, BSD-3-Clause)

Their license texts are in `installer/licenses`.

## License

The remaster code is licensed under Apache 2.0, see [LICENSE](LICENSE) & [NOTICE](NOTICE). If you reuse it, keep the credit from the NOTICE file.

## Disclaimer

This is a fan project. It is not affiliated with Midway, Stainless Steel Studios or the current rights holders.

You need your own copy of the game. This repository & the installer contain no game files.
