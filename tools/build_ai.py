#!/usr/bin/env python3
"""Build improved .tai unit AI scripts from the user's install (read-only) and lint them.

Usage:
  python tools/build_ai.py build [--game "D:/Games/Rise and Fall"]   # writes ai/unit ai scripts/*.tai
  python tools/build_ai.py lint  [--game ...]                        # lint stock + patched scripts
  python tools/build_ai.py diff  [--game ...]                        # unified diffs (used for docs/ai.md)

Every patch is an exact-match replacement that must hit exactly once, so a game
update that changes the stock files makes the build fail loudly instead of silently.
Stock files are never modified; output goes to ai/unit ai scripts/ only.
"""
import argparse, difflib, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "ai", "unit ai scripts")
DEFAULT_GAME = r"D:\Games\Rise and Fall"
NL = "\r\n"


def L(*lines):
    return NL.join(lines)


KITE_OLD = "\tallof(GoalIsPlayerInitiated,UnitIsArtillery,EnemyWithinMinimumRange) true(MoveOutOfMinimumRange)"
KITE_NEW = "\tallof(UnitIsArtillery,EnemyWithinMinimumRange) true(MoveOutOfMinimumRange)"
ABANDON = "\tAbandonEnemy true(ShouldIReturnToInitialContactLocation)"

TRANSPORT_BLOCK = [
    "",
    "// loaded transports run from attackers instead of sitting idle",
    "Idle",
    "{",
    "\tAmIUnderAttack remove()",
    "}",
    "Idle",
    "{",
    "\tAmIUnderAttack true(UnderAttack)",
    "}",
    "UnderAttack",
    "{",
    "\tCanFlee true(RunFromAttacker) false(Idle)",
    "}",
    "RunFromAttacker",
    "{",
    "\tAlwaysTrue true(PrepareToMove)",
    "}",
]

