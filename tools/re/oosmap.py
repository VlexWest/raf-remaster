import rx,re,json,sys
start,end=int(sys.argv[1],16),int(sys.argv[2],16)
o=rx.va2off(start)
ins=list(rx.md.disasm(rx.data[o:o+(end-start)],start))
res={}
def cstr(va):
    o=rx.va2off(va)
    if o is None: return None
    e=rx.data.find(b'\0',o); return rx.data[o:e].decode('latin1')
last=[]
for i in ins:
    m=re.search(r'\[(e[a-z]{2}) \+ (0x[0-9a-f]+)\]',i.op_str)
    if m and i.mnemonic in('mov','fld','movzx','movsx','fild'): last.append((m.group(1),int(m.group(2),16)))
    if i.mnemonic=='push' and i.op_str.startswith('0x'):
        s=cstr(int(i.op_str,16))
        if s and 'OUT OF SYNCH' in s and last:
            name=s.split('DUMP:')[1].strip().split(':')[0].strip()
            fmt='f' if '%6.6f' in s else 'i'
            res.setdefault(hex(last[-1][1]),[]).append((name,fmt,last[-1][0]))
            last=[]
json.dump(res,open(sys.argv[3],'w'),indent=0)
print(len(res))
