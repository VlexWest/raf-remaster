# Online multiplayer revival (GameSpy replacement)

Researched 2026-10-15. Nothing installed, game not launched, no third-party patch downloaded.

## Verdict

Feasible, and a community fix already exists: an "OpenSpy Patch (Multiplayer Fix) v1.0.1" for
Rise and Fall v1.15 by zoli456 (last updated 2026-02-21, 268.5 KB). OpenSpy (openspy.net) is a live
GameSpy replacement; the patch points the game at it. No Hamachi needed. No self-hosted server needed.

## Sources

- https://www.gamepressure.com/download/rise-fall-civilizations-at-war-openspy-patch-multiplayer-fix-v10/z1155d2
  (v1.15 only, unpack into game dir, start via included .bat, log in with OpenSpy
  account, includes a UPnP client for port forwarding. Fallback: account.openspy.net/profile, add a
  profile with nickname "rafcivatwar", own unique nick, Namespace ID 1. No real email needed.)
- https://community.pcgamingwiki.com/files/file/3883-rise-and-fall-civilizations-at-war-openspy-patch/
  (original host of the patch; returned 403, only seen via search snippet)
- https://github.com/anzz1/openspy-client (generic OpenSpy hook DLL loaded as dinput8/dsound/version/winmm
  and so on; redirects GameSpy to OpenSpy on the fly; Rise and Fall NOT in its list, so zoli456's patch
  is a separate work)
- https://github.com/openspy (org; openspy-core C++, natneg-helper, qr.service, openspy-web-backend)
- https://github.com/openspy/openspy-core README: services QR (master reporting), server browsing
  (28900 v1 / 28910 v2), NatNeg, GP 29900, Search 29901, GStats 29920, Peerchat 6667 (IRC), needs Redis
  and RabbitMQ; self-hostable via CMake/Docker. License not stated on the README page.
- Not found: any GameRanger support, community Discord, ModDB or forum revival (searches for these
  returned nothing). Wikipedia says multiplayer is GameSpy powered, up to 8 players.
- Not verified: whether openspy.net currently lists Rise and Fall servers/players, and whether the
  service is online today. The openspy.net game lists & the archive could not be fetched.

## Facts from the exe (D:\Games\Rise and Fall\RiseAndFall.exe, 13,520,896 bytes)

GameSpy gamename: `rafcivatwar` at file offset 0x859a10 (matches OpenSpy profile nickname in the patch
instructions). Product string `svcname=epicengine` (Arcade) at 0x88cc78.

Hostnames (file offset, length incl. no NUL):

| offset | string | len |
|---|---|---|
| 0x9275ac | %s.master.gamespy.com | 21 |
| 0x927a00 | %s.available.gamespy.com | 24 |
| 0x927f7c | peerchat.gamespy.com | 20 |
| 0x9280a8 | %s.ms%d.gamespy.com | 19 |
| 0x928490 | natneg2.gamespy.com | 19 |
| 0x9284a4 | natneg1.gamespy.com | 19 |
| 0x928510 | gamestats.gamespy.com | 21 |
| 0x929638 | gpcm.gamespy.com | 16 |
| 0x929d38 | gpsp.gamespy.com | 16 |
| 0x92ba90, 0x92bb30, 0x92bba8 | http://motd.gamespy.com/motd/{vercheck,motd}.asp?... | URLs |
| 0x872794 | http://www.gamespyid.com | |
| 0x88cc78 | http://www.gamespyarcade.com/features/launch.asp?svcname=epicengine | |
| 0x859f14 | http://data.riseandfallgame.com/motd/risefall/motd | (dead game-owner host) |
| 0x872338 | http://www.riseandfallgame.com/stats-rankings.php | |

All hostnames are in RiseAndFall.exe only (LowLevelEngine.dll just exports GetGameSpy*Rating /
NATNegotiationCookie accessors). The `openspy` feature rewrites these host names to openspy.net.

Same-length observation (not checked): `gamespy.com` and `openspy.net` are both 11 chars, so a plain
byte patch of every `gamespy.com` occurrence in the exe to `openspy.net` fits. Whether OpenSpy serves
exactly those subhostnames (rafcivatwar.master.openspy.net, natneg1/2, peerchat, gpcm, gpsp, gamestats,
available) I did not verify, though ModDB's Worms 4 patch is described as doing exactly this swap
(gamespy.com to openspy.org, so the TLD may differ by service; check `openspy.net` vs `openspy.org`).

Account: the game needs a GameSpy account (GP login); the account must be created on OpenSpy.

## Redirect methods for sibling GameSpy games

1. Hook DLL (anzz1 openspy-client, OpenSpy org proxies: ut3-proxy, RA3Proxy, sr2_proxy): proxy DLL
   (dinput8 etc.) intercepts DNS/winsock, redirects gamespy.com hosts. No exe edit, no hosts file.
2. Exe hostname byte patch (same length rule), as in the Worms 4 ModDB patch.
3. hosts file: works only for plain host to IP; fine with a self-run server, but the official OpenSpy
   uses its own hostnames and the games use HTTPS-less UDP/TCP, so hosts entries are workable but need
   the OpenSpy IPs; fragile. Not recommended.
Which one zoli456 uses (".bat launcher + UPnP client") is unknown; do not assume, inspect the archive
before running (it is unsigned third-party binary; 268 KB).

## Recommended path

1. Get the patch from the PCGamingWiki community page (user decides; it is third-party, scan it, read
   the .bat, check it against our exe: v1.15). Test in a copy of the game dir, since our
   remaster/patches may conflict with its exe edits or launcher.
2. Make an OpenSpy account (account.openspy.net), profile nickname `rafcivatwar`, namespace 1.
3. Two machines, host/join in the GameSpy lobby. Check UPnP / NatNeg.
4. Compatibility with our mods: both sides must run identical exe/data (deterministic lockstep,
   see OUT OF SYNCH DUMP strings), so patches in /patches must be identical on all players.

Effort: 1-3 hours to test; no development. If we later want our own integrated redirect: ~1 day
(byte patch of 9 hostnames + verification with a packet capture of what OpenSpy answers).

## If OpenSpy dropped the game / goes offline (fallback)

Self-hosting openspy-core needs: QR master server (v1 ASCII, heartbeat `\gamename\rafcivatwar`), server
browsing list 28900, NatNeg (natneg1/2, port 27901 plus a helper), GP/SP login (29900/29901), Peerchat
IRC (6667, rooms like #GSP!rafcivatwar!), gamestats optional, motd/available optional (the game checks
`available` to see if service is up). Open-source pieces: openspy-core (above). Effort estimate:
3-7 days including the Redis & RabbitMQ stack & debugging; only worthwhile if OpenSpy refuses the game.

## In-game tests (not run yet)

- With a hosts or patched copy: capture DNS (Wireshark) at lobby open; expect lookups of the 9
  hostnames above. Any hostname not in the table = missed.
- After patch: lobby tab shows channel list; expect peerchat connect on 6667.
