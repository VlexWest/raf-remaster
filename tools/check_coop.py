"""Offline checks for the co-op modes (tools/build_coop.py). One script runs every check.

Usage:
    python tools/check_coop.py <game_dir> [<overlay_dir>]

1. build:  deterministic, matches the overlay (if given), survival maps unchanged by the shared
           builder hook (byte-identical to a build without it is checked via check_survival);
2. file:   re-parse, round trip, template chunks untouched, map ids unique (stock + survival);
3. refs:   index rules, ids, counters (check_survival.check_refs), Trigger-effect targets,
           every "/#PA<id>" token names a PlayerHasResource condition;
4. vocab:  classes and enum values seen in shipped scenarios or proven (check_survival);
5. stub:   a stub of the trigger engine (FUN_008d0d80 rules, with looping/true_for, Trigger
           on/off, resources and tokens, ChangeOwner, alive/complete filters) plays every mode
           against scripted worlds, normal and failure paths;
6. negative tests: broken maps must be caught.
Nothing here starts the game.
"""
import argparse
import copy
import hashlib
import re
import struct
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_scn as R  # noqa: E402
import build_survival as B  # noqa: E402
import build_coop as C  # noqa: E402
import check_survival as CS  # noqa: E402
import map_texts as M  # noqa: E402

check = CS.check
FAILS = CS.FAILS
GAME = None

CS.PROVEN_NEW.update({
    ('E', 'ChangeDiplomaticStance', 'player', 4): 'FUN_008c36c0 resolves player with FUN_0089c9a0 (case 4)',
    ('E', 'ChangeResourceLevel', 'player', 3): 'FUN_0089c9a0 case 3',
})
TOKEN = re.compile(rb'/#PA(\d{4})')
COLOR = re.compile(r'/r\d+/g\d+/b\d+')

# --------------------------------------------------------------------------- stub engine


class World:
    """Fake game state. Players 1..n; humans and computers given per scenario."""

    def __init__(self, humans, cpus):
        self.humans, self.cpus = list(humans), list(cpus)
        self.units = []            # dict(owner, type, alive, hp, born)
        self.res = defaultdict(lambda: defaultdict(int))
        self.tcs = {p: 1 for p in self.humans}
        self.chat = []
        self.techs = []            # (player, tech id, time) from ModifyTechnology
        self.result = None

    def resolve(self, enum):
        if enum == B.PLAYER_ALL_HUMANS:
            return self.humans
        if enum == B.PLAYER_ALL_CPUS:
            return self.cpus
        if enum >= 7:
            return [enum - 6]
        if enum == 0:
            return [0]
        raise AssertionError('stub: player enum %d not modelled' % enum)


