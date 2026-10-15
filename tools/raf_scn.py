"""Rise and Fall scenario (.scn) reader/writer, focused on the trigger system.

File layout (see docs/scenario-format.md):

    u32  payload_length            (= file size - 4)
    header                         (parse_header/build_header: names, version 4.0, game setup
                                    with 16 player slots, chunk type list, map id)
    chunk*                         FSChunk: u32 ver_major, u32 ver_minor, u32 type, u32 size, data[size]
    u32  map id                    (same value as header['map_id'])

Chunk data is an FSMemoryFile: either raw, or "ZL01" + u32 raw_size + u32 0 + zlib stream.
Chunk type 6 is the scenario manager (EEScenarioManager): triggers, conditions, effects,
scenario objects, areas, cameras, ... Its serialisation is reproduced by `Manager` below.

Usage:
    python tools/raf_scn.py chunks <file.scn>
    python tools/raf_scn.py dump <file.scn> [--json out.json]
    python tools/raf_scn.py roundtrip <file.scn|dir>...
    python tools/raf_scn.py stock <game_dir>        (round trip every shipped scenario)
"""
import json
import os
import struct
import sys
import zlib

# --------------------------------------------------------------------------- binary io


class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def _take(self, n):
        if self.p + n > len(self.d):
            raise ValueError('read past end at 0x%x (+%d of %d)' % (self.p, n, len(self.d)))
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u32(self):
        return struct.unpack('<I', self._take(4))[0]

    def i32(self):
        return struct.unpack('<i', self._take(4))[0]

    def f32(self):
        return struct.unpack('<f', self._take(4))[0]

    def bool(self):
        v = self._take(1)[0]
        if v > 1:
            raise ValueError('bool byte %d at 0x%x' % (v, self.p - 1))
        return v

    def uws(self):
        n = self.u32()
        if n > 1 << 20:
            raise ValueError('string length %d at 0x%x' % (n, self.p - 4))
        return self._take(n)


class Writer:
    def __init__(self):
        self.b = bytearray()

    def u32(self, v):
        self.b += struct.pack('<I', v & 0xffffffff)

    def i32(self, v):
        self.b += struct.pack('<i', v)

    def f32(self, v):
        self.b += struct.pack('<f', v)

    def bool(self, v):
        self.b.append(1 if v else 0)

    def uws(self, v):
        self.b += struct.pack('<I', len(v)) + v


def S(text):
    """Text -> UWideString bytes (cp1251 = the Russian release's text encoding, two NULs, as
    the game writes them; ASCII is identical in every code page)."""
    if isinstance(text, bytes):
        return text
    return text.encode('cp1251') + b'\0\0'


def T(raw):
    """UWideString bytes -> text."""
    return raw.rstrip(b'\0').decode('cp1251', 'replace')


# --------------------------------------------------------------------------- chunk file


class ScnFile:
    def __init__(self, data):
        self.data = data
        (plen,) = struct.unpack_from('<I', data, 0)
        if plen != len(data) - 4:
            raise ValueError('not a plain scenario (first u32 %x, size %x); campaign files are'
                             ' compressed as a whole, unpack them first' % (plen, len(data)))
        start = self._find_chain(data)
        if start is None:
            raise ValueError('chunk chain not found')
        self.header = data[4:start]
        self.trailer = data[-4:]
        self.chunks = []  # [major, minor, type, payload(bytes as stored)]
        p = start
        while p < len(data) - 4:
            maj, mn, typ, sz = struct.unpack_from('<IIII', data, p)
            self.chunks.append([maj, mn, typ, data[p + 16:p + 16 + sz]])
            p += 16 + sz

    @staticmethod
    def _find_chain(d):
        first_z = d.find(b'ZL01')
        if first_z < 0:
            return None
        for start in range(4, first_z):
            p, n = start, 0
            while p + 16 <= len(d) - 4:
                maj, mn, typ, sz = struct.unpack_from('<IIII', d, p)
                if maj != 4 or mn != 0 or typ > 64 or p + 16 + sz > len(d) - 4:
                    break
                p += 16 + sz
                n += 1
            if p == len(d) - 4 and n >= 5:
                return start
        return None

    def chunk(self, typ):
        for c in self.chunks:
            if c[2] == typ:
                return c
        raise KeyError(typ)

    def get(self, typ):
        return unpack_chunk(self.chunk(typ)[3])

    def put(self, typ, raw, compress=True):
        self.chunk(typ)[3] = pack_chunk(raw) if compress else raw

    def to_bytes(self):
        body = bytearray(self.header)
        for maj, mn, typ, payload in self.chunks:
            body += struct.pack('<IIII', maj, mn, typ, len(payload)) + payload
        body += self.trailer
        return struct.pack('<I', len(body)) + bytes(body)


def unpack_chunk(payload):
    if len(payload) > 12 and payload[:4] == b'ZL01':
        raw_size, zero = struct.unpack_from('<II', payload, 4)
        raw = zlib.decompress(payload[12:])
        if len(raw) != raw_size:
            raise ValueError('ZL01 size mismatch')
        return raw
    return payload


def pack_chunk(raw, level=9):
    return b'ZL01' + struct.pack('<II', len(raw), 0) + zlib.compress(raw, level)


