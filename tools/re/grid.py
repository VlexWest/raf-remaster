"""grid.py <prefix> : 2x2 grid of <prefix>_{A,Ain,W,Wlow}s.png -> <prefix>_grid.png"""
import os
import sys
from PIL import Image
S = os.path.join(os.environ.get('RAF_SHOTS') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'work', 'shots'), '')
ims = [Image.open(f'{S}{sys.argv[1]}_{n}s.png') for n in ['A', 'Ain', 'W', 'Wlow']]
w, h = ims[0].size; out = Image.new('RGB', (w * 2, h * 2))
for i, im in enumerate(ims): out.paste(im, ((i % 2) * w, (i // 2) * h))
out.save(f'{S}{sys.argv[1]}_grid.png')
