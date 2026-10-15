"""Offline checks for the Survival maps (tools/build_survival.py). Runs every check in one go.

Usage:
    python tools/check_survival.py <game_dir> [<overlay_dir>]

1. format:  the shipped scenarios still round-trip byte for byte (tools/raf_scn.py stock);
2. build:   the generator is deterministic and matches the overlay files (if given);
3. file:    our .scn re-parses, round-trips, keeps every template chunk except the trigger
            chunk byte for byte, header/trailer map id agree;
4. refs:    every trigger/condition/effect/object reference resolves under the game's index
            rules, condition memory order is kept, ids are unique and the id counters cover them;
5. vocab:   every condition/effect class and every enum-like field value we write was seen in
            the shipped scenarios, or is listed in PROVEN_NEW with the code that proves it;
            unit types, unit sets, sounds and environments exist in the install;
6. stub:    a stub of the trigger engine (rules from FUN_008d0d80) plays the map against a fake
            world: normal win, solo, defeat mid-game, early defeat, survivors left alive.
Nothing here starts the game.
"""
import hashlib
import struct
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_scn as R  # noqa: E402
import build_survival as B  # noqa: E402

FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)
        print('  FAIL', msg)
    return ok


# enum-like fields: (component kind, class name, field)
ENUM_FIELDS = [
    ('E', 'TaskToObject', 'task'), ('E', 'TaskToArea', 'task'), ('E', 'SetStance', 'stance'),
    ('E', 'ChangeUnitClassAttribute', 'attr'), ('E', 'ChangeUnitClassAttribute', 'op'),
    ('E', 'ChangeUnitClassAttribute', 'b4c'), ('E', 'ChangeResourceLevel', 'resource'),
    ('E', 'ChangeResourceLevel', 'amount'), ('E', 'AIToggleSetting', 'setting'),
    ('E', 'ChangeDiplomaticStance', 'stance'), ('E', 'Counter', 'u74'),
    ('E', 'Victory', 'player'), ('E', 'Defeat', 'player'), ('E', 'ChangeResourceLevel', 'player'),
    ('E', 'AIToggleSetting', 'player'), ('E', 'ActivateHeroBotAI', 'player'),
    ('E', 'SendChatMessage', 'u54'), ('E', 'ChangeDiplomaticStance', 'other'),
    ('E', 'ChangeDiplomaticStance', 'player'),
    ('C', 'GameHasAttribute', 'b3d'), ('C', 'GameHasAttribute', 'u40'),
    ('O', 'object', 'player'), ('O', 'object', 'ub8'), ('O', 'object', 'u8c'),
    ('O', 'object', 'uc4'), ('O', 'object', 'ua8'),
]
# values not used by any shipped scenario, with the code that defines them
# effect fields that carry player-visible text (and the effect names derived from them: 'MSG ...',
# 'COUNTER ...'): ASCII plus cp1251 Cyrillic, as in the stock Russian scenarios (tutorials,
# (2) gamersday); every other text field stays ASCII
PLAYER_TEXT_FIELDS = ('text', 'counter', 'name')

PROVEN_NEW = {
    ('E', 'Victory', 'player', 3): 'FUN_0089c9a0 case 3 = every human player (bfada0 loops them)',
    ('E', 'Defeat', 'player', 3): 'FUN_0089c9a0 case 3 = every human player (8c3fa0 loops them)',
    ('E', 'Defeat', 'player', 4): 'FUN_0089c9a0 case 4 = every computer player',
    ('E', 'ChangeResourceLevel', 'player', 4): 'stock uses 4 = all computers (gaugamela)',
    ('E', 'AIToggleSetting', 'player', 4): 'FUN_008af7f0 resolves players with FUN_0089c9a0',
    ('E', 'ActivateHeroBotAI', 'player', 4): 'player effect, FUN_0089c9a0 case 4',
    ('E', 'SendChatMessage', 'u54', 3): 'FUN_008b6490 resolves u54 with FUN_0089c9a0, shows locally',
    ('E', 'ChangeDiplomaticStance', 'other', 3): 'FUN_008c36c0 resolves other with FUN_0089c9a0',
    ('E', 'ChangeDiplomaticStance', 'other', 4): 'FUN_008c36c0 resolves other with FUN_0089c9a0',
    ('E', 'ChangeDiplomaticStance', 'player', 3): 'FUN_008c36c0 resolves player with FUN_0089c9a0',
    ('O', 'object', 'player', 3): 'Create/select resolve the object player with FUN_0089c9a0',
    ('O', 'object', 'player', 4): 'Create/select resolve the object player with FUN_0089c9a0',
    ('O', 'object', 'ub8', 1): 'near-object placement, FUN_008cee10 (+0xb8 == 1)',
    ('O', 'object', 'u8c', 0): 'near distance 0 = line of sight radius, FUN_008cee10',
}


