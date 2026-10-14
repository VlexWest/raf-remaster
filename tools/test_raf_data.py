#!/usr/bin/env python3
"""Offline checks for raf_data.py against the user's install (read only).

  python tools/test_raf_data.py ["D:\\Games\\Rise and Fall\\Data\\db"]

1. every db/*.dat round-trips byte for byte through JSON text
2. editing one field changes only that field's bytes
3. adding a record bumps the count and the record reads back
4. dbcpbehavior: every row with a name has an id, names cover the difficulty knobs
5. malformed input fails loudly (short file, wrong blob count, overlong string)
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raf_data  # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else r'D:\Games\Rise and Fall\Data\db'
fails = []


def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def load(name):
    return open(os.path.join(DB, name + '.dat'), 'rb').read()


def via_json(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


# 1
import io, contextlib  # noqa: E401,E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ok = raf_data.cmd_roundtrip(DB)
check(ok, 'round trip of all tables: ' + buf.getvalue().strip().splitlines()[-1])

# 2
src = load('dbobjects')
o = via_json(raf_data.unpack_bytes('dbobjects', src))
idx = next(i for i, r in enumerate(o['records']) if r['name'] == 'A - Inf01 - Spear Infantry (Level 1 Rome)')
o['records'][idx]['hit_points'] = 999
out = raf_data.pack_obj(o)
diff = [i for i, (a, b) in enumerate(zip(src, out)) if a != b]
base = 4 + idx * 2012 + 0x78
check(len(out) == len(src) and diff and all(base <= d < base + 4 for d in diff),
      'dbobjects hit_points edit touches only bytes %d..%d' % (base, base + 3))
check(struct.unpack_from('<i', out, base)[0] == 999, 'edited hit_points reads back as 999')

src = load('dbcpbehavior')
c = via_json(raf_data.unpack_bytes('dbcpbehavior', src))
row = next(r for r in c['records'] if r['id'] == 11)
row['v12'] = 400.0
out = raf_data.pack_obj(c)
diff = [i for i, (a, b) in enumerate(zip(src, out)) if a != b]
check(diff and min(diff) >= 4 + 11 * 56 + 48 and max(diff) < 4 + 11 * 56 + 52,
      'dbcpbehavior id 11 v12 edit touches only that float')

src = load('dbtechtree')
t = via_json(raf_data.unpack_bytes('dbtechtree', src))
node = next(k for r in t['roots'] for k in r['children'] if k['name'] == 'A - Inf01 - Spear Infantry (Level 1 Rome)')
check(node['object_index'] == idx, 'tech tree node object_index points at the dbobjects record')
node['cost_0x7c'] = 31
out = raf_data.pack_obj(t)
check(len(out) == len(src) and sum(a != b for a, b in zip(src, out)) == 1, 'tech tree cost edit changes one byte (30 -> 31)')

# 3
src = load('dbstartingresources')
s = via_json(raf_data.unpack_bytes('dbstartingresources', src))
new = dict(s['records'][0])
new['s_0x0'] = 'Rich'
s['records'].append(new)
out = raf_data.pack_obj(s)
back = raf_data.unpack_bytes('dbstartingresources', out)
check(struct.unpack_from('<I', out, 0)[0] == 4 and len(out) == len(src) + 136, 'added record bumps count to 4')
names = [r['s_0x0'] if isinstance(r['s_0x0'], str) else r['s_0x0']['s'] for r in back['records']]
check(names[-1] == 'Rich', 'added record reads back')

# 4
c = raf_data.unpack_bytes('dbcpbehavior', load('dbcpbehavior'))
named = [r for r in c['records'] if '#names' in r]
check(len(named) >= 120, '%d of 143 AI rows carry names' % len(named))
allnames = ' '.join(v for r in named for v in r['#names'].values())
for knob in ('AttackGroupSizeLevelOfDifficulty', 'AttackDelayLevelOfDifficulty', 'PopLimitAdjust',
             'CostDiscountLevelOfDifficulty', 'AICostPercentage', 'ResignationPercent'):
    check(knob in allnames, 'AI knob named: ' + knob)

# 5
def raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


check(raises(lambda: raf_data.unpack_bytes('dbcpbehavior', load('dbcpbehavior')[:100])), 'short file rejected')
e = via_json(raf_data.unpack_bytes('dbeffects', load('dbeffects')))
e['records'].pop()
check(raises(lambda: raf_data.pack_obj(e)), 'dbeffects with 1999 records rejected')
o = via_json(raf_data.unpack_bytes('dbcpbehavior', load('dbcpbehavior')))
o['schema'] = [['id', 'i32']]
check(raises(lambda: raf_data.pack_obj(o)) or len(raf_data.pack_obj(o)) != len(load('dbcpbehavior')),
      'schema mismatch does not silently produce the stock file')
s = via_json(raf_data.unpack_bytes('dbtechtree', load('dbtechtree')))
s['roots'][0]['name'] = 'x' * 200
check(raises(lambda: raf_data.pack_obj(s)), 'overlong char[100] rejected')

print('\n%d failed' % len(fails))
sys.exit(1 if fails else 0)
