#!/bin/bash
# closeup.sh <name> : zoom in fully (wheel up 14 notches, slow) and screenshot; then zoom back out
export PYTHONUTF8=1; UM=um
IN=(); for i in $(seq 1 14); do IN+=("wheel 120" "sleep 250"); done
timeout 60 $UM win drive --proc RiseAndFall focus "move 1720 560" "sleep 300" "${IN[@]}" "sleep 2000" >/dev/null 2>&1
work/scripts/shot.sh $1
python work/scripts/peek.py $(cat work/shots/pid) 101dcc0 1
