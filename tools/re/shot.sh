#!/bin/bash
# shot.sh <name> : gfxcapture the game window into work/shots, plus a 860px-wide copy (<name>s.png)
S=work/shots
export PYTHONUTF8=1; UM=um
timeout 40 $UM win shot --exe RiseAndFall.exe $S/$1.png >/dev/null 2>&1
python -c "
from PIL import Image; im=Image.open(r'$S/$1.png'); print(im.size); im.resize((860,int(860*im.height/im.width))).save(r'$S/${1}s.png')"
