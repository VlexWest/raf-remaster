"""callers.py <pe> <target_va>... : find E8 rel32 calls and imm32 refs to each target."""
import sys, struct, re
sys.path.insert(0, 'work/scripts')
from xref import load, off2va
d, b, s = load(sys.argv[1])
for t in sys.argv[2:]:
    t = int(t, 16); out = []
    for i in range(len(d) - 5):
        if d[i] == 0xE8:
            va = off2va(s, b, i)
            if va and va + 5 + struct.unpack_from('<i', d, i + 1)[0] == t: out.append(hex(va))
    refs = [hex(off2va(s, b, m.start())) for m in re.finditer(re.escape(struct.pack('<I', t)), d)]
    print(hex(t), 'calls', out[:20], 'refs', refs[:10])
