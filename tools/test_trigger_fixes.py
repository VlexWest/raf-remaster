"""Offline tests for the trigger-signed-compare and trigger-resource-floor patches
(raf_patch.TRIGGER_SIGNED_COMPARE, raf_patch.TRIGGER_RESOURCE_FLOOR, docs/scenario-format.md
section 3.7). Reads the base install only; writes exe copies into a temp folder; never touches the
registry or a running game.

    python tools/test_trigger_fixes.py [stock_game_dir]   (default D:/Games/Rise and Fall)
    python tools/test_trigger_fixes.py --print            print the generated patch tuples
    python tools/test_trigger_fixes.py -v                 also list the cave disassembly

trigger-signed-compare: the PlayerHasResource evaluator FUN_008aabc0 (vtable 0xc6eb10) compares the
player's value with the amount through FUN_008a9c90, which uses unsigned setb/setbe/setae/seta. A
negative gold/wood balance (ChangeResourceLevel subtract has no floor) is a huge unsigned number and
passes "gold >= 900". The three calls of FUN_008a9c90 (all in FUN_008aabc0) go to a cave that keeps the
stock helper for resource ids above 6 (pop cap, Var0..Var9 = 11..20, statistics: the campaign medal
score Var4 relies on the unsigned compare, its "Var4 < 0" condition is written as "Var4 > 100000") and
compares signed (setl/setle/sete/setge/setg) for 0 random, 1 total, 2 recruitment points, 3 gold,
4 wood, 6 glory.

trigger-resource-floor: ChangeResourceLevel FUN_00bfa1e0 writes old + (-amount) for op 2 (subtract)
through FUN_007a7920 without a floor. The four `mov reg,[player+x]; add reg,edi` of resources 2, 3,
4, 6 call a cave each that adds and, for op 2 (ebx) with a negative result, writes 0. Set / add and
every other resource (pop cap, variables) stay stock.

1. static: stock bytes, whole instructions, no branch into a hook tail, single caller / jump table,
   caves zero / unreferenced / clear of the other caves and the stray values, generated == raf_patch
2. emulation (unicorn): the compare cave against a Python model (signed and stock path), the floor
   caves alone, and the whole FUN_00bfa1e0 with a FUN_007a7920 stub
3. apply / re-apply / revert byte-exact on an exe copy together with the other exe patches; foreign
   bytes refused; feature registration, installer text, fingerprint marks
"""
import contextlib
import hashlib
import io
import struct
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "work" / "tools" / "py"))  # capstone, unicorn
import capstone  # noqa: E402
from test_target_priority import Asm  # noqa: E402

BASE = 0x400000
EXE = "RiseAndFall.exe"
# ---------------------------------------------------------------- addresses (v1.15)
HELPER = 0x8A9C90                   # FUN_008a9c90(value, op, amount), ret 0xc
HELPER_SETCC = {0x8A9CAA: "0f92c0", 0x8A9CB8: "0f96c0", 0x8A9CC6: "0f94c0", 0x8A9CD4: "0f93c0",
                0x8A9CE2: "0f97c0"}  # setb / setbe / sete / setae / seta
EVAL = (0x8AABC0, 0x8AAD70)         # FUN_008aabc0, PlayerHasResource evaluate
EVAL_VTABLE = 0xC6EB10
CALLS = [0x8AACA5, 0x8AACC4, 0x8AACF3]
COND_RES = 0x44                     # condition object: resource id
SIGNED_MAX = 6                      # resource ids 0..6 compare signed

EFFECT = (0xBFA1E0, 0xBFA8E8)       # FUN_00bfa1e0(player, resource, op, amount), ret 0x10
SETRES = 0x7A7920                   # FUN_007a7920(kind, value), thiscall, ret 8
PLAYERS = 0x101DB18                 # player pointer table
JT_IDX, JT = 0xBFA92C, 0xBFA8E8     # resource -> case byte -> case address
# resource: (case start, hook va, register, player offset, FUN_007a7920 kind)
EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)
FLOOR_SITES = {
    2: (0xBFA2A7, 0xBFA2C2, ECX, 0xFEC, 4),     # recruitment points
    3: (0xBFA2E1, 0xBFA2FC, EDX, 0xFF0, 5),     # gold
    4: (0xBFA319, 0xBFA334, EAX, 0xFE8, 3),     # wood
    6: (0xBFA351, 0xBFA36C, ECX, 0xFF4, 6),     # glory
}
OP_SET, OP_ADD, OP_SUB = 0, 1, 2

