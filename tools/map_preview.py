"""Lobby preview pictures for our scenario maps, made from the user's own stock files.

Where the lobby takes them from (RiseAndFall.exe v1.15, evidence in docs/survival.md
section 8):

* still picture: FUN_00bc87d0 loads `textures\\<TextureName>` (the .rmv key, default = the .rmv
  file name without extension, FUN_00bcd8f0) and falls back to `textures\\DefaultRandomMap`
  (Data\\textures\\defaultrandommap.sst, the "?" picture). The stock maps ship
  Data\\textures\\<map>.tga: 256x256, 32 bit, uncompressed, bottom-up, picture in the top-left
  212x160 (the lobby shows the rectangle 2..213 x 2..161).
* movie: FUN_00bc7ab0 looks for `Movies\\<map>.bik` and falls back to
  `Movies\\Random Map Default.bik`.

We copy the template map's picture with a small badge drawn on it (pure Python, deterministic)
and copy the template's movie unchanged (no Bink encoder; Bink is RAD's format).
"""
import struct
from pathlib import Path

PICTURE = (212, 160)          # visible part, top-left of the 256x256 texture

# 11 x 11 glyphs, 'X' = ink; drawn 3x inside a round badge
GLYPHS = {
    'shield': ['XXXXXXXXXXX',
               'XXXXX.XXXXX',
               'XXXXX.XXXXX',
               'X.........X',
               'XXXXX.XXXXX',
               'XXXXX.XXXXX',
               '.XXXX.XXXX.',
               '.XXXX.XXXX.',
               '..XXX.XXX..',
               '...XX.XX...',
               '....XXX....'],
    'skull': ['..XXXXXXX..',
              '.XXXXXXXXX.',
              'XXXXXXXXXXX',
              'XX...X...XX',
              'XX...X...XX',
              'XXXXXXXXXXX',
              '.XXXX.XXXX.',
              '..XXXXXXX..',
              '..X.X.X.X..',
              '..XXXXXXX..',
              '...........'],
    'infinity': ['...........',
                 '...........',
                 '.XXX...XXX.',
                 'XX.XX.XX.XX',
                 'X...XXX...X',
                 'X....X....X',
                 'X...XXX...X',
                 'XX.XX.XX.XX',
                 '.XXX...XXX.',
                 '...........',
                 '...........'],
    'crown': ['...........',
              'X....X....X',
              'XX..XXX..XX',
              'XXX.XXX.XXX',
              'XXXXXXXXXXX',
              'XXXXXXXXXXX',
              'XXXXXXXXXXX',
              '...........',
              'XXXXXXXXXXX',
              'XXXXXXXXXXX',
              '...........'],
    'pair': ['...........',
             '...........',
             '..XX...XX..',
             '.XXXX.XXXX.',
             '..XX...XX..',
             '...........',
             '.XXXX.XXXX.',
             '.XXXX.XXXX.',
             '.XXXX.XXXX.',
             '...........',
             '...........'],
    'swords': ['XX.......XX',
               'XXX.....XXX',
               '.XXX...XXX.',
               '..XXX.XXX..',
               '...XXXXX...',
               '....XXX....',
               '...XXXXX...',
               '.XXXX.XXXX.',
               '.XX.....XX.',
               'XX.......XX',
               'X.........X'],
}

# map stem -> (glyph, ring/ink colour RGB)
BADGES = {
    '(4) survival': ('shield', (225, 185, 35)),
    '(4) survival zombies': ('skull', (150, 255, 150)),
    '(4) survival endless': ('infinity', (225, 185, 35)),
    '(4) boss hunt': ('crown', (255, 80, 80)),
    '(4) co-op roles': ('pair', (225, 185, 35)),
    '(4) co-op roles vs ai': ('pair', (255, 80, 80)),
    '(5) co-op vs hard ai': ('swords', (255, 80, 80)),
}


def read_tga(path):
    """Uncompressed 32-bit TGA -> (header bytes, width, height, rows top-down of BGRA bytes)."""
    data = Path(path).read_bytes()
    idlen, cmap, itype = data[0], data[1], data[2]
    w, h, bpp, desc = struct.unpack_from('<HHBB', data, 12)
    if itype != 2 or cmap != 0 or bpp != 32:
        raise ValueError('%s: not an uncompressed 32-bit TGA (type %d, %d bpp)' % (path, itype, bpp))
    start = 18 + idlen
    rows = [bytearray(data[start + y * w * 4:start + (y + 1) * w * 4]) for y in range(h)]
    if len(rows[-1]) != w * 4:
        raise ValueError('%s: truncated' % path)
    if not desc & 0x20:            # bit 5 clear = bottom-up
        rows.reverse()
    tail = data[start + w * h * 4:]
    return data[:start], w, h, rows, desc, tail


def write_tga(header, w, h, rows, desc, tail):
    rows = list(rows)
    if not desc & 0x20:
        rows.reverse()
    return bytes(header) + b''.join(bytes(r) for r in rows) + bytes(tail)


def draw_badge(rows, glyph, colour, centre, radius=22, scale=3):
    """Dark round badge with a coloured ring and the glyph, alpha 255."""
    cx, cy = centre
    r_out, r_ring = radius * radius, (radius - 3) * (radius - 3)
    ink = (colour[2], colour[1], colour[0], 255)
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            d = (x - cx) * (x - cx) + (y - cy) * (y - cy)
            if d > r_out:
                continue
            px = ink if d > r_ring else (24, 20, 18, 255)
            rows[y][x * 4:x * 4 + 4] = bytes(px)
    g = GLYPHS[glyph]
    gw, gh = len(g[0]) * scale, len(g) * scale
    x0, y0 = cx - gw // 2, cy - gh // 2
    for j, line in enumerate(g):
        for i, ch in enumerate(line):
            if ch != 'X':
                continue
            for dy in range(scale):
                for dx in range(scale):
                    x, y = x0 + i * scale + dx, y0 + j * scale + dy
                    if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r_ring:   # inside the ring
                        rows[y][x * 4:x * 4 + 4] = bytes(ink)


def make_picture(stock_tga, stem):
    header, w, h, rows, desc, tail = read_tga(stock_tga)
    if (w, h) != (256, 256):
        raise ValueError('%s: %dx%d, expected 256x256' % (stock_tga, w, h))
    glyph, colour = BADGES[stem]
    pw, ph = PICTURE
    draw_badge(rows, glyph, colour, (pw - 28, ph - 28))
    return write_tga(header, w, h, rows, desc, tail)


def movie_name(stem):
    """Stock movies are named in title case ("(4) Plains.bik"); Windows lookups ignore case."""
    return ' '.join(w[:1].upper() + w[1:] for w in stem.split(' ')) + '.bik'


def write_previews(game, template, stem, out):
    """Write <out>/Data/textures/<stem>.tga and <out>/Data/movies/<Stem>.bik from the template's
    stock files. Returns the list of written paths; a missing stock file is skipped (the lobby
    then shows its fallback, as before)."""
    game, out = Path(game), Path(out)
    written = []
    src = game / 'Data' / 'textures' / (template + '.tga')
    if src.is_file():
        dst = out / 'Data' / 'textures' / (stem + '.tga')
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(make_picture(src, stem))
        written.append(dst)
    mv = game / 'Data' / 'movies' / movie_name(template)
    if mv.is_file():
        dst = out / 'Data' / 'movies' / movie_name(stem)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(mv.read_bytes())
        written.append(dst)
    return written
