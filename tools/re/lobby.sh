#!/bin/bash
# testscene.sh : launch RAF-remaster (borderless 3440x1440) and click into a default skirmish. Prints the PID.
S=work/shots
export PYTHONUTF8=1; UM=um
P=$(python tools/gamectl.py launch D:/Games/RAF-remaster); echo $P > $S/pid; echo "pid $P"
sleep ${WAIT:-40}
# the game ignores clicks until it has been deactivated and re-activated (twice to be safe)
for i in 1 2; do timeout 20 $UM win drive --proc WindowsTerminal focus >/dev/null 2>&1; timeout 40 $UM win drive --proc RiseAndFall focus "sleep 800" "move 1720 700" >/dev/null 2>&1; done
timeout 40 $UM win drive --proc RiseAndFall focus "sleep 1000" "move 430 1347" "sleep 300" "click 430 1347" "sleep 2500" "click 928 444" "sleep 3500" >/dev/null 2>&1

