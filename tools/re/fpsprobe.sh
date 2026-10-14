#!/bin/bash
# fpsprobe.sh <name> [mode] : focus game, sweep cursor (mode=cursor) or hold Right arrow (mode=scroll), capture 2 s, count distinct frames
S=work/shots
MODE=${2:-cursor}
export PYTHONUTF8=1; UM=um
if [ $MODE = scroll ]; then
  timeout 40 $UM win drive --proc RiseAndFall focus "click 1720 120" "hold ${KEY:-0x27} 3500" fg >$S/drive.log 2>&1 &
else
  timeout 40 $UM win drive --proc RiseAndFall focus "click 1720 120" fg >$S/drive.log 2>&1
  python work/scripts/cursor_motion.py 3.5 &
fi
sleep 1.2
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "gfxcapture=window_exe=RiseAndFall.exe:capture_cursor=0:max_framerate=240,hwdownload,format=bgra,crop=1600:900:920:150,scale=400:225" -t 2 -c:v ffv1 $S/$1.mkv
wait; cat $S/drive.log | grep fg
cd $S && python - $1.mkv <<'PY'
import subprocess, numpy as np, sys
p=sys.argv[1]
out=subprocess.run(['ffprobe','-v','error','-select_streams','v','-show_entries','frame=pts_time','-of','csv=p=0',p],capture_output=True,text=True).stdout.split()
raw=subprocess.run(['ffmpeg','-v','error','-i',p,'-f','rawvideo','-pix_fmt','gray','-'],capture_output=True).stdout
fr=np.frombuffer(raw,np.uint8).reshape(-1,225,400).astype(np.int16)
d=np.array([np.abs(fr[i]-fr[i-1]).mean() for i in range(1,len(fr))])
span=float(out[-1])-float(out[0])
print(f"{len(fr)} captured, distinct {1+(d>0.05).sum()} in {span:.2f}s = {(1+(d>0.05).sum())/span:.1f}/s")
PY
