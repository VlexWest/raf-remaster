"""Build the co-op game modes (multiplayer scenario maps) into an overlay.

Usage:
    python tools/build_coop.py <game_dir> <overlay_dir> [--mode all|endless|bosshunt|roles|roles-ai|vsai]
                               [--explicit-waves 50] [--boss-buffs] [--test-schedule] [--probe]

Writes, built on stock multiplayer maps of the user's install (nothing is copied into the repo):

    (4) survival endless.scn    endless waves, wave counter, "fallen in wave N" message
    (4) boss hunt.scn           12 hero bosses one after another, each with a bigger escort
    (4) co-op roles.scn         P1 economist / P2 commander against the survival waves
    (4) co-op roles vs ai.scn   the same roles against 1-2 computer players with their AI on
    (5) co-op vs hard ai.scn    2 humans allied against 3 computers (AI on, allied)

plus one Data/map scripts/<map>.rmv lobby entry each. Rules, lobby setup and in-game tests:
docs/coop-modes.md. Trigger format: docs/scenario-format.md. Shares the builder, the
vocabulary and the computer-neutralising setup with tools/build_survival.py.

Trigger facts this relies on (see docs/coop-modes.md section 1 for the evidence):
* looping triggers re-fire every `true_for` seconds while their conditions hold;
* the Trigger effect turns other triggers on/off (chains: boss k dead -> boss k+1);
* player variables Var0..Var9 = resource 11..20 (ChangeResourceLevel / PlayerHasResource);
* text fields expand "/#PA<id>" to the current value of the PlayerHasResource condition with
  that id (campaign usage: chat and counters, e.g. "Carry-over: /#PA0125");
* ChangeOwner moves the selected units to another player (campaign usage).
"""
import argparse
import hashlib
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_scn as R  # noqa: E402
import build_survival as B  # noqa: E402
import map_texts as M  # noqa: E402
import map_preview as P  # noqa: E402

PLAYER_ALL_HUMANS, PLAYER_ALL_CPUS = B.PLAYER_ALL_HUMANS, B.PLAYER_ALL_CPUS
P1, P2 = 7, 8                      # player enum 7.. = lobby player (value - 6)
RES_GOLD, RES_WOOD, RES_POPCAP, RES_VAR0 = 3, 4, 8, 11
RES_GLORY, RES_MAXGLORY, GLORY_CAP = 6, 59, 99999
HERO_LEVEL_TECHS = (6100, 7100, 8100, 9100, 10100, 10101, 10102, 10103, 10104)   # "A - ACTION - LEVEL 02..10 (Epoch tech)"
OP_SET, OP_ADD, OP_SUB = 0, 1, 2   # ChangeResourceLevel 'amount' field (stock: gaugamela, scendefault)
CMP_LT, CMP_GE, CMP_REF = 0, 3, 2  # PlayerHasResource 'f50' (stock: "Glory < 5" = 0, "Gold > 900" = 3, "REF ..." = 2)
ATTR_HP = 3                        # object attribute filter: 3 = hit points (bde=1: percent)
TASK_ATTACK_MOVE = B.TASK_ATTACK_MOVE
STANCE_AGGRESSIVE, STANCE_INVULNERABLE = B.STANCE_AGGRESSIVE, B.STANCE_INVULNERABLE
FOREVER = B.FOREVER

HEROES = {   # label -> dbobjects name (all in unit set 'A-All Heroes (RTS MODE)'), weakest first
    'Cleopatra': 'A - Inf00 - Cleopatra Melee - RTS mode (Egypt)',
    'Octavian': 'A - Inf00 - Octavian Melee - RTS mode (Rome)',
    'Nebuchadnezzar': 'A - Inf00 - Nebechadnezzar Melee - RTS mode (Persian)',
    'Aristander': 'A - Inf00 - Aristander Melee - RTS mode (Greek)',
    'Sargon': 'A - Inf00 - Sargon Melee - RTS mode (Persian)',
    'Ramses': 'A - Inf00 - Ramses Melee - RTS mode (Egypt)',
    'Tiberius': 'A - Inf00 - Tiberius Melee - RTS Mode (Greek)',
    'Tor': 'A - Inf00 - Tor Melee - RTS Mode (Egypt)',
    'Alexander': 'A - Inf00 - Alexander Melee - RTS mode (Greek)',
    'Julius Caesar': 'A - Inf00 - J Caesar Melee - RTS mode (Rome)',
    'Achilles': 'A - Inf00 - Achilles Melee - RTS mode (Greek)',
    'Germanicus': 'A - Inf00 - G Caesar Melee - RTS mode (Rome)',
    'The Minotaur': 'A - Inf00 - Gladiator Melee - RTS mode (Minotaur)',
}
HERO_POOL = list(HEROES)           # endless boss rotation (dbobjects HP 1000 .. 1680)

# --------------------------------------------------------------------------- helpers


def hero(vocab, label):
    return vocab.unit(HEROES[label])


def time_window(b, lo, hi, name):
    """GameHasAttribute with the time flag: true while lo < scenario seconds <= hi (0x8a9620)."""
    return b.cond(7, name, b3c=0, b3d=1, b3e=0, u40=1, u48=hi, u44=lo, u4c=0)


def res_cond(b, player, resource, value, name, op=CMP_GE):
    """PlayerHasResource as the shipped maps write it (gaugamela "P1G": f50 = compare op,
    'compare' = the amount, amount 8 / f48 2 constant)."""
    return b.cond(2, name, player=player, resource=resource, f50=op, compare=value, amount=8,
                  f48=2, f54=0)


def cond_id(b, handle):
    return b.cond_new[handle[1]]['c_unused38']


def token(b, handle):
    """Text token that the game replaces with the condition's current value (campaign usage)."""
    return '/#PA%04d' % cond_id(b, handle)


def set_resource(b, name, player, resource, op, value):
    return b.eff((2, 4), name, resource=resource, amount=op, text=str(value), player=player)


def alive_filter(b, ref):
    """Only living units: attribute filter hit points 1..100 % (stock 'Ramses HP' 0..100 %,
    'P1 Town Center 1-20%'); keeps a dead or revivable hero out of the selection."""
    b.m.objects[ref - 1].update(ubc=1, u98=ATTR_HP, u9c=1, ua0=100, bde=1)
    return ref


