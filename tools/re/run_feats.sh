#!/bin/bash
# run_feats.sh <prefix> <features> : kill game, apply features, vsync off + HUD for measuring, load skirmish, spots
S=work/shots
P=$(cat $S/pid 2>/dev/null); [ -n "$P" ] && taskkill //PID $P //F >/dev/null 2>&1; sleep 3
cd .
python tools/raf_patch.py apply D:/Games/RAF-remaster --only $2 | grep -v "^registry" || exit 1
reg add "HKCU\Software\Midway Home Entertainment\Rise and Fall" //v "Wait for VSync" //t REG_DWORD //d 0 //f >/dev/null
printf 'dxvk.hud = fps\n' >> D:/Games/RAF-remaster/dxvk.conf
work/scripts/ingame.sh
work/scripts/spots.sh $1
python tools/gamectl.py mem