def class_name(kind, o):
    if kind == 'C':
        return R.CONDITIONS[o['_type']][0]
    if kind == 'E':
        return R.EFFECTS[R.effect_key(o['_cat'], o['_type'])][0]
    return 'object'


def stock_vocab(game):
    vocab = defaultdict(set)
    classes = set()
    for _, f in R.stock_scenarios(str(game)):
        m = R.Manager.parse(f.get(6))
        for kind, items in (('C', m.conditions), ('E', m.effects), ('O', m.objects)):
            for o in items:
                cn = class_name(kind, o)
                classes.add((kind, cn))
                for k, v in o.items():
                    if isinstance(v, int):
                        vocab[(kind, cn, k)].add(v)
    return classes, vocab


# --------------------------------------------------------------------------- structure


def check_file(data, raw, template, label, environment=None):
    """environment: the theme's night lighting; then the terrain chunk (4) may differ from the
    template, but only by that environment name (build_survival.set_terrain_environment)."""
    f = R.ScnFile(data)
    check(struct.unpack_from('<I', data, 0)[0] == len(data) - 4, label + ': payload length')
    h = R.parse_header(f.header)
    check(R.build_header(h) == f.header and not h['_rest'], label + ': header round trip')
    check(struct.unpack('<I', f.trailer)[0] == h['map_id'], label + ': trailer = map id')
    t = R.load_any(template)
    check([c[2] for c in f.chunks] == [c[2] for c in t.chunks], label + ': chunk order')
    for a, b in zip(f.chunks, t.chunks):
        if a[2] == 4 and environment:
            check(f.get(4) == B.set_terrain_environment(t.get(4), environment),
                  label + ': chunk 4 differs by more than the environment name')
        elif a[2] != 6:
            check(a == b, label + ': chunk %d changed' % a[2])
    check(f.get(6) == raw, label + ': chunk 6 content')
    m = R.Manager.parse(raw, full_tail=True)
    check(m.serialize() == raw, label + ': manager round trip')
    return m, h


def check_refs(m, label, base_trig):
    nc, ne, no, na, nt = len(m.conditions), len(m.effects), len(m.objects), len(m.areas), len(m.triggers)
    first_oe = next((i for i, c in enumerate(m.conditions) if c['_type'] == 1), nc)
    check(all(c['_type'] == 1 for c in m.conditions[first_oe:]),
          label + ': ObjectExists conditions must come last (loader reorders them)')
    for t in m.triggers:
        for neg, op, c in t['if']:
            check(c == 0 or 3 <= c < 3 + nc, label + ': condition ref %d' % c)
            check(op in (0, 1, 2), label + ': condition op')
        for key in ('then', 'else'):
            for delay, op, e in t[key]:
                check(0 <= e <= ne, label + ': effect ref %d' % e)
        check(t['if'][-1][1] == 0 and t['then'][-1][1] == 0, label + ': list end op')
    for e in m.effects:
        for k in ('object', 'target', 'mount', 'with_object'):
            if k in e and k != 'with_object':
                check(0 <= e[k] <= no, label + ': %s ref %d' % (k, e[k]))
        if R.effect_key(e['_cat'], e['_type']) == (3, 0):
            check(e['action'] < nt, label + ': trigger ref')
        if 'area' in e:
            check(e['area'] < 2 + na, label + ': area ref')
    for o in m.objects:
        check(o['u90'] <= no and o['u94'] <= no and o['u88'] < 2 + na, label + ': object refs')
        if o['ub8']:
            check(o['u90'] >= 1, label + ': near object set')
        check(o['bdd'] == 1 or o['bdc'] == 1, label + ': dynamic object must have bdd=1')
        if R.T(o['name']).startswith('SV W'):
            check(o['ub4'] == 1 and o['u88'] >= 2 and not o['ub8'],
                  label + ': wave spawn must use the shipped "inside area" encoding')
    for kind, items, key in (('trigger', m.triggers, 'u88'), ('condition', m.conditions, 'c_unused38'),
                             ('effect', m.effects, 'e_unused38'), ('object', m.objects, 'ub0'),
                             ('area', m.areas, 'u74')):
        ids = [o[key] for o in items]
        check(len(ids) == len(set(ids)), label + ': %s ids unique' % kind)
    counters = struct.unpack_from('<5I', m.tail, 0)
    maxima = [max([t['u88'] for t in m.triggers], default=0),
              max([c['c_unused38'] for c in m.conditions], default=0),
              max([e['e_unused38'] for e in m.effects], default=0),
              max([o['ub0'] for o in m.objects], default=0),
              max([a['u74'] for a in m.areas], default=0)]
    check(all(c >= mx for c, mx in zip(counters, maxima)), label + ': id counters')
    ours = m.triggers[base_trig:]
    check(all(R.T(t['name']).startswith('SV ') for t in ours), label + ': our triggers are SV *')


