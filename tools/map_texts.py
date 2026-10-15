"""Player-visible texts of our scenario maps (tools/build_survival.py, tools/build_coop.py).

Two kinds of text, two mechanisms (evidence: docs/survival.md section 8):

* Lobby name and help. The map list reads Data\\map scripts\\<map>.rmv (FUN_00bcd8f0): with
  `StringTableID` / `StringHelpID` the name and help come from Language.dll, which is how every
  stock map does it (e.g. (4) plains: 27032 / 630). Our ids live in free Language.dll slots and
  are written into the generated Language.dll of the `credits` overlay (raf_patch.build_credits),
  in Russian, or in English when lang-en is on. The .rmv itself only carries the ids, so it is
  the same for every language and the gameplay fingerprint does not depend on the language.
* In-game texts (chat, counters) are stored in the .scn trigger chunk as 8-bit text. The Russian
  release stores cp1251 there itself ((2) gamersday.scn, the three tutorials), so we do the same.
  The .scn is a gameplay file (fingerprint), so one language per build: Russian by default,
  English with `--lang en` (all players must use the same build).

Rules for every string here: cp1251-encodable, only ASCII, newline and the Cyrillic letters
0xC0-0xFF (no yo, no typographic quotes or dashes: the game fonts are 8-bit and the stock
Russian texts use plain ASCII punctuation).
"""

LANGS = ('ru', 'en')

# --------------------------------------------------------------------------- lobby (Language.dll)
# Free in the stock Russian Language.dll and in the lang-en build (checked by check_survival):
# names 27040.. (stock map names end at 27036), help 640.. (stock map help 600..630).
NAME_BASE, HELP_BASE = 27040, 640

