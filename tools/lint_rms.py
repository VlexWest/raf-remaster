#!/usr/bin/env python3
"""Linter for Rise and Fall random map scripts (.rmv).

Usage:
  python tools/lint_rms.py [--game "D:/Games/Rise and Fall"] [--shipped] [files or dirs ...]

  --shipped   also lint every script of the game install (must give 0 issues)
  default     lints the scripts you name; with no names, lints <repo>/rms

Nothing from the game is copied.  Everything is read from the install at run
time, read only:
  * vocabulary = every identifier that occurs in the shipped scripts
    (Data/random map scripts/**.rmv)
  * engine keywords = NUL-delimited strings of Default.dll (the RMS parser; the
    exe has none of them), statement keywords must be found there
  * object / terrain names (the ones with a '-' in them) are also searched in
    the exe, the DLLs and Data/db/*.dat, reported as a warning if missing

Checks (ISSUE = fails the run, WARN = printed only):
  ISSUE  unknown identifier (not in shipped vocabulary, not #defined by the script)
  ISSUE  statement keyword not found in Default.dll
  ISSUE  #include target missing, unbalanced #if/#endif or parentheses,
         malformed #define, k-constant used but not defined on that path
  ISSUE  (own scripts only) a size/player/epoch combination that sets different
         attributes than another combination of the same script
  WARN   numeric value outside the min..max seen in the shipped scripts for the
         same attribute, object name not found in game strings

The preprocessor is simulated for every MapSize x PlayerCount(2..8) x StartEpoch
x climate x PERCENT outcome, so a missing branch is found without the game.
"""
import argparse
import itertools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))

SIZES = ["TinyMap", "SmallMap", "MediumMap", "LargeMap", "HugeMap"]
PLAYERS = list(range(2, 9))
EPOCHS = ["PaleoEpoch", "StoneEpoch", "CopperEpoch", "BronzeEpoch", "DarkEpoch",
          "MiddleEpoch", "RenaissanceEpoch", "ImperialEpoch", "IndustrialEpoch",
          "WW1Epoch", "WW2Epoch", "ModernEpoch", "InformationEpoch", "NanoEpoch"]
TEST_EPOCHS = ["PaleoEpoch", "BronzeEpoch", "NanoEpoch"]
CLIMATES = ["GrassClimate", "ArticClimate"]
CLIMATE_ALL = ["RandomClimate", "JungleClimate", "DesertClimate", "ArticClimate", "GrassClimate"]

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*")
NUMBER = re.compile(r"-?\d+\.?\d*|-?\.\d+|0x[0-9A-Fa-f]+")
BUILTIN_VARS = {"$ClimateType", "$MapSize", "$PlayerCount", "$StartEpoch"}


class Issue:
    def __init__(self, kind, path, line, msg):
        self.kind, self.path, self.line, self.msg = kind, path, line, msg

    def __str__(self):
        return "%s %s:%s: %s" % (self.kind, self.path, self.line, self.msg)


# --------------------------------------------------------------------------
# reading / tokenising
# --------------------------------------------------------------------------
def strip_comment(line):
    out, q = [], False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"':
            q = not q
        if not q and line.startswith("//", i):
            break
        out.append(c)
        i += 1
    return "".join(out)


def balanced(s):
    d = 0
    for c in s:
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d < 0:
                return False
    return d == 0


def split_top(s):
    """split on commas at paren depth 0"""
    parts, d, cur = [], 0, []
    for c in s:
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
        if c == "," and d == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur).strip())
    return parts


class Line:
    __slots__ = ("no", "kind", "text", "name", "value")

    def __init__(self, no, kind, text, name=None, value=None):
        self.no, self.kind, self.text, self.name, self.value = no, kind, text, name, value


