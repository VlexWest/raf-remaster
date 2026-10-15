#!/bin/bash
# run_feats.sh <prefix> <features> : kill game, apply features, vsync off + HUD for measuring, load skirmish, spots
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
S=${RAF_SHOTS:-$REPO/work/shots}; mkdir -p "$S"; GAME=${RAF_GAME:-D:/Games/RAF-remaster}
P=$(cat $S/pid 2>/dev/null); [ -n "$P" ] && taskkill //PID $P //F >/dev/null 2>&1; sleep 3
cd "$REPO"
python tools/raf_patch.py apply $GAME --only $2 | grep -v "^registry" || exit 1
reg add "HKCU\Software\Midway Home Entertainment\Rise and Fall" //v "Wait for VSync" //t REG_DWORD //d 0 //f >/dev/null
printf 'dxvk.hud = fps\n' >> $GAME/dxvk.conf
$HERE/ingame.sh
$HERE/spots.sh $1
python tools/gamectl.py mem