# Shown in the lobby's help box when the map is hovered (FUN_00b9e000 sets it as the list
# button's help string; box 738x153 of 1600x1200, 18 pt): stock help texts are at most 311
# characters with two line breaks, so ours stay within 320 characters and 2 line breaks.
LOBBY = {
    '(4) survival': {
        'ru': ('(4) Выживание',
               '(4) /fbВыживание/fd - 1-2 игрока обороняют город от 20 волн персов из центра '
               'карты. Волны растут, каждую 5-ю ведет герой.\n'
               '/fbПобеда/fd - пережить 20 волн и добить врагов. /fbПоражение/fd - пали все '
               'ваши городские центры.\n'
               '/fbЛобби/fd - люди в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Survival',
               '(4) /fbSurvival/fd - 1-2 players defend their town against 20 Persian waves from '
               'the map centre. Waves grow, a hero leads every 5th.\n'
               '/fbVictory/fd - survive 20 waves and kill every enemy. /fbDefeat/fd - all your '
               'town centres are lost.\n'
               '/fbLobby/fd - humans on one team, exactly one computer on another.'),
    },
    '(4) survival zombies': {
        'ru': ('(4) Выживание: зомби',
               '(4) /fbВыживание: зомби/fd - Хэллоуин: 20 орд мертвецов, только ближний бой, но '
               'их больше и они чаще. Орды 5, 10, 15 и 20 ведут Минотавры.\n'
               '/fbПобеда/fd - пережить 20 орд и добить всех. /fbПоражение/fd - пали все ваши '
               'городские центры.\n'
               '/fbЛобби/fd - люди в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Survival Zombies',
               '(4) /fbSurvival Zombies/fd - Halloween: 20 hordes of the dead, melee only, but '
               'more and faster. The Minotaur leads hordes 5, 10, 15 and 20.\n'
               '/fbVictory/fd - survive 20 hordes and kill them all. /fbDefeat/fd - all your '
               'town centres are lost.\n'
               '/fbLobby/fd - humans on one team, exactly one computer on another.'),
    },
    '(4) survival endless': {
        'ru': ('(4) Выживание: сложно',
               '(4) /fbВыживание: сложно/fd - Бесконечные волны, первая через 4 мин, тараны и '
               'онагры со 2-й, каждую 5-ю ведут герои.\n'
               '/fbЦель/fd - продержаться как можно дольше: когда город падет, игра скажет, '
               'сколько волн вы пережили.\n'
               '/fbЛобби/fd - 1-2 игрока в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Survival: Hard',
               '(4) /fbSurvival: Hard/fd - Endless waves, the first after 4 min, rams & onagers '
               'from wave 2, heroes lead every 5th.\n'
               '/fbGoal/fd - hold out as long as you can: when the town falls the game tells '
               'you how many waves you survived.\n'
               '/fbLobby/fd - 1-2 humans on one team, exactly one computer on another.'),
    },
    '(4) boss hunt': {
        'ru': ('(4) Охота на героев',
               '(4) /fbОхота на героев/fd - 12 вражеских героев по одному, каждый сильнее и с '
               'большей свитой; следующий - через 45 с после гибели прежнего.\n'
               '/fbПобеда/fd - убить последних (Юлий Цезарь и Тор). /fbПоражение/fd - пали все '
               'ваши городские центры.\n'
               '/fbЛобби/fd - 1-2 игрока в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Boss Hunt',
               '(4) /fbBoss Hunt/fd - 12 enemy heroes one at a time, each stronger and with a '
               'bigger escort; the next comes 45 s after the last one dies.\n'
               '/fbVictory/fd - kill the last ones (Julius Caesar and Tor). /fbDefeat/fd - all '
               'your town centres are lost.\n'
               '/fbLobby/fd - 1-2 humans on one team, exactly one computer on another.'),
    },
    '(4) co-op roles': {
        'ru': ('(4) Кооп: роли',
               '(4) /fbКооп: роли/fd - Слот 1 - экономист: жители, стройка, ресурсы. Слот 2 - '
               'полководец: ему переходят все солдаты, герои и готовые военные здания, '
               'экономист платит ему дань. 20 волн с осадными машинами.\n'
               '/fbЛобби/fd - люди строго в слотах 1 и 2 одной команды, ровно один компьютер в '
               'другой.'),
        'en': ('(4) Co-op Roles',
               '(4) /fbCo-op Roles/fd - Slot 1 is the economist: citizens, building, resources. '
               'Slot 2 is the commander: he gets every soldier, hero and finished military '
               'building, paid by a tithe. 20 waves with siege engines.\n'
               '/fbLobby/fd - humans exactly in slots 1 and 2 of one team, exactly one computer '
               'on another.'),
    },
    '(4) co-op roles vs ai': {
        'ru': ('(4) Кооп: роли против ИИ',
               '(4) /fbКооп: роли против ИИ/fd - Те же роли (слот 1 - экономист, слот 2 - '
               'полководец), но без волн: 1-2 компьютера со своим ИИ в союзе друг с другом. '
               'Цель - обычная победа.\n'
               '/fbЛобби/fd - люди строго в слотах 1 и 2 одной команды, 1-2 компьютера в '
               'другой, сложность максимальная.'),
        'en': ('(4) Co-op Roles vs AI',
               '(4) /fbCo-op Roles vs AI/fd - The same roles (slot 1 economist, slot 2 '
               'commander) without waves: 1-2 computers with their own AI, allied with each '
               'other. Goal: a normal win.\n'
               '/fbLobby/fd - humans exactly in slots 1 and 2 of one team, 1-2 computers on '
               'another, hardest difficulty.'),
    },
    '(5) co-op vs hard ai': {
        'ru': ('(5) Кооп против сильного ИИ',
               '(5) /fbКооп против сильного ИИ/fd - Два союзника против трех объединенных '
               'компьютерных империй с полным ИИ. Цель - обычная победа.\n'
               '/fbЛобби/fd - люди в слотах 1-2 (команда 1), компьютеры в слотах 3-5 (команда '
               '2): Греция, Египет, Персия; сложность до упора вправо.'),
        'en': ('(5) Co-op vs Hard AI',
               '(5) /fbCo-op vs Hard AI/fd - Two allies against three allied computer empires '
               'with their full AI. Goal: a normal win.\n'
               '/fbLobby/fd - humans in slots 1-2 (team 1), computers in slots 3-5 (team 2): '
               'Greece, Egypt, Persia; difficulty slider fully right.'),
    },
    '(4) survival endless easy': {
        'ru': ('(4) Выживание: легко',
               '(4) /fbВыживание: легко/fd - Бесконечные волны вдвое меньше, первая через 6 мин, '
               'тараны и онагры с 8-й, больше времени между волнами.\n'
               '/fbЦель/fd - продержаться как можно дольше: когда город падет, игра скажет, '
               'сколько волн вы пережили.\n'
               '/fbЛобби/fd - 1-2 игрока в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Survival: Easy',
               '(4) /fbSurvival: Easy/fd - Endless half-size waves, the first after 6 min, rams & '
               'onagers from wave 8, more time between waves.\n'
               '/fbGoal/fd - hold out as long as you can: when the town falls the game tells '
               'you how many waves you survived.\n'
               '/fbLobby/fd - 1-2 humans on one team, exactly one computer on another.'),
    },
    '(4) survival endless normal': {
        'ru': ('(4) Выживание: средне',
               '(4) /fbВыживание: средне/fd - Бесконечные волны поменьше, первая через 5 мин, '
               'тараны и онагры с 4-й, каждую 5-ю ведут герои.\n'
               '/fbЦель/fd - продержаться как можно дольше: когда город падет, игра скажет, '
               'сколько волн вы пережили.\n'
               '/fbЛобби/fd - 1-2 игрока в одной команде, ровно один компьютер в другой.'),
        'en': ('(4) Survival: Normal',
               '(4) /fbSurvival: Normal/fd - Endless smaller waves, the first after 5 min, rams & '
               'onagers from wave 4, heroes lead every 5th.\n'
               '/fbGoal/fd - hold out as long as you can: when the town falls the game tells '
               'you how many waves you survived.\n'
               '/fbLobby/fd - 1-2 humans on one team, exactly one computer on another.'),
    },
}
HELP_MAX_CHARS, HELP_MAX_BREAKS = 320, 2
MAPS = list(LOBBY)          # fixed order = fixed string ids; append new maps at the end only