def stub_run(m, vocab, sc, t_end):
    """sc: dict(humans, cpus, tcs(t)->{player: n}, kill(u, t)->bool, tick(w, t) optional)."""
    tc_set = vocab.unitset(B.UNITSETS['town_centers'])
    w = World(sc['humans'], sc['cpus'])
    trig = [dict(t, _on=bool(t['on']), _since=None) for t in m.triggers]
    conds_by_id = {c['c_unused38']: c for c in m.conditions}
    pending = []
    fires = defaultdict(list)
    names = [R.T(t['name']) for t in m.triggers]

    def units_of(o):
        owners = w.resolve(o['player'])
        out = [u for u in w.units if u['alive'] and u['owner'] in owners and u['type'] == o['u84']]
        if o['ubc']:
            assert o['u98'] == C.ATTR_HP and o['bde'] == 1, 'stub models HP-percent filters only'
            out = [u for u in out if o['u9c'] <= u['hp'] <= o['ua0']]
        return out

    def count(o):
        if o['u80'] == tc_set:
            return sum(w.tcs.get(p, 0) for p in w.resolve(o['player']))
        if o['u80']:
            raise AssertionError('stub: unit set %d selection not modelled' % o['u80'])
        return len(units_of(o))

    def resource(player_enum, res):
        ps = w.resolve(player_enum)
        return w.res[ps[0]][res]

    def text(raw):
        def sub(mt):
            c = conds_by_id[int(mt.group(1))]
            assert c['_type'] == 2
            return str(resource(c['player'], c['resource'])).encode()
        return R.T(TOKEN.sub(sub, raw))

    def cond_true(ref, t):
        if ref == 0:
            return True
        c = m.conditions[ref - 3]
        if c['_type'] == 7:
            return c['u44'] < t <= c['u48']
        if c['_type'] == 1:
            o = m.objects[c['object'] - 1]
            return count(o) >= int(R.T(o['class_name']))
        if c['_type'] == 2:
            v = resource(c['player'], c['resource'])
            return {0: v < c['compare'], 1: v <= c['compare'], 2: v == c['compare'],
                    3: v >= c['compare'], 4: v > c['compare']}[c['f50']]
        raise AssertionError('stub does not model condition type %d' % c['_type'])

    def apply(ref, t):
        e = m.effects[ref - 1]
        key = R.effect_key(e['_cat'], e['_type'])
        if key == (1, 0):
            o = m.objects[e['object'] - 1]
            n = int(R.T(o['class_name']))
            assert int(R.T(o['unit_name'])) == n, 'Create count must be exact'
            for p in w.resolve(o['player']):
                for _ in range(n):
                    w.units.append(dict(owner=p, type=o['u84'], alive=True, hp=100, born=t))
        elif key == (1, 4):
            for u in units_of(m.objects[e['object'] - 1]):
                u['alive'] = False
        elif key == (1, 9):
            for u in units_of(m.objects[e['object'] - 1]):
                u['owner'] = e['new_player'] - 6
        elif key == (2, 4):
            v = int(text(e['text']))
            for p in w.resolve(e['player']):
                r = w.res[p]
                r[e['resource']] = {0: v, 1: r[e['resource']] + v,
                                    2: r[e['resource']] - v}[e['amount']]
        elif key == (2, 5):
            assert e['u44'] == 2 and e['b48'] == 1, 'stub: ModifyTechnology as stock only'
            for p in w.resolve(e['player']):
                w.techs.append((p, e['tech'], t))
        elif key == (2, 0) and e['player'] == B.PLAYER_ALL_HUMANS:
            w.result = w.result or ('victory', t)
        elif key == (2, 2) and e['player'] == B.PLAYER_ALL_HUMANS:
            w.result = w.result or ('defeat', t)
        elif key == (3, 0):
            trig[e['action']]['_on'] = e['trigger'] == 0
            trig[e['action']]['_since'] = None
        elif key == (4, 3):
            w.chat.append((t, text(e['text'])))

    t, dt = 0.0, 0.5
    while t < t_end and (w.result is None or t < w.result[1] + 5):
        w.tcs = sc['tcs'](t)
        for u in w.units:
            if u['alive'] and sc['kill'](u, t):
                u['alive'] = False
        if sc.get('tick'):
            sc['tick'](w, t)
        while pending and pending[0][0] <= t:
            _, ref = pending.pop(0)
            apply(ref, t)
        for i, tr in enumerate(trig):
            if not tr['_on']:
                continue
            ok = all(cond_true(c, t) != bool(neg) for neg, op, c in tr['if'])
            if not ok:
                tr['_since'] = None
                continue
            if tr['true_for']:
                if tr['_since'] is None:
                    tr['_since'] = t
                    continue
                if t - tr['_since'] < tr['true_for']:
                    continue
            tr['_since'] = None
            if not tr['looping']:
                tr['_on'] = False
            fires[names[i]].append(t)
            for delay, op, ref in tr['then']:
                if ref:
                    pending.append((t + delay / 100.0, ref))
            pending.sort(key=lambda x: x[0])
        t += dt
    return w, fires


def kill_after(sec):
    return lambda u, t: t >= u['born'] + sec


# --------------------------------------------------------------------------- per-mode checks


def two_humans(tcs=lambda t: {1: 1, 2: 1}, kill=kill_after(60), tick=None):
    return dict(humans=[1, 2], cpus=[3], tcs=tcs, kill=kill, tick=tick)


