"""xref.py <pe> <ascii string>... : print string VAs and every code location holding that VA as imm32."""
import os, sys, struct, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'work', 'tools', 'py'))
def load(p):
    d=open(p,'rb').read()
    pe=struct.unpack_from('<I',d,0x3c)[0]
    nsec=struct.unpack_from('<H',d,pe+6)[0]; opt=struct.unpack_from('<H',d,pe+20)[0]
    base=struct.unpack_from('<I',d,pe+24+28)[0]
    secs=[]; o=pe+24+opt
    for i in range(nsec):
        vs,va,rs,ro=struct.unpack_from('<IIII',d,o+8); secs.append((va,vs,ro,rs)); o+=40
    return d,base,secs
def off2va(secs,base,off):
    for va,vs,ro,rs in secs:
        if ro<=off<ro+rs: return base+va+off-ro
def va2off(secs,base,v):
    for va,vs,ro,rs in secs:
        if base+va<=v<base+va+rs: return v-base-va+ro
if __name__=='__main__':
    d,b,s=load(sys.argv[1])
    for st in sys.argv[2:]:
        for m in re.finditer(re.escape(st.encode())+b'\0', d):
            if m.start()>0 and d[m.start()-1]!=0: continue
            v=off2va(s,b,m.start()); print(st, 'VA', hex(v))
            for r in re.finditer(re.escape(struct.pack('<I',v)), d):
                print('   ref at', hex(off2va(s,b,r.start())), 'op', d[r.start()-1:r.start()].hex())