def string_ids(stem):
    """(name id, help id) of a map, e.g. '(4) survival' -> (27040, 640)."""
    i = MAPS.index(stem)
    return NAME_BASE + i, HELP_BASE + i


def string_repl(lang):
    """{Language.dll string id: text} for every map, 'ru' or 'en'."""
    lang = 'en' if lang == 'en' else 'ru'
    out = {}
    for stem in MAPS:
        nid, hid = string_ids(stem)
        out[nid], out[hid] = LOBBY[stem][lang]
    return out


# --------------------------------------------------------------------------- heroes

HEROES = {   # English label (build_coop.HEROES keys) -> (Russian name as in Language2.dll, gender)
    'Cleopatra': ('Клеопатра', 'f'),
    'Octavian': ('Октавиан', 'm'),
    'Nebuchadnezzar': ('Навуходоносор', 'm'),
    'Aristander': ('Аристандер', 'm'),
    'Sargon': ('Саргон', 'm'),
    'Ramses': ('Рамзес', 'm'),
    'Tiberius': ('Тиберий', 'm'),
    'Tor': ('Тор', 'm'),
    'Alexander': ('Александр', 'm'),
    'Julius Caesar': ('Юлий Цезарь', 'm'),
    'Achilles': ('Ахиллес', 'm'),
    'Germanicus': ('Германик', 'm'),
    'The Minotaur': ('Минотавр', 'm'),
}


def hero(lang, label):
    return HEROES[label][0] if lang == 'ru' else label


def heroes(lang, labels):
    """Display text for a list of hero labels: 'X', 'X and Y', or 'N x X' for N of the same."""
    if not labels:
        return ''
    if len(labels) > 1 and len(set(labels)) == 1:
        return ('%s x%d' % (hero(lang, labels[0]), len(labels)) if lang == 'ru'
                else '%d x %s' % (len(labels), labels[0]))
    return (' и ' if lang == 'ru' else ' and ').join(hero(lang, h) for h in labels)


def ru_plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


# --------------------------------------------------------------------------- in-game: survival

GOLD, RED, GREEN, WHITE = '/r225/g185/b35', '/r255/g80/b80', '/r150/g255/b150', '/r255/g255/b255'

