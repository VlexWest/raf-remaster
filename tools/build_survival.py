"""Build the co-op Survival game mode (multiplayer scenario maps) into an overlay.

Usage:
    python tools/build_survival.py <game_dir> <overlay_dir> [--theme classic|zombie|all]
                                   [--template "(4) plains"] [--boss-buffs] [--zombie-buffs]
                                   [--no-diplomacy] [--table]

Writes, for each theme, our own scenario built on a stock multiplayer map of the user's install:

    <overlay>/Data/scenarios/<map>.scn        stock terrain/start positions + our trigger system
    <overlay>/Data/map scripts/<map>.rmv      lobby entry (scenario maps are listed from *.rmv)

Nothing is written into the game folder. The trigger format is documented in
docs/scenario-format.md, the mode in docs/survival.md.

Design in one paragraph: players 1-4 are lobby slots. Humans are addressed with the trigger
player group "all humans" (3), the enemy with "all computer players" (4), so the mode does not
depend on which lobby slot the computer takes. At start the computer's own AI is switched off,
its citizens are removed, its town centre is made invulnerable and its gold/wood are kept at 0.
Waves are created next to the computer's town centre at fixed game times (game time is part of
the lockstep simulation, so every client fires the same trigger on the same tick) and sent
attack-moving at the human town centres. Every 5th wave adds an enemy hero (boss). A second
human town centre adds a co-op bonus group to every wave. Win: survive the last wave and kill
every enemy unit. Lose: no human town centre left.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_scn as R  # noqa: E402
import map_texts as M  # noqa: E402
import map_preview as P  # noqa: E402

# --------------------------------------------------------------------------- game vocabulary
# Enums proven from the exe (docs/scenario-format.md section 5).
PLAYER_GAIA, PLAYER_RANDOM_HUMAN, PLAYER_RANDOM_CPU, PLAYER_ALL_HUMANS, PLAYER_ALL_CPUS = 0, 1, 2, 3, 4
TASK_MOVE, TASK_PATROL, TASK_ATTACK_MOVE = 0, 1, 2
STANCE_AGGRESSIVE, STANCE_INVULNERABLE = 10, 14
RES_GOLD, RES_WOOD = 3, 4
ATTR_ATTACK, ATTR_HP, ATTR_SPEED = 40, 46, 51          # ChangeUnitClassAttribute ids
STATE_IDLE = 5000
AI_SETTING_ENABLED = 0
UNITSET_BASE = 134    # class value of dbunitset record 0: live test 2026-10-15 (137 emptied the TC selection) and every campaign file
FOREVER = 999999                                        # GameHasAttribute upper bound (seconds)

UNITSETS = {
    'town_centers': 'A-All Town Centers (MP) (All Civs)',   # not the (All Civs) set: it holds 'INVISIBLE Capital'
    'citizens': 'A-All Citizens (All Civs)',
    'army': 'A-All Units (Non-buildings, non-heroes, non-siege)',   # 'A-All Military' holds buildings
    'heroes': 'A-All Heroes (RTS MODE)',
}

PERSIAN = {
    'sword': {1: 'A - Inf01 - Sword Infantry (Level 1 Persian)',
              2: 'A - Inf02 - Sword Infantry (Level 2 Persian)',
              3: 'A - Inf03 - Sword Infantry (Level 3 Persian)',
              4: 'A - Inf04 - Sword Infantry (Level 4 Persian)',
              5: 'A - Inf05 - Sword Infantry (level 5 Persian)'},
    'spear': {1: 'A - Inf01 - Spear Infantry (Level 1 Persian)',
              2: 'A - Inf02 - Spear Infantry (Level 2 Persian)',
              3: 'A - Inf03 - Spear Infantry (Level 3 Persian)',
              4: 'A - Inf04 - Spear Infantry (Level 4 Persian)',
              5: 'A - Inf05 - Spear Infantry (Level 5 Persian)'},
    'archer': {1: 'A - Arc01 - Archer (Level 1 Persian)',
               2: 'A - Arc02 - Archer (Level 2 Persian)',
               3: 'A - Arc03 - Archer (Level 3 Persian)',
               4: 'A - Arc04 - Archer (Level 4 Persian)',
               5: 'A - Arc05 - Archer (Level 5 Persian)'},
    'cavalry': {1: 'A - Cav01 - Sword Cavalry (Level 1 Persian)',
                2: 'A - Cav02 - Spear Cavalry (Level 2 Persian)',
                3: 'A - Cav03 - Sword Cavalry (Level 3 Persian)',
                4: 'A - Cav04 - Spear Cavalry (Level 4 Persian)',
                5: 'A - Cav05 - Sword Cavalry (Level 5 Persian)'},
    'elephant': {3: 'A - Cav03a - War Elephant (Archer) (Level 3 Persian)'},
    # siege, so walls alone cannot hold the waves: rams for gates & walls, onagers from range
    'ram': {1: 'A - Siege02b - Siege Ram (Persian)'},
    'onager': {1: 'A - Siege03a - Onager (Persian)'},
}
SIEGE = ('ram', 'onager')

# --------------------------------------------------------------------------- themes


def classic_mix(k):
    # walls alone hold infantry forever, so siege is about a third of every wave from wave 2
    if k <= 1:
        return {'sword': 60, 'spear': 40}
    if k <= 5:
        return {'sword': 40, 'spear': 30, 'archer': 30, 'ram': 25, 'onager': 25}
    if k <= 10:
        return {'sword': 30, 'spear': 25, 'archer': 25, 'cavalry': 20, 'ram': 25, 'onager': 25}
    if k <= 15:
        return {'sword': 25, 'spear': 20, 'archer': 25, 'cavalry': 20, 'elephant': 10, 'ram': 25, 'onager': 30}
    return {'sword': 25, 'spear': 20, 'archer': 20, 'cavalry': 25, 'elephant': 10, 'ram': 25, 'onager': 30}


def zombie_mix(k):
    return {'sword': 55, 'spear': 45}


THEMES = {
    'classic': {
        'map': '(4) survival',
        'title': 'Survival',
        'help': 'Co-op survival: 1-2 humans hold their town against 20 waves. Add exactly one '
                'computer player as the enemy.',
        'roster': PERSIAN,
        'mix': classic_mix,
        'size': lambda k: round(3 + 1.25 * k + 0.03 * k * k),
        'coop_bonus': 0.5,
        'waves': 20,
        'first_wave': 240,
        'intervals': [(5, 150), (10, 135), (15, 120), (20, 110)],   # (up to wave, seconds)
        'boss_breather': 30,
        'level': lambda k: min(5, 1 + (k - 1) // 4),
        'bosses': {5: [('A - Inf00 - Sargon Melee - RTS mode (Persian)', 'Sargon')],
                   10: [('A - Inf00 - Nebechadnezzar Melee - RTS mode (Persian)', 'Nebuchadnezzar')],
                   15: [('A - Inf00 - G Caesar Melee - RTS mode (Rome)', 'Germanicus')],
                   20: [('A - Inf00 - J Caesar Melee - RTS mode (Rome)', 'Julius Caesar'),
                        ('A - Inf00 - Ramses Melee - RTS mode (Egypt)', 'Ramses')]},
        'boss_hp_bonus': {5: 50, 10: 100, 15: 150, 20: 200},       # percent, --boss-buffs only
        'environment': None,
        'final_environment': 'hdri stormy weather',
        'unit_mods': [],
        'sounds': {'wave': 'a_warning bell', 'boss': 'a_hero horn', 'win': 'a_completion bell'},
        'text': {
            'intro': '/r225/g185/b35SURVIVAL/r255/g255/b255  Hold your town for %(waves)d waves. '
                     'The enemy marches from its camp. Every 5th wave is led by a hero.',
            'wave': '/r225/g185/b35Wave %(k)d of %(waves)d/r255/g255/b255 is coming!',
            'boss': '/r255/g80/b80%(boss)s/r255/g255/b255 leads wave %(k)d!',
            'next': 'Wave %(k)d in',
            'last': 'Last wave: destroy every enemy',
            'win': '/r225/g185/b35Victory!/r255/g255/b255 The town stands.',
            'lose': '/r255/g80/b80The town has fallen.',
        },
    },
    'zombie': {
        'map': '(4) survival zombies',
        'title': 'Survival: Zombies',
        'help': 'Halloween survival: the dead walk at night. Slow, tough, melee only, many. '
                'Add exactly one computer player as the horde.',
        'roster': {'sword': PERSIAN['sword'], 'spear': PERSIAN['spear']},
        'mix': zombie_mix,
        'size': lambda k: round(1.4 * (3 + 1.25 * k + 0.03 * k * k)),
        'coop_bonus': 0.5,
        'waves': 20,
        'first_wave': 180,
        'intervals': [(5, 120), (10, 110), (15, 100), (20, 95)],
        'boss_breather': 30,
        'level': lambda k: min(5, 1 + (k - 1) // 4),
        'bosses': {5: [('A - Inf00 - Gladiator Melee - RTS mode (Minotaur)', 'The Minotaur')],
                   10: [('A - Inf00 - Gladiator Melee - RTS mode (Minotaur)', 'The Minotaur')] * 2,
                   15: [('A - Inf00 - Gladiator Melee - RTS mode (Minotaur)', 'The Minotaur')] * 3,
                   20: [('A - Inf00 - Gladiator Melee - RTS mode (Minotaur)', 'The Minotaur')] * 4},
        'boss_hp_bonus': {},
        'environment': 'hdri grassland night',
        'final_environment': 'hdri desert night ocean',
        # --zombie-buffs: applied once to every zombie unit class via a template unit
        'unit_mods': [(ATTR_HP, 0, 100, 'HP +100%'), (ATTR_SPEED, 1, 40, 'speed -40%')],
        'sounds': {'wave': 'a_warning bell', 'boss': 'a_hero horn', 'win': 'a_completion bell'},
        'text': {
            'intro': '/r150/g255/b150THE DEAD WALK/r255/g255/b255  Survive %(waves)d nights of the '
                     'horde. They are slow, but they never stop coming.',
            'wave': '/r150/g255/b150Horde %(k)d of %(waves)d/r255/g255/b255 rises!',
            'boss': '/r255/g80/b80%(boss)s/r255/g255/b255 walks with horde %(k)d!',
            'next': 'Horde %(k)d in',
            'last': 'Last horde: destroy every walker',
            'win': '/r150/g255/b150Dawn breaks./r255/g255/b255 You survived.',
            'lose': '/r255/g80/b80The town is overrun.',
        },
    },
}

# --------------------------------------------------------------------------- db lookups


def db_records(game_dir, table, rec_size):
    data = (Path(game_dir) / 'Data' / 'db' / (table + '.dat')).read_bytes()
    (count,) = struct.unpack_from('<I', data, 0)
    if 4 + count * rec_size > len(data):
        raise ValueError('%s: unexpected size' % table)
    return [data[4 + i * rec_size:4 + (i + 1) * rec_size] for i in range(count)]


def cstr(raw, n=100):
    return raw[:n].split(b'\0', 1)[0].decode('cp1252')


def unitset_members(raw):
    """dbunitset record (272 bytes): char[100] name, i32 id, i32 index, 15 x i32 (?),
    15 x i32 object types, 5 x i32 included sets, 5 x i32 excluded sets, i32 flag."""
    v = struct.unpack_from('<43i', raw, 100)
    return {'types': [x for x in v[17:32] if x > 0], 'include': [x for x in v[32:37] if x >= 0],
            'exclude': [x for x in v[37:42] if x >= 0], 'flag': v[42]}


class Vocab:
    def __init__(self, game_dir, unitset_base=UNITSET_BASE):
        self.unitset_base = unitset_base
        self.objects = [cstr(r) for r in db_records(game_dir, 'dbobjects', 2012)]
        self._sets = db_records(game_dir, 'dbunitset', 272)
        self.unitsets = [cstr(r) for r in self._sets]
        self._obj = {}
        for i, n in enumerate(self.objects):
            self._obj.setdefault(n, []).append(i)

    def unit(self, name):
        hits = self._obj.get(name)
        if not hits:
            raise KeyError('unit type not in dbobjects: %r' % name)
        if len(hits) > 1:
            raise KeyError('unit name not unique in dbobjects: %r' % name)
        return hits[0]

    def unitset(self, name):
        hits = [i for i, n in enumerate(self.unitsets) if n == name]
        if not hits:
            raise KeyError('unit set %r not found' % name)
        # the stock table has exact duplicates (same members, other id); they are equivalent
        members = {repr(unitset_members(self._sets[i])) for i in hits}
        if len(members) != 1:
            raise KeyError('unit set %r is ambiguous (%d different records)' % (name, len(hits)))
        return self.unitset_base + hits[0]

    def set_members(self, ref):
        return unitset_members(self._sets[ref - self.unitset_base])


# --------------------------------------------------------------------------- schedule


def wave_times(theme):
    times, t = [], theme['first_wave']
    for k in range(1, theme['waves'] + 1):
        times.append(t)
        gap = next(s for upto, s in theme['intervals'] if k <= upto)
        if k in theme['bosses']:
            gap += theme['boss_breather']
        t += gap
    return times


def wave_groups(theme, k, scale=1.0):
    """[(role, level, count)] for wave k; counts sum to round(size*scale)."""
    total = max(1, round(theme['size'](k) * scale))
    mix = {r: w for r, w in theme['mix'](k).items() if r in theme['roster']}
    want = theme['level'](k)
    wsum = sum(mix.values())

    def level(role):
        levels = sorted(theme['roster'][role])
        below = [lv for lv in levels if lv <= want]
        return below[-1] if below else levels[0]

    # siege first, so rounding cannot drop it: at least one per siege role, at most total/siege_div each
    # (theme difficulty: no siege before wave siege_from)
    if k < theme.get('siege_from', 0):
        mix = {r: w for r, w in mix.items() if r not in SIEGE}
        wsum = sum(mix.values())
    div = theme.get('siege_div', 6)
    siege, left = [], total
    for role in [r for r in SIEGE if r in mix]:
        n = min(left - 1, max(1, min(round(total * mix.pop(role) / wsum), total // div)))
        if n > 0:
            siege.append((role, level(role), n))
            left -= n
    groups, total = [], left
    roles = sorted(mix, key=lambda r: -mix[r])
    wsum = sum(mix.values())
    for i, role in enumerate(roles):
        n = left if i == len(roles) - 1 else min(left, round(total * mix[role] / wsum))
        if role == 'elephant':
            n = min(n, max(1, total // 8))
        if n <= 0:
            continue
        groups.append((role, level(role), n))
        left -= n
    if left > 0 and groups:
        role, lv, n = groups[0]
        groups[0] = (role, lv, n + left)
    return groups + siege


def boss_label(bosses, lang='en'):
    """Hero names for the messages: 'X', 'X and Y', 'N x X' (map_texts.heroes, Russian names)."""
    if not bosses:
        return ''
    return M.heroes(lang, [lb for _, lb in bosses])


# --------------------------------------------------------------------------- builder


def S(text):
    return R.S(text)


class Builder:
    """Appends our components to a parsed EEScenarioManager, keeping the game's index rules:
    condition refs = 3 + memory index, effect refs = 1 + index, object refs = 1 + index,
    area refs = 2 + index, trigger refs = index; memory condition order = non-ObjectExists
    conditions first, then ObjectExists (the loader moves them, FUN_008a1c00)."""

    def __init__(self, m):
        self.m = m
        tail = R.parse_tail(R.Reader(m.tail), (4, 0))
        self.ids = list(tail['u6d0'])     # last used ids: trigger, condition, effect, object, area
        self.base_triggers = len(m.triggers)
        self.cond_new = []                # (kind_is_object_exists, dict)
        self.trig_new = []

    def _id(self, slot):
        self.ids[slot] += 1
        return self.ids[slot]

    # objects --------------------------------------------------------------------------------
    def area(self, name, left, top, right, bottom):
        """Rectangular area (tile coordinates), base fields as in the shipped maps."""
        a = {'_type': 0, 'x': 0.0, 'y': 0.0, 'left': left, 'top': top, 'right': right,
             'bottom': bottom, 'b80': 1, 'b81': 0, 'u74': self._id(4), 'u7c': 0, 'u78': 0,
             'name': S(name), 'desc': S('')}
        self.m.areas.append(a)
        return 1 + len(self.m.areas)      # area ref (2 + index)

    def obj(self, name, player, unit_type=0, unit_class=0, count=(1, 9999), near=None,
            state=None, area=None):
        o = {'name': S(name), 'desc': S(''), 'units': [], 'bdc': 0, 'player': player,
             'u80': unit_class, 'u84': unit_type, 'u94': 0,
             'class_name': S(str(count[0])), 'unit_name': S(str(count[1])), 'bdd': 1,
             'ub4': 0, 'ub8': 0, 'ubc': 0, 'uc0': 0, 'uc4': 0, 'uc8': 0, 'u88': 0, 'u8c': 0,
             'u90': 0, 'u98': 0, 'u9c': 0, 'ua0': 0, 'ua4': 1, 'ua8': 1000, 'uac': 7, 'bde': 0,
             'ub0': self._id(3), 'bdf': 0, 'be0': 0, 'be1': 0, 'be2': 0, 'ucc': 0, 'ud0': 0,
             'ud4': 0, 'ud8': 0}
        if near is not None:              # place/select within line of sight of object `near`
            o['ub8'], o['u90'], o['u8c'] = 1, near, 0
        if state is not None:
            o['uc4'], o['ua8'] = 1, state
        if area is not None:              # inside area (shipped maps: ub4=1, u88=area ref)
            o['ub4'], o['u88'] = 1, area
        self.m.objects.append(o)
        return len(self.m.objects)        # object ref (1-based, 0 = default object)

    # conditions -----------------------------------------------------------------------------
    def cond(self, typ, name, **fields):
        spec = R.CONDITIONS[typ][1]
        o = {k: 0 for k, t in spec if t != 'uws'}
        o.update({k: S('') for k, t in spec if t == 'uws'})
        o.update(fields)
        o.update({'name': S(name), 'desc': S(''), 'c_unused38': self._id(1), '_type': typ})
        self.cond_new.append(o)
        return ('C', len(self.cond_new) - 1)

    def time_after(self, seconds, name=None):
        return self.cond(7, name or 'Game time > %d s' % seconds, b3c=0, b3d=1, b3e=0, u40=1,
                         u48=FOREVER, u44=seconds, u4c=0)

    def exists(self, obj_ref, name):
        return self.cond(1, name, object=obj_ref)

    # effects --------------------------------------------------------------------------------
    def eff(self, key, name, **fields):
        spec = R.EFFECTS[key][1]
        if not isinstance(spec, list):
            raise ValueError('builder does not write %s' % (key,))
        o = {k: 0 for k, t in spec if t not in ('uws', 'f32')}
        o.update({k: 0.0 for k, t in spec if t == 'f32'})
        o.update({k: S('') for k, t in spec if t == 'uws'})
        o.update(fields)
        for k, v in list(o.items()):
            if isinstance(v, str):
                o[k] = S(v)
        o.update({'name': S(name), 'desc': S(''), 'e_unused38': self._id(2),
                  '_cat': key[0], '_type': 0xffffffff if key[0] == 3 else key[1]})
        self.m.effects.append(o)
        return len(self.m.effects)        # effect ref (1-based, 0 = default "do nothing")

    def chat(self, text, seconds=10):
        return self.eff((4, 3), 'MSG ' + text[:40], text=text, u54=PLAYER_ALL_HUMANS,
                        u58=seconds, b5c=0)

    def sound(self, wav):
        return self.eff((4, 0), 'SOUND ' + wav, sound=wav, f54=0.95, b60=0, i58=1, u5c=0, b61=0)

    def counter(self, title, seconds, show_time=True):
        return self.eff((5, 6), 'COUNTER ' + title, counter=title, i6c=seconds, b70=1,
                        b71=0 if show_time else 1, u74=0, text54='', b72=0)

    # triggers -------------------------------------------------------------------------------
    def trigger(self, name, conds, effects, looping=False, on=True, true_for=0):
        """conds: list of (cond_handle, negate) ANDed; effects: list of (effect_ref, delay_cs)."""
        t = {'name': S(name), 'desc': S(''), 'on': 1 if on else 0, 'looping': 1 if looping else 0,
             'b8d': 0, 'u7c': 0, 'b8f': 0, 'true_for': true_for, 'u84': 0, 'f78': 0.0,
             'f74': 500.0, 'u88': self._id(0), '_conds': conds,
             'then': [(delay, 1 if i < len(effects) - 1 else 0, ref)
                      for i, (ref, delay) in enumerate(effects)],
             'else': [(0, 0, 0)]}
        self.trig_new.append(t)
        return self.base_triggers + len(self.trig_new) - 1

    # finish ---------------------------------------------------------------------------------
    def finish(self):
        m = self.m
        old = m.conditions
        # memory order after load: non-ObjectExists first, then ObjectExists
        nonoe = [('old', i) for i, c in enumerate(old) if c['_type'] != 1] + \
                [('new', i) for i, c in enumerate(self.cond_new) if c['_type'] != 1]
        oe = [('old', i) for i, c in enumerate(old) if c['_type'] == 1] + \
             [('new', i) for i, c in enumerate(self.cond_new) if c['_type'] == 1]
        order = nonoe + oe
        ref = {key: 3 + n for n, key in enumerate(order)}
        old_ref = {3 + i: ref[('old', i)] for i in range(len(old))}
        m.conditions = [(old if src == 'old' else self.cond_new)[i] for src, i in order]
        for t in m.triggers:              # remap the template's own triggers
            t['if'] = [(neg, op, old_ref.get(c, c)) for neg, op, c in t['if']]
        for t in self.trig_new:
            conds = t.pop('_conds')
            if not conds:
                t['if'] = [(0, 0, 0)]
            else:
                t['if'] = [(1 if neg else 0, 1 if i < len(conds) - 1 else 0, ref[('new', h[1])])
                           for i, (h, neg) in enumerate(conds)]
            m.triggers.append(t)
        # last-used id counters at the start of the tail (u6d0[5])
        m.tail = struct.pack('<5I', *self.ids) + m.tail[20:]


# --------------------------------------------------------------------------- the mode


def spawn_rect(map_size, half=5):
    """Spawn area at the map centre: on the symmetric 4-player template every start corner is
    the same walk away, and it does not depend on which lobby slot the computer takes."""
    w, h = map_size
    cx, cy = w // 2, h // 2
    return (float(cx - half), float(cy - half), float(cx + half), float(cy + half))


def enemy_types(theme, vocab):
    """Every unit type the waves can create (roster + bosses), as dbobjects indices."""
    types = {vocab.unit(n) for role in theme['roster'].values() for n in role.values()}
    types |= {vocab.unit(hero) for heroes in theme['bosses'].values() for hero, _ in heroes}
    return sorted(types)


def build_mode(m, theme, vocab, opts, map_size, extra=None):
    """extra(b, ctx): optional layer added before finish (tools/build_coop.py, Co-op Roles)."""
    b = Builder(m)
    waves = theme['waves']
    times = wave_times(theme)
    sets = {k: vocab.unitset(v) for k, v in UNITSETS.items()}

    # placement: the encoding of the shipped maps (contested sands "Create WJ1": object with
    # player, unit type, count and "inside area"); all 211 shipped Create effects use an area,
    # none places units near another object
    a_spawn = b.area('SV Spawn centre', *spawn_rect(map_size))

    # selections ------------------------------------------------------------------------------
    o_enemy_tc = b.obj('SV Enemy town centres', PLAYER_ALL_CPUS, unit_class=sets['town_centers'],
                       count=(1, 99))
    spawn = dict(area=a_spawn) if opts.spawn == 'area' else dict(near=o_enemy_tc)
    o_human_tc = b.obj('SV Human town centres', PLAYER_ALL_HUMANS,
                       unit_class=sets['town_centers'], count=(1, 99))
    o_human_tc2 = b.obj('SV Two human town centres', PLAYER_ALL_HUMANS,
                        unit_class=sets['town_centers'], count=(2, 99))
    # enemy units by exact type: no unit-set membership involved (live test 2026-10-15: the
    # computer had nothing left after the unit-set based clean-up)
    o_type = {ut: b.obj('SV Enemy type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut, count=(1, 9999))
              for ut in enemy_types(theme, vocab)}
    citizens = vocab.set_members(vocab.unitset(UNITSETS['citizens']))['types']
    o_cit = [b.obj('SV Enemy citizen type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut,
                   count=(1, 9999)) for ut in citizens]

    fmt = dict(waves=waves)
    T = theme['text']

    def remove_citizens(tag):
        return [(b.eff((1, 4), 'SV Remove enemy citizens %d%s' % (i, tag), object=o), 0)
                for i, o in enumerate(o_cit)]

    def orders(tag, delay):
        out = []
        for ut, o in o_type.items():
            out.append((b.eff((1, 7), 'SV Aggressive %d%s' % (ut, tag), stance=STANCE_AGGRESSIVE,
                              object=o), delay))
            out.append((b.eff((1, 5), 'SV Attack-move %d%s' % (ut, tag), target=o_human_tc,
                              task=TASK_ATTACK_MOVE, b48=0, object=o), delay + 50))
        return out

    # setup -----------------------------------------------------------------------------------
    setup = []
    if opts.ai_off:
        setup.append((b.eff((6, 4), 'SV Computer AI off', setting=AI_SETTING_ENABLED, on=0,
                            player=PLAYER_ALL_CPUS), 0))
    setup += [(b.eff((1, 7), 'SV Enemy TC invulnerable', stance=STANCE_INVULNERABLE,
                     object=o_enemy_tc), 0)]
    setup += remove_citizens('')
    setup += [(b.eff((2, 4), 'SV Enemy gold 0', resource=RES_GOLD, amount=0, text='0',
                     player=PLAYER_ALL_CPUS), 0),
              (b.eff((2, 4), 'SV Enemy wood 0', resource=RES_WOOD, amount=0, text='0',
                     player=PLAYER_ALL_CPUS), 0),
              (b.chat(T['intro'] % fmt, 20), 100),
              (b.counter(T['next'] % {'k': 1}, times[0] - 2), 100)]
    if theme['environment']:
        setup.append((b.eff((5, 7), 'SV Environment', env=theme['environment'], i54=10, b58=1,
                            b59=1), 0))
    if opts.force_diplomacy:      # FUN_008c36c0 resolves both sides with FUN_0089c9a0
        setup += [(b.eff((2, 3), 'SV Humans allied', other=PLAYER_ALL_HUMANS, stance=0, b48=1,
                         player=PLAYER_ALL_HUMANS), 0),
                  (b.eff((2, 3), 'SV Humans vs computers', other=PLAYER_ALL_CPUS, stance=1,
                         b48=1, player=PLAYER_ALL_HUMANS), 0)]
    b.trigger('SV Setup', [(b.time_after(1), False)], setup)

    # keep the computer passive: no citizens, no money (looping every ~20 s)
    b.trigger('SV Keep enemy passive', [(b.time_after(5), False)],
              remove_citizens(' (loop)') +
              [(b.eff((2, 4), 'SV Enemy gold 0 (loop)', resource=RES_GOLD, amount=0, text='0',
                      player=PLAYER_ALL_CPUS), 0),
               (b.eff((2, 4), 'SV Enemy wood 0 (loop)', resource=RES_WOOD, amount=0, text='0',
                      player=PLAYER_ALL_CPUS), 0),
               (b.eff((1, 7), 'SV Enemy TC invulnerable (loop)', stance=STANCE_INVULNERABLE,
                      object=o_enemy_tc), 0)],
              looping=True, true_for=20)

    # zombie class buffs (experimental): one template unit per type, buff its class, remove it
    if theme['unit_mods'] and opts.zombie_buffs:
        eff = []
        types = sorted({vocab.unit(n) for role in theme['roster'].values() for n in role.values()})
        for ut in types:
            o_t = b.obj('SV Template %d' % ut, PLAYER_ALL_CPUS, unit_type=ut, count=(1, 1),
                        **spawn)
            eff.append((b.eff((1, 0), 'SV Create template %d' % ut, object=o_t), 0))
            for attr, op, val, label in theme['unit_mods']:
                eff.append((b.eff((1, 12), 'SV Zombie %s %d' % (label, ut), attr=attr, op=op,
                                  value=val, b4c=1, u50=0, i54=-1, object=o_t), 100))
            eff.append((b.eff((1, 4), 'SV Remove template %d' % ut, object=o_t), 200))
        b.trigger('SV Zombie class buffs', [(b.time_after(2), False)], eff)

    # waves -----------------------------------------------------------------------------------
    snd_wave = b.sound(theme['sounds']['wave'])
    snd_boss = b.sound(theme['sounds']['boss'])
    plan = []
    for k in range(1, waves + 1):
        t = times[k - 1]
        f = dict(fmt, k=k)
        eff = [(b.chat(T['wave'] % f, 12), 0), (snd_wave, 0)]
        groups = wave_groups(theme, k)
        used = set()
        for role, lv, n in groups:
            ut = vocab.unit(theme['roster'][role][lv])
            used.add(ut)
            o = b.obj('SV W%02d %s L%d x%d' % (k, role, lv, n), PLAYER_ALL_CPUS, unit_type=ut,
                      count=(n, n), **spawn)
            eff.append((b.eff((1, 0), 'SV W%02d create %s' % (k, role), object=o), 0))
        bosses = theme['bosses'].get(k, [])
        for i, (hero, label) in enumerate(bosses):
            ut = vocab.unit(hero)
            used.add(ut)
            o = b.obj('SV W%02d boss %d' % (k, i + 1), PLAYER_ALL_CPUS, unit_type=ut, count=(1, 1),
                      **spawn)
            eff.append((b.eff((1, 0), 'SV W%02d create boss %d' % (k, i + 1), object=o), 0))
            if opts.boss_buffs and k in theme['boss_hp_bonus'] and i == 0:
                eff.append((b.eff((1, 12), 'SV W%02d boss HP' % k, attr=ATTR_HP, op=0,
                                  value=theme['boss_hp_bonus'][k], b4c=1, u50=0, i54=-1,
                                  object=o_type[ut]), 50))
        if bosses:
            names = boss_label(bosses, theme.get('lang', 'en'))
            boss_text = T['boss_pl'] if len(bosses) > 1 and 'boss_pl' in T else T['boss']
            eff += [(b.chat(boss_text % dict(f, boss=names), 15), 50), (snd_boss, 50),
                    (b.eff((2, 15), 'SV W%02d hero bot AI on' % k, on=1,
                           player=PLAYER_ALL_CPUS), 100)]
        if k == waves and theme['final_environment']:
            eff.append((b.eff((5, 7), 'SV Final environment', env=theme['final_environment'],
                              i54=20, b58=1, b59=1), 0))
        for ut in sorted(used):
            eff += [(b.eff((1, 7), 'SV W%02d aggressive %d' % (k, ut), stance=STANCE_AGGRESSIVE,
                           object=o_type[ut]), 100),
                    (b.eff((1, 5), 'SV W%02d attack-move %d' % (k, ut), target=o_human_tc,
                           task=TASK_ATTACK_MOVE, b48=0, object=o_type[ut]), 150)]
        if k < waves:
            eff.append((b.counter(T['next'] % {'k': k + 1}, times[k] - t - 1), 200))
        else:
            eff.append((b.counter(T['last'], 0, show_time=False), 200))
        b.trigger('SV Wave %02d' % k, [(b.time_after(t, 'SV Wave %02d time' % k), False)], eff)
        # co-op bonus: a second human town centre adds half a wave
        bonus = wave_groups(theme, k, theme['coop_bonus'])
        beff = []
        for role, lv, n in bonus:
            ut = vocab.unit(theme['roster'][role][lv])
            o = b.obj('SV W%02d bonus %s L%d x%d' % (k, role, lv, n), PLAYER_ALL_CPUS,
                      unit_type=ut, count=(n, n), **spawn)
            beff.append((b.eff((1, 0), 'SV W%02d bonus %s' % (k, role), object=o), 50))
            beff.append((b.eff((1, 5), 'SV W%02d bonus attack-move %d' % (k, ut),
                               target=o_human_tc, task=TASK_ATTACK_MOVE, b48=0,
                               object=o_type[ut]), 200))
        b.trigger('SV Wave %02d co-op bonus' % k,
                  [(b.time_after(t, 'SV Wave %02d bonus time' % k), False),
                   (b.exists(o_human_tc2, 'SV Two human TCs exist (W%02d)' % k), False)], beff)
        plan.append({'wave': k, 'time': t, 'groups': groups, 'bonus': bonus,
                     'bosses': boss_label(bosses)})

    # enemies that stopped (target dead, fight over) march again every 15 s
    b.trigger('SV Enemies keep attacking', [(b.time_after(times[0] + 15, 'SV After wave 1'),
                                             False)],
              orders(' (loop)', 0), looping=True, true_for=15)

    # end of game -----------------------------------------------------------------------------
    alive = [(b.exists(o, 'SV Enemy type %d exists' % ut), True) for ut, o in o_type.items()]
    b.trigger('SV Victory', [(b.time_after(times[-1] + 10, 'SV After last wave'), False)] + alive,
              [(b.chat(T['win'], 30), 0), (b.sound(theme['sounds']['win']), 0),
               (b.eff((2, 0), 'SV Victory humans', player=PLAYER_ALL_HUMANS), 300),
               (b.eff((2, 2), 'SV Defeat computers', player=PLAYER_ALL_CPUS), 400)],
              true_for=2)
    b.trigger('SV Defeat', [(b.time_after(30, 'SV Game running'), False),
                            (b.exists(o_human_tc, 'SV Human TC exists'), True)],
              [(b.chat(T['lose'], 30), 0),
               (b.eff((2, 2), 'SV Defeat humans', player=PLAYER_ALL_HUMANS), 300)],
              true_for=3)
    if extra:
        extra(b, dict(vocab=vocab, sets=sets, o_human_tc=o_human_tc, times=times))
    b.finish()
    return plan


def build_probe(m, theme, vocab, opts, map_size):
    """Diagnostic map: one trigger action at a time, each announced in chat with its label, each
    probe a different unit type so a screenshot tells them apart. Read the result with the
    table in docs/survival.md (section 'Probe map')."""
    b = Builder(m)
    sets = {k: vocab.unitset(v) for k, v in UNITSETS.items()}
    a_spawn = b.area('SV Spawn centre', *spawn_rect(map_size))
    o_enemy_tc = b.obj('SV Enemy town centres', PLAYER_ALL_CPUS, unit_class=sets['town_centers'],
                       count=(1, 99))
    o_human_tc = b.obj('SV Human town centres', PLAYER_ALL_HUMANS,
                       unit_class=sets['town_centers'], count=(1, 99))
    P = PERSIAN
    steps = [  # (seconds, label, player enum, unit name, placement)
        (5, 'P1 human: L1 sword at map centre', 7, P['sword'][1], 'area'),
        (10, 'all computers: L1 spear at map centre', PLAYER_ALL_CPUS, P['spear'][1], 'area'),
        (15, 'slot 2: L1 archer at map centre', 8, P['archer'][1], 'area'),
        (20, 'slot 3: L1 cavalry at map centre', 9, P['cavalry'][1], 'area'),
        (25, 'slot 4: L3 spear at map centre', 10, P['spear'][3], 'area'),
        (30, 'all computers: L3 sword next to their TC', PLAYER_ALL_CPUS, P['sword'][3], 'near'),
        (35, 'all computers: elephant at centre, 3 units', PLAYER_ALL_CPUS, P['elephant'][3],
         'area3'),
    ]
    probe_types = []
    for t, label, player, unit, place in steps:
        ut = vocab.unit(unit)
        kw = dict(near=o_enemy_tc) if place == 'near' else dict(area=a_spawn)
        n = 3 if place == 'area3' else 1
        o = b.obj('SV Probe %d' % t, player, unit_type=ut, count=(n, n), **kw)
        if player == PLAYER_ALL_CPUS:
            probe_types.append(ut)
        b.trigger('SV Probe %02d s' % t, [(b.time_after(t), False)],
                  [(b.chat('PROBE %d s: %s' % (t, label), 25), 0),
                   (b.eff((1, 0), 'SV Probe create %d' % t, object=o), 50)])
    # selections and diplomacy readings
    c_tc = b.exists(o_enemy_tc, 'SV Probe enemy TC exists')
    b.trigger('SV Probe 40 s TC yes', [(b.time_after(40), False), (c_tc, False)],
              [(b.chat('PROBE 40 s: enemy town centre selection FOUND', 25), 0)])
    b.trigger('SV Probe 40 s TC no', [(b.time_after(40), False), (c_tc, True)],
              [(b.chat('PROBE 40 s: enemy town centre selection EMPTY', 25), 0)])
    for ut in probe_types:
        o = b.obj('SV Probe type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut, count=(1, 99))
        c = b.exists(o, 'SV Probe type %d exists' % ut)
        b.trigger('SV Probe 45 s type %d' % ut, [(b.time_after(45), False), (c, False)],
                  [(b.chat('PROBE 45 s: computer owns type %d (%s)' % (ut, vocab.objects[ut][:32]),
                           25), 0)])
        b.trigger('SV Probe 50 s attack %d' % ut, [(b.time_after(50), False)],
                  [(b.eff((1, 7), 'SV Probe aggressive %d' % ut, stance=STANCE_AGGRESSIVE,
                          object=o), 0),
                   (b.eff((1, 5), 'SV Probe attack-move %d' % ut, target=o_human_tc,
                          task=TASK_ATTACK_MOVE, b48=0, object=o), 50)])
    b.trigger('SV Probe 50 s msg', [(b.time_after(50), False)],
              [(b.chat('PROBE 50 s: computer units ordered to attack-move to your TC', 25), 0)])
    if opts.ai_off:
        b.trigger('SV Probe 55 s AI off', [(b.time_after(55), False)],
                  [(b.chat('PROBE 55 s: computer AI switched off', 25), 0),
                   (b.eff((6, 4), 'SV Probe AI off', setting=AI_SETTING_ENABLED, on=0,
                          player=PLAYER_ALL_CPUS), 0)])
    b.trigger('SV Probe 60 s spawn after AI off', [(b.time_after(60), False)],
              [(b.chat('PROBE 60 s: all computers: L5 sword at centre after AI off', 25), 0),
               (b.eff((1, 0), 'SV Probe create 60', object=b.obj(
                   'SV Probe 60', PLAYER_ALL_CPUS, unit_type=vocab.unit(P['sword'][5]),
                   count=(2, 2), area=a_spawn)), 50)])
    b.trigger('SV Probe 120 s victory', [(b.time_after(120), False)],
              [(b.chat('PROBE 120 s: victory for all humans in 3 s', 25), 0),
               (b.eff((2, 0), 'SV Probe victory', player=PLAYER_ALL_HUMANS), 300)])
    b.finish()
    return [{'wave': 0, 'time': t, 'groups': [], 'bonus': [], 'bosses': label}
            for t, label, *_ in steps]


# --------------------------------------------------------------------------- file level


def test_schedule(theme):
    """Same triggers, compressed clock and small waves, so a live test reaches boss waves,
    victory and the co-op bonus in about 8 minutes."""
    t = dict(theme)
    size = theme['size']
    t['first_wave'], t['intervals'], t['boss_breather'] = 30, [(theme['waves'], 20)], 5
    t['size'] = lambda k: max(1, round(size(k) / 4))
    t['help'] = 'TEST SCHEDULE BUILD. ' + theme['help']
    t['lobby'] = False          # own DisplayName/DisplayHelp instead of the release strings
    return t


def map_id(name):
    """Unique, stable map id (the stock ones look like editor tick counts ~0x12xxxxx)."""
    return 0x7A000000 | (int(hashlib.sha1(name.encode()).hexdigest(), 16) & 0x00FFFFFF)


def set_terrain_environment(raw, env):
    """The map's lighting (.env name) is a length-prefixed string in the terrain chunk (4):
    u32 len incl. two NULs, text, two NULs (e.g. "hdri_clearsky_grasslands" in (4) plains).
    The Environment trigger effect alone did not change the lighting live."""
    import re
    m = re.search(rb'(.{4})(hdri[ -~]{3,60})\0\0', raw, re.S)
    if not m or struct.unpack('<I', m.group(1))[0] != len(m.group(2)) + 2:
        raise ValueError('environment name not found in the terrain chunk')
    new = env.encode('ascii')
    return raw[:m.start()] + struct.pack('<I', len(new) + 2) + new + raw[m.end(2):]


def build_scn(template_path, theme, vocab, opts):
    f = R.load_any(template_path)
    if any(c[0:2] != [4, 0] for c in f.chunks):
        raise ValueError('template chunk version is not 4.0')
    m = R.Manager.parse(f.get(6))
    map_size = struct.unpack_from('<II', f.get(4), 0)      # terrain chunk: width, height
    plan = (build_probe if theme.get('probe') else build_mode)(m, theme, vocab, opts, map_size)
    raw = m.serialize()
    f.put(6, raw)
    if theme.get('environment'):
        f.put(4, set_terrain_environment(f.get(4), theme['environment']))
    h = R.parse_header(f.header)
    file_name = theme['map'] + '.scn'
    pretty = theme['map'].replace('survival zombies', 'Survival Zombies').replace(
        'survival', 'Survival') + '.scn'
    h['name'] = S(pretty)
    h['map_name'] = S(pretty)
    h['desc'] = S(header_help(theme))
    h['map_id'] = map_id(file_name)
    f.header = R.build_header(h)
    f.trailer = struct.pack('<I', h['map_id'])      # the file ends with the map id again
    return f.to_bytes(), raw, plan


def localize(name, theme, lang):
    """Theme with the in-game texts of `lang` ('ru' = default build, 'en' = THEMES as written)."""
    if lang == 'en' or name not in M.SURVIVAL_RU:
        return dict(theme, lang='en')
    return dict(theme, lang='ru', text=dict(M.SURVIVAL_RU[name]))


def header_help(theme):
    """Scenario header description: the lobby help in the build's language."""
    if theme.get('lobby', True) and theme['map'] in M.LOBBY:
        return M.LOBBY[theme['map']][theme.get('lang', 'en')][1]
    return theme['help']