def check_vocab(m, game, vocab_stock, classes_stock, label, template_m):
    skip = (len(template_m.conditions), len(template_m.effects), len(template_m.objects))
    ours = [('C', c) for c in m.conditions if R.T(c['name']).startswith('SV ')] + \
           [('E', e) for e in m.effects[skip[1]:]] + [('O', o) for o in m.objects[skip[2]:]]
    vocab = B.Vocab(game)
    sounds = {p.stem.lower() for p in (Path(game) / 'Data' / 'sounds' / 'high').glob('*.wav')}
    envs = {p.stem.lower() for p in (Path(game) / 'Data' / 'environments').glob('*.env')}
    new_values = set()
    for kind, o in ours:
        cn = class_name(kind, o)
        check((kind, cn) in classes_stock, label + ': class %s/%s never used by a shipped scenario'
              % (kind, cn))
        for k, fcn, f in ENUM_FIELDS:
            if k == kind and fcn == cn and f in o:
                v = o[f]
                if v not in vocab_stock[(kind, cn, f)]:
                    why = PROVEN_NEW.get((kind, cn, f, v))
                    check(why is not None, label + ': %s.%s = %d not in stock vocabulary %s' % (
                        cn, f, v, sorted(vocab_stock[(kind, cn, f)])[:12]))
                    new_values.add((cn, f, v, why))
        if kind == 'O':
            if o['u84']:
                name = vocab.objects[o['u84']]
                check(not any(w in name for w in ('(Test)', 'Cinematic', 'zzz')),
                      label + ': unit type %r looks unusable' % name)
            if o['u80'] and not R.T(o['name']).startswith('SV W'):
                check(B.UNITSET_BASE <= o['u80'] < B.UNITSET_BASE + len(vocab.unitsets),
                      label + ': unit set ref')
            check(o['class_name'] == R.S(str(int(R.T(o['class_name'])))), label + ': count text')
        if kind == 'E' and cn == 'PlaySound':
            check(R.T(o['sound']).lower() in sounds, label + ': sound %s missing' % R.T(o['sound']))
        if kind == 'E' and cn == 'Environment':
            check(R.T(o['env']).lower() in envs, label + ': environment %s missing' % R.T(o['env']))
        for k, v in o.items():
            if isinstance(v, bytes):
                body = v.rstrip(b'\0')
                if k in PLAYER_TEXT_FIELDS:     # shown to players: cp1251 like the stock texts
                    check(all(b == 0x0A or 0x20 <= b < 0x7F or b >= 0xC0 for b in body),
                          label + ': %s has bytes outside ASCII + cp1251 Cyrillic' % k)
                else:
                    check(all(b < 0x80 for b in body), label + ': non-ASCII text in %s' % k)
                check(len(v) < 400, label + ': text too long')
    heroes = vocab.set_members(vocab.unitset(B.UNITSETS['heroes']))['types']
    for o in m.objects[skip[2]:]:
        if 'boss' in R.T(o['name']) and o['u84']:
            check(o['u84'] in heroes, label + ': boss %d not in the hero unit set' % o['u84'])
    return new_values


# --------------------------------------------------------------------------- lobby texts, previews


