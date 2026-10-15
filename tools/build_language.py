#!/usr/bin/env python3
"""Build a language pack for Rise and Fall (Russian install) from our own translation catalog.

    python tools/build_language.py <game_dir> <overlay_dir> [--lang en] [--catalog work/lang/en.json]
                                   [--dump-source FILE] [--update-catalog] [--check-only]

What it does (offline, game dir is only read):
  1. extracts every translatable string: STRINGTABLE resources of Language.dll / Language2.dll
     (UTF-16, only strings that contain Cyrillic) and the campaign text Data/scenarios/*.lcl
     (cp1251, CRLF; section bodies and Player Name / ScenarioName labels that contain Cyrillic);
  2. looks each one up in the catalog (key = source location + sha1[:8] of the Russian text);
  3. validates the English (format codes, %-placeholders, newline count, ASCII, hotkey names);
  4. writes patched copies into <overlay_dir>: Language.dll, Language2.dll, Data/scenarios/*.lcl
     (same file names as the install, so the overlay is a drop-in).
The catalog holds only English text plus keys. The Russian source never goes into the repo;
--dump-source writes it to a file you pick (keep it outside git) for translators.
"""
import argparse, hashlib, json, os, re, struct, sys, glob

try:
    import pefile
except ImportError:  # repo-local copy
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'work', 'tools', 'py'))
    import pefile

CYR = re.compile('[Ѐ-ӿ]')
RT_STRING = 6
DLLS = ['Language.dll', 'Language2.dll']

# ---------------------------------------------------------------- tokens ---
# Markup the engine interprets inside strings. A translation must contain exactly the same
# tokens in the same order as the source.
_WORDS = ['ac', 'action', 'al', 'amount', 'ar', 'area', 'bk', 'calamity', 'fb', 'fd', 'fe', 'fc', 'fn', 'fish', 'fu',
          'hotkey', 'mana', 'mine', 'morale', 'mouse', 'np', 'pop', 'prereq', 'res', 'spectech', 'specunit',
          'standdown', 'stat', 'string', 'tech', 'tilemouse', 'type', 'unit', 't', 'f']
# longest first so "/type" is not read as "/t" + "ype"; 2-letter codes may be glued to text ("/fbRevenge")
TOKEN_RE = re.compile(
    r'%[-+#0-9.]*(?:l?[sdiuxXfcgeE])'                       # printf
    r'|\[textures\\[^\]]*\]'                      # bullet icons
    r'|/(?:r|g|b|co|cw|fp|fs|hk|bk)\d+'            # colour / column / font size / hotkey
    r'|/(?:' + '|'.join(sorted(_WORDS, key=lambda w: -len(w))) + r')'
    r'|#PA\d+|#OA\d+|#OC\d+|#\d{3,4}|/\d+|/(?=#)'
    r'|\{%[a-z]\}')
HK_RE = re.compile(r'/hk\d\[([^\]]*)\]')


def sha(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:8]


# the Russian build has three tokens spelled in Russian ("/боец /рес /нас" = "/unit /res /pop"); the English one is the real token
_RU_TOK = {'/боец': '/unit', '/рес': '/res', '/нас': '/pop'}
_RU_TOK_RE = re.compile('|'.join(map(re.escape, _RU_TOK)))


def tokens(s):
    s = _RU_TOK_RE.sub(lambda m: _RU_TOK[m.group()], s)
    return TOKEN_RE.findall(s)


# ------------------------------------------------------- resource reading ---
def _u16(d, o): return struct.unpack_from('<H', d, o)[0]
def _u32(d, o): return struct.unpack_from('<I', d, o)[0]