def complete_filter(b, ref):
    """Only finished, undamaged buildings: hit points 100..100 % (stock 'Glory Statue Built'
    3 100..100 %, tutorial 'P1 Barracks' = full HP)."""
    b.m.objects[ref - 1].update(ubc=1, u98=ATTR_HP, u9c=100, ua0=100, bde=1)
    return ref


def trigger_switch(b, name, on):
    """Trigger effect; the target index is filled in later with set_target()."""
    return b.eff((3, 0), name, trigger=0 if on else 1, action=0)


def set_target(b, eff_ref, trig_index):
    b.m.effects[eff_ref - 1]['action'] = trig_index


def neutralise_computer(b, vocab, sets, intro, first_counter, opts, keep_ai=False):
    """Same start as the survival maps (live-verified there): humans allied, computers hostile,
    computer AI off, its citizens removed, its town centre invulnerable, gold/wood 0, looped."""
    o_enemy_tc = b.obj('SV Enemy town centres', PLAYER_ALL_CPUS, unit_class=sets['town_centers'],
                       count=(1, 99))
    citizens = vocab.set_members(vocab.unitset(B.UNITSETS['citizens']))['types']
    o_cit = [b.obj('SV Enemy citizen type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut,
                   count=(1, 9999)) for ut in citizens]

    def passive(tag):
        out = [(b.eff((1, 4), 'SV Remove enemy citizens %d%s' % (i, tag), object=o), 0)
               for i, o in enumerate(o_cit)]
        out += [(set_resource(b, 'SV Enemy gold 0' + tag, PLAYER_ALL_CPUS, RES_GOLD, OP_SET, 0), 0),
                (set_resource(b, 'SV Enemy wood 0' + tag, PLAYER_ALL_CPUS, RES_WOOD, OP_SET, 0), 0),
                (b.eff((1, 7), 'SV Enemy TC invulnerable' + tag, stance=STANCE_INVULNERABLE,
                       object=o_enemy_tc), 0)]
        return out

    setup = []
    if not keep_ai:
        setup.append((b.eff((6, 4), 'SV Computer AI off', setting=B.AI_SETTING_ENABLED, on=0,
                            player=PLAYER_ALL_CPUS), 0))
    setup += passive('')
    setup += [(b.chat(intro, 25), 100)]
    if first_counter:
        setup.append((b.counter(*first_counter), 100))
    setup += diplomacy(b)
    b.trigger('SV Setup', [(b.time_after(1), False)], setup)
    b.trigger('SV Keep enemy passive', [(b.time_after(5), False)], passive(' (loop)'),
              looping=True, true_for=20)


def diplomacy(b, computers_allied=False):
    out = [(b.eff((2, 3), 'SV Humans allied', other=PLAYER_ALL_HUMANS, stance=0, b48=1,
                  player=PLAYER_ALL_HUMANS), 0),
           (b.eff((2, 3), 'SV Humans vs computers', other=PLAYER_ALL_CPUS, stance=1, b48=1,
                  player=PLAYER_ALL_HUMANS), 0)]
    if computers_allied:
        out.append((b.eff((2, 3), 'SV Computers allied', other=PLAYER_ALL_CPUS, stance=0, b48=1,
                          player=PLAYER_ALL_CPUS), 0))
    return out


def create_groups(b, tag, groups, roster, vocab, area, delay=0):
    """Create effects for [(role, level, n)]; returns (effects, set of unit types)."""
    eff, used = [], set()
    for role, lv, n in groups:
        ut = vocab.unit(roster[role][lv])
        used.add(ut)
        o = b.obj('SV W %s %s L%d x%d' % (tag, role, lv, n), PLAYER_ALL_CPUS, unit_type=ut,
                  count=(n, n), area=area)
        eff.append((b.eff((1, 0), 'SV %s create %s' % (tag, role), object=o), delay))
    return eff, used


def march(b, tag, types, o_type, o_human_tc, delay=100):
    out = []
    for ut in sorted(types):
        out += [(b.eff((1, 7), 'SV %s aggressive %d' % (tag, ut), stance=STANCE_AGGRESSIVE,
                       object=o_type[ut]), delay),
                (b.eff((1, 5), 'SV %s attack-move %d' % (tag, ut), target=o_human_tc,
                       task=TASK_ATTACK_MOVE, b48=0, object=o_type[ut]), delay + 50)]
    return out


def keep_attacking(b, o_type, o_human_tc, after):
    b.trigger('SV Enemies keep attacking', [(b.time_after(after, 'SV Attack loop start'), False)],
              march(b, 'loop', o_type, o_type, o_human_tc, 0), looping=True, true_for=15)


def human_defeat(b, o_human_tc, text):
    b.trigger('SV Defeat', [(b.time_after(30, 'SV Game running'), False),
                            (b.exists(o_human_tc, 'SV Human TC exists'), True)],
              ([(b.chat(text, 30), 0)] if text else []) +
              [(b.eff((2, 2), 'SV Defeat humans', player=PLAYER_ALL_HUMANS), 300)],
              true_for=3)


def human_victory(b, text, sound):
    return [(b.chat(text, 30), 0), (b.sound(sound), 0),
            (b.eff((2, 0), 'SV Victory humans', player=PLAYER_ALL_HUMANS), 300),
            (b.eff((2, 2), 'SV Defeat computers', player=PLAYER_ALL_CPUS), 400)]


# every chat/counter text: map_texts.coop (Russian by default, --lang en)


# --------------------------------------------------------------------------- 1. endless