# --------------------------------------------------------------------------- scenario manager
# Field specs: (name, type).  'u32','i32','f32','bool','uws'.  Subclass fields come first,
# then the base class (that is the order of the game's Load functions).

CB = [('name', 'uws'), ('desc', 'uws')]                     # EESMComponentBase 0x8a9c30
COND = [('c_unused38', 'u32')] + CB                         # EESMCondition 0x8a9d20
EFF = [('e_unused38', 'u32')] + CB                          # EESMEffect 0x8afac0
EOBJ = [('object', 'u32')] + EFF                            # EESMEObject 0x8b7450
EPLR = [('player', 'u32')] + EFF                            # EESMEPlayer 0x8c40d0
EAI = [('player', 'u32')] + EFF                             # EESMEAI 0x8ab3e0

# condition type id -> (class, fields)        factory FUN_008a9e30
CONDITIONS = {
    0: ('AlwaysTrue', COND),
    1: ('ObjectExists', [('object', 'u32')] + COND),
    2: ('PlayerHasResource', [('player', 'u32'), ('resource', 'u32'), ('f50', 'u32'),
                              ('compare', 'u32'), ('amount', 'u32'), ('f48', 'u32'),
                              ('f54', 'bool')] + COND),
    3: ('PlayerHasTechnology', [('player', 'u32'), ('tech', 'i32')] + COND),
    4: ('PlayerDefeated', [('player', 'u32')] + COND),
    5: ('TriggerHasAttribute', [('trigger', 'u32'), ('attr40', 'bool'), ('attr41', 'bool')] + COND),
    6: ('PlayerHasDiplomacy', [('player2', 'u32'), ('stance', 'u32'), ('player', 'u32')] + COND),
    7: ('GameHasAttribute', [('b3c', 'bool'), ('b3d', 'bool'), ('b3e', 'bool'), ('u40', 'u32'),
                             ('u48', 'u32'), ('u44', 'u32'), ('u4c', 'u32')] + COND),
    8: ('GameCounter', [('counter', 'u32'), ('value', 'u32'), ('compare', 'bool')] + COND),
    9: ('ChatMessageEquals', [('player', 'u32'), ('text', 'uws')] + COND),
    10: ('CanPath', [('object', 'u32'), ('area', 'u32')] + COND),
    11: ('CanRam', [('object', 'u32'), ('target', 'u32')] + COND),
    12: ('PlayingCameraScript', COND),
    13: ('HaveDialogMessage', COND),
}

