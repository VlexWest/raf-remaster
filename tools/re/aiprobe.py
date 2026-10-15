"""aiprobe.py <pid> : dump per-player AI values (docs/ai-personalities.md section 5)."""
import sys, struct
sys.path.insert(0, 'work/scripts'); import memscan
h = memscan.openp(int(sys.argv[1]))
rd = lambda a, n=4: memscan.read(h, a, n)
u32 = lambda a: struct.unpack('<I', rd(a))[0]
f32 = lambda a: struct.unpack('<f', rd(a))[0]
n = u32(0x101db70)
print('players', n)
for i in range(n):
    o = u32(0x101db18 + 4 * i)
    if not o: print(i, 'null'); continue
    try:
        civ = u32(u32(o + 0xe14) + 0x211c)
    except Exception:
        civ = None
    print(i, hex(o), 'civ', civ, 'atkdelay', u32(o + 0x1288), u32(o + 0x128c), 'grp%', round(f32(o + 0x1124), 3),
          'def%', round(f32(o + 0x118c), 3), 'defforce', u32(o + 0x12b0), u32(o + 0x12b4),
          'army', u32(o + 0x13a0), 'tech', u32(o + 0x13a4), 'dock', u32(o + 0x13c0), u32(o + 0x1308))
