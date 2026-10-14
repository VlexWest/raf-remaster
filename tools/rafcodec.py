"""Lossless binary <-> JSON codec primitives for Rise and Fall data files.

A schema is a list of (name, type) pairs. Types:
  'u8' 'i8' 'u16' 'i16' 'u32' 'i32' 'f32' 'bool8'
  ('str', N)        fixed char[N], NUL-terminated, latin-1. Bytes after the NUL are kept
                    (the game's editor wrote uninitialised memory there).
  ('bytes', N)      opaque block, hex in JSON
  ('arr', T, N)     fixed array of N items of type T
  ('list', CT, T)   count of type CT followed by that many items of type T
  ('pstr', CT)      length-prefixed string (count CT, latin-1, kept verbatim)
  ('struct', schema)
Every value must round-trip to the exact same bytes. Values that would not
(NaN payloads, odd floats) are written as {"hex": "..."}.
"""
import math
import struct

_SIMPLE = {
    'u8': '<B', 'i8': '<b', 'u16': '<H', 'i16': '<h',
    'u32': '<I', 'i32': '<i', 'f32': '<f', 'bool8': '<B',
}


class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def take(self, n):
        if self.p + n > len(self.d):
            raise EOFError('read past end at %d (+%d) of %d' % (self.p, n, len(self.d)))
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def eof(self):
        return self.p >= len(self.d)


def _f32_value(b):
    v = struct.unpack('<f', b)[0]
    if math.isfinite(v):
        # shortest repr that packs back to the same bits
        for digits in range(6, 12):
            r = float('%.*g' % (digits, v))
            if struct.pack('<f', r) == b:
                return int(r) if r == int(r) and abs(r) < 1e15 and '.' not in repr(r) else r
        if struct.pack('<f', v) == b:
            return v
    return {'hex': b.hex()}


def read(r, t):
    if isinstance(t, str):
        if t == 'f32':
            return _f32_value(r.take(4))
        fmt = _SIMPLE[t]
        return struct.unpack(fmt, r.take(struct.calcsize(fmt)))[0]
    kind = t[0]
    if kind == 'str':
        b = r.take(t[1])
        s, _, tail = b.partition(b'\0')
        if tail.strip(b'\0') or len(s) == t[1]:
            if len(s) == t[1]:
                return {'s': s.decode('latin-1'), 'full': True}
            return {'s': s.decode('latin-1'), 'tail': tail.hex()}
        return s.decode('latin-1')
    if kind == 'bytes':
        return r.take(t[1]).hex()
    if kind == 'arr':
        return [read(r, t[1]) for _ in range(t[2])]
    if kind == 'list':
        n = read(r, t[1])
        if n > 1000000:
            raise ValueError('implausible list count %d at %d' % (n, r.p))
        return [read(r, t[2]) for _ in range(n)]
    if kind == 'pstr':
        n = read(r, t[1])
        return r.take(n).decode('latin-1')
    if kind == 'struct':
        return read_struct(r, t[1])
    raise ValueError(t)


def read_struct(r, schema):
    out = {}
    for name, t in schema:
        out[name] = read(r, t)
    return out


def write(t, v):
    if isinstance(v, dict) and 'hex' in v and len(v) == 1:
        return bytes.fromhex(v['hex'])
    if isinstance(t, str):
        if t == 'f32':
            return struct.pack('<f', float(v))
        return struct.pack(_SIMPLE[t], v)
    kind = t[0]
    if kind == 'str':
        n = t[1]
        if isinstance(v, dict):
            s = v['s'].encode('latin-1')
            if v.get('full'):
                b = s
            else:
                tail = bytes.fromhex(v.get('tail', ''))
                b = s + b'\0' + tail
        else:
            b = v.encode('latin-1') + b'\0'
        if len(b) > n:
            raise ValueError('string too long for char[%d]: %r' % (n, v))
        return b + b'\0' * (n - len(b))
    if kind == 'bytes':
        b = bytes.fromhex(v)
        assert len(b) == t[1], (len(b), t[1])
        return b
    if kind == 'arr':
        assert len(v) == t[2]
        return b''.join(write(t[1], x) for x in v)
    if kind == 'list':
        return write(t[1], len(v)) + b''.join(write(t[2], x) for x in v)
    if kind == 'pstr':
        b = v.encode('latin-1')
        return write(t[1], len(b)) + b
    if kind == 'struct':
        return write_struct(t[1], v)
    raise ValueError(t)


def write_struct(schema, v):
    return b''.join(write(t, v[name]) for name, t in schema)


def size_of(t):
    """Byte size of a fixed-size type, or None if variable."""
    if isinstance(t, str):
        return struct.calcsize(_SIMPLE[t])
    kind = t[0]
    if kind in ('str', 'bytes'):
        return t[1]
    if kind == 'arr':
        s = size_of(t[1])
        return None if s is None else s * t[2]
    if kind == 'struct':
        tot = 0
        for _, ft in t[1]:
            s = size_of(ft)
            if s is None:
                return None
            tot += s
        return tot
    return None


def pad_schema(fields, total):
    """Fill gaps between (offset, name, type) fields with raw byte blocks so the
    record is exactly `total` bytes. Returns an ordered schema."""
    out = []
    pos = 0
    for off, name, t in sorted(fields, key=lambda f: f[0]):
        if off < pos:
            raise ValueError('overlapping field %s at %d (pos %d)' % (name, off, pos))
        if off > pos:
            out.append(('_raw_%d' % pos, ('bytes', off - pos)))
        out.append((name, t))
        pos = off + size_of(t)
    if pos < total:
        out.append(('_raw_%d' % pos, ('bytes', total - pos)))
    if pos > total:
        raise ValueError('fields run past record size %d' % total)
    return out
