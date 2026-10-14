import sys,struct
sys.path.insert(0,r'work\tools\py')
import pefile,capstone
PATH=r'D:\Games\Rise and Fall\RiseAndFall.exe'
pe=pefile.PE(PATH,fast_load=True)
base=pe.OPTIONAL_HEADER.ImageBase
data=open(PATH,'rb').read()
def off2va(o):
    for s in pe.sections:
        if s.PointerToRawData<=o<s.PointerToRawData+s.SizeOfRawData: return base+s.VirtualAddress+o-s.PointerToRawData
def va2off(v):
    for s in pe.sections:
        if s.VirtualAddress<=v-base<s.VirtualAddress+s.Misc_VirtualSize: return v-base-s.VirtualAddress+s.PointerToRawData
def xrefs(va):
    pat=struct.pack('<I',va); r=[];i=data.find(pat)
    while i>=0: r.append(off2va(i)); i=data.find(pat,i+1)
    return r
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
def dis(va,n=60):
    o=va2off(va)
    for k,ins in enumerate(md.disasm(data[o:o+n*8],va)):
        if k>=n:break
        print('%08x  %-8s %s'%(ins.address,ins.mnemonic,ins.op_str))
if __name__=='__main__':
    cmd=sys.argv[1]
    if cmd=='str':
        s=sys.argv[2].encode(); o=data.find(s+b'\0'); va=off2va(o); print('str va %x'%va); print(['%x'%x for x in xrefs(va)])
    elif cmd=='dis': dis(int(sys.argv[2],16),int(sys.argv[3]) if len(sys.argv)>3 else 60)
