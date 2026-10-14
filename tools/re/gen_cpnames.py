"""Regenerate tools/raf_cpnames.py from decomp/ai_param_map.json (written by aimap.py).

Run order (needs the Ghidra decompile in decomp/RiseAndFall.c, see DecompAll.java):
  python tools/re/oosmap.py 4642f0 466000 decomp/ai_oos_map.json
  python tools/re/aimap.py > decomp/ai_param_map.txt
  python tools/re/gen_cpnames.py
"""
import collections
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
m = json.load(open(os.path.join(ROOT, 'decomp', 'ai_param_map.json')))
d = collections.defaultdict(dict)
for r, f, off, name, how in m:
    if name.startswith('(spending'):
        o = off.split('+')[1]
        o = int(o, 16) if o.startswith('0x') else int(o)
        name = 'SpendingCategory%d.slot%d' % (o // 0x14, (o % 0x14) // 4)
    if name == '?':
        continue
    k = {4: 'v4', 7: 'v7', 12: 'v12'}.get(f, 'f%d' % f)
    n = name + ((' [' + how + ']') if how else '')
    if k in d[r] and n not in d[r][k]:
        d[r][k] += ' | ' + n
    else:
        d[r][k] = n
path = os.path.join(ROOT, 'tools', 'raf_cpnames.py')
head = open(path, encoding='utf-8').read().split('CP_PARAM_NAMES = {')[0]
lines = [head + 'CP_PARAM_NAMES = {']
for r in sorted(d):
    lines.append('    %d: %r,' % (r, dict(sorted(d[r].items()))))
lines.append('}')
open(path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('wrote %d records' % len(d))
