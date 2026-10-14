import re,json,sys
C=open(r'decomp\RiseAndFall.c',encoding='latin1').read().splitlines()
idx={}
for i,l in enumerate(C):
    if l.startswith('// ==== '): idx[l.split()[2].lower()]=i
def body(addr):
    s=idx[addr]; e=s+1
    while e<len(C) and not C[e].startswith('// ==== '): e+=1
    return C[s:e]
oos=json.load(open(r'decomp\ai_oos_map.json'))
oosn={int(k,16):(v[0][0],v[0][1]) for k,v in oos.items()}
B=0xd2cd00
def rf(a):
    a-=B; return a//0x38, (a%0x38)//4
SRC=re.compile(r'(?:= |\(float\)\(?|FUN_0046bd20\()_?DAT_(00d2[c-f][0-9a-f]{3})')
def getter_src(fn):
    for l in body(fn):
        m=re.search(r"(?:= |ROUND\()_?DAT_(00d2[c-f][0-9a-f]{3})[;)]",l)
        if m: return int(m.group(1),16)
def scan(fn):
    out=[]; src=None; how=''
    for l in body(fn):
        m=SRC.search(l)
        if m:
            src=int(m.group(1),16); how=('pct/100 ' if '/ 100.0' in l else '')
            if '60000' in l: how+='minutes->ms '
        m=re.search(r'= (FUN_[0-9a-f]+)\(iVar1\)',l)
        if m:
            g=getter_src(m.group(1)[4:].lower().rjust(8,'0'))
            if g: src=g; how='getter '+m.group(1)+' '
        if '/ 100.0' in l and src: how='pct/100 '
        if '60000' in l and 'minutes' not in how: how+='minutes->ms '
        m=re.search(r'^\s*\*?\(?\*?\(\w+ \*\)\(in_ECX \+ (0x[0-9a-f]+)\) = ',l) or re.search(r'^\s*\*\((\w+) \*\)\(in_ECX \+ (0x[0-9a-f]+)\) = ',l)
        m=re.search(r'^\s*\*\(\w+ \*\)\(in_ECX \+ (0x[0-9a-f]+)\) = ',l)
        if m and src and B<=src<B+0x38*160:
            off=int(m.group(1),16); r,f=rf(src)
            out.append((r,f,off,oosn.get(off,('?',''))[0],how.strip()))
            src=None; how=''
        m2=re.search(r'\(in_ECX \+ 0x10d8\) \+ (0x[0-9a-f]+|\d+)\) = |\*\*\(float \*\*\)\(in_ECX \+ 0x10d8\) = ',l)
        if m2 and src and B<=src<B+0x38*160:
            o=m2.group(1) or '0'; r,f=rf(src)
            out.append((r,f,'sub+'+o,'(spending sub-object)',how.strip())); src=None; how=''
    return out
res=scan('004701a0')
for r in res: print(r)
json.dump(res,open(r'decomp\ai_param_map.json','w'))