# (category, id) -> (class, fields)           factory FUN_008b1550
EFFECTS = {
    (0, 0): ('DoNothing', EFF),
    # category 1: objects
    (1, 0): ('Create', EOBJ),
    (1, 1): ('Freeze', EOBJ),
    (1, 2): ('Unfreeze', EOBJ),
    (1, 3): ('KillUnit', EOBJ),
    (1, 4): ('RemoveUnit', EOBJ),
    (1, 5): ('TaskToObject', [('target', 'u32'), ('task', 'u32'), ('b48', 'bool')] + EOBJ),
    (1, 6): ('TaskToArea', [('area', 'u32'), ('task', 'u32'), ('b48', 'bool')] + EOBJ),
    (1, 7): ('SetStance', [('stance', 'u32')] + EOBJ),
    (1, 8): ('ChangeUnitAttribute', [('attr', 'u32'), ('op', 'u32'), ('value', 'u32'),
                                     ('b4c', 'bool'), ('u50', 'u32')] + EOBJ),
    (1, 9): ('ChangeOwner', [('new_player', 'u32')] + EOBJ),
    (1, 10): ('ChangeUnitClassName', [('text', 'uws'), ('b', 'bool')] + EOBJ),
    (1, 11): ('FaceObject', [('target', 'u32'), ('u44', 'u32'), ('b48', 'bool')] + EOBJ),
    (1, 12): ('ChangeUnitClassAttribute', [('attr', 'u32'), ('op', 'u32'), ('value', 'u32'),
                                           ('b4c', 'bool'), ('u50', 'u32'), ('i54', 'i32')] + EOBJ),
    (1, 13): ('ChangeUnitName', [('text', 'uws'), ('b1', 'bool'), ('b2', 'bool')] + EOBJ),
    (1, 14): ('ReplaceObjects', [('with_object', 'u32')] + EOBJ),
    (1, 15): ('ChangeAnimation', 'animation'),
    (1, 16): ('SetMedal', [('medal', 'u32'), ('b', 'bool')] + EOBJ),
    (1, 17): ('MountObject', [('mount', 'u32')] + EOBJ),
    (1, 18): ('MakeFormation', EOBJ),
    (1, 19): ('BreakFormation', EOBJ),
    (1, 20): ('CreateUnitSpawner', 'spawner'),
    (1, 21): ('DeleteUnitSpawner', [('creation_effect', 'u32')] + EOBJ),
    (1, 22): ('ResearchTechnology', [('tech', 'i32'), ('b44', 'bool'), ('i48', 'i32')] + EOBJ),
    (1, 23): ('AddToPhysicsUpdate', EOBJ),
    (1, 24): ('RemoveFromPhysicsUpdate', EOBJ),
    # category 2: players
    (2, 0): ('Victory', EPLR),
    (2, 1): ('ScriptCamera', [('b40', 'bool'), ('u44', 'u32'), ('u48', 'u32'), ('b4c', 'bool'),
                              ('u50', 'u32'), ('u54', 'u32'), ('b58', 'bool'), ('b59', 'bool'),
                              ('i5c', 'i32'), ('i60', 'i32'), ('b64', 'bool'), ('u68', 'u32')] + EPLR),
    (2, 2): ('Defeat', EPLR),
    (2, 3): ('ChangeDiplomaticStance', [('other', 'u32'), ('stance', 'u32'), ('b48', 'bool')] + EPLR),
    (2, 4): ('ChangeResourceLevel', [('resource', 'u32'), ('amount', 'u32'), ('text', 'uws')] + EPLR),
    (2, 5): ('ModifyTechnology', [('tech', 'i32'), ('u44', 'u32'), ('b48', 'bool')] + EPLR),
    (2, 6): ('NoBuildZone', [('area', 'u32'), ('u44', 'u32'), ('b48', 'bool')] + EPLR),
    (2, 7): ('CameraFadeIn', [('ms', 'i32')] + EPLR),
    (2, 8): ('CameraFadeOut', [('ms', 'i32')] + EPLR),
    (2, 9): ('ChangeVisibility', [('u40', 'u32'), ('b44', 'bool'), ('b45', 'bool'), ('u48', 'u32'),
                                  ('b4c', 'bool'), ('u50', 'u32')] + EPLR),
    (2, 10): ('MiniMapFlare', [('b40', 'bool'), ('b41', 'bool'), ('b42', 'bool'), ('b43', 'bool'),
                               ('u44', 'u32'), ('u48', 'u32')] + EPLR),
    (2, 11): ('Objective', [('u40', 'u32'), ('u44', 'u32')] + EPLR),
    (2, 12): ('RenameCiv', [('text', 'uws')] + EPLR),
    (2, 13): ('Player13', [('b', 'bool')] + EPLR),
    (2, 14): ('Player14', [('b', 'bool')] + EPLR),
    (2, 15): ('ActivateHeroBotAI', [('on', 'bool')] + EPLR),
    # category 3
    (3, 0): ('Trigger', [('trigger', 'u32'), ('action', 'u32')] + EFF),
    # category 4: media
    (4, 0): ('PlaySound', [('sound', 'uws')] + EFF + [('f54', 'f32'), ('b60', 'bool'), ('i58', 'i32'),
                                                     ('u5c', 'u32'), ('b61', 'bool')]),
    (4, 1): ('ChangeScenarioText', [('text', 'uws'), ('b54', 'bool'), ('u58', 'u32')] + EFF),
    (4, 2): ('SendDialogueMessage', [('text', 'uws'), ('u54', 'u32'), ('u58', 'u32'), ('u5c', 'u32'),
                                     ('text2', 'uws'), ('i78', 'i32'), ('i7c', 'i32')] + EFF),
    (4, 3): ('SendChatMessage', [('text', 'uws'), ('u54', 'u32'), ('u58', 'u32'), ('b5c', 'bool')] + EFF),
    (4, 4): ('QuestionBox', 'questionbox'),
    (4, 5): ('PlayMusic', [('u3c', 'u32'), ('u40', 'u32')] + EFF),
    (4, 6): ('StopMusic', [('u3c', 'u32')] + EFF),
    (4, 7): ('SetMusicGrooveLevel', [('u3c', 'u32'), ('u40', 'u32')] + EFF),
    (4, 8): ('SetMusicMoodLevel', [('u3c', 'u32'), ('u40', 'u32')] + EFF),
    # category 5: game
    (5, 0): ('SetTime', [('u3c', 'u32')] + EFF),
    (5, 1): ('SetDayNightCycle', [('u3c', 'u32')] + EFF),
    (5, 2): ('StartCalamity', [('u3c', 'u32'), ('u40', 'u32'), ('u44', 'u32'), ('u48', 'u32'),
                               ('b4c', 'bool')] + EFF),
    (5, 3): ('GraphicEffect', [('effect', 'uws'), ('b', 'bool'), ('u1', 'u32'), ('u2', 'u32'),
                               ('b2', 'bool'), ('f', 'f32'), ('u3', 'u32'), ('u4', 'u32')] + EFF),
    (5, 4): ('StartCinematicMode', [('u3c', 'u32'), ('u40', 'u32'), ('b44', 'bool')] + EFF),
    (5, 5): ('EndCinematicMode', EFF),
    (5, 6): ('Counter', [('counter', 'uws'), ('i6c', 'i32'), ('b70', 'bool'), ('b71', 'bool'),
                         ('u74', 'u32'), ('text54', 'uws'), ('b72', 'bool')] + EFF),
    (5, 7): ('Environment', [('env', 'uws'), ('i54', 'i32'), ('b58', 'bool'), ('b59', 'bool')] + EFF),
    (5, 8): ('LoadNextScenario', EFF),
    (5, 9): ('SetSlowDeath', [('f3c', 'f32')] + EFF),
    (5, 10): ('SetGameSpeed', [('u3c', 'u32')] + EFF),
    (5, 11): ('SetIsHeroSwimmingEnabled', [('on', 'bool')] + EFF),
    # category 6: computer player
    (6, 0): ('AIModifyMilitaryTarget', [('u40', 'u32'), ('u44', 'u32'), ('b48', 'bool'),
                                        ('b49', 'bool'), ('b4a', 'bool')] + EAI),
    (6, 1): ('AICreateMilitaryGroup', 'aigroup'),
    (6, 2): ('AIBuildObject', [('u40', 'u32')] + EAI),
    (6, 3): ('AIMaintainObject', [('u40', 'u32')] + EAI),
    (6, 4): ('AIToggleSetting', [('setting', 'u32'), ('on', 'bool')] + EAI),
    (6, 5): ('AISetAttribute', [('attr', 'u32'), ('f44', 'f32'), ('i48', 'i32'), ('i4c', 'i32')] + EAI),
    (6, 6): ('AISetFavoriteUnits', [('u40', 'u32'), ('u44', 'u32'), ('u48', 'u32')] + EAI),
}