PATCHES = {
    "Generic Attack.tai": [
        # FIX 1a: CheckRange - artillery steps out of minimum range on auto-acquired targets too
        (L(ABANDON, KITE_OLD,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange) true(ShouldIReturnToInitialContactLocation)"),
         L(ABANDON, KITE_NEW,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange) true(ShouldIReturnToInitialContactLocation)")),
        # FIX 1b: FaceEnemyUnit - same, but out-of-ammo artillery must not walk away
        (L(ABANDON, KITE_OLD,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange,AmmoExhausted) true(ShouldIReturnToInitialContactLocation)"),
         L(ABANDON, "\tAmmoExhausted true(ShouldIReturnToInitialContactLocation)", KITE_NEW,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange,AmmoExhausted) true(ShouldIReturnToInitialContactLocation)")),
    ],
    "Naval Onager.tai": [
        # FIX 1c: same for naval onagers (own copy of the attack states)
        (L(ABANDON, KITE_OLD,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange) true(ShouldIReturnToInitialContactLocation)"),
         L(ABANDON, KITE_NEW,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange) true(ShouldIReturnToInitialContactLocation)")),
        (L(ABANDON, KITE_OLD,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange,AmmoExhausted) true(LostEnemyUnit)"),
         L(ABANDON, "\tAmmoExhausted true(LostEnemyUnit)", KITE_NEW,
           "\tanyof(AbandonEnemy,EnemyWithinMinimumRange,AmmoExhausted) true(LostEnemyUnit)")),
        (L("\tReloaded true(ReacquireGoal)", "\tAbandonEnemy true(LostEnemyUnit)", KITE_OLD),
         L("\tReloaded true(ReacquireGoal)", "\tAbandonEnemy true(LostEnemyUnit)", KITE_NEW)),
    ],
    "Sea Transport.tai": [
        # FIX 2: loaded troop ships react to being hit (remove-then-add, the pairing hero.tai uses)
        ('#include("Transport.tai")', L('#include("Transport.tai")', *TRANSPORT_BLOCK)),
    ],
    "Helicopter Transport.tai": [
        ('#include("transport.tai")', L('#include("transport.tai")', *TRANSPORT_BLOCK)),
    ],
    "Medic Surgeon.tai": [
        # FIX 3: medic keeps healing; the stock HealUnit override dropped the patient whenever an enemy was visible
        (L("HealUnit\t\t ", "{", "\tCanISeeEnemy true(CheckRange)", "}", "", ""), ""),
    ],
    "Bomber.tai": [
        # FIX 4: UnitDestroyed has no handler in the unit trigger table, so bombers never picked a secondary target
        ("allof(GoalIsUnit,UnitDestroyed) true(SearchForSecondaryTarget)",
         "allof(GoalIsUnit,EnemyUnitDestroyed) true(SearchForSecondaryTarget)"),
    ],
    "Horse Archer.tai": [
        # FIX 5: horse archers step back from melee attackers on auto-acquired targets (same flee gate as air units)
        ('#include("Generic Attack.tai")',
         L("// horse archers kite melee attackers instead of trading blows",
           "AttackEnemyUnit",
           "{",
           "\tallof(AttackerIsMeleeUnit,GoalIsNotPlayerInitiated,CanFlee) true(RunFromAttacker)",
           "}",
           "",
           '#include("Generic Attack.tai")')),
    ],
}


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("latin1")


def patched(game):
    src = os.path.join(game, "Data", "unit ai scripts")
    res = {}
    for name, edits in PATCHES.items():
        stock = read(os.path.join(src, name))
        txt = stock
        for old, new in edits:
            n = txt.count(old)
            if n != 1:
                sys.exit(f"{name}: patch anchor matched {n} times (need 1):\n{old}")
            txt = txt.replace(old, new)
        res[name] = (stock, txt)
    return res


def build(game):
    os.makedirs(OUT, exist_ok=True)
    for name, (_, txt) in patched(game).items():
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(txt.encode("latin1"))
        print("wrote", name)


def diffs(game):
    out = []
    for name, (stock, txt) in patched(game).items():
        d = difflib.unified_diff(stock.replace("\r\n", "\n").splitlines(), txt.replace("\r\n", "\n").splitlines(),
                                 f"a/unit ai scripts/{name}", f"b/ai/unit ai scripts/{name}", lineterm="", n=3)
        out.append("\n".join(d))
    return "\n\n".join(out)


# ---------------------------------------------------------------- lint
def exe_strings(game):
    d = open(os.path.join(game, "RiseAndFall.exe"), "rb").read()
    return set(m.decode() for m in re.findall(rb"[\x20-\x7e]{3,}", d))


def parse(text):
    """-> list of (state, [entry lines], line); raises ValueError on structural errors"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    states, cur, depth, pending = [], None, 0, None
    for ln, raw in enumerate(text.splitlines(), 1):
        s = raw.split("//")[0].strip()
        if not s:
            continue
        if s.startswith("#include"):
            states.append(("#include", [s], ln))
            continue
        if s == "{":
            if pending is None or depth:
                raise ValueError(f"line {ln}: stray {{")
            cur = (pending, [], ln)
            depth, pending = 1, None
            continue
        if s == "}":
            if not depth:
                raise ValueError(f"line {ln}: stray }}")
            states.append(cur)
            cur, depth = None, 0
            continue
        if depth:
            cur[1].append(s)
        else:
            if pending is not None:
                raise ValueError(f"line {ln}: two names in a row")
            pending = s
    if depth or pending:
        raise ValueError("unterminated block")
    return states


def lint_text(name, text, vocab):
    errs = []
    try:
        states = parse(text)
    except ValueError as e:
        return [f"{name}: {e}"]
    for st, entries, ln in states:
        if st == "#include":
            continue
        if st not in vocab:
            errs.append(f"{name}:{ln}: unknown state {st}")
        for e in entries:
            if e == "Flush()":
                continue
            m = re.match(r"^(?:(allof|anyof)\(([\w,]+)\)|(\w+))\s*(.*)$", e)
            if not m:
                errs.append(f"{name}:{ln}: bad entry {e}")
                continue
            for t in (m.group(2) or m.group(3)).split(","):
                if t not in vocab:
                    errs.append(f"{name}:{ln}: unknown trigger {t}")
            rest = m.group(4)
            if rest != "remove()":
                acts = re.findall(r"(true|false)\((\w+)\)", rest)
                if not acts or re.sub(r"(true|false)\(\w+\)|\s", "", rest):
                    errs.append(f"{name}:{ln}: bad action list {e}")
                for _, a in acts:
                    if a not in vocab:
                        errs.append(f"{name}:{ln}: unknown target state {a}")
    return errs


def lint(game):
    vocab = exe_strings(game)
    src = os.path.join(game, "Data", "unit ai scripts")
    print("-- stock scripts")
    stock_bad = 0
    for f in sorted(os.listdir(src)):
        e = lint_text(f, read(os.path.join(src, f)), vocab)
        for x in e:
            print("  ", x)
        stock_bad += len(e)
    print("stock issues:", stock_bad, "(non-zero means the linter is stricter than the game or a script has a typo)")
    print("-- patched scripts")
    bad = 0
    low = {i.lower() for i in os.listdir(src)}
    for name, (_, txt) in patched(game).items():
        e = lint_text(name, txt, vocab)
        for x in e:
            print("  ", x)
        bad += len(e)
        for m in re.finditer(r'#include\("([^"]+)"\)', txt):
            if m.group(1).lower() not in low:
                print("   missing include", name, m.group(1))
                bad += 1
    print("patched issues:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "lint", "diff"])
    ap.add_argument("--game", default=DEFAULT_GAME)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.game)
    elif a.cmd == "diff":
        print(diffs(a.game))
    else:
        sys.exit(lint(a.game))