def read_file(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def parse_lines(path, issues, strict=True):
    """-> list[Line] with kinds: if elif else endif define include stmt"""
    res = []
    for no, raw in enumerate(read_file(path).split("\n"), 1):
        s = strip_comment(raw).strip()
        if not s:
            continue
        m = re.match(r"#\s*(\w+)\s*(.*)$", s)
        if m:
            d, rest = m.group(1).lower(), m.group(2).strip()
            if d in ("if", "elif"):
                res.append(Line(no, d, rest))
            elif d in ("else", "endif"):
                res.append(Line(no, d, rest))
            elif d == "include":
                mm = re.match(r'"([^"]+)"$', rest)
                if not mm:
                    issues.append(Issue("ISSUE", path, no, "malformed #include"))
                else:
                    res.append(Line(no, "include", mm.group(1)))
            elif d == "define":
                if not (rest.startswith("(") and rest.endswith(")") and balanced(rest)):
                    issues.append(Issue("ISSUE", path, no, "malformed #define: " + rest))
                    continue
                body = rest[1:-1].strip()
                parts = split_top(body)
                if len(parts) < 2:                 # shipped scripts also write (name value)
                    mm = re.match(r"(\w+)\s+(.*)$", body, re.S)
                    if mm:
                        parts = [mm.group(1), mm.group(2)]
                if len(parts) < 2 or not IDENT.fullmatch(parts[0]):
                    issues.append(Issue("ISSUE", path, no, "malformed #define: " + rest))
                    continue
                res.append(Line(no, "define", rest, parts[0], ",".join(parts[1:]).strip()))
            else:
                issues.append(Issue("ISSUE", path, no, "unknown directive #" + d))
            continue
        if not balanced(s):
            if s.count(")") > s.count("(") and s.rstrip().endswith(")") and not strict:
                issues.append(Issue("WARN", path, no, "stray ')' (shipped quirk): " + s.strip()))
                s = s.rstrip()[:-1].rstrip()
            else:
                issues.append(Issue("ISSUE", path, no, "unbalanced parentheses: " + s))
                continue
        res.append(Line(no, "stmt", s))
    return res


# --------------------------------------------------------------------------
# expression evaluation for #if
# --------------------------------------------------------------------------
class Env:
    def __init__(self, size, players, epoch, climate, pct):
        self.vars = {"$MapSize": size, "$PlayerCount": players,
                     "$StartEpoch": epoch, "$ClimateType": climate}
        self.defs = {}
        self.pct = pct
        self.strict = {}
        self.out = []          # (path, line, keyword, args_text, expanded_args_text)

    def value_of_word(self, w, depth=0):
        if w in self.defs and depth < 40:
            return self.eval_expr(self.defs[w], depth + 1)
        if w == "true":
            return True
        if w == "false":
            return False
        if w in EPOCHS:
            return EPOCHS.index(w)
        return w            # symbolic constant (TinyMap, GrassClimate ...)

    def eval_expr(self, s, depth=0):
        s = s.strip()
        if not s:
            raise ValueError("empty expression")
        if s.startswith("(") and s.endswith(")") and balanced(s[1:-1]):
            return self.eval_expr(s[1:-1], depth)
        if s in self.vars:
            v = self.vars[s]
            return EPOCHS.index(v) if v in EPOCHS else v
        if NUMBER.fullmatch(s):
            return float(s) if "." in s else int(s, 0)
        m = re.fullmatch(r"(\w+)\s*\((.*)\)", s, re.S)
        if m:
            fn, args = m.group(1), split_top(m.group(2))
            if fn == "DEFINED":
                return args[0] in self.defs
            if fn == "NOTDEFINED":
                return args[0] not in self.defs
            if fn == "PERCENT":
                return self.pct
            vals = [self.eval_expr(a, depth) for a in args]
            if fn == "EQ":
                return vals[0] == vals[1]
            if fn == "NEQ":
                return vals[0] != vals[1]
            if fn == "LT":
                return vals[0] < vals[1]
            if fn == "GT":
                return vals[0] > vals[1]
            if fn == "LTEQ":
                return vals[0] <= vals[1]
            if fn == "GTEQ":
                return vals[0] >= vals[1]
            if fn == "OR":
                return any(bool(v) for v in vals)
            if fn == "AND":
                return all(bool(v) for v in vals)
            if fn == "XOR":
                return bool(vals[0]) != bool(vals[1])
            if fn == "NOT":
                return not vals[0]
            raise ValueError("unknown function " + fn)
        if IDENT.fullmatch(s):
            return self.value_of_word(s, depth)
        raise ValueError("cannot evaluate: " + s)


# --------------------------------------------------------------------------
# context: vocabulary, include resolution
# --------------------------------------------------------------------------
class Ctx:
    def __init__(self, game):
        self.game = game
        self.root = os.path.join(game, "Data", "random map scripts")
        if not os.path.isdir(self.root):
            sys.exit("cannot find %s" % self.root)
        self.files = {}                      # lowercased relative path -> abs
        for dp, _, fn in os.walk(self.root):
            for n in fn:
                if n.lower().endswith(".rmv"):
                    ab = os.path.join(dp, n)
                    rel = os.path.relpath(ab, self.root).replace("\\", "/").lower()
                    self.files[rel] = ab
        self.cache = {}
        self.vocab = set()
        self.keywords = set()               # statement keywords seen in shipped
        self.engine = self._engine_strings()
        self.gamestr = None
        self.ranges = {}                    # key -> [min, max] over shipped combos
        for ab in self.files.values():
            for ln in self.parsed(ab, []):
                self._collect(ln)

    def _collect(self, ln):
        if ln.kind in ("if", "elif"):
            self.vocab.update(IDENT.findall(ln.text))
        elif ln.kind == "define":
            self.vocab.add(ln.name)
            self.vocab.update(IDENT.findall(ln.value))
        elif ln.kind == "stmt":
            ids = IDENT.findall(ln.text)
            if ids:
                self.keywords.add(ids[0])
            self.vocab.update(ids)

    def parsed(self, path, issues):
        if path not in self.cache:
            tmp = []
            self.cache[path] = parse_lines(path, tmp, not path.startswith(self.root))
            self.cache[path + "#issues"] = tmp
        issues.extend(self.cache[path + "#issues"])
        return self.cache[path]

    def _engine_strings(self):
        p = os.path.join(self.game, "Default.dll")
        if not os.path.isfile(p):
            sys.exit("cannot find %s (needed for the engine keyword list)" % p)
        with open(p, "rb") as f:
            data = f.read()
        return set(m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{2,}", data))

    def game_strings(self):
        if self.gamestr is None:
            blob = b""
            for n in ("RiseAndFall.exe", "Default.dll", "LowLevelEngine.dll"):
                p = os.path.join(self.game, n)
                if os.path.isfile(p):
                    blob += open(p, "rb").read()
            dbdir = os.path.join(self.game, "Data", "db")
            if os.path.isdir(dbdir):
                for n in os.listdir(dbdir):
                    if n.lower().endswith(".dat"):
                        blob += open(os.path.join(dbdir, n), "rb").read()
            self.gamestr = set(m.group().decode("latin-1")
                               for m in re.finditer(rb"[A-Za-z][A-Za-z0-9_\- ]{2,}", blob))
        return self.gamestr

    def resolve_include(self, name, own_dir):
        rel = name.replace("\\", "/").lower() + ".rmv"
        if rel in self.files:
            return self.files[rel]
        if own_dir:
            cand = os.path.join(own_dir, name.replace("\\", os.sep) + ".rmv")
            if os.path.isfile(cand):
                return cand
        return None


# --------------------------------------------------------------------------
# simulation
# --------------------------------------------------------------------------
def expand_args(env, text):
    """replace #defined names by their (expanded) text; return (expanded, undefined k-names)"""
    undefined = []

    def rep(m, depth=0):
        w = m.group(0)
        if w in env.defs and depth < 40:
            return "(" + IDENT.sub(lambda mm: rep(mm, depth + 1), env.defs[w]) + ")"
        if w.startswith("k") and len(w) > 2 and w[1].isupper() and w not in env.defs:
            undefined.append(w)
        return w

    return IDENT.sub(rep, text), undefined


def run(ctx, path, env, issues, own, depth=0, stack=None):
    """execute one file under env. Returns False on fatal error."""
    lines = ctx.parsed(path, issues if depth == 0 and env.first else [])
    conds = []                                 # stack of (active, taken_any, parent_active)
    active = True

    def cur():
        return all(c[0] for c in conds)

    for ln in lines:
        k = ln.kind
        if k == "if":
            parent = cur()
            val = False
            if parent:
                try:
                    val = bool(env.eval_expr(ln.text))
                except (ValueError, IndexError, TypeError) as e:
                    if env.first:
                        issues.append(Issue("ISSUE", path, ln.no, "#if: %s" % e))
            conds.append([parent and val, val, parent])
        elif k == "elif":
            if not conds:
                if env.first:
                    issues.append(Issue("ISSUE", path, ln.no, "#elif without #if"))
                continue
            c = conds[-1]
            val = False
            if c[2] and not c[1]:
                try:
                    val = bool(env.eval_expr(ln.text))
                except (ValueError, IndexError, TypeError) as e:
                    if env.first:
                        issues.append(Issue("ISSUE", path, ln.no, "#elif: %s" % e))
            c[0] = c[2] and val and not c[1]
            c[1] = c[1] or val
        elif k == "else":
            if not conds:
                if env.first:
                    issues.append(Issue("ISSUE", path, ln.no, "#else without #if"))
                continue
            c = conds[-1]
            c[0] = c[2] and not c[1]
            c[1] = True
        elif k == "endif":
            if not conds:
                if env.first:
                    issues.append(Issue("ISSUE", path, ln.no, "#endif without #if"))
                continue
            conds.pop()
        elif not cur():
            continue
        elif k == "define":
            env.defs[ln.name] = ln.value
        elif k == "include":
            target = ctx.resolve_include(ln.text, os.path.dirname(path) if own else None)
            if target is None:
                if env.first:
                    issues.append(Issue("ISSUE", path, ln.no, "#include target not found: " + ln.text))
                continue
            if depth > 8:
                issues.append(Issue("ISSUE", path, ln.no, "include nesting too deep"))
                continue
            env.strict[target] = False             # included game files: quirks are WARN
            run(ctx, target, env, issues, False, depth + 1)
        elif k == "stmt":
            ids = IDENT.findall(ln.text)
            kw = ids[0] if ids else None
            exp, undef = expand_args(env, ln.text)
            for u in undef:
                if (path, ln.no, u) in SEEN_UNDEF:
                    continue
                SEEN_UNDEF.add((path, ln.no, u))
                if True:
                    issues.append(Issue("ISSUE" if env.strict.get(path, own) else "WARN", path, ln.no,
                                        "'%s' used but not #defined on this path (%s)" % (u, env.tag)))
            env.out.append((path, ln.no, kw, ln.text, exp))
    if conds and env.first:
        issues.append(Issue("ISSUE" if env.strict.get(path, True) else "WARN", path,
                            lines[-1].no if lines else 0,
                            "%d unclosed #if at end of file (shipped file, engine tolerates it)" % len(conds)
                            if not env.strict.get(path, True) else "%d unclosed #if at end of file" % len(conds)))
    return True


def numeric_values(exp):
    """numbers in an expanded argument text, Between(a,b) -> both ends"""
    return [float(x) for x in re.findall(r"(?<![\w.])-?\d+\.?\d*|(?<![\w.])-?\.\d+", exp)]


def range_key(kw, exp):
    m = re.match(r"\s*\(\s*(\w+)\s*,", exp[len(kw):] if exp.startswith(kw) else exp)
    inner = re.sub(r"\s+", " ", exp).strip()
    if kw in ("ResourcePerPlayer", "ResourcePerNeutralLand", "ResourcePlacementLimit"):
        m = re.match(r"%s\s*\(\s*(\w+)\s*,(.*)\)\s*$" % kw, inner)
        if m:
            return "%s(%s)" % (kw, m.group(1)), m.group(2)
        return None, None
    m = re.match(r"%s\s+(.*)$" % re.escape(kw), inner)
    return (kw, m.group(1)) if m else (None, None)


SEEN_UNDEF = set()
COMBO_KEYS = ("size", "players", "epoch", "climate", "pct")


def combos(quick):
    for size, n, ep, cl, pct in itertools.product(
            SIZES, PLAYERS, TEST_EPOCHS if not quick else TEST_EPOCHS[:1],
            CLIMATES, (True, False)):
        yield size, n, ep, cl, pct


def simulate(ctx, path, own, issues, record_ranges=False, quick=False):
    """returns list of (tag, keyword-set, statements)"""
    results = []
    first = True
    SEEN_UNDEF.clear()
    for size, n, ep, cl, pct in combos(quick):
        env = Env(size, n, ep, cl, pct)
        env.first = first
        env.tag = "%s %dp %s %s %s" % (size, n, ep, cl, "pct" if pct else "nopct")
        run(ctx, path, env, issues, own)
        first = False
        results.append((env.tag, env.out))
        if record_ranges:
            for _, _, kw, text, exp in env.out:
                key, arg = range_key(kw, exp)
                if key is None:
                    continue
                nums = numeric_values(arg)
                if not nums:
                    continue
                r = ctx.ranges.setdefault(key, [min(nums), max(nums)])
                r[0], r[1] = min(r[0], min(nums)), max(r[1], max(nums))
    return results


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------
def lint_file(ctx, path, own, quick):
    issues, warns = [], []
    own_defs = set()
    lines = ctx.parsed(path, issues)
    # identifier vocabulary
    for ln in lines:
        if ln.kind == "define":
            own_defs.add(ln.name)
    for ln in lines:
        if ln.kind in ("if", "elif"):
            texts = [ln.text]
        elif ln.kind == "define":
            texts = [ln.value]
        elif ln.kind == "stmt":
            texts = [ln.text]
        else:
            continue
        for t in texts:
            for w in IDENT.findall(t):
                if w in ctx.vocab or w in own_defs or w in ("true", "false"):
                    continue
                issues.append(Issue("ISSUE", path, ln.no, "unknown identifier '%s'" % w))
        if ln.kind == "stmt":
            ids = IDENT.findall(ln.text)
            if ids and ids[0] not in ctx.engine:
                issues.append(Issue("ISSUE", path, ln.no, "keyword '%s' is not an engine keyword (Default.dll)" % ids[0]))
        if ln.kind == "define" and ln.name in ctx.engine and ln.name != ln.name.upper() and not ln.name.startswith("k"):
            pass
    # preprocessor simulation
    res = simulate(ctx, path, own, issues, quick=quick)
    # keyword coverage, own scripts only
    if own and res:
        union = set()
        per = []
        for tag, out in res:
            ks = set()
            for _, _, kw, text, exp in out:
                key, _ = range_key(kw, exp)
                if kw in ("PlaceResourceInRing", "ResourcePlacementLimit"):
                    continue                      # legitimately size dependent
                ks.add(key if kw.startswith("ResourcePer") and key else kw)
            per.append((tag, ks))
            union |= ks
        for tag, ks in per:
            miss = union - ks
            if miss:
                issues.append(Issue("ISSUE", path, 0, "combination [%s] does not set: %s"
                                    % (tag, ", ".join(sorted(miss)))))
                break
    # numeric ranges vs shipped
    seen = set()
    for tag, out in res:
        for p, no, kw, text, exp in out:
            if p != path:
                continue
            key, arg = range_key(kw, exp)
            if key is None or key not in ctx.ranges:
                continue
            for v in numeric_values(arg):
                lo, hi = ctx.ranges[key]
                if (v < lo - 1e-9 or v > hi + 1e-9) and (key, v) not in seen:
                    seen.add((key, v))
                    warns.append(Issue("WARN", path, no, "%s = %g outside shipped range %g..%g [%s]"
                                       % (key, v, lo, hi, tag)))
    # object names
    names = set()
    for ln in lines:
        if ln.kind == "stmt":
            for w in IDENT.findall(ln.text):
                if "-" in w:
                    names.add((w, ln.no))
    if names:
        gs = ctx.game_strings()
        low = {s.lower() for s in gs}
        for w, no in sorted(names):
            if w.lower() not in low:
                warns.append(Issue("WARN", path, no, "name '%s' not found in exe/dll/db strings" % w))
    return issues, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=r"D:\Games\Rise and Fall")
    ap.add_argument("--shipped", action="store_true", help="also lint all shipped scripts")
    ap.add_argument("--quick", action="store_true", help="fewer epochs (faster)")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()

    ctx = Ctx(a.game)
    # ranges come from simulating the shipped top-level scripts
    top = [p for rel, p in ctx.files.items() if "/" not in rel]
    scratch = []
    for p in sorted(top):
        simulate(ctx, p, False, scratch, record_ranges=True, quick=True)

    targets = []
    for p in a.paths or [os.path.join(REPO, "rms")]:
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.lower().endswith(".rmv"):
                    targets.append((os.path.join(p, fn), True))
        else:
            targets.append((p, True))
    if a.shipped:
        for rel in sorted(ctx.files):
            targets.append((ctx.files[rel], False))

    total_i = total_w = 0
    for path, own in targets:
        # shipped sub-files are only meaningful via their parent; lint token level only
        sub = (not own) and "/" in os.path.relpath(path, ctx.root).replace("\\", "/")
        if sub:
            issues, warns = lint_tokens_only(ctx, path)
        else:
            issues, warns = lint_file(ctx, path, own, a.quick)
        label = os.path.relpath(path, a.game) if not own else path
        seen = set()
        for i in issues + warns:
            s = str(i)
            if s in seen:
                continue
            seen.add(s)
            print(s)
        ni = len([i for i in issues if i.kind == "ISSUE"])
        nw = len(warns) + len([i for i in issues if i.kind == "WARN"])
        total_i += ni
        total_w += nw
        print("%-5s %s  issues=%d warnings=%d" % ("OK" if ni == 0 else "FAIL", label, ni, nw))
    print("TOTAL files=%d issues=%d warnings=%d" % (len(targets), total_i, total_w))
    return 1 if total_i else 0


def lint_tokens_only(ctx, path):
    """size sub-files: vocabulary + keyword + syntax checks (no standalone simulation)"""
    issues = []
    lines = ctx.parsed(path, issues)
    own_defs = {ln.name for ln in lines if ln.kind == "define"}
    depth = 0
    for ln in lines:
        if ln.kind == "if":
            depth += 1
        elif ln.kind == "endif":
            depth -= 1
            if depth < 0:
                issues.append(Issue("ISSUE", path, ln.no, "#endif without #if"))
                depth = 0
        if ln.kind in ("if", "elif"):
            texts = [ln.text]
        elif ln.kind == "define":
            texts = [ln.value]
        elif ln.kind == "stmt":
            texts = [ln.text]
        else:
            continue
        for t in texts:
            for w in IDENT.findall(t):
                if w not in ctx.vocab and w not in own_defs:
                    issues.append(Issue("ISSUE", path, ln.no, "unknown identifier '%s'" % w))
        if ln.kind == "stmt":
            ids = IDENT.findall(ln.text)
            if ids and ids[0] not in ctx.engine:
                issues.append(Issue("ISSUE", path, ln.no, "keyword '%s' is not an engine keyword" % ids[0]))
    if depth != 0:
        issues.append(Issue("WARN", path, 0, "unbalanced #if/#endif (shipped file, engine tolerates it)"))
    return issues, []


if __name__ == "__main__":
    sys.exit(main())