# English stays in tools/build_survival.py THEMES (byte-identical to the earlier builds).
SURVIVAL_RU = {
    'classic': {
        'intro': GOLD + 'ВЫЖИВАНИЕ' + WHITE + '  Удержите город %(waves)d волн. Враг выходит из '
                 'центра карты. Каждую 5-ю волну ведет герой.',
        'wave': GOLD + 'Волна %(k)d из %(waves)d' + WHITE + ' наступает!',
        'boss': RED + '%(boss)s' + WHITE + ' ведет волну %(k)d!',
        'boss_pl': RED + '%(boss)s' + WHITE + ' ведут волну %(k)d!',
        'next': 'До волны %(k)d',
        'last': 'Последняя волна: уничтожьте всех врагов',
        'win': GOLD + 'Победа!' + WHITE + ' Город выстоял.',
        'lose': RED + 'Город пал.',
    },
    'zombie': {
        'intro': GREEN + 'МЕРТВЕЦЫ ИДУТ' + WHITE + '  Переживите %(waves)d орд. Они идут без '
                 'остановки.',
        'wave': GREEN + 'Орда %(k)d из %(waves)d' + WHITE + ' поднимается!',
        'boss': RED + '%(boss)s' + WHITE + ' идет с ордой %(k)d!',
        'boss_pl': RED + '%(boss)s' + WHITE + ' идут с ордой %(k)d!',
        'next': 'До орды %(k)d',
        'last': 'Последняя орда: уничтожьте всех',
        'win': GREEN + 'Рассвет.' + WHITE + ' Вы выжили.',
        'lose': RED + 'Город захвачен.',
    },
}

# --------------------------------------------------------------------------- in-game: co-op modes


def gold(text):
    return GOLD + text + WHITE


def red(text):
    return RED + text + WHITE


