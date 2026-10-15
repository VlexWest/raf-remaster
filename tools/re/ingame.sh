#!/bin/bash
# ingame.sh : launch, click into a skirmish (Greece), retry the menu clicks until the match loads (> 450 MB)
S=work/shots
export PYTHONUTF8=1; UM=um
P=$(python tools/gamectl.py launch D:/Games/RAF-remaster); echo $P > $S/pid; echo "pid $P"
sleep 35
loaded() { python tools/gamectl.py mem | awk '{exit !($1>450)}'; }
for attempt in 1 2 3 4; do
  timeout 20 $UM win drive --proc WindowsTerminal focus >/dev/null 2>&1
  timeout 60 $UM win drive --proc RiseAndFall focus "sleep 1000" "move 1720 700" "sleep 300" "move 430 1347" "sleep 300" "click 430 1347" "sleep 2500" "click 928 444" "sleep 3500" "click 1220 146" "sleep 900" "click 1220 232" "sleep 900" "click 2160 1344" >/dev/null 2>&1
  for i in $(seq 1 25); do loaded && break 2; sleep 3; done
  timeout 20 $UM win drive --proc RiseAndFall focus "key 0x1B" "sleep 800" "key 0x1B" >/dev/null 2>&1
done
sleep 8