def effect_key(cat, typ):
    """FUN_008b1550: category 3 has one class whatever the id; id 0xfffffffe is case 0."""
    if cat == 3:
        return (3, 0)
    if typ == 0xfffffffe:
        return (cat, 0)
    return (cat, typ)


EFFECT_BY_NAME = {v[0]: k for k, v in EFFECTS.items()}
COND_BY_NAME = {v[0]: k for k, v in CONDITIONS.items()}

AREA_BASE = [('x', 'f32'), ('y', 'f32'), ('left', 'f32'), ('top', 'f32'), ('right', 'f32'),
             ('bottom', 'f32'), ('b80', 'bool'), ('b81', 'bool'), ('u74', 'u32'), ('u7c', 'u32'),
             ('u78', 'u32')] + CB                                       # 0x8a52a0
AREAS = {0: 'RectangularArea', 1: 'ContinentArea', 2: 'TownArea', 3: 'MountableObjectArea',
         4: 'CustomArea'}

# EESMObject 0x8cb780 (after name/desc and the unit id list)
OBJECT_FIELDS = [('bdc', 'bool'), ('player', 'u32'), ('u80', 'u32'), ('u84', 'u32'), ('u94', 'u32'),
                 ('class_name', 'uws'), ('unit_name', 'uws'), ('bdd', 'bool'),
                 ('ub4', 'u32'), ('ub8', 'u32'), ('ubc', 'u32'), ('uc0', 'u32'), ('uc4', 'u32'),
                 ('uc8', 'u32'), ('u88', 'u32'), ('u8c', 'u32'), ('u90', 'u32'), ('u98', 'u32'),
                 ('u9c', 'u32'), ('ua0', 'u32'), ('ua4', 'u32'), ('ua8', 'u32'), ('uac', 'u32'),
                 ('bde', 'bool'), ('ub0', 'u32'), ('bdf', 'bool'), ('be0', 'bool'), ('be1', 'bool'),
                 ('be2', 'bool'), ('ucc', 'u32'), ('ud0', 'u32'), ('ud4', 'u32'), ('ud8', 'u32')]

COUNTER_FIELDS = [('name', 'uws'), ('i1', 'i32'), ('b1', 'bool'), ('i2', 'i32'), ('b2', 'bool'),
                  ('b3', 'bool'), ('text', 'uws'), ('b4', 'bool')]                    # 0x8aa070
DIALOG_FIELDS = [('name', 'uws'), ('u1', 'u32'), ('text', 'uws'), ('u2', 'u32'), ('u3', 'u32'),
                 ('i4', 'i32'), ('b5', 'bool')]                                     # 0x885360


def rd(r, spec):
    o = {}
    for name, typ in spec:
        o[name] = getattr(r, typ)()
    return o


def wr(w, spec, o):
    for name, typ in spec:
        getattr(w, typ)(o[name])


def _ver_ge_3_2(ver):
    return ver[0] > 3 or (ver[0] == 3 and ver[1] > 1)


ANIM_STEP = [('f18', 'f32'), ('f20', 'f32'), ('u24', 'u32'), ('b30', 'bool'), ('name', 'uws'),
             ('i2c', 'i32'), ('f1c', 'f32'), ('i28', 'i32')]
SPAWNER_HEAD = [('u68', 'u32'), ('f48', 'f32'), ('f4c', 'f32'), ('u50', 'u32'), ('u54', 'u32')]
SPAWNER_MID = [('u58', 'u32'), ('u5c', 'u32'), ('b45', 'bool'), ('u60', 'u32'), ('u64', 'u32')]