ENDLESS = {
    'map': '(4) survival endless', 'pretty': '(4) Survival Endless', 'title': 'Survival Endless',
    'help': 'Co-op endless survival: the waves never stop and grow stronger, a hero boss every '
            '5th wave. How far can you go? Add exactly one computer player as the enemy.',
    'roster': B.PERSIAN, 'mix': B.classic_mix, 'coop_bonus': 0.5,
    'first_wave': 240,
    'intervals': [(5, 150), (10, 135), (15, 120), (20, 110), (10 ** 6, 100)],
    'boss_breather': 30, 'size_cap': 50, 'loop_gap': 100, 'tier_waves': 10, 'tiers': 10,
    'level': lambda k: min(5, 1 + (k - 1) // 4),
    # difficulty knobs (this map = hard): wave size factor, first siege wave, siege share divisor
    'scale': 1.0, 'siege_from': 2, 'siege_div': 6,
}
# easier variants: smaller waves, siege later and fewer, more time to build up
ENDLESS_EASY = dict(ENDLESS, map='(4) survival endless easy', pretty='(4) Survival Endless Easy',
                    title='Survival Endless (Easy)',
                    help='Co-op endless survival, easy: half-size waves, siege from wave 8, more time '
                         'between waves. Add exactly one computer player as the enemy.',
                    first_wave=360, intervals=[(5, 200), (10, 180), (20, 160), (10 ** 6, 140)],
                    loop_gap=140, scale=0.5, siege_from=8, siege_div=12, onager_from=30)
ENDLESS_NORMAL = dict(ENDLESS, map='(4) survival endless normal', pretty='(4) Survival Endless Normal',
                      title='Survival Endless (Normal)',
                      help='Co-op endless survival, normal: smaller waves, siege from wave 4, a little '
                           'more time between waves. Add exactly one computer player as the enemy.',
                      first_wave=300, intervals=[(5, 170), (10, 155), (20, 135), (10 ** 6, 115)],
                      loop_gap=115, scale=0.75, siege_from=4, siege_div=8, onager_from=16)


def endless_size(theme, k):
    return max(2, round(theme['scale'] * min(theme['size_cap'], round(3 + 1.25 * k + 0.03 * k * k))))


def endless_bosses(k):
    """Every 5th wave: 1 + k//20 heroes, rotating through the pool from the weakest."""
    if k % 5:
        return []
    n = 1 + k // 20
    return [HERO_POOL[(k // 5 - 1 + i) % len(HERO_POOL)] for i in range(n)]


def endless_theme(theme, explicit):
    """The survival helpers' theme shape for the explicit waves."""
    return dict(theme, waves=explicit, size=lambda k: endless_size(theme, k),
                bosses={k: [(HEROES[h], h) for h in endless_bosses(k)]
                        for k in range(1, explicit + 1) if endless_bosses(k)})


def build_endless(m, theme, vocab, opts, map_size):
    b = B.Builder(m)
    n = opts.explicit_waves
    th = endless_theme(theme, n)
    times = B.wave_times(th)
    loop_gap = theme['loop_gap']
    t_loop = times[-1] + loop_gap                 # first looped wave (wave n + 1)
    sets = {k: vocab.unitset(v) for k, v in B.UNITSETS.items()}
    a_spawn = b.area('SV Spawn centre', *B.spawn_rect(map_size))
    o_human_tc = b.obj('SV Human town centres', PLAYER_ALL_HUMANS, unit_class=sets['town_centers'],
                       count=(1, 99))
    o_human_tc2 = b.obj('SV Two human town centres', PLAYER_ALL_HUMANS,
                        unit_class=sets['town_centers'], count=(2, 99))
    types = {vocab.unit(x) for role in theme['roster'].values() for x in role.values()}
    types |= {hero(vocab, h) for h in HERO_POOL}
    o_type = {ut: b.obj('SV Enemy type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut, count=(1, 9999))
              for ut in sorted(types)}
    c_wave = res_cond(b, P1, RES_VAR0, 0, 'SV REF P1 Var0 wave number', op=CMP_REF)
    tok = token(b, c_wave)
    L = opts.lang
    neutralise_computer(b, vocab, sets, M.coop(L, 'endless_intro'),
                        (M.coop(L, 'wave_in', k=1), times[0] - 2), opts)
    b.trigger('SV Wave counter reset', [(b.time_after(1, 'SV Counter reset time'), False)],
              [(set_resource(b, 'SV P1 Var0 = 0', P1, RES_VAR0, OP_SET, 0), 0),
               (set_resource(b, 'SV P1 Var1 = 0', P1, RES_VAR0 + 1, OP_SET, 0), 0)])
    snd_wave, snd_boss = b.sound('a_warning bell'), b.sound('a_hero horn')
    plan = []
    for k in range(1, n + 1):
        t = times[k - 1]
        eff = [(b.chat(M.coop(L, 'wave_coming', k=k), 12), 0), (snd_wave, 0),
               (set_resource(b, 'SV W%03d P1 Var0 + 1' % k, P1, RES_VAR0, OP_ADD, 1), 0)]
        groups = B.wave_groups(th, k)
        ce, used = create_groups(b, 'W%03d' % k, groups, theme['roster'], vocab, a_spawn)
        eff += ce
        bosses = endless_bosses(k)
        for i, h in enumerate(bosses):
            o = b.obj('SV W %03d boss %d' % (k, i + 1), PLAYER_ALL_CPUS, unit_type=hero(vocab, h),
                      count=(1, 1), area=a_spawn)
            eff.append((b.eff((1, 0), 'SV W%03d create boss %d' % (k, i + 1), object=o), 0))
            used.add(hero(vocab, h))
        if bosses:
            eff += [(b.chat(M.coop(L, 'lead_wave', labels=bosses, k=k), 15), 50),
                    (snd_boss, 50),
                    (b.eff((2, 15), 'SV W%03d hero bot AI on' % k, on=1, player=PLAYER_ALL_CPUS), 100)]
        eff += march(b, 'W%03d' % k, used, o_type, o_human_tc)
        nxt = times[k] if k < n else t_loop
        eff.append((b.counter(M.coop(L, 'wave_in', k=k + 1), nxt - t - 1), 200))
        b.trigger('SV Wave %03d' % k, [(b.time_after(t, 'SV Wave %03d time' % k), False)], eff)
        bonus = B.wave_groups(th, k, theme['coop_bonus'])
        be, bused = create_groups(b, 'W%03d bonus' % k, bonus, theme['roster'], vocab, a_spawn, 50)
        be += march(b, 'W%03d bonus' % k, bused, o_type, o_human_tc, 150)
        b.trigger('SV Wave %03d co-op bonus' % k,
                  [(b.time_after(t, 'SV Wave %03d bonus time' % k), False),
                   (b.exists(o_human_tc2, 'SV Two human TCs (W%03d)' % k), False)], be)
        plan.append({'wave': k, 'time': t, 'groups': groups, 'bonus': bonus,
                     'bosses': ' and '.join(bosses)})
    # endless phase: looping triggers re-fire every loop_gap seconds after the last explicit wave
    top = B.wave_groups(th, n)
    loop_eff = [(b.chat(M.coop(L, 'wave_coming', k=tok), 12), 10), (snd_wave, 0),
                (set_resource(b, 'SV Loop P1 Var0 + 1', P1, RES_VAR0, OP_ADD, 1), 0)]
    ce, used = create_groups(b, 'Loop', top, theme['roster'], vocab, a_spawn)
    loop_eff += ce + march(b, 'Loop', used, o_type, o_human_tc)
    loop_eff.append((b.counter(M.coop(L, 'next_wave_in'), loop_gap - 1), 200))
    t_start = times[-1]
    b.trigger('SV Endless loop', [(b.time_after(t_start, 'SV Endless phase'), False)], loop_eff,
              looping=True, true_for=loop_gap)
    lb = B.wave_groups(th, n, theme['coop_bonus'])
    be, bused = create_groups(b, 'Loop bonus', lb, theme['roster'], vocab, a_spawn, 50)
    b.trigger('SV Endless loop co-op bonus',
              [(b.time_after(t_start, 'SV Endless phase (bonus)'), False),
               (b.exists(o_human_tc2, 'SV Two human TCs (loop)'), False)],
              be + march(b, 'Loop bonus', bused, o_type, o_human_tc, 150),
              looping=True, true_for=loop_gap)
    boss_pair = ['Achilles', 'The Minotaur']
    beff = [(b.chat(M.coop(L, 'lead_wave', labels=boss_pair, k=tok), 15), 60),
            (snd_boss, 60)]
    bused = set()
    for i, h in enumerate(boss_pair):
        o = b.obj('SV W loop boss %d' % (i + 1), PLAYER_ALL_CPUS, unit_type=hero(vocab, h),
                  count=(1, 1), area=a_spawn)
        beff.append((b.eff((1, 0), 'SV Loop create boss %d' % (i + 1), object=o), 0))
        bused.add(hero(vocab, h))
    beff += [(b.eff((2, 15), 'SV Loop hero bot AI on', on=1, player=PLAYER_ALL_CPUS), 100)]
    beff += march(b, 'Loop boss', bused, o_type, o_human_tc)
    b.trigger('SV Endless boss loop', [(b.time_after(t_start, 'SV Endless boss phase'), False)],
              beff, looping=True, true_for=5 * loop_gap)
    # escalation: every tier_waves loop waves another group of level-5 units joins every wave
    tiers = []
    for j in range(1, theme['tiers'] + 1):
        start = t_start + j * theme['tier_waves'] * loop_gap
        sc = theme['scale']
        groups = [(r, lv, max(1, round(sc * n))) for r, lv, n in
                  [('sword', 5, 3 + j // 3), ('cavalry', 5, 3 + j // 3), ('archer', 5, 2 + j // 4),
                   ('ram', 1, 3 + j // 2), ('catapult', 1, 3 + j // 2), ('onager', 1, 1 + j // 5)]]
        te, tused = create_groups(b, 'Tier %d' % j, groups, theme['roster'], vocab, a_spawn, 20)
        te += march(b, 'Tier %d' % j, tused, o_type, o_human_tc)
        b.trigger('SV Endless tier %02d' % j,
                  [(b.time_after(start, 'SV Endless tier %02d start' % j), False)], te,
                  looping=True, true_for=loop_gap)
        tiers.append({'tier': j, 'start': start, 'groups': groups})
    keep_attacking(b, o_type, o_human_tc, times[0] + 15)
    # the end: one defeat, and per time window a message with the wave reached (static text for
    # the explicit waves, the Var0 token for the endless phase)
    bounds = [5] + times + [t_loop]     # the defeat itself still waits for 30 s (SV Defeat)
    # Var1 of P1 = "fallen message shown": the town can fall in one window and the defeat comes
    # 3-30 s later, in the next window; only the first message may show
    c_quiet = res_cond(b, P1, RES_VAR0 + 1, 1, 'SV P1 Var1 < 1 (no message yet)', op=CMP_LT)
    shown = set_resource(b, 'SV P1 Var1 = 1 (message shown)', P1, RES_VAR0 + 1, OP_SET, 1)
    windows = [(bounds[k], bounds[k + 1], k) for k in range(0, n + 1)] + [(t_loop, FOREVER, None)]
    for lo, hi, k in windows:
        if k == 0:
            text = M.coop(L, 'fallen_first')
        elif k is None:
            text = M.coop(L, 'fallen_endless', tok=tok, n=n)
        else:
            text = M.coop(L, 'fallen_wave', k=k)
        tag = 'endless phase' if k is None else 'wave %03d' % k
        b.trigger('SV Fallen in ' + tag,
                  [(time_window(b, lo, hi, 'SV Window ' + tag), False), (c_quiet, False),
                   (b.exists(o_human_tc, 'SV Human TC (msg %s)' % tag), True)],
                  [(b.chat(text, 40), 0), (shown, 0)], true_for=3)
    human_defeat(b, o_human_tc, None)
    b.finish()
    return {'plan': plan, 'times': times, 't_loop': t_loop, 'loop_gap': loop_gap,
            'tiers': tiers, 'token_cond': cond_id(b, c_wave)}


# --------------------------------------------------------------------------- 2. boss hunt


BOSSHUNT = {
    'map': '(4) boss hunt', 'pretty': '(4) Boss Hunt', 'title': 'Boss Hunt',
    'help': 'Co-op boss hunt: 12 enemy heroes come one after another, each stronger and with a '
            'bigger escort. Kill the last one to win. Add exactly one computer player.',
    'roster': B.PERSIAN, 'first': 180, 'breather': 45, 'coop_bonus': 0.5,
    'stages': [['Cleopatra'], ['Octavian'], ['Nebuchadnezzar'], ['Aristander'], ['Sargon'],
               ['Ramses'], ['Tiberius'], ['Alexander'], ['Achilles'], ['Germanicus'],
               ['The Minotaur'], ['Julius Caesar', 'Tor']],
}


def escort_theme(theme):
    return {'roster': theme['roster'], 'mix': lambda k: B.classic_mix(min(20, 2 * k)),
            'size': lambda k: 6 + 4 * k, 'level': lambda k: min(5, 1 + (k - 1) // 2)}


def build_bosshunt(m, theme, vocab, opts, map_size):
    b = B.Builder(m)
    stages = theme['stages']
    et = escort_theme(theme)
    sets = {k: vocab.unitset(v) for k, v in B.UNITSETS.items()}
    a_spawn = b.area('SV Spawn centre', *B.spawn_rect(map_size))
    o_human_tc = b.obj('SV Human town centres', PLAYER_ALL_HUMANS, unit_class=sets['town_centers'],
                       count=(1, 99))
    o_human_tc2 = b.obj('SV Two human town centres', PLAYER_ALL_HUMANS,
                        unit_class=sets['town_centers'], count=(2, 99))
    types = {vocab.unit(x) for role in theme['roster'].values() for x in role.values()}
    types |= {hero(vocab, h) for st in stages for h in st}
    o_type = {ut: b.obj('SV Enemy type %d' % ut, PLAYER_ALL_CPUS, unit_type=ut, count=(1, 9999))
              for ut in sorted(types)}
    o_alive = {h: alive_filter(b, b.obj('SV Boss alive %s' % h, PLAYER_ALL_CPUS,
                                        unit_type=hero(vocab, h), count=(1, 99)))
               for st in stages for h in st}
    L = opts.lang
    neutralise_computer(b, vocab, sets, M.coop(L, 'hunt_intro', n=len(stages)),
                        (M.coop(L, 'boss_in', k=1), theme['first'] - 2), opts)
    snd_boss, snd_down = b.sound('a_hero horn'), b.sound('a_completion bell')
    spawn_idx, watch_idx, bonus_idx = [], [], []
    fixups = []                                   # (effect ref, ('spawn'|'watch'|'bonus', k))
    plan = []
    for k, bosses in enumerate(stages, 1):
        label = ' and '.join(bosses)
        groups = B.wave_groups(et, k)
        eff = [(b.chat(M.coop(L, 'boss_coming', labels=bosses, k=k, n=len(stages)), 15), 0),
               (snd_boss, 0)]
        ce, used = create_groups(b, 'B%02d escort' % k, groups, theme['roster'], vocab, a_spawn)
        eff += ce
        for i, h in enumerate(bosses):
            o = b.obj('SV W B%02d boss %d' % (k, i + 1), PLAYER_ALL_CPUS, unit_type=hero(vocab, h),
                      count=(1, 1), area=a_spawn)
            eff.append((b.eff((1, 0), 'SV B%02d create boss %d' % (k, i + 1), object=o), 0))
            used.add(hero(vocab, h))
            if opts.boss_buffs and k > 1:
                eff.append((b.eff((1, 12), 'SV B%02d boss %d HP' % (k, i + 1), attr=B.ATTR_HP, op=0,
                                  value=10 * (k - 1), b4c=1, u50=0, i54=-1,
                                  object=o_type[hero(vocab, h)]), 50))
        eff += [(b.eff((2, 15), 'SV B%02d hero bot AI on' % k, on=1, player=PLAYER_ALL_CPUS), 100)]
        eff += march(b, 'B%02d' % k, used, o_type, o_human_tc)
        eff.append((b.counter(M.coop(L, 'boss_counter', labels=bosses, k=k, n=len(stages)), 0,
                              show_time=False), 200))
        e_watch = trigger_switch(b, 'SV B%02d watch on' % k, True)
        e_bonus = trigger_switch(b, 'SV B%02d bonus on' % k, True)
        fixups += [(e_watch, ('watch', k)), (e_bonus, ('bonus', k))]
        eff += [(e_bonus, 0), (e_watch, 1000)]    # watch only after the boss surely exists
        conds = [(b.time_after(theme['first'], 'SV First boss time'), False)] if k == 1 else []
        spawn_idx.append(b.trigger('SV Boss %02d' % k, conds, eff, on=(k == 1)))
        bonus = B.wave_groups(et, k, theme['coop_bonus'])
        be, bused = create_groups(b, 'B%02d bonus' % k, bonus, theme['roster'], vocab, a_spawn, 50)
        be += march(b, 'B%02d bonus' % k, bused, o_type, o_human_tc, 150)
        bonus_idx.append(b.trigger('SV Boss %02d co-op bonus' % k,
                                   [(b.exists(o_human_tc2, 'SV Two human TCs (B%02d)' % k), False)],
                                   be, on=False))
        # watch: every boss of the stage dead (alive filter) for 2 s
        weff = [(b.chat(M.coop(L, 'boss_fallen', labels=bosses), 15), 0),
                (snd_down, 0)]
        e_off = trigger_switch(b, 'SV B%02d bonus off' % k, False)
        fixups.append((e_off, ('bonus', k)))
        weff.append((e_off, 0))
        if k < len(stages):
            e_next = trigger_switch(b, 'SV B%02d next boss on' % k, True)
            fixups.append((e_next, ('spawn', k + 1)))
            weff += [(b.counter(M.coop(L, 'boss_in', k=k + 1), theme['breather'] - 1), 100),
                     (e_next, theme['breather'] * 100)]
        else:
            weff += human_victory(b, M.coop(L, 'hunt_victory'),
                                  'a_completion bell')
        watch_idx.append(b.trigger('SV Boss %02d down' % k,
                                   [(b.exists(o_alive[h], 'SV %s alive (B%02d)' % (h, k)), True)
                                    for h in bosses], weff, on=False, true_for=2))
        plan.append({'stage': k, 'bosses': label, 'groups': groups, 'bonus': bonus})
    idx = {'spawn': spawn_idx, 'watch': watch_idx, 'bonus': bonus_idx}
    for ref, (kind, k) in fixups:
        set_target(b, ref, idx[kind][k - 1])
    keep_attacking(b, o_type, o_human_tc, theme['first'] + 15)
    human_defeat(b, o_human_tc, M.coop(L, 'hunt_defeat'))
    b.finish()
    return {'plan': plan, 'spawn': spawn_idx, 'watch': watch_idx, 'bonus': bonus_idx}


# --------------------------------------------------------------------------- 3. roles

MILITARY_RE = re.compile(r'^A - (Inf|Arc|Cav)(0[1-5])[a-z]? - (.*) \([Ll]evel \d (Greek|Persian|Rome|Egypt)\)$')
BUILDING_RE = re.compile(r'^A - b  (Barracks|Stable|Archery Range) ')
STATUE_RE = re.compile(r'^A - b  Statue Glory \((Egypt|Greek|Rome|Persian)\)$')
START_TC_RE = re.compile(r'^A - b  Town Center \(MP\) \((Egypt|Greek|Rome|Persian)\)$')

ROLES = {
    'map': '(4) co-op roles', 'pretty': '(4) Co-op Roles', 'title': 'Co-op Roles',
    'help': 'Two players, two jobs: slot 1 is the economist (all citizens, builds the town), slot '
            '2 the commander (gets every soldier, military building and glory statue, paid by a '
            'tithe). Against the survival waves. Add exactly one computer player. Both humans '
            'play the same civ.',
    'tithe': [(300, 100), (800, 200)],       # (P1 stock >= x, move y) per resource every 30 s
    'tithe_every': 30, 'handover_every': 5, 'glory_every': 5,
}
ROLES_AI = dict(ROLES, map='(4) co-op roles vs ai', pretty='(4) Co-op Roles vs AI',
                title='Co-op Roles vs AI',
                help='Two players, two jobs (slot 1 economist, slot 2 commander) against 1-2 '
                     'computer players with their normal AI. Set the computers to the hardest level. '
                     'Both humans play the same civ.')


def military_types(vocab):
    return sorted(i for i, n in enumerate(vocab.objects)
                  if MILITARY_RE.match(n) and 'Building Defender' not in n)


def building_types(vocab):
    return sorted(i for i, n in enumerate(vocab.objects) if BUILDING_RE.match(n) or STATUE_RE.match(n))


def start_town_centers(vocab):
    return sorted(i for i, n in enumerate(vocab.objects) if START_TC_RE.match(n))


def roles_layer(theme, lang, intro_delay=600):
    def layer(b, ctx):
        vocab = ctx['vocab']
        sets = ctx['sets']
        mil = military_types(vocab)
        heroes = vocab.set_members(sets['heroes'])['types']
        cit = vocab.set_members(vocab.unitset(B.UNITSETS['citizens']))['types']
        blds = building_types(vocab)
        hand = []
        for ut in mil + heroes:
            o = b.obj('SV Roles P1 unit %d' % ut, P1, unit_type=ut, count=(1, 9999))
            hand.append((b.eff((1, 9), 'SV Roles unit %d to P2' % ut, new_player=P2, object=o), 0))
        for ut in blds:
            o = complete_filter(b, b.obj('SV Roles P1 building %d' % ut, P1, unit_type=ut,
                                         count=(1, 9999)))
            hand.append((b.eff((1, 9), 'SV Roles building %d to P2' % ut, new_player=P2,
                               object=o), 0))
        for ut in cit:
            o = b.obj('SV Roles P2 citizen %d' % ut, P2, unit_type=ut, count=(1, 9999))
            hand.append((b.eff((1, 9), 'SV Roles citizen %d to P1' % ut, new_player=P1,
                               object=o), 0))
        b.trigger('SV Roles hand-over', [(b.time_after(2, 'SV Roles start'), False)], hand,
                  looping=True, true_for=theme['handover_every'])
        c_pop = res_cond(b, P1, RES_POPCAP, 0, 'SV REF P1 pop cap', op=CMP_REF)
        b.trigger('SV Roles pop cap', [(b.time_after(2, 'SV Roles pop cap start'), False)],
                  [(set_resource(b, 'SV Roles P2 pop cap = P1', P2, RES_POPCAP, OP_SET,
                                 token(b, c_pop)), 0)],
                  looping=True, true_for=theme['handover_every'])
        levels = [(b.eff((2, 5), 'SV Roles P1 hero level %d' % (i + 2), tech=tech, u44=2, b48=1,
                         player=P1), 50 * i) for i, tech in enumerate(HERO_LEVEL_TECHS)]
        levels.append((set_resource(b, 'SV Roles P1 max glory', P1, RES_MAXGLORY, OP_SET,
                                    GLORY_CAP), 0))
        b.trigger('SV Roles hero levels', [(b.time_after(3, 'SV Roles hero levels start'), False)],
                  levels)
        b.trigger('SV Roles glory', [(b.time_after(4, 'SV Roles glory start'), False)],
                  [(set_resource(b, 'SV Roles P1 glory', P1, RES_GLORY, OP_SET, GLORY_CAP), 0)],
                  looping=True, true_for=theme['glory_every'])
        b.trigger('SV Roles intro', [(b.time_after(6, 'SV Roles intro time'), False)],
                  [(b.chat(M.coop(lang, 'roles_intro'), 30), intro_delay),
                   (b.chat(M.coop(lang, 'roles_tithe', every=theme['tithe_every'],
                                  give=theme['tithe'][0][1], have=theme['tithe'][0][0],
                                  more=theme['tithe'][1][0]), 30),
                    intro_delay + 300)])
        tcs = start_town_centers(vocab)
        tc1 = {ut: b.obj('SV Roles P1 start TC %d' % ut, P1, unit_type=ut) for ut in tcs}
        tc2 = {ut: b.obj('SV Roles P2 start TC %d' % ut, P2, unit_type=ut) for ut in tcs}
        for u1 in tcs:
            for u2 in tcs:
                if u1 != u2:
                    b.trigger('SV Roles civ warning %d-%d' % (u1, u2),
                              [(b.time_after(8, 'SV Roles civ check time'), False),
                               (b.exists(tc1[u1], 'SV Roles P1 has TC %d' % u1), False),
                               (b.exists(tc2[u2], 'SV Roles P2 has TC %d' % u2), False)],
                              [(b.chat(M.coop(lang, 'roles_civ_warning'), 30), 0)])
        for res, rname in ((RES_GOLD, 'gold'), (RES_WOOD, 'wood')):
            for i, (have, give) in enumerate(theme['tithe']):
                c = res_cond(b, P1, res, have, 'SV Roles P1 %s >= %d' % (rname, have))
                b.trigger('SV Roles tithe %s %d' % (rname, i + 1),
                          [(b.time_after(60, 'SV Roles tithe start %s %d' % (rname, i)), False),
                           (c, False)],
                          [(set_resource(b, 'SV Roles P1 %s - %d' % (rname, give), P1, res,
                                         OP_SUB, give), 0),
                           (set_resource(b, 'SV Roles P2 %s + %d' % (rname, give), P2, res,
                                         OP_ADD, give), 0)],
                          looping=True, true_for=theme['tithe_every'])
    return layer


def build_roles(m, theme, vocab, opts, map_size):
    wave_theme = dict(B.localize('classic', B.THEMES['classic'], opts.lang), first_wave=360,
                      help=theme['help'], title=theme['title'])
    wopts = argparse.Namespace(**dict(vars(opts), boss_buffs=False))   # survival waves as shipped
    plan = B.build_mode(m, wave_theme, vocab, wopts, map_size,
                        extra=roles_layer(theme, opts.lang))
    return {'plan': plan, 'wave_theme': wave_theme}


def build_roles_ai(m, theme, vocab, opts, map_size):
    b = B.Builder(m)
    sets = {k: vocab.unitset(v) for k, v in B.UNITSETS.items()}
    b.trigger('SV Setup', [(b.time_after(1), False)],
              diplomacy(b, computers_allied=True) +
              [(b.chat(M.coop(opts.lang, 'roles_ai_intro'), 20), 100)])
    roles_layer(theme, opts.lang, intro_delay=0)(b, dict(vocab=vocab, sets=sets))
    b.finish()
    return {}


# --------------------------------------------------------------------------- 4. vs hard AI

VSAI = {
    'map': '(5) co-op vs hard ai', 'pretty': '(5) Co-op vs Hard AI', 'title': 'Co-op vs Hard AI',
    'help': 'Two humans allied against three allied computer players with their full AI. Lobby: '
            'humans in slots 1-2 on one team, computers in slots 3-5 (Greece, Egypt, Persia) on '
            'another team, hardest difficulty.',
    'template': '(5) babylon',
}


def build_vsai(m, theme, vocab, opts, map_size):
    b = B.Builder(m)
    eff = diplomacy(b, computers_allied=True)
    eff.append((b.chat(M.coop(opts.lang, 'vsai_intro'), 20), 100))
    if opts.ai_bonus:
        eff += [(set_resource(b, 'SV Computer gold +%d' % opts.ai_bonus, PLAYER_ALL_CPUS, RES_GOLD,
                              OP_ADD, opts.ai_bonus), 0),
                (set_resource(b, 'SV Computer wood +%d' % opts.ai_bonus, PLAYER_ALL_CPUS, RES_WOOD,
                              OP_ADD, opts.ai_bonus), 0)]
    b.trigger('SV Setup', [(b.time_after(1), False)], eff)
    b.finish()
    return {}


# --------------------------------------------------------------------------- probe


def build_probe(m, theme, vocab, opts, map_size):
    """Live diagnostic for the mechanisms the new modes add (docs/coop-modes.md 6): token text,
    Var0 counter, looping re-fire, Trigger on/off chain, alive filter, ChangeOwner, tithe."""
    b = B.Builder(m)
    sets = {k: vocab.unitset(v) for k, v in B.UNITSETS.items()}
    a_spawn = b.area('SV Spawn centre', *B.spawn_rect(map_size))
    c_var = res_cond(b, P1, RES_VAR0, 0, 'SV REF P1 Var0', op=CMP_REF)
    c_gold = res_cond(b, P1, RES_GOLD, 0, 'SV REF P1 gold', op=CMP_REF)
    c_gold2 = res_cond(b, P2, RES_GOLD, 0, 'SV REF P2 gold', op=CMP_REF)
    b.trigger('SV Probe 05 s', [(b.time_after(5), False)],
              [(b.chat('PROBE 5 s: Var0 set to 7, next line must read 7', 20), 0),
               (set_resource(b, 'SV Probe Var0 = 7', P1, RES_VAR0, OP_SET, 7), 0),
               (b.chat('PROBE 5 s: Var0 = ' + token(b, c_var) + ' / your gold = ' + token(b, c_gold),
                       20), 100)] + diplomacy(b))
    b.trigger('SV Probe loop', [(b.time_after(10), False)],
              [(set_resource(b, 'SV Probe Var0 + 1', P1, RES_VAR0, OP_ADD, 1), 0),
               (b.chat('PROBE loop (every 10 s from 20 s): Var0 = ' + token(b, c_var), 8), 10)],
              looping=True, true_for=10)
    h = hero(vocab, 'Cleopatra')
    o_h = b.obj('SV W probe boss', PLAYER_ALL_CPUS, unit_type=h, count=(1, 1), area=a_spawn)
    o_alive = alive_filter(b, b.obj('SV Probe boss alive', PLAYER_ALL_CPUS, unit_type=h,
                                    count=(1, 9)))
    e_watch = trigger_switch(b, 'SV Probe watch on', True)
    b.trigger('SV Probe 30 s boss', [(b.time_after(30), False)],
              [(b.chat('PROBE 30 s: enemy Cleopatra at the map centre; kill her', 25), 0),
               (b.eff((6, 4), 'SV Probe AI off', setting=B.AI_SETTING_ENABLED, on=0,
                      player=PLAYER_ALL_CPUS), 0),
               (b.eff((1, 0), 'SV Probe create boss', object=o_h), 50), (e_watch, 1000)])
    watch = b.trigger('SV Probe boss down', [(b.exists(o_alive, 'SV Probe boss alive'), True)],
                      [(b.chat('PROBE: boss-down trigger fired (chain + alive filter work)', 25), 0)],
                      on=False, true_for=2)
    set_target(b, e_watch, watch)
    sword = vocab.unit(B.PERSIAN['sword'][1])
    o_p1 = b.obj('SV W probe P1 sword', P1, unit_type=sword, count=(2, 2), area=a_spawn)
    o_p1sel = b.obj('SV Probe P1 swords', P1, unit_type=sword, count=(1, 99))
    b.trigger('SV Probe 40 s owner', [(b.time_after(40), False)],
              [(b.chat('PROBE 40 s: 2 swordsmen for slot 1 at the centre, handed to slot 2 in 5 s',
                       25), 0),
               (b.eff((1, 0), 'SV Probe create P1 swords', object=o_p1), 0),
               (b.eff((1, 9), 'SV Probe swords to P2', new_player=P2, object=o_p1sel), 500)])
    b.trigger('SV Probe 60 s tithe', [(b.time_after(60), False),
                                      (res_cond(b, P1, RES_GOLD, 100, 'SV Probe P1 gold >= 100'),
                                       False)],
              [(b.chat('PROBE 60 s: before tithe P1 gold ' + token(b, c_gold) + ', P2 gold ' +
                       token(b, c_gold2), 25), 0),
               (set_resource(b, 'SV Probe P1 gold - 100', P1, RES_GOLD, OP_SUB, 100), 100),
               (set_resource(b, 'SV Probe P2 gold + 100', P2, RES_GOLD, OP_ADD, 100), 100),
               (b.chat('PROBE 60 s: after tithe P1 gold ' + token(b, c_gold) + ', P2 gold ' +
                       token(b, c_gold2), 25), 200)])
    b.trigger('SV Probe 180 s victory', [(b.time_after(180), False)],
              [(b.chat('PROBE 180 s: victory in 3 s', 25), 0),
               (b.eff((2, 0), 'SV Probe victory', player=PLAYER_ALL_HUMANS), 300)])
    b.finish()
    return {'sets': sets}


PROBE = {'map': '(4) coop probe', 'pretty': '(4) Coop Probe', 'title': 'Coop probe', 'lobby': False,
         'help': 'DIAGNOSTIC MAP for the co-op mode triggers (docs/coop-modes.md).'}

MODES = {
    'endless': (ENDLESS, build_endless),
    'endless-easy': (ENDLESS_EASY, build_endless),
    'endless-normal': (ENDLESS_NORMAL, build_endless),
    'bosshunt': (BOSSHUNT, build_bosshunt),
    'roles': (ROLES, build_roles),
    'roles-ai': (ROLES_AI, build_roles_ai),
    'vsai': (VSAI, build_vsai),
}

# --------------------------------------------------------------------------- file level


def test_schedule(name, theme):
    """LIVE TESTING ONLY: compressed clocks so a test reaches the interesting parts quickly."""
    t = dict(theme, help='TEST SCHEDULE BUILD. ' + theme['help'], lobby=False)
    if name.startswith('endless'):
        t.update(first_wave=30, intervals=[(10 ** 6, 20)], boss_breather=5, size_cap=6,
                 loop_gap=20, tier_waves=2)
    elif name == 'bosshunt':
        t.update(first=30, breather=10)
    return t


def build_file(game, name, theme, fn, vocab, opts):
    template = Path(game) / 'Data' / 'scenarios' / (theme.get('template', '(4) plains') + '.scn')
    f = R.load_any(template)
    if any(c[0:2] != [4, 0] for c in f.chunks):
        raise ValueError('template chunk version is not 4.0')
    m = R.Manager.parse(f.get(6))
    map_size = struct.unpack_from('<II', f.get(4), 0)
    info = fn(m, theme, vocab, opts, map_size)
    raw = m.serialize()
    f.put(6, raw)
    h = R.parse_header(f.header)
    file_name = theme['map'] + '.scn'
    h['name'] = R.S(theme['pretty'] + '.scn')
    h['map_name'] = R.S(theme['pretty'] + '.scn')
    h['desc'] = R.S(B.header_help(dict(theme, lang=opts.lang)))
    h['map_id'] = B.map_id(file_name)
    f.header = R.build_header(h)
    f.trailer = struct.pack('<I', h['map_id'])
    return f.to_bytes(), raw, info, template


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_dir')
    ap.add_argument('overlay_dir')
    ap.add_argument('--mode', default='all', choices=['all'] + sorted(MODES))
    ap.add_argument('--explicit-waves', type=int, default=50,
                    help='endless: waves with their own trigger before the looping phase')
    ap.add_argument('--boss-buffs', action='store_true',
                    help='experimental: boss hunt +10%% HP per stage on the boss class')
    ap.add_argument('--ai-bonus', type=int, default=0,
                    help='vs hard AI: extra gold and wood for every computer at the start')
    ap.add_argument('--test-schedule', action='store_true', help='LIVE TESTING ONLY: short clocks')
    ap.add_argument('--probe', action='store_true',
                    help='LIVE TESTING ONLY: write "(4) coop probe" instead of the modes')
    ap.add_argument('--lang', choices=M.LANGS, default='ru',
                    help='language of the in-game texts (default ru; all players need the same '
                         'build). Lobby name/help come from Language.dll either way.')
    ap.add_argument('--no-previews', dest='previews', action='store_false',
                    help='do not write the lobby picture (Data/textures) and movie (Data/movies)')
    opts = ap.parse_args(argv)
    opts.spawn, opts.ai_off, opts.force_diplomacy, opts.zombie_buffs = 'area', True, True, False
    game = Path(opts.game_dir)
    vocab = B.Vocab(game)
    out = Path(opts.overlay_dir)
    jobs = [('probe', PROBE, build_probe)] if opts.probe else \
        [(n, *MODES[n]) for n in (sorted(MODES) if opts.mode == 'all' else [opts.mode])]
    results = {}
    for name, theme, fn in jobs:
        if opts.test_schedule:
            theme = test_schedule(name, theme)
        data, raw, info, template = build_file(game, name, theme, fn, vocab, opts)
        scn = out / 'Data' / 'scenarios' / (theme['map'] + '.scn')
        rmv = out / 'Data' / 'map scripts' / (theme['map'] + '.rmv')
        scn.parent.mkdir(parents=True, exist_ok=True)
        rmv.parent.mkdir(parents=True, exist_ok=True)
        scn.write_bytes(data)
        rmv.write_bytes(B.rmv_text(theme).replace('build_survival', 'build_coop').encode('ascii'))
        if opts.previews and name != 'probe':
            P.write_previews(game, theme.get('template', '(4) plains'), theme['map'], out)
        print('%-9s %s  %d bytes  sha256 %s' % (name, scn, len(data),
                                                hashlib.sha256(data).hexdigest()[:12]))
        results[name] = (theme, data, raw, info, template)
    return results


if __name__ == '__main__':
    main()
    sys.exit(0)
