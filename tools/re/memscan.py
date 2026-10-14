"""memscan.py <pid> <hex bytes pattern> [dump_before dump_after] : find pattern in committed private/image memory."""
import ctypes, ctypes.wintypes as wt, sys, struct
k=ctypes.windll.kernel32
class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD)]
def regions(h):
    a=0; m=MBI()
    while a<0x100000000 and k.VirtualQueryEx(h,ctypes.c_void_p(a),ctypes.byref(m),ctypes.sizeof(m)):
        base=m.BaseAddress or 0
        if m.State==0x1000 and (m.Protect&0xEE) and not (m.Protect&0x100): yield base,m.RegionSize
        a=base+m.RegionSize
def read(h,a,n):
    buf=ctypes.create_string_buffer(n); r=ctypes.c_size_t()
    k.ReadProcessMemory(h,ctypes.c_void_p(a),buf,n,ctypes.byref(r)); return buf.raw[:r.value]
def openp(pid): return k.OpenProcess(0x0410,False,pid)
if __name__=='__main__':
    pid=int(sys.argv[1]); pat=bytes.fromhex(sys.argv[2]); before=int(sys.argv[3]) if len(sys.argv)>3 else 0; after=int(sys.argv[4]) if len(sys.argv)>4 else 64
    h=openp(pid); hits=0
    for b,n in regions(h):
        d=read(h,b,n); i=d.find(pat)
        while i>=0 and hits<20:
            hits+=1; print(hex(b+i)); blk=read(h,b+i-before,before+after)
            print('  ',[struct.unpack_from('<I',blk,j)[0] for j in range(0,len(blk)-3,4)])
            i=d.find(pat,i+1)