def read_effect_body(r, kind, ver):
    if kind == 'spawner':                                            # 0x8bbe70
        o = rd(r, SPAWNER_HEAD)
        o['pairs'] = [(r.i32(), r.u32()) for _ in range(r.u32())]
        o.update(rd(r, SPAWNER_MID))
        o['ids'] = [r.u32() for _ in range(r.u32())]
        o['b46'] = r.bool()
        o['b47'] = r.bool()
        if _ver_ge_3_2(ver):
            o['b44'] = r.bool()
        o.update(rd(r, EOBJ))
        return o
    if kind == 'questionbox':                                        # 0x8b60d0
        o = {'text': r.uws(), 'u54': r.u32()}
        o['answers'] = [(r.i32(), r.uws()) for _ in range(r.u32())]
        o.update(rd(r, EFF))
        return o
    if kind == 'aigroup':                                            # 0x8abed0
        o = rd(r, [('u40', 'u32'), ('u44', 'u32'), ('b1', 'bool'), ('b2', 'bool'), ('b3', 'bool')])
        o['ids'] = [r.u32() for _ in range(r.u32())]
        o.update(rd(r, EAI))
        return o
    if kind == 'animation':                                          # 0x8b8290
        o = {'keys': []}
        for _ in range(r.u32()):
            key = r.u32()
            o['keys'].append((key, [rd(r, ANIM_STEP) for _ in range(r.u32())]))
        o.update(rd(r, [('anim', 'uws'), ('b64', 'bool')] + EOBJ))
        return o
    return rd(r, kind)


def write_effect_body(w, kind, o, ver):
    if kind == 'spawner':
        wr(w, SPAWNER_HEAD, o)
        w.u32(len(o['pairs']))
        for a, b in o['pairs']:
            w.i32(a)
            w.u32(b)
        wr(w, SPAWNER_MID, o)
        w.u32(len(o['ids']))
        for x in o['ids']:
            w.u32(x)
        w.bool(o['b46'])
        w.bool(o['b47'])
        if _ver_ge_3_2(ver):
            w.bool(o['b44'])
        wr(w, EOBJ, o)
        return
    if kind == 'questionbox':
        w.uws(o['text'])
        w.u32(o['u54'])
        w.u32(len(o['answers']))
        for a, t in o['answers']:
            w.i32(a)
            w.uws(t)
        wr(w, EFF, o)
        return
    if kind == 'aigroup':
        wr(w, [('u40', 'u32'), ('u44', 'u32'), ('b1', 'bool'), ('b2', 'bool'), ('b3', 'bool')], o)
        w.u32(len(o['ids']))
        for x in o['ids']:
            w.u32(x)
        wr(w, EAI, o)
        return
    if kind == 'animation':
        w.u32(len(o['keys']))
        for key, steps in o['keys']:
            w.u32(key)
            w.u32(len(steps))
            for st in steps:
                wr(w, ANIM_STEP, st)
        wr(w, [('anim', 'uws'), ('b64', 'bool')] + EOBJ, o)
        return
    wr(w, kind, o)


TRIGGER_FIELDS = [('on', 'bool'), ('looping', 'bool'), ('b8d', 'bool'), ('u7c', 'u32'),
                  ('b8f', 'bool'), ('true_for', 'u32'), ('u84', 'u32'), ('f78', 'f32'),
                  ('f74', 'f32'), ('u88', 'u32')]                                    # 0x8d2760


