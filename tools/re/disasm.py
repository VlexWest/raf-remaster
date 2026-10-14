"""dis.py <pe> <start_va> <end_va> : disassemble a VA range (x86-32)."""
import sys
sys.path.insert(0,'work/tools/py'); sys.path.insert(0,'work/scripts')
import capstone
from xref import load, va2off
d,b,s=load(sys.argv[1]); a=int(sys.argv[2],16); e=int(sys.argv[3],16)
o=va2off(s,b,a)
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
for i in md.disasm(d[o:o+(e-a)],a):
    print(f"{i.address:08x}: {i.bytes.hex():<16} {i.mnemonic} {i.op_str}")
