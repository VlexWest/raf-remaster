#!/bin/bash
# skirmish8.sh : launch, open the skirmish lobby, fill all 7 other slots with computer players, start; wait for load
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
S=${RAF_SHOTS:-$REPO/work/shots}; mkdir -p "$S"; GAME=${RAF_GAME:-D:/Games/RAF-remaster}
export PYTHONUTF8=1; UM=${UM:-um}
cd "$HERE"
./lobby.sh >/dev/null
for pass in 1 2; do
  C=(); for y in 332 420 512 600 692 784; do C+=("click 420 $y" "sleep 900" "click 220 $((y+56))" "sleep 900"); done
  timeout 90 $UM win drive --proc RiseAndFall focus "${C[@]}" >/dev/null 2>&1
done
./shot.sh lobby8 >/dev/null
timeout 30 $UM win drive --proc RiseAndFall focus "click 2160 1344" >/dev/null 2>&1
for i in $(seq 1 60); do python $REPO/tools/gamectl.py mem | awk '{exit !($1>450)}' && break; sleep 3; done
sleep 8