class Manager:
    """EEScenarioManager stream (chunk 6), FUN_008a1c00."""

    def __init__(self):
        self.triggers = []
        self.conditions = []
        self.effects = []
        self.objects = []
        self.areas = []
        self.cameras = []
        self.list7 = []
        self.list8 = []
        self.pending = []
        self.tail = b''

    @classmethod
    def parse(cls, raw, ver=(4, 0), full_tail=False):
        m = cls()
        r = Reader(raw)
        for _ in range(r.u32()):
            t = rd(r, CB + TRIGGER_FIELDS)
            t['if'] = [(r.bool(), r.u32(), r.u32()) for _ in range(r.u32())]     # not, op, cond
            t['then'] = [(r.u32(), r.u32(), r.u32()) for _ in range(r.u32())]   # delay, op, effect
            t['else'] = [(r.u32(), r.u32(), r.u32()) for _ in range(r.u32())]
            m.triggers.append(t)
        for _ in range(r.u32()):
            typ = r.u32()
            if typ not in CONDITIONS:
                raise ValueError('unknown condition type %d at 0x%x' % (typ, r.p))
            o = rd(r, CONDITIONS[typ][1])
            o['_type'] = typ
            m.conditions.append(o)
        for _ in range(r.u32()):
            cat, typ = r.u32(), r.u32()
            m.effects.append(m._read_effect(r, cat, typ, ver))
        for _ in range(r.u32()):
            o = rd(r, CB)
            o['units'] = [r.u32() for _ in range(r.u32())]
            o.update(rd(r, OBJECT_FIELDS))
            m.objects.append(o)
        for _ in range(r.u32()):
            typ = r.u32()
            o = {'_type': typ}
            if typ == 4:
                o['points'] = [(r.i32(), r.i32()) for _ in range(r.u32())]
            elif typ == 3:
                o.update(rd(r, [('mount', 'u32'), ('m1', 'f32'), ('m2', 'f32'), ('m3', 'f32'),
                                ('m4', 'f32')]))
            elif typ not in (0, 1, 2):
                raise ValueError('unknown area type %d' % typ)
            o.update(rd(r, AREA_BASE))
            m.areas.append(o)
        for _ in range(r.u32()):                                          # EESMCameraPath 0x8a7bd0
            o = {'a': [r.u32() for _ in range(r.u32())]}
            o['b'] = [r.f32() for _ in range(r.u32())]
            o.update(rd(r, [('u78', 'u32'), ('f7c', 'f32'), ('b80', 'bool'), ('b81', 'bool'),
                            ('b82', 'bool')]))
            if o['b82']:
                o['s60'] = r.uws()
            o.update(rd(r, CB))
            m.cameras.append(o)
        m.list7 = [r.u32() for _ in range(r.u32())]
        m.list8 = [(r.u32(), r.u32(), r.bool()) for _ in range(r.u32())]
        for _ in range(r.u32()):
            cat, typ = r.u32(), r.u32()
            m.pending.append(m._read_effect(r, cat, typ, ver))
        m.tail_offset = r.p
        m.tail = raw[r.p:]
        if full_tail:
            m.tail_parsed = parse_tail(Reader(raw, r.p), ver)
        return m

    @staticmethod
    def _read_effect(r, cat, typ, ver):
        key = effect_key(cat, typ)
        if key not in EFFECTS:
            raise ValueError('unknown effect %d/%d at 0x%x' % (cat, typ, r.p))
        o = read_effect_body(r, EFFECTS[key][1], ver)
        o['_cat'], o['_type'] = cat, typ
        return o

    def serialize(self, ver=(4, 0)):
        w = Writer()
        w.u32(len(self.triggers))
        for t in self.triggers:
            wr(w, CB + TRIGGER_FIELDS, t)
            for key, fmt in (('if', 'b'), ('then', 'u'), ('else', 'u')):
                w.u32(len(t[key]))
                for a, b, c in t[key]:
                    (w.bool if fmt == 'b' else w.u32)(a)
                    w.u32(b)
                    w.u32(c)
        w.u32(len(self.conditions))
        for o in self.conditions:
            w.u32(o['_type'])
            wr(w, CONDITIONS[o['_type']][1], o)
        w.u32(len(self.effects))
        for o in self.effects:
            self._write_effect(w, o, ver)
        w.u32(len(self.objects))
        for o in self.objects:
            wr(w, CB, o)
            w.u32(len(o['units']))
            for u in o['units']:
                w.u32(u)
            wr(w, OBJECT_FIELDS, o)
        w.u32(len(self.areas))
        for o in self.areas:
            w.u32(o['_type'])
            if o['_type'] == 4:
                w.u32(len(o['points']))
                for a, b in o['points']:
                    w.i32(a)
                    w.i32(b)
            elif o['_type'] == 3:
                wr(w, [('mount', 'u32'), ('m1', 'f32'), ('m2', 'f32'), ('m3', 'f32'), ('m4', 'f32')], o)
            wr(w, AREA_BASE, o)
        w.u32(len(self.cameras))
        for o in self.cameras:
            w.u32(len(o['a']))
            for x in o['a']:
                w.u32(x)
            w.u32(len(o['b']))
            for x in o['b']:
                w.f32(x)
            wr(w, [('u78', 'u32'), ('f7c', 'f32'), ('b80', 'bool'), ('b81', 'bool'), ('b82', 'bool')], o)
            if o['b82']:
                w.uws(o['s60'])
            wr(w, CB, o)
        w.u32(len(self.list7))
        for x in self.list7:
            w.u32(x)
        w.u32(len(self.list8))
        for a, b, c in self.list8:
            w.u32(a)
            w.u32(b)
            w.bool(c)
        w.u32(len(self.pending))
        for o in self.pending:
            self._write_effect(w, o, ver)
        w.b += self.tail
        return bytes(w.b)

    @staticmethod
    def _write_effect(w, o, ver):
        w.u32(o['_cat'])
        w.u32(o['_type'])
        write_effect_body(w, EFFECTS[effect_key(o['_cat'], o['_type'])][1], o, ver)


def parse_tail(r, ver):
    """Rest of FUN_008a1c00 after the pending-effect list (used for checking only)."""
    t = {}
    t['u6d0'] = [r.u32() for _ in range(5)]
    t['f6c0'] = (r.f32(), r.f32())
    t['strings8'] = [r.uws() for _ in range(8)]                         # FUN_008c7bb0
    t['triples'] = [(r.uws(), r.uws(), r.bool()) for _ in range(r.u32())]
    t['b6f9'] = r.bool()
    t['f6b8'] = (r.f32(), r.f32())
    t['b6fa'] = r.bool()
    t['dialogs'] = [rd(r, DIALOG_FIELDS) for _ in range(r.u32())]      # FUN_008a0b10
    t['s8'] = r.uws()
    t['lists17'] = [[r.uws() for _ in range(r.u32())] for _ in range(17)]
    t['has_counter'] = r.bool()
    if t['has_counter']:
        t['counter'] = rd(r, COUNTER_FIELDS)
    n_anim = r.u32()                                                    # FUN_00860f60
    if n_anim:
        raise NotImplementedError('scripted animations (%d) not decoded' % n_anim)
    t['anim_states'] = [(r.u32(), r.bool()) for _ in range(r.u32())]
    t['anim_f'] = r.f32()
    t['per_player'] = [[(r.i32(), r.bool(), r.bool()) for _ in range(r.u32())] for _ in range(17)]
    t['u5c8'] = [r.u32() for _ in range(r.u32())]
    t['u6e8'] = r.u32()
    t['u6e4'] = r.u32()
    t['b6fe'] = r.bool()
    t['u6f0'] = r.u32()
    t['u6ec'] = r.u32()
    t['s20'] = r.uws()
    t['s38'] = r.uws()
    t['player_strings'] = [(r.bool(), r.uws()) for _ in range(17)]
    t['i6cc'] = r.i32()
    if r.p != len(r.d):
        raise ValueError('tail: %d bytes left' % (len(r.d) - r.p))
    return t


