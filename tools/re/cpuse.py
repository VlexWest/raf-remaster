import re,json,collections
C=open(r'decomp\RiseAndFall.c',encoding='latin1').read().splitlines()
B=0xd2cd00
use=collections.defaultdict(set); fn=None
for l in C:
    if l.startswith('// ==== '): fn=l.split()[2]; continue
    for m in re.finditer(r'DAT_(00d2[c-f][0-9a-f]{3})',l):
        a=int(m.group(1),16)
        if B<=a<B+143*0x38:
            r=(a-B)//0x38; f=((a-B)%0x38)//4
            use[r].add((f,fn))
named=collections.defaultdict(list)
for r,f,off,name,how in json.load(open(r'decomp\ai_param_map.json')):
    named[r].append((f,name,how))
json.dump({'named':named,'use':{k:sorted(v) for k,v in use.items()}},open(r'decomp\cp_usage.json','w'))
for r in range(143):
    if r not in named:
        print(r, sorted(use.get(r,[]))[:6])
