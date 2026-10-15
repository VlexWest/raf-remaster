#!/bin/bash
# shot.sh <name> : gfxcapture the game window into $RAF_SHOTS (default work/shots), plus a 860px-wide copy (<name>s.png)
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
S=${RAF_SHOTS:-$REPO/work/shots}; mkdir -p "$S"; GAME=${RAF_GAME:-D:/Games/RAF-remaster}
export PYTHONUTF8=1; UM=${UM:-um}
timeout 40 $UM win shot --exe RiseAndFall.exe $S/$1.png >/dev/null 2>&1
python -c "
from PIL import Image; im=Image.open(r'$S/$1.png'); print(im.size); im.resize((860,int(860*im.height/im.width))).save(r'$S/${1}s.png')"