def parse_rsrc(data, rva_base):
    """Parse a resource section blob. Returns tree: {type: {name: {lang: (bytes, codepage)}}}.
    type/name/lang are int ids or str names."""
    def entry_key(raw):
        if raw & 0x80000000:
            o = raw & 0x7fffffff
            n = _u16(data, o)
            return data[o + 2:o + 2 + 2 * n].decode('utf-16le')
        return raw

    def walk_dir(off):
        named, ids = _u16(data, off + 12), _u16(data, off + 14)
        out = []
        for i in range(named + ids):
            nm, to = struct.unpack_from('<II', data, off + 16 + 8 * i)
            out.append((entry_key(nm), to))
        return out

    tree = {}
    for tk, to in walk_dir(0):
        assert to & 0x80000000
        for nk, to2 in walk_dir(to & 0x7fffffff):
            assert to2 & 0x80000000
            for lk, to3 in walk_dir(to2 & 0x7fffffff):
                assert not to3 & 0x80000000
                rva, size, cp, _ = struct.unpack_from('<IIII', data, to3)
                blob = data[rva - rva_base:rva - rva_base + size]
                tree.setdefault(tk, {}).setdefault(nk, {})[lk] = (bytes(blob), cp)
    return tree


def build_rsrc(tree, rva_base):
    """Serialise a tree back into a resource section blob (standard layout)."""
    def key_sort(keys):
        names = sorted([k for k in keys if isinstance(k, str)], key=lambda s: s.upper())
        ids = sorted([k for k in keys if isinstance(k, int)])
        return names, ids

    # plan directory sizes
    dirs = []  # (level, path, entries)
    root_keys = tree
    dir_off = {}
    pos = 0

    def dsize(n): return 16 + 8 * n
    # order: root, all type dirs, all name dirs (per type), all lang dirs
    layout = [()]
    for t in sorted(tree, key=lambda k: (isinstance(k, int), k if isinstance(k, int) else k.upper())):
        layout.append((t,))
    for t in sorted(tree, key=lambda k: (isinstance(k, int), k if isinstance(k, int) else k.upper())):
        for n in sorted(tree[t], key=lambda k: (isinstance(k, int), k if isinstance(k, int) else k.upper())):
            layout.append((t, n))
    def children(path):
        node = tree
        for p in path: node = node[p]
        return node
    for path in layout:
        dir_off[path] = pos
        pos += dsize(len(children(path)))
    # data entries
    leaf_paths = []
    for t in tree:
        for n in tree[t]:
            for l in tree[t][n]:
                leaf_paths.append((t, n, l))
    leaf_paths.sort(key=lambda p: [(isinstance(k, int), k if isinstance(k, int) else k.upper()) for k in p])
    de_off = {}
    for p in leaf_paths:
        de_off[p] = pos; pos += 16
    # name strings
    name_off = {}
    names = set()
    for p in layout:
        for k in children(p):
            if isinstance(k, str): names.add(k)
    for s in sorted(names):
        name_off[s] = pos
        pos += 2 + 2 * len(s)
    pos = (pos + 3) & ~3
    data_off = {}
    for p in leaf_paths:
        data_off[p] = pos
        blob = tree[p[0]][p[1]][p[2]][0]
        pos += (len(blob) + 3) & ~3
    out = bytearray(pos)

    def put_dir(path):
        o = dir_off[path]
        ch = children(path)
        nm = sorted([k for k in ch if isinstance(k, str)], key=lambda s: s.upper())
        ids = sorted([k for k in ch if isinstance(k, int)])
        struct.pack_into('<IIHHHH', out, o, 0, 0, 4, 0, len(nm), len(ids))
        for i, k in enumerate(nm + ids):
            if isinstance(k, str): kv = 0x80000000 | name_off[k]
            else: kv = k
            sub = path + (k,)
            if len(sub) < 3: tv = 0x80000000 | dir_off[sub]
            else: tv = de_off[sub]
            struct.pack_into('<II', out, o + 16 + 8 * i, kv, tv)
    for path in layout:
        put_dir(path)
    for p in leaf_paths:
        blob, cp = tree[p[0]][p[1]][p[2]]
        struct.pack_into('<IIII', out, de_off[p], rva_base + data_off[p], len(blob), cp, 0)
        out[data_off[p]:data_off[p] + len(blob)] = blob
    for s, o in name_off.items():
        struct.pack_into('<H', out, o, len(s))
        out[o + 2:o + 2 + 2 * len(s)] = s.encode('utf-16le')
    return bytes(out)