def stub_endless(m, vocab, info, label, lang='ru'):
    times, t_loop, gap = info['times'], info['t_loop'], info['loop_gap']
    n = len(times)
    # a) never ends while the town stands; loop phase keeps firing every gap seconds
    end = t_loop + 25 * gap
    w, f = stub_run(m, vocab, two_humans(), end)
    check(w.result is None, label + ': endless map ended (%s)' % (w.result,))
    for k, tk in enumerate(times, 1):
        fk = f['SV Wave %03d' % k]
        check(len(fk) == 1 and tk < fk[0] <= tk + 1, label + ': wave %d fired %s want %d' % (k, fk, tk))
        check(len(f['SV Wave %03d co-op bonus' % k]) == 1, label + ': bonus %d' % k)
    lp = f['SV Endless loop']
    check(len(lp) >= 24 and abs(lp[0] - t_loop) <= 1.0, label + ': first loop wave %s want %d'
          % (lp[:1], t_loop))
    gaps = {round(b - a) for a, b in zip(lp, lp[1:])}
    check(gaps <= {gap, gap + 1}, label + ': loop gaps %s' % sorted(gaps))
    check(len(f['SV Endless boss loop']) >= 4, label + ': boss loop fired %d' % len(f['SV Endless boss loop']))
    check(len(f['SV Endless tier 01']) >= 1, label + ': tier 1 never joined')
    waves_started = n + len(lp)
    check(w.res[1][C.RES_VAR0] == waves_started, label + ': Var0 %d, waves %d' % (
        w.res[1][C.RES_VAR0], waves_started))
    mk = M.MARK[lang]
    loop_msgs = [s for _, s in w.chat if mk['coming'] in s and mk['wave'] % (n + 1) in s]
    check(len(loop_msgs) == 1, label + ': token wave message for wave %d: %s' % (n + 1, loop_msgs))
    check(not any('/#PA' in s for _, s in w.chat), label + ': unresolved token in chat')
    alive = sum(1 for u in w.units if u['alive'])
    print('  stub endless: %d explicit waves, %d loop waves to %.0f s, %d units created, %d alive' % (
        n, len(lp), end, len(w.units), alive))
    # b) defeat at several points: message names the wave reached, exactly one defeat message
    mid = lambda k: (times[k - 1] + times[k]) / 2
    for when, k in [(min(20, times[0] - 8), 0), (mid(1), 1), (mid(2), 2), (mid(n // 2 + 1), n // 2 + 1),
                    (times[-1] + gap / 4, n), (t_loop + 3 * gap + gap / 2, None)]:
        w, f = stub_run(m, vocab, two_humans(tcs=lambda t, when=when: {1: 0, 2: 0} if t > when
                                             else {1: 1, 2: 1}), when + 60)
        msgs = [COLOR.sub('', s) for _, s in w.chat if mk['fallen'] in s]
        check(w.result is not None and w.result[0] == 'defeat', label + ': no defeat at %s' % when)
        check(len(msgs) == 1, label + ': defeat at %d: messages %s' % (when, msgs))
        if k is None:     # token expanded by the stub: the 4th looped wave
            want = COLOR.sub('', M.coop(lang, 'fallen_endless', tok=str(n + 4), n=n))
        elif k == 0:
            want = COLOR.sub('', M.coop(lang, 'fallen_first'))
        else:
            want = COLOR.sub('', M.coop(lang, 'fallen_wave', k=k))
        check(msgs and want in msgs[0], label + ': defeat at %d says %r, want %r' % (
            when, msgs[:1], want))
        print('  stub endless defeat at %6.0f s -> %-8s %s' % (when, w.result and w.result[0],
                                                             msgs[0] if msgs else None))


def stub_bosshunt(m, vocab, info, label, theme):
    stages = theme['stages']
    boss_types = {C.hero(vocab, h) for st in stages for h in st}
    first = theme['first']

    def killer(boss_after, escort_after=40):
        return lambda u, t: t >= u['born'] + (boss_after if u['type'] in boss_types else escort_after)

    w, f = stub_run(m, vocab, two_humans(kill=killer(50)), 5000)
    check(w.result is not None and w.result[0] == 'victory', label + ': normal run %s' % (w.result,))
    for k in range(1, len(stages) + 1):
        check(len(f['SV Boss %02d' % k]) == 1, label + ': boss %d spawned %d times' % (
            k, len(f['SV Boss %02d' % k])))
        check(len(f['SV Boss %02d down' % k]) == 1, label + ': boss %d down %d times' % (
            k, len(f['SV Boss %02d down' % k])))
        if k > 1:
            gap = f['SV Boss %02d' % k][0] - f['SV Boss %02d down' % (k - 1)][0]
            check(theme['breather'] <= gap <= theme['breather'] + 1.5, label + ': breather %d %.1f'
                  % (k, gap))
    check(f['SV Boss 01'][0] > first, label + ': boss 1 early')
    created = defaultdict(int)
    for u in w.units:
        created[u['type']] += 1
    check(all(created[bt] == 1 for bt in boss_types), label + ': boss counts %s' % (
        {bt: created[bt] for bt in boss_types},))
    escorts = [len([u for u in w.units if abs(u['born'] - f['SV Boss %02d' % k][0]) < 1.1 and
                    u['type'] not in boss_types]) for k in range(1, len(stages) + 1)]
    check(all(a < b for a, b in zip(escorts, escorts[1:])), label + ': escorts not growing %s' % escorts)
    print('  stub bosshunt normal -> %s at %.0f s, escorts (with co-op bonus) %s' % (
        w.result[0], w.result[1], escorts))
    # solo: no co-op bonus ever
    w2, f2 = stub_run(m, vocab, dict(humans=[1], cpus=[2], tcs=lambda t: {1: 1}, kill=killer(50)), 5000)
    check(w2.result and w2.result[0] == 'victory', label + ': solo %s' % (w2.result,))
    check(not any(f2['SV Boss %02d co-op bonus' % k] for k in range(1, len(stages) + 1)),
          label + ': solo got a co-op bonus')
    # escorts die but boss 3 never: stuck at boss 3, no victory
    w3, f3 = stub_run(m, vocab, two_humans(kill=lambda u, t: u['type'] != C.hero(vocab, stages[2][0])
                                           and t >= u['born'] + 30), 4000)
    check(w3.result is None and not f3['SV Boss 04'], label + ': advanced past a living boss')
    # a wounded boss (HP 50 %) is still alive; a boss at HP 0 (revivable corpse) counts as dead
    def wound(w, t):
        for u in w.units:
            if u['type'] in boss_types and u['alive'] and t > u['born'] + 20:
                u['hp'] = 50 if t < u['born'] + 60 else 0
    w4, f4 = stub_run(m, vocab, two_humans(kill=lambda u, t: u['type'] not in boss_types and
                                           t >= u['born'] + 30, tick=wound), 5000)
    check(w4.result and w4.result[0] == 'victory', label + ': HP-0 bosses not counted dead %s' % (w4.result,))
    check(len(f4['SV Boss 02']) == 1 and f4['SV Boss 02'][0] - f4['SV Boss 01'][0] >= 60,
          label + ': wounded boss counted dead')
    # defeat
    w5, _ = stub_run(m, vocab, two_humans(tcs=lambda t: {1: 0, 2: 0} if t > 400 else {1: 1, 2: 1},
                                          kill=killer(10 ** 6)), 600)
    check(w5.result and w5.result[0] == 'defeat' and 400 < w5.result[1] < 410, label + ': defeat %s' % (w5.result,))
    print('  stub bosshunt solo -> %s, stuck boss -> %s, corpse boss -> %s, defeat -> %s' % (
        w2.result, w3.result, w4.result and w4.result[0], w5.result))


def stub_roles(m, vocab, info, label, theme, waves=True):
    mil = C.military_types(vocab)
    blds = C.building_types(vocab)
    statue = next(i for i, n in enumerate(vocab.objects) if n == 'A - b  Statue Glory (Greek)')
    cit = vocab.set_members(vocab.unitset(B.UNITSETS['citizens']))['types']
    log = {}

    def tick(w, t):
        if t == 0.5:
            w.res[1][3] = w.res[1][4] = 200
            w.res[2][3] = w.res[2][4] = 0
            w.res[1][8], w.res[2][8] = 50, 20
            for ut in cit[:2]:
                w.units.append(dict(owner=2, type=ut, alive=True, hp=100, born=t))
        if 0 < t < 2000 and t % 1 == 0:
            w.res[1][3] += 10        # economist gathers 10 gold + 6 wood a second
            w.res[1][4] += 6
        if t == 100:
            w.units.append(dict(owner=1, type=mil[0], alive=True, hp=100, born=t, tag='p1sold'))
            w.units.append(dict(owner=1, type=blds[0], alive=True, hp=40, born=t, tag='found'))
            w.units.append(dict(owner=1, type=blds[1], alive=True, hp=100, born=t, tag='done'))
            w.units.append(dict(owner=1, type=statue, alive=True, hp=100, born=t, tag='statue'))
            w.units.append(dict(owner=2, type=cit[0], alive=True, hp=100, born=t, tag='p2cit'))
        if t == 200:
            [u for u in w.units if u.get('tag') == 'found'][0]['hp'] = 100
            log['at200'] = {u['tag']: u['owner'] for u in w.units if u.get('tag')}
        if t == 300:
            w.res[1][8] = 120        # economist builds a granary
        if t == 310:
            log['pop310'] = (w.res[1][8], w.res[2][8])
        for p in (1, 2):
            for r in (3, 4):
                if w.res[p][r] < 0:
                    log['negative'] = (p, r, t)
        if t == 500:
            w.res[1][6] = 0          # economist buys advisors with all his glory
        if t == 540:
            log['glory540'] = (w.res[1][6], w.res[2][6])
        if t == 1000:
            log['res1000'] = (dict(w.res[1]), dict(w.res[2]))

    sc = two_humans(tick=tick, kill=lambda u, t: u['owner'] == 3 and t >= u['born'] + 60)
    w, f = stub_run(m, vocab, sc, 1200 if not waves else 4000)
    tags = {u['tag']: u['owner'] for u in w.units if u.get('tag')}
    check(log.get('at200', {}).get('p1sold') == 2, label + ': P1 soldier not handed to P2 %s' % log)
    check(log.get('at200', {}).get('found') == 2 or tags.get('found') == 2,
          label + ': finished building not handed over')
    check(log.get('at200', {}).get('done') == 2, label + ': complete building not handed over')
    check(log.get('at200', {}).get('statue') == 2, label + ': glory statue not handed over')
    check(log.get('at200', {}).get('p2cit') == 1, label + ': P2 citizen not handed to P1')
    check(all(u['owner'] == 1 for u in w.units if u['type'] in cit and u['owner'] in (1, 2)),
          label + ': citizen left with P2')
    check('negative' not in log, label + ': negative resources %s' % (log.get('negative'),))
    r1, r2 = log['res1000']
    check(r2.get(3, 0) > 0 and r2.get(4, 0) > 0, label + ': no tithe reached P2 %s' % (r2,))
    check(log.get('pop310') == (120, 120), label + ': P2 pop cap does not follow P1 %s' % (
        log.get('pop310'),))
    check(r1.get(8) == r2.get(8) == 120, label + ': pop cap at 1000 s %s / %s' % (r1.get(8), r2.get(8)))
    check([(p, tk) for p, tk, _ in w.techs] == [(1, tk) for tk in C.HERO_LEVEL_TECHS],
          label + ': hero level techs granted %s' % (w.techs,))
    check(len(C.HERO_LEVEL_TECHS) == 9 and all(tt < 20 for _, _, tt in w.techs),
          label + ': hero level techs late %s' % (w.techs,))
    check(log.get('glory540') == (C.GLORY_CAP, 0), label + ': economist glory not refilled %s' % (
        log.get('glory540'),))
    check(r1.get(C.RES_MAXGLORY) == C.GLORY_CAP and not r2.get(C.RES_MAXGLORY),
          label + ': max glory %s / %s' % (r1.get(C.RES_MAXGLORY), r2.get(C.RES_MAXGLORY)))
    n_tithe = len(f['SV Roles tithe gold 1'])
    check(abs(n_tithe - (1000 - 60) / 30) < 4 or n_tithe >= 25, label + ': tithe fired %d' % n_tithe)
    if waves:
        check(w.result and w.result[0] == 'victory', label + ': waves did not end in victory %s' % (w.result,))
    print('  stub %s: hand-over %s, tithe x%d, at 1000 s P1 gold %d wood %d, P2 gold %d wood %d, %s' % (
        label.split()[0], log.get('at200'), n_tithe, r1.get(3, 0), r1.get(4, 0), r2.get(3, 0),
        r2.get(4, 0), w.result))
    # foundation (HP 40 %) must stay with P1 while unfinished
    w2, _ = stub_run(m, vocab, dict(sc, tick=lambda w, t: (
        w.units.append(dict(owner=1, type=blds[0], alive=True, hp=40, born=t, tag='f'))
        if t == 50 else None)), 120)
    check([u['owner'] for u in w2.units if u.get('tag') == 'f'] == [1],
          label + ': unfinished building handed over')


def stub_civ_warning(m, vocab, label, lang='ru'):
    tcs = C.start_town_centers(vocab)
    civ = {vocab.objects[i].rsplit('(', 1)[1][:-1]: i for i in tcs}
    check(len(tcs) == 4 and set(civ) == {'Greek', 'Egypt', 'Persian', 'Rome'},
          label + ': start town centre types %s' % civ)
    names = [R.T(t['name']) for t in m.triggers if R.T(t['name']).startswith('SV Roles civ warning')]
    check(len(names) == 12 and len(set(names)) == 12, label + ': %d civ warning triggers' % len(names))
    warning = M.coop(lang, 'roles_civ_warning')

    def run(c1, c2, t_end=40):
        def tick(w, t):
            if t == 0.5:
                for p, c in ((1, c1), (2, c2)):
                    w.units.append(dict(owner=p, type=civ[c], alive=True, hp=100, born=t))
        w, f = stub_run(m, vocab, two_humans(tick=tick, kill=lambda u, t: False), t_end)
        return [t for t, msg in w.chat if msg == warning], sum(len(v) for k, v in f.items()
                                                               if k.startswith('SV Roles civ warning'))
    for c1 in civ:
        for c2 in civ:
            said, fired = run(c1, c2)
            if c1 == c2:
                check(not said and not fired, label + ': warning for %s + %s' % (c1, c2))
            else:
                check(len(said) == 1 and fired == 1 and 8 < said[0] < 12,
                      label + ': %s + %s warned %s (fired %d)' % (c1, c2, said, fired))
    check(len(run('Greek', 'Rome', 400)[0]) == 1, label + ': warning repeats')
    print('  stub %s: civ warning once for each of the 12 mixed pairs, never for the same civ' % label)


def stub_vsai(m, vocab, label):
    w, f = stub_run(m, vocab, dict(humans=[1, 2], cpus=[3, 4, 5], tcs=lambda t: {1: 1, 2: 1},
                                   kill=lambda u, t: False), 120)
    check(w.result is None and not w.units, label + ': vs AI map must not create units or end')
    kinds = [R.EFFECTS[R.effect_key(e['_cat'], e['_type'])][0] for e in m.effects
             if R.T(e['name']).startswith('SV ')]
    check('AIToggleSetting' not in kinds, label + ': AI must stay on')
    dip = [(e['player'], e['other'], e['stance']) for e in m.effects
           if R.T(e['name']).startswith('SV ') and R.effect_key(e['_cat'], e['_type']) == (2, 3)]
    check(sorted(dip) == [(3, 3, 0), (3, 4, 1), (4, 4, 0)], label + ': diplomacy %s' % dip)
    print('  stub %s: no units, no end, diplomacy %s, setup fired %s' % (label, dip, f['SV Setup']))


# --------------------------------------------------------------------------- structure


def check_tokens_and_switches(m, label):
    ids = {c['c_unused38']: c for c in m.conditions}
    n_tok = 0
    for e in m.effects:
        for k, v in e.items():
            if isinstance(v, bytes):
                for mt in TOKEN.finditer(v):
                    n_tok += 1
                    c = ids.get(int(mt.group(1)))
                    check(c is not None and c['_type'] == 2, label + ': token %s has no '
                          'PlayerHasResource condition' % mt.group(0))
        if R.effect_key(e['_cat'], e['_type']) == (3, 0) and R.T(e['name']).startswith('SV '):
            tname = R.T(m.triggers[e['action']]['name'])
            ename = R.T(e['name'])
            check(tname.startswith('SV ') and e['action'] != 0, label + ': %s -> %s' % (ename, tname))
            want = re.search(r'B(\d\d) (watch|bonus|next boss)', ename)
            if want:
                k, kind = int(want.group(1)), want.group(2)
                exp = {'watch': 'SV Boss %02d down' % k, 'bonus': 'SV Boss %02d co-op bonus' % k,
                       'next boss': 'SV Boss %02d' % (k + 1)}[kind]
                check(tname == exp, label + ': %s targets %s, want %s' % (ename, tname, exp))
    return n_tok


def stock_map_ids(game):
    ids = {}
    for p in (Path(game) / 'Data' / 'scenarios').glob('*.scn'):
        ids[R.parse_header(R.load_any(p).header)['map_id']] = p.name
    return ids


def negative_tests(results, vocab):
    print('6. negative tests (each mutation must be caught)')

    def caught(label, run):
        before = len(FAILS)
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            run()
        n = len(FAILS) - before
        del FAILS[before:]
        check(n > 0, 'negative test not caught: ' + label)
        print('  caught: %-62s (%d findings)' % (label, n))

    theme, data, raw, info, _ = results['endless']
    m0 = R.Manager.parse(raw)

    def mut(fn):
        m = copy.deepcopy(m0)
        fn(m)
        return m
    names = [R.T(t['name']) for t in m0.triggers]

    def no_loop(m):
        m.triggers[names.index('SV Endless loop')]['looping'] = 0
    caught('endless loop not looping', lambda: stub_endless(mut(no_loop), vocab, info, 'neg'))

    def bad_token(m):
        e = next(e for e in m.effects if b'/#PA' in e.get('text', b''))
        e['text'] = TOKEN.sub(b'/#PA9999', e['text'])
    caught('token pointing to no condition', lambda: check_tokens_and_switches(mut(bad_token), 'neg'))

    def window_gap(m):
        t = m.triggers[names.index('SV Fallen in wave 002')]
        t['on'] = 0
    caught('missing defeat message window', lambda: stub_endless(mut(window_gap), vocab, info, 'neg'))

    theme, data, raw, info, _ = results['bosshunt']
    mb = R.Manager.parse(raw)
    bn = [R.T(t['name']) for t in mb.triggers]

    def no_alive(m):
        for o in m.objects:
            if R.T(o['name']).startswith('SV Boss alive'):
                o['ubc'] = 0
    m = copy.deepcopy(mb)
    no_alive(m)
    caught('boss watch without the alive filter', lambda: stub_bosshunt(m, vocab, info, 'neg', theme))

    m = copy.deepcopy(mb)
    e = next(e for e in m.effects if R.T(e['name']) == 'SV B03 next boss on')
    e['action'] = bn.index('SV Boss 05')
    caught('chain skips a boss', lambda: check_tokens_and_switches(m, 'neg'))

    theme, data, raw, info, _ = results['roles']
    mr = R.Manager.parse(raw)
    m = copy.deepcopy(mr)
    for o in m.objects:
        if R.T(o['name']).startswith('SV Roles P1 building'):
            o['ubc'] = 0
    caught('roles hands over unfinished buildings', lambda: stub_roles(m, vocab, info, 'neg', theme))
    m = copy.deepcopy(mr)
    for c in m.conditions:
        if R.T(c['name']).startswith('SV Roles P1 gold'):
            c['compare'] = 0
            c['f50'] = 3
    m.triggers[[R.T(t['name']) for t in m.triggers].index('SV Roles tithe gold 1')]['true_for'] = 1
    caught('tithe without the stock guard', lambda: stub_roles(m, vocab, info, 'neg', theme))
    m = copy.deepcopy(mr)
    m.triggers[[R.T(t['name']) for t in m.triggers].index('SV Roles pop cap')]['on'] = 0
    caught('pop cap not shared with P2', lambda: stub_roles(m, vocab, info, 'neg', theme))
    m = copy.deepcopy(mr)
    m.triggers[[R.T(t['name']) for t in m.triggers].index('SV Roles glory')]['on'] = 0
    caught('economist glory not refilled', lambda: stub_roles(m, vocab, info, 'neg', theme))
    m = copy.deepcopy(mr)
    m.triggers[[R.T(t['name']) for t in m.triggers].index('SV Roles hero levels')]['on'] = 0
    caught('economist gets no hero levels', lambda: stub_roles(m, vocab, info, 'neg', theme))
    rn = [R.T(t['name']) for t in mr.triggers]
    m = copy.deepcopy(mr)
    m.triggers[next(i for i, n in enumerate(rn) if n.startswith('SV Roles civ warning'))]['on'] = 0
    caught('civ warning trigger switched off', lambda: stub_civ_warning(m, vocab, 'neg'))
    m = copy.deepcopy(mr)
    for t in m.triggers:
        if R.T(t['name']).startswith('SV Roles civ warning'):
            t['if'] = [(0, 1, t['if'][0][2]), (0, 0, t['if'][1][2])]
    caught('civ warning without the P2 civ condition', lambda: stub_civ_warning(m, vocab, 'neg'))


# --------------------------------------------------------------------------- main


def main(argv):
    sys.stdout.reconfigure(errors='backslashreplace')   # Russian chat lines on any console code page
    ap = argparse.ArgumentParser()
    ap.add_argument('game_dir')
    ap.add_argument('overlay_dir', nargs='?')
    a = ap.parse_args(argv)
    game = Path(a.game_dir)
    overlay = Path(a.overlay_dir) if a.overlay_dir else None
    vocab = B.Vocab(game)
    print('1. build twice, compare with the overlay')
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            results = C.main([str(game), d1])
            again = C.main([str(game), d2])
            english = C.main([str(game), d2, '--lang', 'en', '--mode', 'endless'])
            ts = C.main([str(game), d2, '--test-schedule'])
            probe = C.main([str(game), d2, '--probe'])
            bb = C.main([str(game), d2, '--mode', 'bosshunt', '--boss-buffs'])
        for name in results:
            check(results[name][1] == again[name][1], name + ': build not deterministic')
            if overlay:
                ov = overlay / 'Data' / 'scenarios' / (results[name][0]['map'] + '.scn')
                check(ov.exists() and ov.read_bytes() == results[name][1],
                      name + ': overlay differs from a fresh build (rebuild it)')
        files = {p.relative_to(d1): p.read_bytes() for p in Path(d1).rglob('*') if p.is_file()}
        if overlay:
            ov = {p.relative_to(overlay): p.read_bytes() for p in overlay.rglob('*') if p.is_file()}
            check(ov == files, 'overlay differs from a fresh build (rebuild it): %s' % sorted(
                str(k) for k in set(ov) ^ set(files) | {k for k in ov if ov[k] != files.get(k)}))
        CS.check_map_outputs(game, d1, {t['map']: t.get('template', '(4) plains')
                                        for t, *_ in results.values()}, 'co-op')
        release = {t['map'] for t, *_ in results.values()} | {t['map'] for t in B.THEMES.values()}
        check(release == set(M.MAPS), 'map_texts.LOBBY %s != built maps %s' % (
            sorted(M.MAPS), sorted(release)))
    print('  %d maps deterministic%s' % (len(results), ', overlay current' if overlay else ''))
    print('2-4. structure, references, vocabulary')
    classes, vocab_stock = CS.stock_vocab(game)
    ids = stock_map_ids(game)
    for sname in ('(4) survival', '(4) survival zombies', '(4) survival probe'):
        ids[B.map_id(sname + '.scn')] = sname
    seen_names = set()
    allsets = list(results.items()) + [('probe', probe['probe'])] + \
        [('ts-' + k, v) for k, v in ts.items()] + [('bb-bosshunt', bb['bosshunt'])]
    for name, (theme, data, raw, info, template) in allsets:
        label = name
        tm = R.Manager.parse(R.load_any(template).get(6))
        m, h = CS.check_file(data, raw, template, label)
        CS.check_refs(m, label, len(tm.triggers))
        newv = CS.check_vocab(m, game, vocab_stock, classes, label, tm)
        n_tok = check_tokens_and_switches(m, label)
        if not name.startswith(('ts-', 'bb-')):
            check(h['map_id'] not in ids, label + ': map id clashes with %s' % ids.get(h['map_id']))
            ids[h['map_id']] = name
            check(theme['map'] not in seen_names, label + ': duplicate map name')
            seen_names.add(theme['map'])
            check(len(data) < 8 << 20, label + ': file too large')
        print('  %-12s %4d triggers %5d conditions %5d effects %5d objects, %d tokens, sha256 %s%s' % (
            label, len(m.triggers), len(m.conditions), len(m.effects), len(m.objects), n_tok,
            hashlib.sha256(data).hexdigest()[:8],
            '' if not newv else ', new values: ' + ', '.join('%s.%s=%d' % x[:3] for x in sorted(newv, key=str))))
    mil, blds = C.military_types(vocab), C.building_types(vocab)
    heroes = set(vocab.set_members(vocab.unitset(B.UNITSETS['heroes']))['types'])
    cit = set(vocab.set_members(vocab.unitset(B.UNITSETS['citizens']))['types'])
    check(len(mil) >= 100 and not (set(mil) & (heroes | cit)), 'roles: military type list %d' % len(mil))
    check(len(blds) >= 13 and not (set(blds) & set(mil)), 'roles: building type list %d' % len(blds))
    statues = [i for i, n in enumerate(vocab.objects) if n.startswith('A - b  Statue Glory (')]
    check(len(statues) == 4 and set(statues) <= set(blds), 'roles: glory statue types %s' % statues)
    print('  roles: %d military unit types, %d military building types, %d hero types, %d citizen types'
          % (len(mil), len(blds), len(heroes), len(cit)))
    print('5. stub engine')
    stub_endless(R.Manager.parse(results['endless'][2]), vocab, results['endless'][3], 'endless')
    stub_endless(R.Manager.parse(ts['endless'][2]), vocab, ts['endless'][3], 'endless test-schedule')
    stub_endless(R.Manager.parse(english['endless'][2]), vocab, english['endless'][3], 'endless --lang en',
                 lang='en')
    stub_bosshunt(R.Manager.parse(results['bosshunt'][2]), vocab, results['bosshunt'][3], 'bosshunt',
                  results['bosshunt'][0])
    stub_bosshunt(R.Manager.parse(ts['bosshunt'][2]), vocab, ts['bosshunt'][3],
                  'bosshunt test-schedule', ts['bosshunt'][0])
    stub_roles(R.Manager.parse(results['roles'][2]), vocab, results['roles'][3], 'roles (waves)',
               results['roles'][0])
    stub_roles(R.Manager.parse(results['roles-ai'][2]), vocab, results['roles-ai'][3], 'roles-ai',
               results['roles-ai'][0], waves=False)
    stub_civ_warning(R.Manager.parse(results['roles'][2]), vocab, 'roles')
    stub_civ_warning(R.Manager.parse(results['roles-ai'][2]), vocab, 'roles-ai')
    stub_vsai(R.Manager.parse(results['vsai'][2]), vocab, 'vsai')
    negative_tests(results, vocab)
    print('FAILED: %d' % len(FAILS) if FAILS else 'ALL CHECKS PASSED')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