def check_lobby_texts(game):
    """map_texts: every string encodable and in the safe byte set, help within the stock size,
    string ids free in the stock Language.dll (and the lang-en build if present) and apart from
    the zoom-setting ids; the patched Language.dll returns exactly our strings."""
    import tempfile as _tf
    import map_texts as M
    import raf_credits as rc
    import zoom_setting as zs
    from build_language import Dll

    n = 0
    for label, text in M.all_texts():
        try:
            M.encode(text)
            n += 1
        except (ValueError, UnicodeEncodeError) as e:
            check(False, 'map_texts %s: %s' % (label, e))
    samples = dict(k=7, n=12, tok='/#PA0042', labels=['Julius Caesar', 'Tor'], every=30, give=100,
                   have=300, more=800)
    keys = ['endless_intro', 'wave_in', 'next_wave_in', 'wave_coming', 'lead_wave', 'fallen_first',
            'fallen_wave', 'fallen_endless', 'hunt_intro', 'boss_in', 'boss_coming', 'boss_counter',
            'boss_fallen', 'hunt_victory', 'hunt_defeat', 'roles_intro', 'roles_tithe',
            'roles_ai_intro', 'vsai_intro']
    for lang in M.LANGS:
        for key in keys:
            for labels in (['Cleopatra'], ['Sargon'], ['Julius Caesar', 'Tor']):
                text = M.coop(lang, key, **dict(samples, labels=labels))
                try:
                    M.encode(text)
                except (ValueError, UnicodeEncodeError) as e:
                    check(False, 'map_texts coop %s %s: %s' % (lang, key, e))
                check(len(text) < 300, 'map_texts coop %s %s: too long' % (lang, key))
    check(M.coop('ru', 'boss_fallen', labels=['Cleopatra']).endswith('пала!'), 'ru: Cleopatra gender')
    check(M.coop('ru', 'fallen_wave', k=6).endswith('5 волн.'), 'ru: plural 5')
    check(M.coop('ru', 'fallen_wave', k=3).endswith('2 волны.'), 'ru: plural 2')
    check(M.coop('ru', 'fallen_wave', k=2).endswith('1 волну.'), 'ru: plural 1')
    for stem in M.MAPS:
        for lang in M.LANGS:
            name, help_ = M.LOBBY[stem][lang]
            check(name.startswith(stem[:4]) and help_.startswith(stem[:3] + ' /fb'),
                  '%s %s: name/help do not start like the stock texts' % (stem, lang))
            check(len(help_) <= M.HELP_MAX_CHARS and help_.count('\n') <= M.HELP_MAX_BREAKS,
                  '%s %s: help longer than the stock ones (%d chars)' % (stem, lang, len(help_)))
            check(help_.count('/fb') == help_.count('/fd'), '%s %s: /fb without /fd' % (stem, lang))
    ids = set()
    for stem in M.MAPS:
        ids |= set(M.string_ids(stem))
    check(len(ids) == 2 * len(M.MAPS), 'map string ids not unique')
    zoom_ids = set(zs.string_repl('ru'))
    check(not (ids & zoom_ids), 'map string ids clash with zoom-setting ids')
    dlls = [Path(game) / 'Language.dll']
    en = Path(__file__).resolve().parent.parent / 'work' / 'overlay-lang-en' / 'Language.dll'
    if en.exists():
        dlls.append(en)
    for dll in dlls:
        d = Dll(str(dll))
        used = ids & set(d.strings)
        check(not used, '%s: map string ids already used: %s' % (dll, sorted(used)))
        for lang in M.LANGS:
            with _tf.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'Language.dll'
                extra = {**zs.string_repl(lang), **M.string_repl(lang)}
                rc.patch_language_dll(dll, out, '1.0', extra=extra, credits=True)
                got = Dll(str(out)).strings
                for sid, text in M.string_repl(lang).items():
                    check(got.get(sid) == text, '%s %s: string %d reads back %r' % (
                        dll.name, lang, sid, (got.get(sid) or '')[:30]))
                check(all(got.get(sid) == t for sid, t in d.strings.items()
                          if sid not in extra and sid not in (rc.COPYRIGHT_ID, rc.CREDITS_FIRST_ID,
                                                               rc.CREDITS_TIME_ID)),
                      '%s %s: other strings changed' % (dll.name, lang))
                if sys.platform == 'win32':
                    from build_language import verify_dll_loads
                    bad = verify_dll_loads(str(out), M.string_repl(lang))
                    check(bad == 0, '%s %s: LoadStringW mismatches %d' % (dll.name, lang, bad))
                    acp, bad = loadstring_a(out, M.string_repl(lang))
                    if acp == 1251:     # the game reads its strings with LoadStringA (LowLevelEngine)
                        check(bad == 0, '%s %s: LoadStringA (cp1251) mismatches %d' % (
                            dll.name, lang, bad))
                    elif lang == 'ru':
                        print('  note: ANSI code page %d, LoadStringA path not checked' % acp)
    print('  %d fixed texts encodable, %d coop texts, %d string ids free in %s' % (
        n, len(keys) * 6, len(ids), ', '.join(p.parent.name + '/' + p.name for p in dlls)))


