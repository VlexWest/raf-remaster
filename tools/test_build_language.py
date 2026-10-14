"""Offline tests for build_language.py: no game files needed (synthetic data). Run: python tools/test_build_language.py"""
import os, sys, struct, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_language as b

def test_tokens():
    t = b.tokens(r'/r0/g255/b0(%s) /fbRevenge/fd /type /tech /t[textures\UI_xYellowBulletT]/co6/hk0[Foo] #1200 #PA0697/1')
    assert t == ['/r0', '/g255', '/b0', '%s', '/fb', '/fd', '/type', '/tech', '/t', r'[textures\UI_xYellowBulletT]', '/co6', '/hk0', '#1200', '#PA0697', '/1'], t

def test_validate():
    src = '/fbПривет/fd %s\nМир '
    assert b.validate(src, '/fbHello/fd %s\nWorld ') == []
    assert b.validate(src, '/fbHello %s\nWorld ')                     # token missing
    assert b.validate(src, '/fbHello/fd %s World ')                   # newline missing
    assert b.validate(src, '/fbHello/fd %s\nWorld')                   # trailing space
    assert b.validate(src, '/fbHello/fd %s\nW\u00f6rld ')              # non-ascii
    assert b.validate(src, '/fbHello/fd %s\nA/B ')                    # stray slash
    assert b.validate('/hk0[Окно]/fd', '/hk0[Nope]/fd', {'Toggle Objectives'})
    assert b.validate('/hk0[Окно]/fd', '/hk0[Toggle Objectives]/fd', {'Toggle Objectives'}) == []

def test_lcl_roundtrip():
    txt = '{Version_0}\r\n\r\n{1_Player Name:Греция}\r\n\r\n{4_ObjectivesName-0}\r\n/fbТекст\r\nвторая\r\n\r\n{87_0_Effect:02 CIN}\r\nHello\r\n'
    pre, secs = b.parse_lcl(txt)
    assert b.render_lcl(pre, secs) == txt
    pre, secs, us = b.lcl_units('x.lcl', txt)
    assert [u[2][1] for u in us] == ['hdr', 'body'], us
    assert us[1][1] == '/fbТекст\nвторая'

def test_rsrc_roundtrip():
    tree = {6: {1: {1033: (b'\x00' * 32, 0)}, 7: {1033: (b'abcd', 1252)}}, 5: {'IDD_X': {1033: (b'12345', 1252)}}, 255: {1: {1033: (b'\t\x04\x00\x00', 0)}}}
    blob = b.build_rsrc(tree, 0x1000)
    back = b.parse_rsrc(blob + b'\0' * 0, 0x1000)
    assert back == tree, back

def test_stringtable():
    strs = ['a', '', 'b\u0436'] + [''] * 13
    assert b.parse_stringtable_block(b.pack_stringtable_block(strs)) == strs

if __name__ == '__main__':
    for n, f in list(globals().items()):
        if n.startswith('test_'): f(); print('ok', n)