# .RDATA zero tail (0xCE3800..0xCE3FFF, RWX, raw == virtual). Taken: click-fix 0xCE3880..0xCE3933,
# zoom-setting 0xCE3980..0xCE3BFF, target-priority 0xCE3C00..0xCE3E8B, ally-attack + attack-choice-fix
# 0xCE3E90..0xCE3F80. Stray dwords elsewhere in the image hold 0xCE3934 / 0xCE3C8C / 0xCE3E8C / 0xCE3F81.
CMP_CAVE, CMP_LIMIT = 0xCE3F88, 0xCE4000        # after the stray 0xCE3F81..0xCE3F84
FLOOR_CAVE, FLOOR_LIMIT = 0xCE3820, 0xCE3880    # below click-fix; 0xCE3800.. stays as a gap after the data
STRAYS = (0xCE3934, 0xCE3C8C, 0xCE3E8C, 0xCE3F81)
JE, JNE, JNS, JA = 0x74, 0x75, 0x79, 0x77


def gen_compare():
    s = Asm(CMP_CAVE)
    s.raw(0x83, 0x79, COND_RES, SIGNED_MAX)             # cmp dword [ecx+0x44],6   (ecx = condition)
    s.rel32(b"\x0f\x87", HELPER)                        # ja FUN_008a9c90         stock unsigned compare
    s.raw(0x8B, 0x4C, 0x24, 0x08)                       # mov ecx,[esp+8]   op
    s.raw(0x8B, 0x44, 0x24, 0x04)                       # mov eax,[esp+4]   value
    s.raw(0x8B, 0x54, 0x24, 0x0C)                       # mov edx,[esp+0xc] amount
    s.raw(0x85, 0xC9); s.jcc8(JE, "lt")                 # op 0 <
    for name in ("le", "eq", "ge", "gt"):               # op 1 <=, 2 ==, 3 >=, 4 >
        s.raw(0x49); s.jcc8(JE, name)                   # dec ecx
    s.raw(0x32, 0xC0, 0xC2, 0x0C, 0x00)                 # xor al,al; ret 0xc   (other ops: false, as stock)
    for name, cc in (("lt", 0x9C), ("le", 0x9E), ("eq", 0x94), ("ge", 0x9D), ("gt", 0x9F)):
        s.label(name)
        s.raw(0x3B, 0xC2, 0x0F, cc, 0xC0, 0xC2, 0x0C, 0x00)  # cmp eax,edx; setcc al; ret 0xc
    return s.finish()


def gen_floor():
    """{resource: (cave va, code)}: mov reg,[esi+x]; add reg,edi; jns ret; cmp ebx,2; jne ret;
    xor reg,reg; ret"""
    out, va = {}, FLOOR_CAVE
    for res, (_case, _hook, reg, off, _kind) in FLOOR_SITES.items():
        s = Asm(va)
        s.raw(0x8B, 0x86 | reg << 3); s.u32(off)        # mov reg,[esi+off]
        s.raw(0x03, 0xC7 | reg << 3)                    # add reg,edi
        s.jcc8(JNS, "ret")
        s.raw(0x83, 0xFB, OP_SUB); s.jcc8(JNE, "ret")   # cmp ebx,2
        s.raw(0x33, 0xC0 | reg << 3 | reg)              # xor reg,reg
        s.label("ret")
        s.raw(0xC3)
        code = s.finish()
        out[res] = (va, code)
        va += len(code)
    return out


def call_hex(va, target, length):
    return (b"\xe8" + struct.pack("<i", target - (va + 5)) + b"\x90" * (length - 5)).hex()


def compare_tuples():
    code = gen_compare()
    t = [(EXE, CMP_CAVE, "00" * len(code), code.hex(), f"signed compare cave ({len(code)} bytes)")]
    for va in CALLS:
        t.append((EXE, va, call_hex(va, HELPER, 5), call_hex(va, CMP_CAVE, 5),
                  "PlayerHasResource: compare via the cave"))
    return t


def floor_tuples():
    caves = gen_floor()
    blob = b"".join(c for _, c in caves.values())
    t = [(EXE, FLOOR_CAVE, "00" * len(blob), blob.hex(), f"resource floor caves ({len(blob)} bytes)")]
    names = {2: "recruitment points", 3: "gold", 4: "wood", 6: "glory"}
    for res, (_case, hook, reg, off, _kind) in FLOOR_SITES.items():
        stock = bytes([0x8B, 0x86 | reg << 3]) + struct.pack("<I", off) + bytes([0x03, 0xC7 | reg << 3])
        t.append((EXE, hook, stock.hex(), call_hex(hook, caves[res][0], 8),
                  f"ChangeResourceLevel {names[res]}: subtract stops at 0"))
    return t


FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def dis(data, va, n):
    o = va - BASE
    return list(MD.disasm(data[o:o + n], va))


def apply_bytes(image: bytes, patches) -> bytes:
    b = bytearray(image)
    for _, va, _old, new, _ in patches:
        raw = bytes.fromhex(new)
        b[va - BASE:va - BASE + len(raw)] = raw
    return bytes(b)


