#!/bin/bash
# zoomtest.sh <name> <notches> : wheel out N notches, print zoom fraction and camera pos, screenshot
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
S=${RAF_SHOTS:-$REPO/work/shots}; mkdir -p "$S"; GAME=${RAF_GAME:-D:/Games/RAF-remaster}
P=$(cat $S/pid); export PYTHONUTF8=1; UM=${UM:-um}
CMDS=(focus "move 1720 600"); for i in $(seq 1 $2); do CMDS+=("wheel -120" "sleep 120"); done; CMDS+=("sleep 1500")
timeout 40 $UM win drive --proc RiseAndFall "${CMDS[@]}" >/dev/null 2>&1
python $HERE/peek.py $P 101dcc0 1; python $HERE/peek.py $P d2f960 6
$HERE/shot.sh $1