def negative_lobby_tests(game):
    """Broken lobby entries / pictures / texts must be caught."""
    import shutil
    import io
    import contextlib
    import map_texts as M

    def caught(label, mutate):
        with tempfile.TemporaryDirectory() as a:
            with contextlib.redirect_stdout(io.StringIO()):
                B.main([str(game), a, '--theme', 'classic'])
            mutate(Path(a))
            before = len(FAILS)
            with contextlib.redirect_stdout(io.StringIO()):
                check_map_outputs(game, a, {'(4) survival': '(4) plains'}, 'neg')
            n = len(FAILS) - before
            del FAILS[before:]
        check(n > 0, 'negative test not caught: ' + label)
        print('  caught: %-60s (%d findings)' % (label, n))

    def old_rmv(a):
        p = a / 'Data' / 'map scripts' / '(4) survival.rmv'
        p.write_bytes(p.read_bytes().replace(b' StringTableID', b'DisplayHelp\t(x)\r\n//'))

    def stray_pixel(a):
        p = a / 'Data' / 'textures' / '(4) survival.tga'
        d = bytearray(p.read_bytes())
        d[18 + 4 * (256 * 200 + 10)] ^= 0xFF          # bottom-up row 200 = top row 55, x 10
        p.write_bytes(bytes(d))

    def other_movie(a):
        p = a / 'Data' / 'movies' / '(4) Survival.bik'
        shutil.copyfile(Path(game) / 'Data' / 'movies' / '(5) Babylon.bik', p)

    caught('rmv with its own help text instead of the string ids', old_rmv)
    caught('picture changed outside the badge', stray_pixel)
    caught('movie that is not the template movie', other_movie)
    for bad in ('Волна — 5', 'ёлка', 'Ура «вперед»'):
        try:
            M.encode(bad)
            check(False, 'negative test not caught: unsafe character in %r' % bad)
        except (ValueError, UnicodeEncodeError):
            print('  caught: %-60s' % ('unsafe character in a text (%s)' % ascii(bad)[:20]))


def loadstring_a(path, expect):
    """The game's own path: UResourceFile::GetString = LoadStringA (ANSI code page, LowLevelEngine
    0x10.. 'LoadStringA'). Returns (code page, mismatches against the cp1251 bytes)."""
    import ctypes
    from ctypes import wintypes
    import map_texts as M
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.LoadStringA.argtypes = [wintypes.HMODULE, wintypes.UINT, ctypes.c_char_p, ctypes.c_int]
    h = k.LoadLibraryExW(str(Path(path).resolve()), None, 0x2)     # LOAD_LIBRARY_AS_DATAFILE
    if not h:
        return k.GetACP(), len(expect)
    buf = ctypes.create_string_buffer(4096)
    bad = 0
    for sid, text in expect.items():
        n = u.LoadStringA(h, sid, buf, 4096)
        bad += buf.raw[:n] != M.encode(text)
    k.FreeLibrary(h)
    return k.GetACP(), bad


def badge_area(stem):
    import map_preview as P
    cx, cy = P.PICTURE[0] - 28, P.PICTURE[1] - 28
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= 22 * 22


def check_map_outputs(game, out, maps, label):
    """maps: {stem: template}. The .rmv names the map's Language.dll strings; the preview picture
    is the template's with only the badge changed; the movie is the template's."""
    import map_texts as M
    import map_preview as P

    game, out = Path(game), Path(out)
    for stem, template in maps.items():
        rmv = (out / 'Data' / 'map scripts' / (stem + '.rmv')).read_bytes()
        nid, hid = M.string_ids(stem)
        check(b' StringTableID\t%d\r\n' % nid in rmv and b' StringHelpID\t%d\r\n' % hid in rmv
              and b'DisplayHelp' not in rmv and b'DisplayName' not in rmv,
              '%s %s: rmv does not name strings %d/%d' % (label, stem, nid, hid))
        src = game / 'Data' / 'textures' / (template + '.tga')
        tga = out / 'Data' / 'textures' / (stem + '.tga')
        if check(tga.is_file(), '%s %s: no preview picture' % (label, stem)):
            h0, w0, hh0, r0, d0, t0 = P.read_tga(src)
            h1, w1, hh1, r1, d1, t1 = P.read_tga(tga)
            check((h0, w0, hh0, d0, t0) == (h1, w1, hh1, d1, t1) and
                  tga.stat().st_size == src.stat().st_size,
                  '%s %s: picture header/size differs from %s' % (label, stem, template))
            inside = badge_area(stem)
            changed = outside = 0
            for y in range(hh0):
                for x in range(w0):
                    a, b = r0[y][x * 4:x * 4 + 4], r1[y][x * 4:x * 4 + 4]
                    if a != b:
                        changed += 1
                        outside += not inside(x, y)
                    if inside(x, y):
                        check(b[3] == 255, '%s %s: badge pixel not opaque' % (label, stem))
            check(changed > 500 and outside == 0, '%s %s: %d pixels changed, %d outside the badge'
                  % (label, stem, changed, outside))
        mv = out / 'Data' / 'movies' / P.movie_name(stem)
        smv = game / 'Data' / 'movies' / P.movie_name(template)
        check(mv.is_file() and mv.read_bytes() == smv.read_bytes(),
              '%s %s: movie is not the template movie' % (label, stem))
    glyphs = {P.BADGES[s] for s in maps}
    check(len(glyphs) == len(maps), label + ': two maps share the same badge')
    print('  %s: %d lobby entries name their strings, pictures + movies from %s' % (
        label, len(maps), ', '.join(sorted(set(maps.values())))))


# --------------------------------------------------------------------------- stub engine