def rmv_text(theme):
    """Lobby entry. Release maps name Language.dll strings like every stock map
    (StringTableID / StringHelpID = map_texts.string_ids; the strings are written into the
    generated Language.dll by raf_patch.build_credits). Test builds carry their own English
    text; the .rmv parser (FUN_00bcd8f0) splits on blanks and groups with [] only."""
    head = ('// %s - generated by tools/build_survival.py (raf-remaster). Scenario map entry:\n'
            '// the game lists Data\\map scripts\\*.rmv and loads Data\\scenarios\\<same name>.scn\n'
            'UseMapGenerator\t\t"Default"\n' % theme['title'])
    if theme.get('lobby', True) and theme['map'] in M.LOBBY:
        nid, hid = M.string_ids(theme['map'])
        body = ' StringTableID\t%d\n StringHelpID\t%d\n' % (nid, hid)
    else:
        body = 'DisplayName\t\t[%s]\nDisplayHelp\t\t[%s]\n' % (theme['map'], theme['help'])
    return (head + body).replace('\n', '\r\n')


def format_table(plan, theme, vocab):
    lines = ['| wave | time | units (2 humans) | composition (level) | boss |',
             '|---:|---:|---:|---|---|']
    for p in plan:
        total = sum(n for _, _, n in p['groups']) + sum(n for _, _, n in p['bonus'])
        solo = sum(n for _, _, n in p['groups'])
        comp = ', '.join('%d %s' % (n, r) for r, lv, n in p['groups'])
        lv = theme['level'](p['wave'])
        lines.append('| %d | %d:%02d | %d (solo %d) | %s (L%d) | %s |' % (
            p['wave'], p['time'] // 60, p['time'] % 60, total, solo, comp, lv,
            p['bosses'] or '-'))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_dir')
    ap.add_argument('overlay_dir')
    ap.add_argument('--theme', default='all', choices=['all'] + sorted(THEMES))
    ap.add_argument('--template', default='(4) plains')
    ap.add_argument('--boss-buffs', action='store_true', help='experimental: boss class HP bonus')
    ap.add_argument('--zombie-buffs', action='store_true',
                    help='experimental: zombie class HP/speed changes via template units')
    ap.add_argument('--no-diplomacy', dest='force_diplomacy', action='store_false',
                    help='do not set "humans allied, computers hostile" by trigger at start')
    ap.add_argument('--table', action='store_true', help='print the wave tables (markdown)')
    ap.add_argument('--spawn', choices=['area', 'near'], default='area',
                    help='area: map centre (encoding of the shipped maps, default); near: next '
                         'to the computer town centre (no shipped precedent, failed live)')
    ap.add_argument('--probe', action='store_true',
                    help='LIVE TESTING ONLY: write "(4) survival probe", one action per step')
    ap.add_argument('--keep-ai', dest='ai_off', action='store_false',
                    help='do not switch the computer AI off at start')
    ap.add_argument('--unitset-base', type=int, default=UNITSET_BASE,
                    help='class value of dbunitset record 0 (137 per the runtime code; the '
                         'campaign files suggest 134, see docs/scenario-format.md 3.5)')
    ap.add_argument('--waves', type=int, help='LIVE TESTING ONLY: number of waves (win-path test)')
    ap.add_argument('--test-schedule', action='store_true',
                    help='LIVE TESTING ONLY: wave 1 at 0:30, 20 s apart, 1/4 size')
    ap.add_argument('--lang', choices=M.LANGS, default='ru',
                    help='language of the in-game texts (default ru; all players need the same '
                         'build). Lobby name/help come from Language.dll either way.')
    ap.add_argument('--no-previews', dest='previews', action='store_false',
                    help='do not write the lobby picture (Data/textures) and movie (Data/movies)')
    opts = ap.parse_args(argv)
    game = Path(opts.game_dir)
    template = game / 'Data' / 'scenarios' / (opts.template + '.scn')
    vocab = Vocab(game, opts.unitset_base)
    out = Path(opts.overlay_dir)
    themes = sorted(THEMES) if opts.theme == 'all' else [opts.theme]
    if opts.probe:
        themes = ['probe']
    for name in themes:
        theme = THEMES.get(name) or dict(THEMES['classic'], map='(4) survival probe',
                                         title='Survival probe', probe=True, lobby=False,
                                         help='DIAGNOSTIC MAP for the survival triggers.')
        theme = localize(name, theme, 'en' if theme.get('probe') else opts.lang)
        if opts.test_schedule:
            theme = test_schedule(theme)
        if opts.waves:
            theme = dict(theme, waves=opts.waves, lobby=False,
                         help='TEST %d WAVES. ' % opts.waves + theme['help'])
        data, raw, plan = build_scn(template, theme, vocab, opts)
        scn = out / 'Data' / 'scenarios' / (theme['map'] + '.scn')
        rmv = out / 'Data' / 'map scripts' / (theme['map'] + '.rmv')
        scn.parent.mkdir(parents=True, exist_ok=True)
        rmv.parent.mkdir(parents=True, exist_ok=True)
        scn.write_bytes(data)
        rmv.write_bytes(rmv_text(theme).encode('ascii'))
        if opts.previews and not theme.get('probe'):
            P.write_previews(game, opts.template, theme['map'], out)
        print('%-8s %s  %d bytes  sha256 %s' % (name, scn, len(data),
                                               hashlib.sha256(data).hexdigest()[:12]))
        if opts.table:
            print(format_table(plan, theme, vocab))
    return 0


if __name__ == '__main__':
    sys.exit(main())
