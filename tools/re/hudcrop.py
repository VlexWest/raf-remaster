"""hudcrop.py <name> : crop the DXVK HUD corner of $RAF_SHOTS/<name>.png into <name>_hud.png (x2)."""
import os
import sys
from PIL import Image
S = os.path.join(os.environ.get('RAF_SHOTS') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'work', 'shots'), '')
im = Image.open(S + sys.argv[1] + '.png'); im.crop((0, 0, 300, 50)).resize((600, 100)).save(S + sys.argv[1] + '_hud.png')