class World:
    """Fake game state for the stub: human town centres and enemy units by kind."""

    def __init__(self, human_tcs):
        self.human_tcs = human_tcs
        self.enemy = []            # [spawn_time, type, kind('army'|'hero'), alive]
        self.log = []
        self.result = None


def stub_run(m, vocab, scenario, t_end=4000.0, label=''):
    hero_types = set(vocab.set_members(vocab.unitset(B.UNITSETS['heroes']))['types'])
    tc_set = vocab.unitset(B.UNITSETS['town_centers'])
    army_set = vocab.unitset(B.UNITSETS['army'])
    hero_set = vocab.unitset(B.UNITSETS['heroes'])
    w = World(scenario['tcs'](0))
    trig = [dict(t, _on=bool(t['on']), _since=0.0, _fired=0) for t in m.triggers]
    pending = []                  # (time, effect_ref, trigger index)
    fires = defaultdict(list)

    def select(o, t):
        if o['u80'] == tc_set and o['player'] == B.PLAYER_ALL_HUMANS:
            return w.human_tcs
        if o['player'] == B.PLAYER_ALL_CPUS and o['u84'] and not o['u80']:
            return sum(1 for u in w.enemy if u[3] and u[1] == o['u84'])
        if o['player'] == B.PLAYER_ALL_CPUS and o['u80'] in (army_set, hero_set):
            want_hero = o['u80'] == hero_set
            n = [u for u in w.enemy if u[3] and (u[2] == 'hero') == want_hero]
            if o['uc4']:      # idle filter: the stub world never leaves units idle
                return 0
            return len(n)
        return 0

    def cond_true(ref, t):
        if ref == 0:
            return True
        c = m.conditions[ref - 3]
        if c['_type'] == 7:
            return c['u44'] < t <= c['u48']
        if c['_type'] == 1:
            o = m.objects[c['object'] - 1]
            return select(o, t) >= int(R.T(o['class_name']))
        raise AssertionError('stub does not model condition type %d' % c['_type'])

    def apply(ref, t):
        e = m.effects[ref - 1]
        key = R.effect_key(e['_cat'], e['_type'])
        name = R.T(e['name'])
        if key == (1, 0):
            o = m.objects[e['object'] - 1]
            n = int(R.T(o['class_name']))
            kind = 'hero' if o['u84'] in hero_types else 'army'
            if 'Template' in R.T(o['name']):
                return
            for _ in range(n):
                w.enemy.append([t, o['u84'], kind, True])
        elif key == (2, 0) and e['player'] == B.PLAYER_ALL_HUMANS:
            if w.result is None:
                w.result = ('victory', t)
        elif key == (2, 2) and e['player'] == B.PLAYER_ALL_HUMANS:
            if w.result is None:
                w.result = ('defeat', t)
        elif key == (3, 0):
            trig[e['action']]['_on'] = e['trigger'] == 0
        w.log.append((t, name))

    t = 0.0
    dt = 0.5
    while t < t_end and w.result is None:
        w.human_tcs = scenario['tcs'](t)
        for u in w.enemy:
            if u[3] and scenario['kill'](u, t):
                u[3] = False
        while pending and pending[0][0] <= t:
            _, ref, _ = pending.pop(0)
            apply(ref, t)
        for i, tr in enumerate(trig):
            if not tr['_on']:
                continue
            ok = all(cond_true(c, t) != bool(neg) for neg, op, c in tr['if'])
            if not ok:
                tr['_since'] = 0.0
                continue
            if tr['true_for']:
                if not tr['_since']:
                    tr['_since'] = t
                    continue
                if (t - tr['_since']) < tr['true_for']:
                    continue
            tr['_since'] = 0.0
            if not tr['looping']:
                tr['_on'] = False
            fires[i].append(t)
            for delay, op, ref in tr['then']:
                if ref:
                    pending.append((t + delay / 100.0, ref, i))
            pending.sort()
        t += dt
    return w, fires


