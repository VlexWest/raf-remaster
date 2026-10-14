"""vtable.py <pe> <mangled class name e.g. .?AVEEUIEWheelZoom@@> : find RTTI vftable(s) and list first entries."""
import sys, struct, re
sys.path.insert(0, 'work/scripts')
from xref import load, off2va, va2off
d, b, s = load(sys.argv[1]); name = sys.argv[2].encode()
for m in re.finditer(re.escape(name) + b'\0', d):
    td = off2va(s, b, m.start()) - 8
    for c in re.finditer(re.escape(struct.pack('<I', td)), d):
        col = off2va(s, b, c.start()) - 12
        if struct.unpack_from('<I', d, c.start() - 12)[0] != 0: continue
        for v in re.finditer(re.escape(struct.pack('<I', col)), d):
            vt = off2va(s, b, v.start()) + 4; o = va2off(s, b, vt)
            print('vftable', hex(vt), [hex(struct.unpack_from('<I', d, o + 4 * i)[0]) for i in range(12)])
