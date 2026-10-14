#!/usr/bin/env python3
"""Rise and Fall: Civilization at War - db/*.dat unpacker and packer.

  python tools/raf_data.py unpack  <file.dat | db dir> <out.json | out dir>
  python tools/raf_data.py pack    <file.json | json dir> <out.dat | out dir>
  python tools/raf_data.py roundtrip <db dir> [--keep <dir>]
  python tools/raf_data.py cpbehavior <dbcpbehavior.dat>     (AI table as text)

Layouts come from the loaders in RiseAndFall.exe (see docs/formats.md). Every
byte is kept: fields the exe does not name are emitted as typed columns
(i_0xNN int32, f_0xNN float32, s_0xNN char[], x_0xNN raw hex), uninitialised
editor garbage after string terminators is kept as "tail", and data after the
last record is kept as "trailing". The JSON carries its own schema, so `pack`
does not guess anything. Keys starting with '#' are notes and are ignored by
`pack`.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rafcodec as rc  # noqa: E402
from raf_cpnames import CP_PARAM_NAMES  # noqa: E402

FORMAT_TAG = 'raf-db/1'

# --------------------------------------------------------------------------
# Table layouts.  'loader' is the RiseAndFall.exe function that reads the
# table (table id in parentheses, from the registration list at 0x7182d0).
# --------------------------------------------------------------------------
FIXED = {
    # name: (record size, loader)
    'dbactiontable': (48, 'not traced; size from file'),
    'dbaiunittargeting': (160, 'FUN_005f2250 (0x0b)'),
    'dbambientsounds': (144, 'FUN_006caf80 (0x1b)'),
    'dbanimals': (272, 'FUN_005f3370 (0x1c)'),
    'dbareaeffect': (200, 'FUN_00baf8c0 (0x17)'),
    'dbbuttons': (232, 'FUN_005f4bc0 (5)'),
    'dbcalamity': (268, 'FUN_00571e20 (0x15)'),
    'dbcivilization': (904, 'FUN_00bc2cd0 (0x11), empty in 1.0'),
    'dbcivpowers': (56, 'FUN_00bc5cb0 (0x22)'),
    'dbcivspecai': (196, 'FUN_005f7380 (0x34)'),
    'dbcivspecificunitdefines': (216, 'FUN_005f60a0 (0x28)'),
    'dbcliffterrain': (124, 'FUN_00605f40 (0x21)'),
    'dbcolortable': (168, 'not traced; size from file'),
    'dbcpbehavior': (56, 'FUN_005f74b0 (0x1a)'),
    'dbcrewedunitdetails': (144, 'FUN_005fa830 (0x35)'),
    'dbfamily': (412, 'FUN_00606ac0 (9)'),
    'dbflora': (1792, 'FUN_005fb530 (0x3a)'),
    'dbgamevariant': (332, 'FUN_005fbee0 (0x1f)'),
    'dbgraphics': (212, 'FUN_005fccc0 (3)'),
    'dbmousepointer': (224, 'not traced; size from file'),
    'dbmusic': (216, 'FUN_005fe110 (1)'),
    'dbnewgfxeffecttable': (208, 'FUN_00619470 (0x26)'),
    'dbobjects': (2012, 'FUN_005f8ef0 -> FUN_005fa9e0 (2)'),
    'dbphoenixcivtable': (364, 'FUN_005ff420 (0x27)'),
    'dbpremadecivs': (124, 'FUN_00bc5010 (0x20)'),
    'dbrandommap': (132, 'FUN_006000e0 (0x10); 19 unread records follow'),
    'dbsoundgroups': (156, 'FUN_006014c0 (0x37)'),
    'dbspecialunittable': (168, 'not traced; size from file'),
    'dbstartingresources': (136, 'FUN_00602990 (0x1e)'),
    'dbterrainsettable': (148, 'FUN_00603ec0 (0x36)'),
    'dbterraintype': (128, 'FUN_006068e0 (0x0e)'),
    'dbtpmeleeattackeffects': (128, 'FUN_006093d0 (0x39)'),
    'dbtpwalkeffects': (140, 'FUN_0060b800 (0x38)'),
    'dbuiback': (564, 'not traced; size from file'),
    'dbuicontrolevents': (0, 'empty'),
    'dbuicontrols': (0, 'empty'),
    'dbuifonts': (128, 'not traced; size from file'),
    'dbuiformevents': (116, 'not traced; size from file'),
    'dbuiforms': (404, 'not traced; size from file'),
    'dbuihotkey': (136, 'FUN_00b8c310 (0x29)'),
    'dbunitbehavior': (124, 'FUN_0060d1c0 (0x1d)'),
    'dbunitset': (272, 'FUN_006ef030 (0x16)'),
    'dbupgrade': (240, 'FUN_0060c5b0 (0x19)'),
    'dbweapontohit': (132, 'FUN_0060d310 (0x14)'),
    'dbworld': (32, 'FUN_0060de70 (0x0f)'),
}
# count, then per record: UWideString (u32 byte length + bytes) + fixed block
WS_FIXED = {
    'dbsounds': (232, 'FUN_00602120 (4)'),
    'dbterrain': (304, 'FUN_00605ba0 (0x0c)'),
    'dbterraingraytextures': (120, 'no loader in RiseAndFall.exe'),
}
# no count: N fixed records (the exe reads 0x2af80 bytes in one go)
BLOB = {
    'dbeffects': (88, 2000, 'FUN_008d2fc0 (with dbevents, id 8)'),
}

# --------------------------------------------------------------------------
# Known fields: (offset, name, type).  'guess:' in a note marks an unchecked guess.
# --------------------------------------------------------------------------
I, F, U8 = 'i32', 'f32', 'u8'

KNOWN = {
    'dbcpbehavior': [
        (0, 'row', I), (4, 'id', I),
        (8, 'a_flag', I), (12, 'a_limit', I), (16, 'v4', I),
        (20, 'b_flag', I), (24, 'b_limit', I), (28, 'v7', I),
        (32, 'u_32', I),
        (36, 'c_flag', I), (40, 'c_limit', I), (44, 'c_scale', I), (48, 'v12', F),
        (52, 'u_52', I),
    ],
    # slot index = civ index of dbphoenixcivtable (3 Greece, 4 Persia, 5 Rome,
    # 10 Egypt); 'rome' also feeds slot 9 (Placeholder Civ 4). See FUN_005f72b0.
    'dbcivspecai': [
        (0x68, 'u_68', I), (0x6c, 'behavior_id', I),
        (0x70, 'greece_mult', F), (0x74, 'greece_set', F),
        (0x78, 'persia_mult', F), (0x7c, 'persia_set', F),
        (0x80, 'rome_mult', F), (0x84, 'rome_set', F),
        (0x88, 'egypt_mult', F), (0x8c, 'egypt_set', F),
        (0x90, 'placeholder1_mult', F), (0x94, 'placeholder1_set', F),
        (0x98, 'placeholder2_mult', F), (0x9c, 'placeholder2_set', F),
        (0xa0, 'placeholder3_mult', F), (0xa4, 'placeholder3_set', F),
        (0xa8, 'placeholder5_mult', F), (0xac, 'placeholder5_set', F),
    ],
    # dbobjects: names from FUN_00a1dd00 (record -> unit type copy) joined with
    # the unit out-of-sync dump at 0x9b???; see docs/formats.md.
    'dbobjects': [
        (0x000, 'name', ('str', 100)),
        (0x074, 'object_id', I),
        (0x078, 'hit_points', I),
        (0x080, 'min_range', F),
        (0x084, 'range', F),
        (0x08c, 'reload_time_s', F),
        (0x090, 'area_effect', F),
        (0x098, 'acceleration', F),
        (0x0a4, 'turret_max_ang_vel', F),
        (0x0b0, 'flight_time_s', I),
        (0x0c4, 'attack', I),
        (0x0e4, 'ammo_type', I),
        (0x0f0, 'behavior', ('str', 52)),
        (0x134, 'work_rate', F),
        (0x16c, 'repair_rate', I),
        (0x1e4, 'healing_points', I),
        (0x1f4, 'fire_while_moving', U8),
        (0x214, 'missile_delay_s', F),
        (0x21c, 'ammunition', I),
        (0x223, 'shoots_high', U8),
        (0x320, 'carry_amount', F),
        (0x328, 'max_objects_carried', I),
        (0x32e, 'build_on_elevation', U8),
        (0x390, 'tech_id', I),
    ],
    # dbtechtree node (452 bytes); offsets inside the node block.
    'dbtechtree': [
        (0x00, 'name', ('str', 100)),
        (0x68, 'tech_id', I),          # = dbobjects.tech_id (value match)
        (0x74, 'cost_0x74', I), (0x78, 'cost_0x78', I), (0x7c, 'cost_0x7c', I),
        (0x80, 'cost_0x80', I), (0x84, 'cost_0x84', I), (0x88, 'cost_0x88', I),
        (0x8c, 'cost_0x8c', I),        # 7 values -> node+0x6c..0x84 (cost array)
        (0x90, 'time_ms', I),          # guess: build/research time
        (0xa4, 'object_index', I),     # dbobjects record index (value match)
        (0xb0, 'string_id', I),        # matches db/string-graphic info.txt
    ],
    'dbevents': [],
}


# --------------------------------------------------------------------------
# column inference for unnamed bytes
# --------------------------------------------------------------------------
def _printable_str(b):
    s = b.split(b'\0', 1)[0]
    if len(s) < 2 or len(s) == len(b):
        return None
    if sum(1 for c in s if 48 <= c < 123 and chr(c).isalnum()) < 2:
        return None
    if all(32 <= c < 127 or c == 9 or 0xa0 <= c < 0xff for c in s):
        return s
    return None


def _is_nice_float(b):
    v = struct.unpack('<f', b)[0]
    if v != v or v in (float('inf'), float('-inf')):
        return False
    if v == 0.0:
        return True
    a = abs(v)
    return 1e-6 <= a <= 1e9 and isinstance(rc._f32_value(b), (int, float))


def infer_schema(recs, size, known):
    """Return a schema covering exactly `size` bytes. `recs` is a list of
    bytes objects of that size (used only to choose column types)."""
    fields = list(known)
    taken = bytearray(size)
    for off, _, t in fields:
        for k in range(off, off + rc.size_of(t)):
            taken[k] = 1
    sample = recs[:4000]
    n = max(1, len(sample))
    # strings: a 4-aligned offset where >=30% records hold a terminated string
    off = 0
    while off < size:
        if taken[off] or off % 4:
            off += 1
            continue
        hits = 0
        maxlen = 0
        for r in sample:
            s = _printable_str(r[off:size])
            if s is not None:
                hits += 1
                maxlen = max(maxlen, len(s) + 1)
        if hits / n >= 0.3 and maxlen >= 4:
            end = min(size, off + (maxlen + 3) // 4 * 4)
            if all(not taken[k] for k in range(off, end)):
                fields.append((off, 's_0x%x' % off, ('str', end - off)))
                for k in range(off, end):
                    taken[k] = 1
                off = end
                continue
        off += 4
    # remaining dwords: int or float
    off = 0
    while off < size:
        if taken[off]:
            off += 1
            continue
        if off % 4 or off + 4 > size or any(taken[off:off + 4]):
            # unaligned leftover byte run up to next taken byte / alignment
            end = off + 1
            while end < size and not taken[end] and end % 4:
                end += 1
            fields.append((off, 'x_0x%x' % off, ('bytes', end - off)))
            off = end
            continue
        col = [r[off:off + 4] for r in sample]
        ints = [struct.unpack('<i', c)[0] for c in col]
        if all(-10000000 <= v <= 10000000 for v in ints):
            t, nm = I, 'i_0x%x' % off
        elif all(_is_nice_float(c) for c in col):
            t, nm = F, 'f_0x%x' % off
        else:
            t, nm = ('bytes', 4), 'x_0x%x' % off
        fields.append((off, nm, t))
        off += 4
    return rc.pad_schema(fields, size)


# --------------------------------------------------------------------------
# schema <-> JSON
# --------------------------------------------------------------------------
def schema_to_json(schema):
    def t2j(t):
        if isinstance(t, str):
            return t
        if t[0] == 'struct':
            return ['struct', schema_to_json(t[1])]
        if t[0] in ('arr', 'list'):
            return [t[0]] + [t2j(x) if not isinstance(x, int) else x for x in t[1:]]
        return list(t)
    return [[n, t2j(t)] for n, t in schema]


def schema_from_json(js):
    def j2t(t):
        if isinstance(t, str):
            return t
        if t[0] == 'struct':
            return ('struct', schema_from_json(t[1]))
        if t[0] in ('arr', 'list'):
            return tuple([t[0]] + [j2t(x) if not isinstance(x, int) else x for x in t[1:]])
        return tuple(t)
    return [(n, j2t(t)) for n, t in js]


def _strip_notes(rec):
    return {k: v for k, v in rec.items() if not k.startswith('#')}


def _decode_records(raws, schema):
    return [rc.read_struct(rc.Reader(r), schema) for r in raws]


# --------------------------------------------------------------------------
# unpack
# --------------------------------------------------------------------------
def table_name(path):
    return os.path.splitext(os.path.basename(path))[0].lower()


def unpack_bytes(name, data):
    out = {'format': FORMAT_TAG, 'table': name}
    if name in FIXED:
        size, loader = FIXED[name]
        count = struct.unpack_from('<I', data, 0)[0]
        out.update(layout='fixed', record_size=size, loader=loader)
        end = 4 + count * size
        if end > len(data):
            raise ValueError('%s: count %d x %d exceeds file size %d' % (name, count, size, len(data)))
        raws = [data[4 + i * size:4 + (i + 1) * size] for i in range(count)]
        schema = infer_schema(raws, size, KNOWN.get(name, [])) if size else []
        out['schema'] = schema_to_json(schema)
        out['records'] = _decode_records(raws, schema)
        out['trailing'] = data[end:].hex()
    elif name in WS_FIXED:
        size, loader = WS_FIXED[name]
        r = rc.Reader(data)
        count = rc.read(r, 'u32')
        strs, raws = [], []
        for _ in range(count):
            strs.append(rc.read(r, ('pstr', 'u32')))
            raws.append(r.take(size))
        schema = infer_schema(raws, size, KNOWN.get(name, []))
        out.update(layout='ws_fixed', record_size=size, loader=loader,
                   schema=schema_to_json(schema))
        recs = _decode_records(raws, schema)
        out['records'] = [dict({'path': s}, **rec) for s, rec in zip(strs, recs)]
        out['trailing'] = data[r.p:].hex()
    elif name in BLOB:
        size, n, loader = BLOB[name]
        if len(data) < size * n:
            raise ValueError('%s: short file' % name)
        raws = [data[i * size:(i + 1) * size] for i in range(n)]
        schema = infer_schema(raws, size, KNOWN.get(name, []))
        out.update(layout='blob', record_size=size, record_count=n, loader=loader,
                   schema=schema_to_json(schema))
        out['records'] = _decode_records(raws, schema)
        out['trailing'] = data[size * n:].hex()
    elif name == 'dbevents':
        out.update(layout='events', loader='FUN_008d2fc0 (id 8)', slots=1500)
        r = rc.Reader(data)
        recs = []
        for _ in range(1500):
            recs.append({
                'name': rc.read(r, ('str', 100)),
                'id': rc.read(r, 'i32'),
                'flag': rc.read(r, 'u8'),
                'effects': rc.read(r, ('list', 'u32', 'i32')),
            })
        out['records'] = recs
        out['trailing'] = data[r.p:].hex()
    elif name == 'dbtechtree':
        out.update(layout='techtree', loader='FUN_008d8260 -> FUN_008dff40 / FUN_008e5550 (6)',
                   node_size=452)
        r = rc.Reader(data)
        roots_raw = []
        for _ in range(14):
            n = rc.read(r, 'u32')
            root = _tt_node_raw(r)
            kids = [_tt_node_raw(r) for _ in range(n)]
            roots_raw.append((root, kids))
        allraw = [x[0][0] for x in roots_raw] + [k[0] for x in roots_raw for k in x[1]]
        schema = infer_schema(allraw, 452, KNOWN['dbtechtree'])
        out['schema'] = schema_to_json(schema)

        def dec(nr):
            rec = rc.read_struct(rc.Reader(nr[0]), schema)
            rec['list_a'] = nr[1]
            rec['list_b'] = nr[2]
            return rec
        out['roots'] = [dict(dec(root), children=[dec(k) for k in kids]) for root, kids in roots_raw]
        out['trailing'] = data[r.p:].hex()
    else:
        raise ValueError('unknown table %s' % name)
    _annotate(out)
    return out


def _tt_node_raw(r):
    raw = r.take(452)
    a = rc.read(r, ('list', 'u32', 'i32'))
    b = rc.read(r, ('list', 'u32', 'i32'))
    return raw, a, b


def _annotate(out):
    if out['table'] == 'dbcpbehavior':
        for rec in out['records']:
            names = CP_PARAM_NAMES.get(rec.get('id'))
            if names:
                rec['#names'] = names


# --------------------------------------------------------------------------
# pack
# --------------------------------------------------------------------------
def pack_obj(obj):
    if obj.get('format') != FORMAT_TAG:
        raise ValueError('not a %s file' % FORMAT_TAG)
    lay = obj['layout']
    trailing = bytes.fromhex(obj.get('trailing', ''))
    if lay == 'events':
        parts = []
        if len(obj['records']) != obj['slots']:
            raise ValueError('dbevents must have exactly %d slots' % obj['slots'])
        for rec in obj['records']:
            parts.append(rc.write(('str', 100), rec['name']))
            parts.append(rc.write('i32', rec['id']))
            parts.append(rc.write('u8', rec['flag']))
            parts.append(rc.write(('list', 'u32', 'i32'), rec['effects']))
        return b''.join(parts) + trailing
    schema = schema_from_json(obj['schema'])
    if lay == 'techtree':
        parts = []
        if len(obj['roots']) != 14:
            raise ValueError('dbtechtree must have 14 epoch roots')

        def enc(n):
            return (rc.write_struct(schema, _strip_notes(n)) +
                    rc.write(('list', 'u32', 'i32'), n['list_a']) +
                    rc.write(('list', 'u32', 'i32'), n['list_b']))
        for root in obj['roots']:
            parts.append(rc.write('u32', len(root['children'])))
            parts.append(enc(root))
            parts.extend(enc(k) for k in root['children'])
        return b''.join(parts) + trailing
    recs = obj['records']
    if lay == 'fixed':
        body = b''.join(rc.write_struct(schema, _strip_notes(x)) for x in recs)
        return rc.write('u32', len(recs)) + body + trailing
    if lay == 'ws_fixed':
        body = b''.join(rc.write(('pstr', 'u32'), x['path']) +
                        rc.write_struct(schema, _strip_notes(x)) for x in recs)
        return rc.write('u32', len(recs)) + body + trailing
    if lay == 'blob':
        if len(recs) != obj['record_count']:
            raise ValueError('blob table needs exactly %d records' % obj['record_count'])
        return b''.join(rc.write_struct(schema, _strip_notes(x)) for x in recs) + trailing
    raise ValueError('unknown layout %s' % lay)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
ALL_TABLES = sorted(list(FIXED) + list(WS_FIXED) + list(BLOB) + ['dbevents', 'dbtechtree'])


def _dump(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def cmd_unpack(src, dst):
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for fn in sorted(os.listdir(src)):
            if fn.lower().endswith('.dat') and table_name(fn) in ALL_TABLES:
                obj = unpack_bytes(table_name(fn), open(os.path.join(src, fn), 'rb').read())
                obj['source_name'] = fn
                _dump(obj, os.path.join(dst, table_name(fn) + '.json'))
                print('unpacked', fn)
    else:
        obj = unpack_bytes(table_name(src), open(src, 'rb').read())
        obj['source_name'] = os.path.basename(src)
        _dump(obj, dst)


def cmd_pack(src, dst):
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for fn in sorted(os.listdir(src)):
            if fn.endswith('.json'):
                obj = _load(os.path.join(src, fn))
                name = obj.get('source_name', obj['table'] + '.dat')
                open(os.path.join(dst, name), 'wb').write(pack_obj(obj))
                print('packed', name)
    else:
        open(dst, 'wb').write(pack_obj(_load(src)))


def cmd_roundtrip(src, keep=None):
    ok = fail = 0
    for fn in sorted(os.listdir(src)):
        if not fn.lower().endswith('.dat'):
            continue
        name = table_name(fn)
        data = open(os.path.join(src, fn), 'rb').read()
        if name not in ALL_TABLES:
            print('SKIP  %s (no layout)' % fn)
            continue
        try:
            obj = unpack_bytes(name, data)
            text = json.dumps(obj, ensure_ascii=False)
            obj2 = json.loads(text)
            out = pack_obj(obj2)
            if keep:
                os.makedirs(keep, exist_ok=True)
                _dump(obj2, os.path.join(keep, name + '.json'))
            if out == data:
                ok += 1
                nrec = len(obj.get('records', obj.get('roots', [])))
                print('OK    %-32s %9d bytes  %5d records' % (fn, len(data), nrec))
            else:
                fail += 1
                first = next((i for i, (a, b) in enumerate(zip(out, data)) if a != b), min(len(out), len(data)))
                print('FAIL  %-32s size %d vs %d, first diff at %d' % (fn, len(out), len(data), first))
        except Exception as e:  # report and go on
            fail += 1
            print('ERROR %-32s %s: %s' % (fn, type(e).__name__, e))
    print('roundtrip: %d identical, %d failed' % (ok, fail))
    return fail == 0


def cmd_cpbehavior(path):
    obj = unpack_bytes('dbcpbehavior', open(path, 'rb').read())
    print('%4s %8s %8s %10s  %s' % ('id', 'v4', 'v7', 'v12', 'names (v4 | v7 | v12)'))
    for rec in obj['records']:
        v12 = rec['v12']
        v12s = ('%g' % v12) if isinstance(v12, (int, float)) else str(v12)
        nm = rec.get('#names', {})
        print('%4d %8d %8d %10s  %s' % (rec['id'], rec['v4'], rec['v7'], v12s,
                                        ' | '.join('%s=%s' % (k, nm[k]) for k in ('v4', 'v7', 'v12') if k in nm)))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == 'unpack' and len(argv) == 4:
        cmd_unpack(argv[2], argv[3])
    elif cmd == 'pack' and len(argv) == 4:
        cmd_pack(argv[2], argv[3])
    elif cmd == 'roundtrip' and len(argv) >= 3:
        keep = argv[argv.index('--keep') + 1] if '--keep' in argv else None
        return 0 if cmd_roundtrip(argv[2], keep) else 1
    elif cmd == 'cpbehavior' and len(argv) == 3:
        cmd_cpbehavior(argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