# --------------------------------------------------------------------------- cli


def load_any(path):
    data = open(path, 'rb').read()
    if data[:4] == b'ZL01':
        data = unpack_chunk(data)
    return ScnFile(data)


def _iter_files(args):
    for a in args:
        if os.path.isdir(a):
            for n in sorted(os.listdir(a)):
                if n.lower().endswith('.scn'):
                    yield os.path.join(a, n)
        else:
            yield a


def _jsonable(o):
    if isinstance(o, bytes):
        return T(o)
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def describe(m):
    out = []
    cn = lambda i: (T(m.conditions[i]['name']) if i < len(m.conditions) else '?%d' % i)
    en = lambda i: (T(m.effects[i]['name']) if i < len(m.effects) else '?%d' % i)
    for t in m.triggers:
        flags = ('' if t['on'] else ' OFF') + (' LOOP' if t['looping'] else '')
        out.append('TRIGGER %s%s' % (T(t['name']), flags))
        for n, op, c in t['if']:
            out.append('   if %s%s op%d' % ('NOT ' if n else '', cn(c), op))
        for d, op, e in t['then']:
            out.append('   then %s delay=%d op%d' % (en(e), d, op))
        for d, op, e in t['else']:
            out.append('   else %s delay=%d op%d' % (en(e), d, op))
    return '\n'.join(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == 'chunks':
        f = load_any(argv[1])
        print('header %d bytes, trailer %s' % (len(f.header), f.trailer.hex()))
        for maj, mn, typ, p in f.chunks:
            print('  type %2d ver %d.%d stored %8d raw %8d %s' % (
                typ, maj, mn, len(p), len(unpack_chunk(p)), 'zlib' if p[:4] == b'ZL01' else 'raw'))
        return 0
    if cmd == 'dump':
        f = load_any(argv[1])
        m = Manager.parse(f.get(6), full_tail=True)
        print(describe(m))
        if '--json' in argv:
            out = argv[argv.index('--json') + 1]
            js = {k: getattr(m, k) for k in ('triggers', 'conditions', 'effects', 'objects', 'areas',
                                             'cameras', 'list7', 'list8', 'pending')}
            js['tail'] = m.tail_parsed
            json.dump(_jsonable(js), open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return 0
    if cmd == 'stock':
        # every shipped scenario: header, manager (incl. tail) and the whole file round trip
        bad = n = 0
        for label, f in stock_scenarios(argv[1]):
            n += 1
            raw = f.get(6)
            m = Manager.parse(raw, full_tail=True)
            h = parse_header(f.header)
            ok = (m.serialize() == raw and build_header(h) == f.header and not h['_rest']
                  and ScnFile(f.to_bytes()).to_bytes() == f.to_bytes()
                  and struct.unpack('<I', f.trailer)[0] == h['map_id'])
            if not ok:
                print('DIFF', label)
            bad += not ok
        print('%d stock scenarios, %d differ' % (n, bad))
        return 1 if bad else 0
    if cmd == 'roundtrip':
        bad = 0
        for p in _iter_files(argv[1:]):
            try:
                f = load_any(p)
                raw = f.get(6)
                m = Manager.parse(raw, full_tail=True)
                again = m.serialize()
                ok = again == raw
                m2 = Manager.parse(again)
                ok = ok and m2.serialize() == raw
                # whole file with the manager chunk re-packed
                f2 = ScnFile(f.to_bytes())
                ok = ok and f2.get(6) == raw and f.to_bytes() == load_any_bytes(p)
                print('%-4s %-60s trig %3d cond %3d eff %4d obj %3d area %3d' % (
                    'OK' if ok else 'DIFF', os.path.basename(p), len(m.triggers), len(m.conditions),
                    len(m.effects), len(m.objects), len(m.areas)))
                bad += not ok
            except Exception as e:  # noqa: BLE001 - report and continue
                print('FAIL %-60s %s: %s' % (os.path.basename(p), type(e).__name__, e))
                bad += 1
        return 1 if bad else 0
    print(__doc__)
    return 2


def load_any_bytes(path):
    data = open(path, 'rb').read()
    if data[:4] == b'ZL01':
        data = unpack_chunk(data)
    return data



# --------------------------------------------------------------------------- header
# Scenario header = FUN_007246f0 -> FUN_00723f70 + FUN_007245c0 (+ game setup FUN_006e0360).

PLAYER_FIELDS = [('kind', 'u32'), ('name', 'uws'), ('f24', 'f32'), ('u30', 'u32'), ('index', 'u32'),
                 ('team', 'u32'), ('u3c', 'u32'), ('b44', 'bool'), ('b45', 'bool'), ('b46', 'bool'),
                 ('civ', 'u32'), ('u28', 'u32'), ('u2c', 'u32'), ('b47', 'bool')]      # FUN_006dedf0
SETUP_FIELDS = [('u514', 'u32'), ('game_type', 'u32'), ('u52c', 'u32'), ('u51c', 'u32'),
                ('i520', 'i32'), ('i524', 'i32'), ('u530', 'u32'), ('u534', 'u32'), ('u538', 'u32'),
                ('u53c', 'u32'), ('b54c', 'bool'), ('b54d', 'bool'), ('b54e', 'bool'), ('b54f', 'bool'),
                ('b550', 'bool'), ('b551', 'bool'), ('b552', 'bool'), ('b554', 'bool'), ('s480', 'uws'),
                ('s498', 'uws'), ('u544', 'u32'), ('b555', 'bool'), ('s4e0', 'uws'), ('u540', 'u32'),
                ('b556', 'bool'), ('b557', 'bool'), ('b558', 'bool'), ('b559', 'bool'), ('b55a', 'bool'),
                ('map_name', 'uws'), ('s4f8_enc', 'uws'), ('b55b', 'bool'), ('b55c', 'bool'),
                ('b55d', 'bool'), ('s4b0', 'uws'), ('b55e', 'bool')]                    # FUN_006e0360


def parse_header(raw):
    r = Reader(raw)
    h = rd(r, [('name', 'uws'), ('desc', 'uws'), ('ver_major', 'u32'), ('ver_minor', 'u32'),
               ('s670', 'uws'), ('date', 'uws'), ('u6a0', 'u32')])
    if (h['ver_major'], h['ver_minor']) != (4, 0):
        raise ValueError('header version %d.%d not handled' % (h['ver_major'], h['ver_minor']))
    h['players'] = [rd(r, PLAYER_FIELDS) for _ in range(16)]
    h.update(rd(r, SETUP_FIELDS))
    h['u6a4'] = r.u32()
    h['chunk_list'] = [r.u32() for _ in range(r.u32())]
    h['strings8'] = [r.uws() for _ in range(8)]                              # FUN_008c7bb0
    h['triples'] = [(r.uws(), r.uws(), r.bool()) for _ in range(r.u32())]
    h['map_id'] = r.u32()
    h['u_after'] = r.u32()                                    # FUN_007246f0, last Read
    h['_rest'] = raw[r.p:]
    return h


def build_header(h):
    w = Writer()
    wr(w, [('name', 'uws'), ('desc', 'uws'), ('ver_major', 'u32'), ('ver_minor', 'u32'),
           ('s670', 'uws'), ('date', 'uws'), ('u6a0', 'u32')], h)
    for p in h['players']:
        wr(w, PLAYER_FIELDS, p)
    wr(w, SETUP_FIELDS, h)
    w.u32(h['u6a4'])
    w.u32(len(h['chunk_list']))
    for x in h['chunk_list']:
        w.u32(x)
    for s in h['strings8']:
        w.uws(s)
    w.u32(len(h['triples']))
    for a, b, c in h['triples']:
        w.uws(a)
        w.uws(b)
        w.bool(c)
    w.u32(h['map_id'])
    w.u32(h['u_after'])
    w.b += h['_rest']
    return bytes(w.b)


# --------------------------------------------------------------------------- stock files


def iter_ssa(data):
    """Campaign archive (.ssa, magic 'rass'): u32 1, u32 0, u32 header_end, then entries
    {u32 len, name (UWideString bytes), u32 start, u32 end, u32 size} up to header_end."""
    if data[:4] != b'rass':
        raise ValueError('not an .ssa archive')
    p = 12
    (hdr_end,) = struct.unpack_from('<I', data, p)
    p += 4
    while p < hdr_end:
        (n,) = struct.unpack_from('<I', data, p)
        name = data[p + 4:p + 4 + n].rstrip(b'\0').decode('cp1251')
        p += 4 + n
        start, end, size = struct.unpack_from('<III', data, p)
        p += 12
        yield name, data[start:start + size]


def stock_scenarios(game_dir):
    """(label, ScnFile) for every scenario shipped with the game: multiplayer maps, tutorials
    and the campaign scenarios inside campaigns/*.ssa (read in memory, nothing extracted)."""
    data_dir = os.path.join(game_dir, 'Data')
    for sub in ('scenarios', 'tutorials'):
        d = os.path.join(data_dir, sub)
        for n in sorted(os.listdir(d)):
            if n.lower().endswith('.scn'):
                yield sub + '/' + n, load_any(os.path.join(d, n))
    cd = os.path.join(data_dir, 'campaigns')
    for n in sorted(os.listdir(cd)):
        if n.lower().endswith('.ssa'):
            for name, blob in iter_ssa(open(os.path.join(cd, n), 'rb').read()):
                if name.lower().endswith('.scn'):
                    raw = unpack_chunk(blob) if blob[:4] == b'ZL01' else blob
                    yield n + '/' + name, ScnFile(raw)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
