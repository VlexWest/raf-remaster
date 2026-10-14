"""hudcrop.py <name> : crop the DXVK HUD corner of <scratch>/<name>.png into <name>_hud.png (x2)."""
import sys
from PIL import Image
S = r'work/shots/'
im = Image.open(S + sys.argv[1] + '.png'); im.crop((0, 0, 300, 50)).resize((600, 100)).save(S + sys.argv[1] + '_hud.png')
