"""modes.py [set W H HZ] : list primary display modes >=1920 wide and current mode; optionally set a mode (not persisted)."""
import ctypes, ctypes.wintypes as wt, sys
class DM(ctypes.Structure):
    _fields_=[('n',wt.WCHAR*32),('a',wt.WORD*4),('f',wt.DWORD),('pos',wt.LONG*2),('o',wt.DWORD*2),('c',ctypes.c_short*5),('form',wt.WCHAR*32),('lp',wt.WORD),('bpp',wt.DWORD),('w',wt.DWORD),('h',wt.DWORD),('df',wt.DWORD),('hz',wt.DWORD)]
u=ctypes.windll.user32; u.SetProcessDPIAware()
def dm(): m=DM(); m.a[2]=ctypes.sizeof(DM); return m
if len(sys.argv)>1 and sys.argv[1]=='set':
    m=dm(); m.w,m.h,m.hz=map(int,sys.argv[2:5]); m.bpp=32; m.f=0x00080000|0x00100000|0x00400000|0x00040000
    print('set ->', u.ChangeDisplaySettingsW(ctypes.byref(m),0))
m=dm(); i=0; s=set()
while u.EnumDisplaySettingsW(None,i,ctypes.byref(m)):
    s.add((m.w,m.h,m.hz,m.bpp)); i+=1
print(i,'modes;', sorted(x[:3] for x in s if x[3]==32 and x[0]>=1920))
c=dm(); u.EnumDisplaySettingsW(None,-1,ctypes.byref(c)); print('current',c.w,c.h,c.hz)
