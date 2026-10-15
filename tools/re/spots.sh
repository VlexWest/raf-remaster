#!/bin/bash
# spots.sh <prefix> : right after load: A = start view (own town centre, zoom 1.0), Ain = 7 wheel notches in.
S=work/shots
export PYTHONUTF8=1; UM=um
SH=work/scripts/shot.sh
$SH ${1}_A
IN=(); for i in $(seq 1 7); do IN+=("wheel 120" "sleep 150"); done
timeout 40 $UM win drive --proc RiseAndFall focus "move 1720 560" "${IN[@]}" "sleep 2500" >/dev/null 2>&1; $SH ${1}_Ain
OUT=(); for i in $(seq 1 7); do OUT+=("wheel -120" "sleep 150"); done
timeout 40 $UM win drive --proc RiseAndFall focus "move 1720 560" "${OUT[@]}" "sleep 1000" >/dev/null 2>&1
python work/scripts/hudcrop.py ${1}_A
