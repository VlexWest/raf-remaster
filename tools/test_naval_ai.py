"""Offline tests for the naval-ai patch (raf_patch.NAVAL_AI, docs/ai-naval.md section 6, RAF-9). Reads the
base install only; writes exe copies into a temp folder; never touches the registry or a running game.

    python tools/test_naval_ai.py [stock_game_dir]      (default D:/Games/Rise and Fall)

P1 0x55929c  `mov edx,[esi]` -> `jmp 0x5592ae`: ferry load timer expired, run the cargo test first
P2 0x4bbc00  `je 0x4bbc12`   -> `jmp 0x4bbc12`: always ask idle units to board
P3 0xc56428  float 2700000.0 -> 900000.0 (early ferry gate); the 0.75 at 0xc56424 stays

1. static: stock bytes, whole instructions, jump targets, float values, single reference
2. apply / re-apply / revert byte-exact on an exe copy, together with click-fix, zoom-setting and
   target-priority; foreign bytes refused; feature registered, fingerprint mark
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
sys.path.insert(0, str(REPO / "work" / "tools" / "py"))  # capstone
import capstone  # noqa: E402
import raf_patch as rp  # noqa: E402

BASE = 0x400000
EXE = "RiseAndFall.exe"
P1, P1_TARGET = 0x55929C, 0x5592AE
P2, P2_TARGET = 0x4BBC00, 0x4BBC12
GATE, SHARED = 0xC56428, 0xC56424
GATE_USER = 0x558B5F
FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def at(data, va, n):
    off = rp.pe_va_to_offset(data, va)
    return bytes(data[off:off + n])


def apply_bytes(data, patches):
    out = bytearray(data)
    for _, va, _old, new, _ in patches:
        off = rp.pe_va_to_offset(out, va)
        out[off:off + len(new) // 2] = bytes.fromhex(new)
    return bytes(out)


def disasm(data, va, n):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(at(data, va, n), va))


def starts(data, va, end):
    return {i.address for i in disasm(data, va, end - va)}


def static_checks():
    by_va = {p[1]: p for p in rp.NAVAL_AI}
    check("three patches at 0x55929c, 0x4bbc00, 0xc56428", sorted(by_va) == [P2, P1, GATE][::1] or
          sorted(by_va) == sorted([P1, P2, GATE]))
    check("every patch has its stock bytes in the exe", all(at(STOCK, va, len(p[2]) // 2).hex() == p[2]
                                                            for va, p in by_va.items()))
    check("patch lengths: 2 / 2 / 4 bytes", [len(by_va[v][3]) // 2 for v in (P1, P2, GATE)] == [2, 2, 4])
    check("old/new lengths match", all(len(p[2]) == len(p[3]) for p in rp.NAVAL_AI))
    patched = apply_bytes(STOCK, rp.NAVAL_AI)

    # P1
    st = disasm(STOCK, P1, 8)
    check("P1 stock: mov edx,[esi]; push eax; push 0x1f7",
          [(i.mnemonic, i.op_str) for i in st[:3]] == [("mov", "edx, dword ptr [esi]"), ("push", "eax"),
                                                       ("push", "0x1f7")])
    i = disasm(patched, P1, 2)[0]
    check("P1 patched: jmp 0x5592ae", (i.mnemonic, i.operands[0].imm) == ("jmp", P1_TARGET))
    check("P1 target is an instruction start of the cargo test (stock code from 0x5592ae)",
          P1_TARGET in starts(STOCK, P1_TARGET, P1_TARGET + 0x41))
    # cargo test = (ship+0x34c - ship+0x348) / 4, then the two SetState calls
    body = [(x.mnemonic, x.op_str) for x in disasm(STOCK, P1_TARGET, 0x45)]
    check("P1 target: cargo count ([ship+0x348], [ship+0x344+8]) >> 2; empty -> SetState(0), cargo -> SetState(0x1f7)",
          ("mov", "ecx, dword ptr [eax + 0x348]") in body and ("sar", "eax, 2") in body
          and ("push", "0") in body and ("push", "0x1f7") in body and body.count(("call", "dword ptr [edx + 0x1c]")) == 2)
    # no other code in the function may jump into the bytes the jmp hides (0x55929e..0x5592ad)
    fn = disasm(STOCK, 0x559280, 0x80)
    into = [x.address for x in fn if x.mnemonic.startswith("j") and x.operands and x.operands[0].type == 2
            and P1 + 2 <= x.operands[0].imm < P1_TARGET]
    check("P1: no branch into the skipped bytes 0x55929e..0x5592ad", not into, hex(into[0]) if into else "")

    # P2
    i = disasm(STOCK, P2, 2)[0]
    check("P2 stock: je 0x4bbc12", (i.mnemonic, i.operands[0].imm) == ("je", P2_TARGET))
    i = disasm(patched, P2, 2)[0]
    check("P2 patched: jmp 0x4bbc12", (i.mnemonic, i.operands[0].imm) == ("jmp", P2_TARGET))
    check("P2 target is an instruction start", P2_TARGET in starts(STOCK, P2 - 0x10, P2_TARGET + 8))
    nxt = [(x.mnemonic, x.op_str) for x in disasm(STOCK, P2 + 2, 0x10)]
    check("P2 hidden fallthrough: cmp DifficultyLevel (+0x1104) with 1, jb 0x4bbddf",
          ("cmp", "dword ptr [eax + 0x1104], 1") in nxt and ("jb", "0x4bbddf") in nxt, str(nxt))

    # P3
    f = lambda d, va: struct.unpack("<f", at(d, va, 4))[0]
    check("P3 stock gate 2700000.0, patched 900000.0", (f(STOCK, GATE), f(patched, GATE)) == (2700000.0, 900000.0))
    check("P3 new bytes are float32 900000.0", bytes.fromhex(by_va[GATE][3]) == struct.pack("<f", 900000.0))
    check("P3 shared 0.75 at 0xc56424 untouched", f(STOCK, SHARED) == f(patched, SHARED) == 0.75)
    refs = [m for m in range(len(STOCK) - 6) if STOCK[m + 2:m + 6] == struct.pack("<I", GATE)
            and STOCK[m:m + 2] in (b"\xd8\x0d", b"\xd8\x05", b"\xd8\x25", b"\xdc\x0d", b"\xa1\x00")]
    check("P3 gate float: a single `fmul [0xc56428]` at 0x558b5f",
          len(refs) == 1 and disasm(STOCK, GATE_USER, 6)[0].mnemonic == "fmul"
          and disasm(STOCK, GATE_USER, 6)[0].op_str == "dword ptr [0xc56428]")
    check("bytes differ in the whole exe: 2 + 1 + 4",
          sum(a != b for a, b in zip(STOCK, patched)) == 7 and len(STOCK) == len(patched))


def patcher_checks():
    with tempfile.TemporaryDirectory() as t:
        g = Path(t)
        exe = g / EXE
        exe.write_bytes(STOCK)
        quiet(rp.byte_patches, g, rp.CLICK_FIX, True, "c")
        quiet(rp.set_zoom_sites, g, "setting", 2.5)
        quiet(rp.byte_patches, g, rp.TARGET_PRIORITY, True, "t")
        base = exe.read_bytes()
        quiet(rp.byte_patches, g, rp.NAVAL_AI, True, "n")
        on = exe.read_bytes()
        check("applied on top of click-fix + zoom-setting + target-priority",
              on == apply_bytes(base, rp.NAVAL_AI))
        check("only the naval-ai bytes changed (2 + 1 + 4 differ)", sum(a != b for a, b in zip(on, base)) == 7)
        for patches, state in ((rp.CLICK_FIX, True), (rp.TARGET_PRIORITY, True), (rp.NAVAL_AI, True)):
            quiet(rp.byte_patches, g, patches, state, "x")
        quiet(rp.set_zoom_sites, g, "setting", 2.5)
        check("re-apply of all four is idempotent", exe.read_bytes() == on)
        quiet(rp.byte_patches, g, rp.NAVAL_AI, False, "n")
        check("revert naval-ai -> the other patches stay", exe.read_bytes() == base)
        quiet(rp.byte_patches, g, rp.NAVAL_AI, False, "n")
        check("revert twice is a no-op", exe.read_bytes() == base)
        quiet(rp.byte_patches, g, rp.NAVAL_AI, True, "n")
        quiet(rp.set_zoom_sites, g, None, 2.5)
        quiet(rp.byte_patches, g, rp.CLICK_FIX, False, "c")
        quiet(rp.byte_patches, g, rp.TARGET_PRIORITY, False, "t")
        quiet(rp.byte_patches, g, rp.NAVAL_AI, False, "n")
        check("revert all (other order) -> stock exe byte for byte", exe.read_bytes() == STOCK)
        for va in (P1, P2, GATE):
            bad = bytearray(STOCK)
            bad[rp.pe_va_to_offset(STOCK, va)] ^= 0x01
            exe.write_bytes(bad)
            try:
                quiet(rp.byte_patches, g, rp.NAVAL_AI, True, "n")
                check(f"foreign bytes at {va:#x} refused", False)
            except SystemExit:
                check(f"foreign bytes at {va:#x} refused", True)
            check(f"refused apply leaves the exe untouched ({va:#x})", exe.read_bytes() == bytes(bad))
    check("feature registered, default on", rp.FEATURES.get("naval-ai") is True)
    import raf_installer_text
    check("installer text has a label in de/ru/en",
          set(raf_installer_text.TEXT.get("f_naval-ai", {})) == {"de", "ru", "en"})
    # fingerprint: unchanged while off, mark mixed in while on, independent of target-priority
    with tempfile.TemporaryDirectory() as t:
        g = Path(t)
        (g / "Data" / "db").mkdir(parents=True)
        (g / "Data" / "db" / "x.dat").write_bytes(b"gameplay")
        (g / EXE).write_bytes(STOCK)
        off = rp.fingerprint(g)
        quiet(rp.byte_patches, g, rp.NAVAL_AI, True, "n")
        on = rp.fingerprint(g)
        check("fingerprint ON differs from OFF, naval_ai_installed", on != off and rp.naval_ai_installed(g))
        h = hashlib.sha256(b"data/db/x.dat\0" + hashlib.sha256(b"gameplay").digest())
        check("fingerprint OFF = plain file hash", h.hexdigest()[:12] == off)
        h.update(rp.NAVAL_AI_MARK)
        check("fingerprint ON = file hash + NAVAL_AI_MARK", h.hexdigest()[:12] == on)
        quiet(rp.byte_patches, g, rp.TARGET_PRIORITY, True, "t")
        check("fingerprint with both marks differs from naval-ai alone", rp.fingerprint(g) != on)
        quiet(rp.byte_patches, g, rp.NAVAL_AI, False, "n")
        quiet(rp.byte_patches, g, rp.TARGET_PRIORITY, False, "t")
        check("fingerprint after revert: back to OFF", rp.fingerprint(g) == off and not rp.naval_ai_installed(g))
    import build_installer as bi
    check("installer release set contains the feature", "naval-ai" in bi.FEATURES)


STOCK = b""


def main():
    global STOCK
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    game = Path(args[0] if args else "D:/Games/Rise and Fall")
    STOCK = (game / EXE).read_bytes()
    static_checks()
    patcher_checks()
    print("ALL CHECKS PASSED" if not FAILED else f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