def run_stub_suite(m, vocab, theme, base_trig, label):
    times = B.wave_times(theme)
    names = [R.T(t['name']) for t in m.triggers]
    idx = {n: i for i, n in enumerate(names)}
    last = times[-1]
    fall = times[len(times) // 2 - 1] + 5

    def kill_after(sec):
        return lambda u, t: t >= u[0] + sec

    cases = {
        'normal (2 humans, kill each unit after 60 s)':
            dict(tcs=lambda t: 2, kill=kill_after(60), expect='victory'),
        'solo (1 human)':
            dict(tcs=lambda t: 1, kill=kill_after(45), expect='victory'),
        'town falls mid-game (after wave %d)' % (len(times) // 2):
            dict(tcs=lambda t: 2 if t < fall else 0, kill=kill_after(60), expect='defeat'),
        'town falls before the 30 s guard':
            dict(tcs=lambda t: 0 if t > 10 else 2, kill=kill_after(60), expect='defeat'),
        'survivors: units of the last wave live until last+300 s':
            dict(tcs=lambda t: 2, kill=lambda u, t: t >= (last + 300 if u[0] >= last else u[0] + 60),
                 expect='victory'),
    }
    for cname, sc in cases.items():
        w, fires = stub_run(m, vocab, sc, label=label)
        res = w.result
        check(res is not None and res[0] == sc['expect'], '%s stub %s: expected %s, got %s' % (
            label, cname, sc['expect'], res))
        if sc['expect'] == 'victory' and res:
            for k, tk in enumerate(times, 1):
                f = fires[idx['SV Wave %02d' % k]]
                check(len(f) == 1 and tk < f[0] <= tk + 1.0, '%s stub %s: wave %d fired %s, want %d'
                      % (label, cname, k, f, tk))
                bonus = fires[idx['SV Wave %02d co-op bonus' % k]]
                if 'solo' in cname:
                    check(not bonus, '%s stub solo: co-op bonus fired at wave %d' % (label, k))
                else:
                    check(len(bonus) == 1, '%s stub %s: bonus wave %d fired %d times' % (
                        label, cname, k, len(bonus)))
            check(res[1] > last + 10, '%s stub %s: victory before the last wave (%s)' % (
                label, cname, res))
            if 'survivors' in cname:
                check(res[1] >= last + 300, '%s stub: victory while enemies alive (%s)' % (label, res))
            n_passive = len(fires[idx['SV Keep enemy passive']])
            check(n_passive >= int(last / 25), '%s stub: passive loop fired %d times' % (label, n_passive))
        if sc['expect'] == 'defeat' and res:
            if 'guard' in cname:
                check(30 <= res[1] <= 40, '%s stub early defeat at %s' % (label, res))
            else:
                check(fall < res[1] <= fall + 10, '%s stub defeat time %s' % (label, res))
        spawned = sum(1 for _ in w.enemy)
        print('  stub %-55s -> %-8s at %7.1f s, %4d enemies spawned' % (
            cname, res[0] if res else None, res[1] if res else -1, spawned))


def negative_tests(game, vocab, template_m):
    """Break the built map on purpose; every check must notice (guards against checks that
    can never fail)."""
    import copy
    theme = B.THEMES['classic']

    class Opts:
        boss_buffs = zombie_buffs = False
        force_diplomacy = True
        ai_off = True
        spawn = 'area'

    tf = R.load_any(Path(game) / 'Data' / 'scenarios' / '(4) plains.scn')
    m0 = R.Manager.parse(tf.get(6))
    B.build_mode(m0, theme, vocab, Opts, struct.unpack_from('<II', tf.get(4), 0))
    base = len(template_m.triggers)
    names = [R.T(t['name']) for t in m0.triggers]

    def caught(label, mutate, run):
        m = copy.deepcopy(m0)
        mutate(m)
        before = len(FAILS)
        run(m)
        n = len(FAILS) - before
        del FAILS[before:]
        check(n > 0, 'negative test not caught: ' + label)
        print('  caught: %-60s (%d findings)' % (label, n))

    def quiet(fn):
        def run(m):
            import io
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                fn(m)
        return run

    refs = quiet(lambda m: check_refs(m, 'neg', base))
    stub = quiet(lambda m: run_stub_suite(m, vocab, theme, base, 'neg'))

    def oe_first(m):
        oe = [c for c in m.conditions if c['_type'] == 1]
        m.conditions[:] = oe + [c for c in m.conditions if c['_type'] != 1]
    caught('ObjectExists conditions stored before the others', oe_first, refs)

    def bad_ref(m):
        t = m.triggers[names.index('SV Wave 03')]
        t['then'][0] = (0, 1, len(m.effects) + 5)
    caught('effect reference past the end', bad_ref, refs)

    def dup_id(m):
        m.objects[-1]['ub0'] = m.objects[-2]['ub0']
    caught('duplicate object id', dup_id, refs)

    def no_bonus_guard(m):
        t = m.triggers[names.index('SV Wave 05 co-op bonus')]
        t['if'] = t['if'][:1]
        t['if'][0] = (t['if'][0][0], 0, t['if'][0][2])
    caught('co-op bonus without the two-town-centre condition', no_bonus_guard, stub)

    def no_guard(m):
        t = m.triggers[names.index('SV Defeat')]
        t['if'] = [(neg, 0, c) for neg, op, c in t['if'][1:]]
    caught('defeat without the 30 s start guard', no_guard, stub)

    def early_victory(m):
        t = m.triggers[names.index('SV Victory')]
        t['if'] = [t['if'][0][:1] + (0,) + t['if'][0][2:]]
    caught('victory that ignores surviving enemies', early_victory, stub)


# --------------------------------------------------------------------------- main


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    game = Path(argv[0])
    overlay = Path(argv[1]) if len(argv) > 1 else None
    print('1. shipped scenarios round trip')
    n = bad = 0
    for lab, f in R.stock_scenarios(str(game)):
        n += 1
        raw = f.get(6)
        ok = R.Manager.parse(raw, full_tail=True).serialize() == raw and \
            R.build_header(R.parse_header(f.header)) == f.header
        bad += not ok
    check(bad == 0, '%d of %d shipped scenarios do not round-trip' % (bad, n))
    print('  %d shipped scenarios, %d differ' % (n, bad))
    classes, vocab_stock = stock_vocab(game)
    vocab = B.Vocab(game)
    template = game / 'Data' / 'scenarios' / '(4) plains.scn'
    template_m = R.Manager.parse(R.load_any(template).get(6))
    for flags in ([], ['--boss-buffs', '--zombie-buffs'], ['--no-diplomacy'], ['--test-schedule'],
                  ['--lang', 'en']):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            B.main([str(game), a] + flags)
            B.main([str(game), b] + flags)
            files_a = {p.relative_to(a): p.read_bytes() for p in Path(a).rglob('*') if p.is_file()}
            files_b = {p.relative_to(b): p.read_bytes() for p in Path(b).rglob('*') if p.is_file()}
            check(files_a == files_b, '%s: build output not deterministic' % (flags,))
            if overlay and not flags:
                ov = {p.relative_to(overlay): p.read_bytes() for p in overlay.rglob('*') if p.is_file()}
                check(ov == files_a, 'overlay differs from a fresh build (rebuild it): %s' % sorted(
                    str(k) for k in set(ov) ^ set(files_a) | {k for k in ov if ov[k] != files_a.get(k)}))
            if not flags:
                check_map_outputs(game, a, {t['map']: '(4) plains' for t in B.THEMES.values()},
                                  'survival')
            for theme_name, theme in sorted(B.THEMES.items()):
                if '--test-schedule' in flags:
                    theme = B.test_schedule(theme)
                label = '%s %s' % (theme_name, ' '.join(flags) or '(default)')
                print('2-6. %s' % label)
                rel = Path('Data') / 'scenarios' / (theme['map'] + '.scn')
                d1, d2 = (Path(a) / rel).read_bytes(), (Path(b) / rel).read_bytes()
                check(d1 == d2, label + ': build not deterministic')
                if overlay and not flags:
                    ov = overlay / rel
                    check(ov.exists() and ov.read_bytes() == d1,
                          label + ': overlay file differs from a fresh build (rebuild it)')
                rmv = (Path(a) / 'Data' / 'map scripts' / (theme['map'] + '.rmv')).read_bytes()
                check(b'UseMapGenerator' in rmv and all(c < 0x80 for c in rmv), label + ': rmv')
                if '--test-schedule' in flags:     # own text, not the release strings
                    check(b'DisplayHelp		[TEST SCHEDULE BUILD.' in rmv and b'StringTableID' not in rmv,
                          label + ': test build rmv must carry its own [text]')
                f = R.ScnFile(d1)
                raw = f.get(6)
                m, h = check_file(d1, raw, template, label, theme.get('environment'))
                check_refs(m, label, len(template_m.triggers))
                newv = check_vocab(m, game, vocab_stock, classes, label, template_m)
                for cn, fld, v, why in sorted(newv, key=str):
                    print('  new value %s.%s=%d: %s' % (cn, fld, v, why))
                print('  %s: %d triggers, %d conditions, %d effects, %d objects, sha256 %s' % (
                    label, len(m.triggers), len(m.conditions), len(m.effects), len(m.objects),
                    hashlib.sha256(d1).hexdigest()[:12]))
                run_stub_suite(m, vocab, theme, len(template_m.triggers), label)
    print('6b. probe map (structure and references only)')
    with tempfile.TemporaryDirectory() as a:
        B.main([str(game), a, '--probe'])
        rel = Path('Data') / 'scenarios' / '(4) survival probe.scn'
        d = (Path(a) / rel).read_bytes()
        f = R.ScnFile(d)
        m, h = check_file(d, f.get(6), template, 'probe')
        check_refs(m, 'probe', len(template_m.triggers))
        print('  probe: %d triggers, sha256 %s' % (len(m.triggers), hashlib.sha256(d).hexdigest()[:12]))
    print('7. negative tests (each mutation must be caught)')
    negative_tests(game, vocab, template_m)
    print('8. lobby texts (Language.dll strings) and in-game text encoding')
    check_lobby_texts(game)
    negative_lobby_tests(game)
    print('FAILED: %d' % len(FAILS) if FAILS else 'ALL CHECKS PASSED')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
