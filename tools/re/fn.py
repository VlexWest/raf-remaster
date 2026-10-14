"""fn.py <c file> <hexaddr>... : print the decompiled function containing each address."""
import sys, re, bisect
txt=open(sys.argv[1],encoding='utf-8',errors='replace').read()
heads=[(int(m.group(1),16),m.start()) for m in re.finditer(r'^// ==== ([0-9a-f]{8}) ',txt,re.M)]
heads.sort(); addrs=[h[0] for h in heads]
for a in sys.argv[2:]:
    a=int(a,16); i=bisect.bisect_right(addrs,a)-1
    s=heads[i][1]; e=heads[i+1][1] if i+1<len(heads) else len(txt)
    print(txt[s:e])
