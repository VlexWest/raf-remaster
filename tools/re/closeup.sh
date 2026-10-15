#!/bin/bash
# closeup.sh <name> : zoom in fully (wheel up 14 notches, slow) and screenshot; then zoom back out
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
S=${RAF_SHOTS:-$REPO/work/shots}; mkdir -p "$S"; GAME=${RAF_GAME:-D:/Games/RAF-remaster}
export PYTHONUTF8=1; UM=${UM:-um}
IN=(); for i in $(seq 1 14); do IN+=("wheel 120" "sleep 250"); done
timeout 60 $UM win drive --proc RiseAndFall focus "move 1720 560" "sleep 300" "${IN[@]}" "sleep 2000" >/dev/null 2>&1
$HERE/shot.sh $1
python $HERE/peek.py $(cat $S/pid) 101dcc0 1