def parse_stringtable_block(blob):
    p, out = 0, []
    for _ in range(16):
        n = _u16(blob, p); p += 2
        out.append(blob[p:p + 2 * n].decode('utf-16le')); p += 2 * n
    return out


def pack_stringtable_block(strs):
    b = bytearray()
    for s in strs:
        b += struct.pack('<H', len(s)) + s.encode('utf-16le')
    return bytes(b)


class Dll:
    def __init__(self, path):
        self.path = path
        self.raw = open(path, 'rb').read()
        pe = pefile.PE(data=self.raw, fast_load=True)
        self.pe = pe
        self.rs = next(s for s in pe.sections if s.Name.rstrip(b'\0') == b'.rsrc')
        d = self.raw[self.rs.PointerToRawData:self.rs.PointerToRawData + self.rs.Misc_VirtualSize]
        self.tree = parse_rsrc(d, self.rs.VirtualAddress)
        self.strings = {}  # id -> text (non-empty)
        for blk, langs in self.tree.get(RT_STRING, {}).items():
            for lang, (blob, cp) in langs.items():
                for i, s in enumerate(parse_stringtable_block(blob)):
                    if s: self.strings[(blk - 1) * 16 + i] = s

    def write(self, out_path, repl):
        """repl: {string id: new text}. Rebuild the resource section and fix the PE headers."""
        tree = json_copy_tree(self.tree)
        # ids in string blocks the DLL does not have yet (scenario map texts 27040.., 640..) get
        # a new empty block in the language/code page of the existing ones; without new ids the
        # output is unchanged
        missing = sorted({sid // 16 + 1 for sid in repl} - set(tree[RT_STRING]))
        if missing:
            lang0, (_, cp0) = next(iter(tree[RT_STRING][min(tree[RT_STRING])].items()))
            for blk in missing:
                tree[RT_STRING][blk] = {lang0: (pack_stringtable_block([''] * 16), cp0)}
        for blk, langs in tree[RT_STRING].items():
            for lang, (blob, cp) in list(langs.items()):
                strs = parse_stringtable_block(blob)
                ch = False
                for i in range(16):
                    sid = (blk - 1) * 16 + i
                    if sid in repl: strs[i] = repl[sid]; ch = True
                if ch: langs[lang] = (pack_stringtable_block(strs), cp)
        pe = self.pe
        opt = pe.OPTIONAL_HEADER
        fa, sa = opt.FileAlignment, opt.SectionAlignment
        al = lambda v, a: (v + a - 1) // a * a
        rs_rva = self.rs.VirtualAddress
        blob = build_rsrc(tree, rs_rva)
        # sections after .rsrc (here only .reloc) move behind it
        secs = list(pe.sections)
        idx = secs.index(self.rs)
        head = bytearray(self.raw[:opt.SizeOfHeaders])
        raw_end = self.rs.PointerToRawData
        body = bytearray(blob + b'\0' * (al(len(blob), fa) - len(blob)))
        new_va = rs_rva + al(len(blob), sa)
        so = self.rs.get_file_offset()
        struct.pack_into('<I', head, so + 8, len(blob))          # VirtualSize
        struct.pack_into('<I', head, so + 16, len(body))         # SizeOfRawData
        va_cursor, raw_cursor = new_va, raw_end + len(body)
        tail = bytearray()
        shift = {}
        for s in secs[idx + 1:]:
            data = self.raw[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
            o = s.get_file_offset()
            shift[s.VirtualAddress] = va_cursor
            struct.pack_into('<I', head, o + 12, va_cursor)
            struct.pack_into('<I', head, o + 20, raw_cursor)
            tail += data
            va_cursor += al(s.Misc_VirtualSize, sa); raw_cursor += s.SizeOfRawData
        # optional header + data directories
        oo = opt.get_file_offset()
        struct.pack_into('<I', head, oo + 56, va_cursor)          # SizeOfImage
        dd_off = oo + 96
        for i, dd in enumerate(opt.DATA_DIRECTORY):
            eo = dd_off + 8 * i
            if i == 2:
                struct.pack_into('<II', head, eo, rs_rva, len(blob))
            elif dd.VirtualAddress in shift:
                struct.pack_into('<I', head, eo, shift[dd.VirtualAddress])
        # SizeOfInitializedData: sum of raw sizes of initialised-data sections
        init = al(len(blob), fa) + sum(s.SizeOfRawData for s in secs[idx + 1:])
        struct.pack_into('<I', head, oo + 8, init)
        # headers are SizeOfHeaders long, .rsrc starts at PointerToRawData == SizeOfHeaders here
        assert raw_end == opt.SizeOfHeaders
        out = bytes(head) + bytes(body) + bytes(tail)   # CheckSum field stays as in the original (0)
        with open(out_path, 'wb') as f: f.write(out)


def json_copy_tree(t):
    return {a: {b: {c: v for c, v in cc.items()} for b, cc in bb.items()} for a, bb in t.items()}


# ------------------------------------------------------------------ lcl ---
SEC_RE = re.compile(r'^\{([^}\r\n]*)\}', re.M)


def parse_lcl(text):
    """-> list of sections {hdr, lead, core, trail}; text before the first header is 'pre'."""
    ms = list(SEC_RE.finditer(text))
    pre = text[:ms[0].start()] if ms else text
    secs = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = text[m.end():end]
        mm = re.match(r'(\r?\n)?(.*?)((?:\r?\n)*)\Z', body, re.S)
        secs.append({'hdr': m.group(1), 'lead': mm.group(1) or '', 'core': mm.group(2), 'trail': mm.group(3)})
    return pre, secs


def render_lcl(pre, secs):
    return pre + ''.join('{%s}%s%s%s' % (s['hdr'], s['lead'], s['core'], s['trail']) for s in secs)


def lcl_units(fname, text):
    """Translatable units of one .lcl: label (text after ':' of Player Name/ScenarioName) and body."""
    pre, secs = parse_lcl(text)
    out = []
    for n, s in enumerate(secs):
        hdr = s['hdr']
        m = re.match(r'(\d+_(?:Player Name|ScenarioName))(.*)', hdr)
        if m and CYR.search(m.group(2)):
            lab = m.group(2)
            out.append(('lcl:%s:%d:hdr:%s' % (fname, n, sha(lab)), lab.lstrip(':'), (n, 'hdr', lab)))
        elif CYR.search(hdr):
            out.append(('lcl:%s:%d:hdr:%s' % (fname, n, sha(hdr)), hdr, (n, 'hdrfull', hdr)))
        if CYR.search(s['core']):
            src = s['core'].replace('\r\n', '\n')
            out.append(('lcl:%s:%d:body:%s' % (fname, n, sha(src)), src, (n, 'body', src)))
    return pre, secs, out


# --------------------------------------------------------------- catalog ---
def collect(game):
    """-> (units: [(key, russian, locator)], dlls{name: Dll}, lcls{fname: (pre, secs, text)})"""
    units, dlls, lcls = [], {}, {}
    for name in DLLS:
        d = Dll(os.path.join(game, name)); dlls[name] = d
        for sid, s in sorted(d.strings.items()):
            if CYR.search(s):
                units.append(('%s:%d:%s' % (name, sid, sha(s)), s, (name, sid)))
    for p in sorted(glob.glob(os.path.join(game, 'Data', 'scenarios', '*.lcl'))):
        fn = os.path.basename(p)
        text = open(p, 'rb').read().decode('cp1251')
        pre, secs, us = lcl_units(fn, text)
        lcls[fn] = (pre, secs)
        for k, s, loc in us:
            units.append((k, s, (fn,) + loc))
    return units, dlls, lcls


def hotkey_names(game):
    p = os.path.join(game, 'Data', 'db', 'dbuihotkey.dat')
    if not os.path.exists(p): return None
    d = open(p, 'rb').read()
    return set(m.group().decode('latin1') for m in re.finditer(rb'[A-Za-z][\x20-\x7e]{3,}', d))


NORM = {'…': '...', '–': '-', '—': ' - ', '“': '"', '”': '"', '‘': "'", '’': "'", ' ': ' '}


def normalise(s):
    for a, b in NORM.items(): s = s.replace(a, b)
    return s


def validate(src, en, hk=None, strict_nl=True):
    errs = []
    if not en.strip(): return ['empty']
    if tokens(src) != tokens(en): errs.append('tokens %r != %r' % (tokens(src), tokens(en)))
    if strict_nl and src.count('\n') != en.count('\n'): errs.append('newlines %d != %d' % (src.count('\n'), en.count('\n')))
    if src.count('\t') != en.count('\t'): errs.append('tab count differs')
    if CYR.search(en): errs.append('cyrillic left')
    if '/' in TOKEN_RE.sub('', en) and '/' not in TOKEN_RE.sub('', src): errs.append('stray "/" in text (use "or"/"-")')
    bad = sorted(set(c for c in en if ord(c) > 126 or (ord(c) < 32 and c not in '\n\t')))
    if bad: errs.append('non-ascii %r' % ''.join(bad))
    if hk is not None:
        for m in HK_RE.finditer(en):
            if m.group(1) not in hk: errs.append('hotkey name %r not in dbuihotkey' % m.group(1))
    if src[:len(src) - len(src.lstrip(' '))] != en[:len(en) - len(en.lstrip(' '))]: errs.append('leading spaces differ')
    if src[len(src.rstrip(' ')):] != en[len(en.rstrip(' ')):]: errs.append('trailing spaces differ')
    return errs


# ----------------------------------------------------------- verification ---
def verify_dll_loads(path, expect):
    """LoadLibraryEx(AS_DATAFILE) + LoadStringW on every id in expect. Windows only."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.LoadStringW.argtypes = [wintypes.HMODULE, wintypes.UINT, ctypes.c_wchar_p, ctypes.c_int]
    h = k.LoadLibraryExW(os.path.abspath(path), None, 0x2)  # LOAD_LIBRARY_AS_DATAFILE
    if not h: raise OSError('LoadLibraryEx failed %d' % ctypes.get_last_error())
    bad = 0
    buf = ctypes.create_unicode_buffer(4096)
    for sid, s in expect.items():
        n = u.LoadStringW(h, sid, buf, 4096)
        if n != len(s) or buf.value != s: bad += 1
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    k.FreeLibrary(h)
    return bad


# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_dir'); ap.add_argument('overlay_dir')
    ap.add_argument('--lang', default='en')
    ap.add_argument('--catalog', help='default work/lang/<lang>.json in the repo (not tracked in git)')
    ap.add_argument('--dump-source', help='write {key: russian} here for translators (keep outside git)')
    ap.add_argument('--update-catalog', action='store_true', help='add missing keys (empty value), drop stale ones')
    ap.add_argument('--check-only', action='store_true', help='validate, do not write the overlay')
    ap.add_argument('--allow-incomplete', action='store_true', help='leave untranslated strings Russian instead of failing')
    a = ap.parse_args()
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    cat_path = a.catalog or os.path.join(root, 'work', 'lang', a.lang + '.json')
    if not os.path.exists(cat_path) and not (a.update_catalog or a.dump_source):
        print('no translation catalog at %s; the language pack is not part of the repo, pass --catalog' % cat_path)
        return 1
    cat = json.load(open(cat_path, encoding='utf-8')) if os.path.exists(cat_path) else {'meta': {}, 'strings': {}}
    tr = cat['strings']
    units, dlls, lcls = collect(a.game_dir)
    print('extracted %d translatable units' % len(units))
    per = {}
    for k, s, loc in units: per[k.split(':')[0] if not k.startswith('lcl') else 'lcl'] = per.get(k.split(':')[0] if not k.startswith('lcl') else 'lcl', 0) + 1
    print('  by source:', per, '| all strings:', {n: len(d.strings) for n, d in dlls.items()})
    if a.dump_source:
        json.dump({k: s for k, s, _ in units}, open(a.dump_source, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print('wrote source dump', a.dump_source)
    keys = {k for k, _, _ in units}
    missing = [k for k in keys if not tr.get(k, '').strip()]
    stale = [k for k in tr if k not in keys]
    hk = hotkey_names(a.game_dir)
    errs = []
    for k, s, loc in units:
        en = tr.get(k)
        if not en: continue
        e = validate(s, normalise(en), hk)
        if e: errs.append((k, e))
    print('translated %d / %d, missing %d, stale catalog keys %d, validation errors %d' %
          (len(units) - len(missing), len(units), len(missing), len(stale), len(errs)))
    for k, e in errs[:40]: print('  ERR', k, e)
    if a.update_catalog:
        for k in missing: tr.setdefault(k, '')
        for k in stale: del tr[k]
        cat['meta'] = {'lang': a.lang, 'note': 'keys = source location + sha1[:8] of the Russian text; values = our English. No game text.',
                       'units': len(units)}
        cat['strings'] = dict(sorted(tr.items()))
        os.makedirs(os.path.dirname(cat_path), exist_ok=True)
        json.dump(cat, open(cat_path, 'w', encoding='utf-8'), ensure_ascii=True, indent=0)
        print('catalog written', cat_path)
    if errs or (missing and not a.allow_incomplete):
        if not (a.check_only or a.allow_incomplete):
            print('refusing to build (use --allow-incomplete to keep Russian for missing strings)'); return 1
    if a.check_only: return 0 if not errs else 1
    ok = {k: normalise(tr[k]) for k, _, _ in units if tr.get(k) and not any(k == e[0] for e in errs)}
    os.makedirs(a.overlay_dir, exist_ok=True)
    # DLLs
    for name, d in dlls.items():
        repl = {}
        for k, s, loc in units:
            if loc[0] == name and k in ok: repl[loc[1]] = ok[k]
        out = os.path.join(a.overlay_dir, name)
        d.write(out, repl)
        # verify
        d2 = Dll(out)
        want = dict(d.strings); want.update(repl)
        assert d2.strings == want, 'string table mismatch after write: ' + name
        assert set(d2.tree) == set(d.tree)
        for t in d.tree:
            if t != RT_STRING: assert d2.tree[t] == d.tree[t], 'non-string resource changed'
        bad = verify_dll_loads(out, want) if sys.platform == 'win32' else -1
        print('%s: %d strings replaced, size %d -> %d, LoadLibraryEx/LoadString mismatches: %s' %
              (name, len(repl), len(d.raw), os.path.getsize(out), bad))
        if bad: return 2
    # lcl
    sd = os.path.join(a.overlay_dir, 'Data', 'scenarios'); os.makedirs(sd, exist_ok=True)
    nl = 0
    for fn, (pre, secs) in lcls.items():
        secs = [dict(s) for s in secs]
        for k, s, loc in units:
            if loc[0] != fn or k not in ok: continue
            n, kind = loc[1], loc[2]
            en = ok[k]
            if kind == 'body': secs[n]['core'] = en.replace('\n', '\r\n')
            elif kind == 'hdr':
                m = re.match(r'(\d+_(?:Player Name|ScenarioName))(.*)', secs[n]['hdr'])
                lab = m.group(2); secs[n]['hdr'] = m.group(1) + (':' if lab.startswith(':') else '') + en
            else: secs[n]['hdr'] = en
            nl += 1
        txt = render_lcl(pre, secs)
        open(os.path.join(sd, fn), 'wb').write(txt.encode('cp1251'))
    print('lcl: %d files, %d units written to %s' % (len(lcls), nl, sd))
    return 0


if __name__ == '__main__':
    sys.exit(main())