def coop(lang, key, **k):
    """Every chat/counter text of tools/build_coop.py. 'en' reproduces the earlier English
    builds byte for byte."""
    ru = lang == 'ru'
    n = len(k.get('labels', ()))
    names = heroes(lang, k.get('labels', ()))
    if key == 'endless_intro':
        return (gold('БЕСКОНЕЧНОЕ ВЫЖИВАНИЕ') + '  Волны не кончаются. Каждую 5-ю ведет герой. '
                'Когда город падет, вы узнаете, сколько волн продержались.') if ru else \
            (gold('ENDLESS SURVIVAL') + '  The waves never stop. Every 5th wave brings a hero. '
             'When the town falls you will see how many waves you held.')
    if key == 'wave_in':                       # counter title; k['k'] = number
        return ('До волны %d' if ru else 'Wave %d in') % k['k']
    if key == 'next_wave_in':
        return 'До следующей волны' if ru else 'Next wave in'
    if key == 'wave_coming':                   # k['k'] = number or token text
        return (gold('Волна %s') % k['k'] + ' наступает!') if ru else \
            (gold('Wave %s') % k['k'] + ' is coming!')
    if key == 'lead_wave':                     # k['labels'], k['k'] = number or token text
        if ru:
            return red(names) + (' ведут' if n > 1 else ' ведет') + ' волну %s!' % k['k']
        return red(names) + ' lead wave %s!' % k['k']
    if key == 'fallen_first':
        return (red('Город пал') + ' еще до первой волны.') if ru else \
            (red('The town has fallen') + ' before the first wave.')
    if key == 'fallen_wave':                   # k['k']: wave number
        w = k['k']
        if ru:
            return red('Город пал в волне %d.' % w) + ' Вы пережили %d %s.' % (
                w - 1, ru_plural(w - 1, 'волну', 'волны', 'волн'))
        return red('The town has fallen in wave %d.' % w) + ' You survived %d wave%s.' % (
            w - 1, '' if w == 2 else 's')
    if key == 'fallen_endless':                # k['tok'], k['n']
        if ru:
            return red('Город пал в волне ' + k['tok'] + '.') + \
                ' Вы продержались дольше %d волн. Достойный бой!' % k['n']
        return red('The town has fallen in wave ' + k['tok'] + '.') + \
            ' You held out past wave %d. Well fought!' % k['n']
    if key == 'hunt_intro':                    # k['n'] stages
        return (gold('ОХОТА НА ГЕРОЕВ') + '  %d вражеских героев придут за вами по одному. '
                'Каждый сильнее прежнего и с большей свитой. Убейте последнего, чтобы '
                'победить.' % k['n']) if ru else \
            (gold('BOSS HUNT') + '  %d enemy heroes will come for you, one at a time. Each '
             'is stronger than the last and brings a bigger escort. Slay the last to win.' % k['n'])
    if key == 'boss_in':
        return ('До босса %d' if ru else 'Boss %d in') % k['k']
    if key == 'boss_coming':                   # k['labels'], k['k'], k['n']
        if ru:
            return red(names) + ' %s! Босс %d из %d.' % ('идут' if n > 1 else 'идет', k['k'], k['n'])
        return red(names) + ' %s coming! Boss %d of %d.' % ('are' if n > 1 else 'is', k['k'], k['n'])
    if key == 'boss_counter':
        return ('Босс %d из %d: %s' if ru else 'Boss %d of %d: %s') % (k['k'], k['n'], names)
    if key == 'boss_fallen':
        if ru:
            verb = 'пали' if n > 1 else ('пала' if HEROES[k['labels'][0]][1] == 'f' else 'пал')
            return red(names) + ' %s!' % verb
        return red(names) + ' %s fallen!' % ('have' if n > 1 else 'has')
    if key == 'hunt_victory':
        return (gold('Победа!') + ' Все герои пали.') if ru else \
            (gold('Victory!') + ' Every hero has fallen.')
    if key == 'hunt_defeat':
        return (red('Город пал.') + ' Охота окончена.') if ru else \
            (red('The town has fallen.') + ' The hunt is over.')
    if key == 'roles_intro':
        return (gold('РОЛИ') + '  Слот 1 = ЭКОНОМИСТ: все жители, строит все. Слот 2 = '
                'ПОЛКОВОДЕЦ: ему переходят все солдаты, герои и достроенные казармы, конюшни и '
                'стрельбища.') if ru else \
            (gold('ROLES') + '  Slot 1 = ECONOMIST: all citizens, builds '
             'everything. Slot 2 = COMMANDER: every soldier, hero and finished '
             'barracks/stable/archery range goes to him.')
    if key == 'roles_tithe':                   # k['every'], k['give'], k['have'], k['more']
        if ru:
            return ('Дань: каждые %d с экономист отдает полководцу %d золота и %d дерева, если '
                    'у него от %d, и еще больше от %d.' % (k['every'], k['give'], k['give'],
                                                          k['have'], k['more']))
        return ('Tithe: every %d s the economist pays the commander %d gold and %d wood '
                'when he holds %d+, more above %d.' % (k['every'], k['give'], k['give'],
                                                       k['have'], k['more']))
    if key == 'roles_ai_intro':
        return (gold('КООП: РОЛИ ПРОТИВ ИИ') + '  Компьютеры играют со своим ИИ.') if ru else \
            (gold('CO-OP ROLES vs AI') + '  The computers keep their own AI.')
    if key == 'vsai_intro':
        return (gold('КООП ПРОТИВ СИЛЬНОГО ИИ') + '  Три компьютерные империи в союзе против '
                'вас. Держитесь вместе.') if ru else \
            (gold('CO-OP vs HARD AI') + '  Three computer empires are allied '
             'against you. Hold together.')
    raise KeyError(key)


# markers the offline stubs use to find a message in the chat log
MARK = {'ru': {'coming': 'наступает', 'fallen': 'Город пал', 'wave': 'Волна %d'},
        'en': {'coming': 'is coming', 'fallen': 'fallen', 'wave': 'Wave %d'}}


# --------------------------------------------------------------------------- validation


def encode(text):
    """cp1251 bytes; raises on anything outside ASCII + newline + Cyrillic 0xC0-0xFF."""
    raw = text.encode('cp1251')
    bad = [b for b in raw if not (b == 0x0A or 0x20 <= b < 0x7F or b >= 0xC0)]
    if bad:
        raise ValueError('character(s) outside the safe set in %r: %s' % (text[:40], bad[:5]))
    return raw


def all_texts():
    """(label, text) of every fixed string in this module (lobby + survival in-game)."""
    for stem in MAPS:
        for lang in LANGS:
            name, help_ = LOBBY[stem][lang]
            yield '%s %s name' % (stem, lang), name
            yield '%s %s help' % (stem, lang), help_
    for theme, d in SURVIVAL_RU.items():
        for k, v in d.items():
            yield 'survival %s ru %s' % (theme, k), v
    for lang in LANGS:
        for label in HEROES:
            yield 'hero %s %s' % (label, lang), hero(lang, label)