def span(p):
    return p[1], p[1] + len(p[3]) // 2


def branches(ins):
    return [(i.address, int(i.op_str, 16)) for i in ins
            if (i.mnemonic.startswith("j") or i.mnemonic == "call") and i.op_str.startswith("0x")]


# ---------------------------------------------------------------- 1. static checks
def static_checks():
    import raf_patch as rp
    import zoom_setting as zs
    cmp_t, floor_t = compare_tuples(), floor_tuples()
    check("raf_patch.TRIGGER_SIGNED_COMPARE == generated",
          [tuple(t[:4]) for t in rp.TRIGGER_SIGNED_COMPARE] == [t[:4] for t in cmp_t])
    check("raf_patch.TRIGGER_RESOURCE_FLOOR == generated",
          [tuple(t[:4]) for t in rp.TRIGGER_RESOURCE_FLOOR] == [t[:4] for t in floor_t])
    for p in cmp_t + floor_t:
        check(f"stock bytes at {p[1]:#x} ({p[4]})", STOCK[p[1] - BASE:p[1] - BASE + len(p[2]) // 2].hex() == p[2])
    c_cave, f_cave = span(cmp_t[0]), span(floor_t[0])
    check(f"compare cave inside {CMP_CAVE:#x}..{CMP_LIMIT:#x}", CMP_CAVE <= c_cave[0] and c_cave[1] <= CMP_LIMIT,
          hex(c_cave[1]))
    check(f"floor caves inside {FLOOR_CAVE:#x}..{FLOOR_LIMIT:#x}",
          FLOOR_CAVE <= f_cave[0] and f_cave[1] <= FLOOR_LIMIT, hex(f_cave[1]))
    caves = [c_cave, f_cave]
    check("caves clear of the stray values", all(not (lo < v + 4 and v < hi) for lo, hi in caves for v in STRAYS))
    others = []
    for name in ("CLICK_FIX", "TARGET_PRIORITY", "NAVAL_AI", "ALLY_ATTACK", "ATTACK_CHOICE_FIX", "SMOOTH_SCROLL",
                 "CMDLINE_FIX", "MODE_LIST_FIX", "AI_CIV_GATE", "OPENSPY"):
        others += [span(p) for p in getattr(rp, name) if p[0] == EXE]
    others += [span(p) for p in zs.patches()]
    mine = [span(p) for p in cmp_t + floor_t]
    check("no overlap with the other exe patches (click-fix, zoom-setting, target-priority, naval-ai, "
          "ally-attack, attack-choice-fix, ...)",
          all(not (lo < b and a < hi) for lo, hi in mine for a, b in others))
    check("no overlap between the two features", all(not (a[0] < b[1] and b[0] < a[1])
                                                      for a in [span(p) for p in cmp_t]
                                                      for b in [span(p) for p in floor_t]))
    pe = struct.unpack_from("<I", STOCK, 0x3C)[0]
    nsec = struct.unpack_from("<H", STOCK, pe + 6)[0]
    opt = struct.unpack_from("<H", STOCK, pe + 20)[0]
    sec = None
    for i in range(nsec):
        o = pe + 24 + opt + 40 * i
        vs, va, rs, ro = struct.unpack_from("<IIII", STOCK, o + 8)
        ch = struct.unpack_from("<I", STOCK, o + 36)[0]
        if va + BASE <= FLOOR_CAVE < va + BASE + rs:
            sec = (STOCK[o:o + 8].rstrip(b"\0"), va, ro, ch, rs)
    check("caves in .RDATA, executable + writable, raw == virtual",
          sec is not None and sec[0] == b".RDATA" and sec[3] & 0xE0000000 == 0xE0000000 and sec[1] == sec[2]
          and CMP_LIMIT <= sec[1] + BASE + sec[4], str(sec))
    check("cave ranges zero in stock", STOCK[CMP_CAVE - BASE:CMP_LIMIT - BASE] == bytes(CMP_LIMIT - CMP_CAVE)
          and STOCK[FLOOR_CAVE - BASE:FLOOR_LIMIT - BASE] == bytes(FLOOR_LIMIT - FLOOR_CAVE))
    hits = [hex(i + BASE) for i in range(len(STOCK) - 3)
            if any(lo <= struct.unpack_from("<I", STOCK, i)[0] < hi for lo, hi in
                   ((CMP_CAVE, CMP_LIMIT), (FLOOR_CAVE, FLOOR_LIMIT)))]
    check("no 4-byte value in the stock image points into the cave ranges", not hits, ",".join(hits[:5]))

    # compare: single caller, stock helper shape
    rel = [i + BASE for i in range(len(STOCK) - 5) if STOCK[i] in (0xE8, 0xE9)
           and struct.unpack_from("<i", STOCK, i + 1)[0] + i + 5 + BASE == HELPER]
    absr = [i + BASE for i in range(len(STOCK) - 3) if struct.unpack_from("<I", STOCK, i)[0] == HELPER]
    check("FUN_008a9c90: exactly the three calls in FUN_008aabc0, no pointer to it",
          rel == CALLS and not absr, str([hex(a) for a in rel + absr]))
    check("FUN_008aabc0 is only referenced by its vtable slot 0xc6eb10",
          [i + BASE for i in range(len(STOCK) - 3) if struct.unpack_from("<I", STOCK, i)[0] == EVAL[0]]
          == [EVAL_VTABLE])
    check("helper setcc: setb / setbe / sete / setae / seta (unsigned)",
          all(STOCK[va - BASE:va - BASE + 3].hex() == h for va, h in HELPER_SETCC.items()))
    hd = [f"{i.mnemonic} {i.op_str}" for i in dis(STOCK, HELPER, 0x1B)]
    check("helper: op = [esp+8], > 4 -> false, jump table 0x8a9ce8",
          hd[:5] == ["mov ecx, dword ptr [esp + 8]", "xor al, al", "cmp ecx, 4", "ja 0x8a9ce5",
                     "jmp dword ptr [ecx*4 + 0x8a9ce8]"], str(hd))
    jt = [struct.unpack_from("<I", STOCK, 0x8A9CE8 - BASE + 4 * k)[0] for k in range(5)]
    check("helper jump table: op 0..4 -> < <= == >= > (value [esp+4] vs amount [esp+0xc])",
          jt == [0x8A9CA2, 0x8A9CB0, 0x8A9CBE, 0x8A9CCC, 0x8A9CDA], str([hex(x) for x in jt]))
    ev = dis(STOCK, EVAL[0], EVAL[1] - EVAL[0])
    check("FUN_008aabc0 disassembles to its end", ev[-1].address + ev[-1].size >= 0x8AAD60)
    seq = {i.address: i for i in ev}
    starts = set(seq)
    for va in CALLS:
        prev = [i for i in ev if i.address < va][-1]
        check(f"{va:#x}: call 0x8a9c90 right after mov ecx, esi (ecx = condition object)",
              seq[va].mnemonic == "call" and seq[va].op_str == hex(HELPER)
              and (prev.mnemonic, prev.op_str) == ("mov", "ecx, esi"))
        check(f"{va + 5:#x} (return) is an instruction start", va + 5 in starts)
    res_reads = [i.address for i in ev if i.op_str.endswith("dword ptr [esi + 0x44]")]
    check("the evaluated resource is [esi+0x44] (passed to FUN_008aa9b0)",
          res_reads == [0x8AAC33], str([hex(a) for a in res_reads]))
    check("op is [esi+0x50] at all three calls",
          sum(1 for i in ev if "[esi + 0x50]" in i.op_str) == 3)
    bad = [hex(a) for a, t in branches(ev) if any(c < t < c + 5 for c in CALLS)]
    check("no branch into a hooked call", not bad, ",".join(bad))

    # floor: effect switch and the four sites
    fx = dis(STOCK, EFFECT[0], EFFECT[1] - EFFECT[0])
    check("FUN_00bfa1e0 disassembles to its jump table", fx[-1].address + fx[-1].size <= EFFECT[1]
          and fx[-1].address + fx[-1].size >= 0xBFA8D0)
    head = [f"{i.mnemonic} {i.op_str}" for i in fx[:13]]
    check("FUN_00bfa1e0: ebx = op, edi = amount, negated for op 2, esi = player",
          head[3] == "mov ebx, dword ptr [esp + 0x94]" and head[5] == "mov ebp, dword ptr [esp + 0x9c]"
          and head[9:13] == ["cmp ebx, 2", "mov edi, ebp", "jne 0xbfa20c", "neg edi"], str(head))
    idx = STOCK[JT_IDX - BASE:JT_IDX - BASE + 0x1B]
    case = lambda r: struct.unpack_from("<I", STOCK, JT - BASE + 4 * idx[r])[0]  # noqa: E731
    fstarts = {i.address for i in fx}
    for res, (cstart, hook, reg, off, kind) in FLOOR_SITES.items():
        check(f"resource {res}: switch case at {cstart:#x}", case(res) == cstart)
        body = [i for i in fx if cstart <= i.address < cstart + 0x40]
        txt = [f"{i.mnemonic} {i.op_str}" for i in body]
        r = {EAX: "eax", ECX: "ecx", EDX: "edx"}[reg]
        want = [f"mov {r}, dword ptr [esi + {off:#x}]", f"add {r}, edi", f"push {r}", f"push {kind}"]
        k = next((j for j, i in enumerate(body) if i.address == hook), None)
        check(f"resource {res}: {hook:#x} = mov {r},[esi+{off:#x}]; add {r},edi; push {r}; push {kind}; "
              "... call FUN_007a7920",
              k is not None and txt[k:k + 4] == want and "call 0x7a7920" in txt[k + 4:k + 6]
              and "test ebx, ebx" in txt[:2], str(txt))
        check(f"resource {res}: hook end {hook + 8:#x} is an instruction start", hook + 8 in fstarts)
    bad = [hex(a) for a, t in branches(fx) if any(h < t < h + 8 for (_c, h, _r, _o, _k) in FLOOR_SITES.values())]
    check("no branch into a hooked add", not bad, ",".join(bad))
    callers = [i + BASE for i in range(len(STOCK) - 5) if STOCK[i] in (0xE8, 0xE9)
               and struct.unpack_from("<i", STOCK, i + 1)[0] + i + 5 + BASE == EFFECT[0]]
    check("FUN_00bfa1e0 callers: its own resource-1 loop 0xbfa28d and the effect 0xbfa9e1",
          callers == [0xBFA28D, 0xBFA9E1], str([hex(a) for a in callers]))

    patched = apply_bytes(STOCK, cmp_t + floor_t)
    diff = [i + BASE for i in range(len(STOCK)) if patched[i] != STOCK[i]]
    spans = [span(t) for t in cmp_t + floor_t]
    check("patched image differs from stock only inside the patch spans",
          all(any(lo <= a < hi for lo, hi in spans) for a in diff))
    for va in CALLS:
        i = dis(patched, va, 5)[0]
        check(f"{va:#x} patched: call {CMP_CAVE:#x}", (i.mnemonic, i.op_str) == ("call", hex(CMP_CAVE)))
    code = bytes.fromhex(cmp_t[0][3])
    ins = dis(patched, CMP_CAVE, len(code))
    check("compare cave disassembles completely", sum(i.size for i in ins) == len(code))
    cst = {i.address for i in ins}
    br = branches(ins)
    check("compare cave: jumps land in the cave or on FUN_008a9c90",
          all(t in cst or t == HELPER for _, t in br) and (ins[1].address, HELPER) in br)
    check("compare cave: every exit is ret 0xc or the jump to the stock helper",
          [i.op_str for i in ins if i.mnemonic == "ret"] == ["0xc"] * 6
          and not any(i.mnemonic in ("call", "push", "pop") for i in ins))
    setcc = [i.mnemonic for i in ins if i.mnemonic.startswith("set")]
    check("compare cave: setl setle sete setge setg", setcc == ["setl", "setle", "sete", "setge", "setg"])
    allins = list(ins)
    for res, (va, c) in gen_floor().items():
        fi = dis(patched, va, len(c))
        allins += fi
        check(f"floor cave {res} at {va:#x} disassembles completely, ends with ret, no stack use",
              sum(i.size for i in fi) == len(c) and fi[-1].mnemonic == "ret"
              and not any(i.mnemonic in ("call", "push", "pop") for i in fi))
        hook = FLOOR_SITES[res][1]
        hi = dis(patched, hook, 8)
        check(f"{hook:#x} patched: call {va:#x}; nop x3",
              [(i.mnemonic, i.op_str) for i in hi] == [("call", hex(va)), ("nop", ""), ("nop", ""), ("nop", "")])
    if "-v" in sys.argv:
        for i in allins:
            print(f"      {i.address:08x}: {i.bytes.hex():<20} {i.mnemonic} {i.op_str}")
    return patched


# ---------------------------------------------------------------- 2. emulation
class Emu:
    MEM = 0x20000000
    STACK = 0x22000000
    RET = 0x21FF0000                    # sentinel return address (mapped, never executed)

    def __init__(self, image: bytes):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn import x86_const as X
        u = self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        size = max((len(image) + 0xFFF) & ~0xFFF, 0x1100000 - BASE)
        u.mem_map(BASE, size)
        u.mem_write(BASE, image)
        u.mem_map(self.MEM, 0x100000)
        u.mem_map(self.RET, 0x1000)
        u.mem_map(self.STACK, 0x10000)
        self.R = [X.UC_X86_REG_EAX, X.UC_X86_REG_ECX, X.UC_X86_REG_EDX, X.UC_X86_REG_EBX,
                  X.UC_X86_REG_ESP, X.UC_X86_REG_EBP, X.UC_X86_REG_ESI, X.UC_X86_REG_EDI]

    def w32(self, a, v):
        self.u.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.u.mem_read(a, 4))[0]

    def call(self, start, regs, args, hooks=None, count=200000):
        """Push args + the sentinel, run until the sentinel. -> (registers, esp delta)"""
        from unicorn import UC_HOOK_CODE
        u = self.u
        for r in range(8):
            u.reg_write(self.R[r], 0x0BAD0000 + r)
        sp = self.STACK + 0x8000
        u.mem_write(sp, bytes(0x400))
        for k, a in enumerate(args):
            self.w32(sp + 4 + 4 * k, a)
        self.w32(sp, self.RET)
        regs = dict(regs)
        regs[ESP] = sp
        for r, v in regs.items():
            u.reg_write(self.R[r], v & 0xFFFFFFFF)

        def hk(uc, addr, size, _):
            if hooks and addr in hooks:
                hooks[addr](self)
            if addr == self.RET:
                uc.emu_stop()
        h = u.hook_add(UC_HOOK_CODE, hk)
        try:
            u.emu_start(start, 0xFFFFFFF0, count=count)
        finally:
            u.hook_del(h)
        out = [u.reg_read(self.R[r]) for r in range(8)]
        assert u.reg_read(self.R[ESP]) - sp >= 0
        return out, out[ESP] - sp


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def model_cmp(value, op, amount, signed):
    a, b = (s32(value), s32(amount)) if signed else (value & 0xFFFFFFFF, amount & 0xFFFFFFFF)
    return {0: a < b, 1: a <= b, 2: a == b, 3: a >= b, 4: a > b}.get(op, False)


def emu_compare(patched: bytes):
    e = Emu(patched)
    cond = Emu.MEM
    values = [0, 1, 899, 900, 901, 5000, 0x7FFFFFFF, -1, -250, -5000, 0x80000000]
    amounts = [0, 900, 5000, 100000, 0xFFFFFFFF]
    bad, n = [], 0
    for res in (0, 1, 2, 3, 4, 5, 6, 7, 8, 11, 15, 20, 25, 59):
        e.w32(cond + COND_RES, res)
        for op in range(6):
            for v in values:
                for a in amounts:
                    out, d = e.call(CMP_CAVE, {ECX: cond}, [v, op, a])
                    got = bool(out[EAX] & 0xFF)
                    want = model_cmp(v, op, a, res <= SIGNED_MAX)
                    n += 1
                    if got != want or d != 16:
                        bad.append((res, op, v, a, got, want, d))
    check(f"compare cave == model on {n} cases (signed for resources 0..6, stock unsigned above), "
          "esp + 16 (ret 0xc)", not bad, str(bad[:3]))
    e.w32(cond + COND_RES, 3)
    out, _ = e.call(CMP_CAVE, {ECX: cond}, [-250 & 0xFFFFFFFF, 3, 900])
    check("gold -250 >= 900: false (stock: true)", out[EAX] & 0xFF == 0)
    e.w32(cond + COND_RES, 15)
    out, _ = e.call(CMP_CAVE, {ECX: cond}, [-30 & 0xFFFFFFFF, 4, 100000])
    check("campaign medal score Var4 = -30 'Var4 < 0' (= Var4 > 100000): still true as in stock",
          out[EAX] & 0xFF == 1)
    s = Emu(STOCK)
    bad = []
    for res in (3, 15):
        for op in range(6):
            for v in values:
                for a in amounts:
                    out, _ = s.call(HELPER, {ECX: cond}, [v, op, a])
                    if bool(out[EAX] & 0xFF) != model_cmp(v, op, a, False):
                        bad.append((op, v, a))
    check("stock FUN_008a9c90 == unsigned model (what the patch replaces)", not bad, str(bad[:3]))


def emu_floor_caves(patched: bytes):
    e = Emu(patched)
    player = Emu.MEM + 0x1000
    bad, n = [], 0
    for res, (va, _c) in gen_floor().items():
        reg, off = FLOOR_SITES[res][2], FLOOR_SITES[res][3]
        for op in (OP_SET, OP_ADD, OP_SUB):
            for old in (0, 100, 250, 300, 5000, -50):
                for amount in (0, 10, 250, 400, -25):
                    delta = -amount if op == OP_SUB else amount
                    e.w32(player + off, old)
                    out, d = e.call(va, {ESI: player, EDI: delta, EBX: op}, [])
                    raw = old + delta
                    want = 0 if op == OP_SUB and raw < 0 else raw
                    keep = all(out[r] == {ESI: player, EDI: delta & 0xFFFFFFFF, EBX: op}.get(r, 0x0BAD0000 + r)
                               for r in range(8) if r not in (reg, ESP))
                    n += 1
                    if s32(out[reg]) != want or d != 4 or not keep or e.r32(player + off) != old & 0xFFFFFFFF:
                        bad.append((res, op, old, amount, s32(out[reg]), want))
    check(f"floor caves on {n} cases: op 2 below 0 -> 0, else old + delta; other registers, flags user "
          "and the player field untouched", not bad, str(bad[:3]))


def emu_effect(image: bytes, cases):
    """Run FUN_00bfa1e0(player, resource, op, amount) with FUN_007a7920 stubbed to `ret 8`;
    -> list of results: [(kind, value) recorded by the stub ...] or the player dword written."""
    e = Emu(image)
    e.u.mem_write(SETRES, b"\xc2\x08\x00")             # ret 8
    player = Emu.MEM + 0x1000
    e.w32(PLAYERS + 4 * 1, player)
    calls = []
    hooks = {SETRES: lambda em: calls.append((em.r32(em.u.reg_read(em.R[ESP]) + 4),
                                              s32(em.r32(em.u.reg_read(em.R[ESP]) + 8))))}
    out = []
    for res, op, amount, fields in cases:
        e.u.mem_write(player, bytes(0x1100))
        for off, v in fields.items():
            e.w32(player + off, v)
        calls.clear()
        _, d = e.call(EFFECT[0], {ECX: 0x0C0DE000}, [1, res, op, amount & 0xFFFFFFFF], hooks)
        assert d == 20, d
        out.append((list(calls), {off: s32(e.r32(player + off)) for off in fields}))
    return out


def emu_effects(patched: bytes):
    G, W, R2, GL = 0xFF0, 0xFE8, 0xFEC, 0xFF4
    VAR4 = (15 + 0x3AA) * 4
    cases = [
        (3, OP_SUB, 250, {G: 100}),             # gaugamela: computers -250 gold
        (3, OP_SUB, 250, {G: 300}),
        (3, OP_SUB, 250, {G: -40}),
        (3, OP_ADD, -250, {G: 100}),            # add of a negative value stays stock
        (3, OP_SET, -5, {G: 100}),              # set stays stock
        (4, OP_SUB, 1000, {W: 200}),
        (2, OP_SUB, 5, {R2: 3}),
        (6, OP_SUB, 10, {GL: 4}),
        (1, OP_SUB, 500, {G: 100, W: 600, R2: 0, GL: 1000}),   # all: 2..6
        (15, OP_SUB, 25, {VAR4: 10}),           # Var4 = 10 - 25: variables stay unclamped
    ]
    stock = emu_effect(STOCK, cases)
    new = emu_effect(patched, cases)
    check("stock: gold 100 - 250 -> FUN_007a7920(5, -150)", stock[0][0] == [(5, -150)], str(stock[0]))
    check("patched: gold 100 - 250 -> FUN_007a7920(5, 0)", new[0][0] == [(5, 0)], str(new[0]))
    check("patched: gold 300 - 250 -> 50", new[1][0] == [(5, 50)], str(new[1]))
    check("patched: gold -40 - 250 -> 0", new[2][0] == [(5, 0)], str(new[2]))
    check("patched: add -250 to 100 stays -150 (stock)", new[3] == stock[3] and new[3][0] == [(5, -150)], str(new[3]))
    check("patched: set -5 stays stock", new[4] == stock[4] and new[4][0] == [(5, -5)], str(new[4]))
    check("patched: wood 200 - 1000 -> FUN_007a7920(3, 0)", new[5][0] == [(3, 0)], str(new[5]))
    check("patched: recruitment points 3 - 5 -> FUN_007a7920(4, 0)", new[6][0] == [(4, 0)], str(new[6]))
    check("patched: glory 4 - 10 -> FUN_007a7920(6, 0)", new[7][0] == [(6, 0)], str(new[7]))
    check("patched: resource 1 (all) - 500 -> recruitment 0, gold 0, wood 100, glory 500",
          new[8][0] == [(4, 0), (5, 0), (3, 100), (6, 500)], str(new[8]))
    check("stock: resource 1 (all) - 500 -> -500, -400, 100, 500",
          stock[8][0] == [(4, -500), (5, -400), (3, 100), (6, 500)], str(stock[8]))
    check("patched: Var4 10 - 25 = -15 as in stock (variables untouched)",
          new[9] == stock[9] and new[9][1][VAR4] == -15, str(new[9]))


# ---------------------------------------------------------------- 3. patcher
def patcher_checks():
    import raf_patch as rp
    import raf_installer_text
    import build_installer as bi
    feats = (("trigger-signed-compare", rp.TRIGGER_SIGNED_COMPARE, rp.TRIGGER_SIGNED_COMPARE_MARK,
              rp.trigger_signed_compare_installed),
             ("trigger-resource-floor", rp.TRIGGER_RESOURCE_FLOOR, rp.TRIGGER_RESOURCE_FLOOR_MARK,
              rp.trigger_resource_floor_installed))
    with tempfile.TemporaryDirectory() as t:
        g = Path(t)
        exe = g / EXE
        exe.write_bytes(STOCK)
        quiet(rp.byte_patches, g, rp.CLICK_FIX, True, "c")
        quiet(rp.set_zoom_sites, g, "setting", 2.5)
        for p in (rp.TARGET_PRIORITY, rp.NAVAL_AI, rp.ALLY_ATTACK, rp.ATTACK_CHOICE_FIX):
            quiet(rp.byte_patches, g, p, True, "x")
        base = exe.read_bytes()
        for _, patches, _, _ in feats:
            quiet(rp.byte_patches, g, patches, True, "t")
        on = exe.read_bytes()
        check("both applied on top of the other exe patches",
              on == apply_bytes(base, rp.TRIGGER_SIGNED_COMPARE + rp.TRIGGER_RESOURCE_FLOOR))
        for _, patches, _, _ in feats:
            quiet(rp.byte_patches, g, patches, True, "t")
        check("re-apply is idempotent", exe.read_bytes() == on)
        quiet(rp.byte_patches, g, rp.TRIGGER_SIGNED_COMPARE, False, "t")
        check("revert signed compare alone -> floor stays",
              exe.read_bytes() == apply_bytes(base, rp.TRIGGER_RESOURCE_FLOOR))
        quiet(rp.byte_patches, g, rp.TRIGGER_RESOURCE_FLOOR, False, "t")
        check("revert both -> the other patches stay", exe.read_bytes() == base)
        quiet(rp.byte_patches, g, rp.TRIGGER_RESOURCE_FLOOR, False, "t")
        check("revert twice is a no-op", exe.read_bytes() == base)
        exe.write_bytes(STOCK)
        for _, patches, _, _ in feats:
            quiet(rp.byte_patches, g, patches, True, "t")
        for _, patches, _, _ in feats:
            quiet(rp.byte_patches, g, patches, False, "t")
        check("apply + revert on a stock exe -> stock byte for byte", exe.read_bytes() == STOCK)
        for name, patches, _, _ in feats:
            for p in patches:
                bad = bytearray(STOCK)
                bad[p[1] - BASE] ^= 0x01
                exe.write_bytes(bad)
                try:
                    quiet(rp.byte_patches, g, patches, True, "t")
                    ok = False
                except SystemExit:
                    ok = True
                check(f"{name}: foreign bytes at {p[1]:#x} refused, exe untouched",
                      ok and exe.read_bytes() == bytes(bad))
    for name, _, _, _ in feats:
        check(f"{name}: feature registered, default on", rp.FEATURES.get(name) is True)
        check(f"{name}: installer text de/ru/en", set(raf_installer_text.TEXT.get("f_" + name, {})) == {"de", "ru", "en"})
        check(f"{name}: in the installer release set", name in bi.FEATURES)
    with tempfile.TemporaryDirectory() as t:
        g = Path(t)
        (g / "Data" / "db").mkdir(parents=True)
        (g / "Data" / "db" / "x.dat").write_bytes(b"gameplay")
        (g / EXE).write_bytes(STOCK)
        off = rp.fingerprint(g)
        h0 = hashlib.sha256(b"data/db/x.dat\0" + hashlib.sha256(b"gameplay").digest())
        check("fingerprint OFF = plain file hash", h0.hexdigest()[:12] == off)
        for name, patches, mark, installed in feats:
            quiet(rp.byte_patches, g, patches, True, "t")
            h = h0.copy()
            h.update(mark)
            check(f"fingerprint {name} alone = file hash + its mark",
                  rp.fingerprint(g) == h.hexdigest()[:12] and installed(g))
            quiet(rp.byte_patches, g, patches, False, "t")
            check(f"{name}: fingerprint back to OFF after revert", rp.fingerprint(g) == off and not installed(g))
        for _, patches, _, _ in feats:
            quiet(rp.byte_patches, g, patches, True, "t")
        h = h0.copy()
        h.update(rp.TRIGGER_SIGNED_COMPARE_MARK)
        h.update(rp.TRIGGER_RESOURCE_FLOOR_MARK)
        check("fingerprint both = file hash + both marks (in that order)", rp.fingerprint(g) == h.hexdigest()[:12])
        check("the two marks differ", rp.TRIGGER_SIGNED_COMPARE_MARK != rp.TRIGGER_RESOURCE_FLOOR_MARK)


STOCK = b""


def main():
    global STOCK
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    game = Path(args[0] if args else "D:/Games/Rise and Fall")
    STOCK = (game / EXE).read_bytes()
    if "--print" in sys.argv:
        for t in compare_tuples() + floor_tuples():
            h = t[3]
            parts = [h[i:i + 96] for i in range(0, len(h), 96)]
            new = "\n     ".join(f'"{x}"' for x in parts)
            old = f'"00" * {len(t[2]) // 2}' if set(t[2]) == {"0"} else f'"{t[2]}"'
            print(f'    (EXE, {t[1]:#010x}, {old},\n     {new},\n     "{t[4]}"),')
        return 0
    patched = static_checks()
    emu_compare(patched)
    emu_floor_caves(patched)
    emu_effects(patched)
    patcher_checks()
    print("ALL CHECKS PASSED" if not FAILED else f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
