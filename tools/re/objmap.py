import re,json
C=open(r'decomp\RiseAndFall.c',encoding='latin1').read().splitlines()
def body(addr):
    s=next(i for i,l in enumerate(C) if l.startswith('// ==== '+addr)); e=s+1
    while not C[e].startswith('// ==== '): e+=1
    return C[s:e]
def num(x): return int(x,16) if x.startswith('0x') else int(x)
# 1) OOS names for objdef (in_ECX[0x24] + Y)
oos={}
# find OOS function containing 'Base Hit Points'
s=next(i for i,l in enumerate(C) if 'Base Hit Points:' in l)
st=max(i for i in range(s) if C[i].startswith('// ==== '))
en=next(i for i in range(s,len(C)) if C[i].startswith('// ==== '))
txt='\n'.join(C[st:en])
for m in re.finditer(r'"OUT OF SYNCH DUMP:\s+([^"%]+?):?\s*(?:\t)*\s*%[^"]*",\s*(?:SUB84\(\(double\))?\*?\(?\w*\s*\*?\)?\(?in_ECX\[0x24\] \+ (0x[0-9a-f]+|\d+)\)',txt):
    oos[num(m.group(2))]=m.group(1).strip()
for m in re.finditer(r'"OUT OF SYNCH DUMP:\s+([^"%]+?):?\s*%[^"]*",\s*\n?\s*\(uint\)\(\*\(char \*\)\(in_ECX\[0x24\] \+ (0x[0-9a-f]+|\d+)\)',txt):
    oos[num(m.group(2))]=m.group(1).strip()
# 2) record->objdef copy
mp=[]
for l in body('00a1dd00'):
    m=re.search(r'(?:\*\((\w+) \*\)\(in_ECX \+ (0x[0-9a-f]+|\d+)\)|in_ECX\[(0x[0-9a-f]+|\d+)\]) = (.*);',l)
    if not m: continue
    dst=num(m.group(2) or m.group(3)); rhs=m.group(4)
    s2=re.search(r'\((\w+) \*\)\(param_2 \+ (0x[0-9a-f]+|\d+)\)',rhs)
    if not s2: continue
    typ=s2.group(1); src=num(s2.group(2))
    if typ=='UReferenceCounter': typ='u8'
    tr='round' if 'ROUND' in rhs else ''
    if '* 1000' in rhs: tr+='x1000'
    mp.append((src,typ,dst,oos.get(dst,''),tr))
seen={}
for r in mp: seen.setdefault(r[0],r)
json.dump({'oos':oos,'map':sorted(seen.values())},open(r'decomp\dbobjects_map.json','w'),indent=0)
print(len(oos),len(seen))
for r in sorted(seen.values()): print(hex(r[0]),r[1],hex(r[2]),r[3],r[4])
