import csv, sys
from collections import Counter, defaultdict
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
tot = sum(int(r["size"]) for r in rows)
print("TOTAL", len(rows), round(tot/2**20,1), "MB")
per = defaultdict(lambda: [0,0])
for r in rows:
    per[r["top"]][0]+=1; per[r["top"]][1]+=int(r["size"])
for k,(n,s) in sorted(per.items(), key=lambda x:-x[1][1]):
    print("FOLDER", k, n, round(s/2**20,2))
print("RES", sorted(Counter(f'{r["w"]}x{r["h"]}' for r in rows).items(), key=lambda x:-x[1]))
print("FMT", Counter(r["fmt"] for r in rows).most_common())
print("MIPS yes", sum(1 for r in rows if int(r["mips"])>1), "no", sum(1 for r in rows if int(r["mips"])<=1))
print("CUBE", sum(1 for r in rows if r["cube"]=="True"))
print("NPOT", sum(1 for r in rows if (int(r["w"])&(int(r["w"])-1)) or (int(r["h"])&(int(r["h"])-1))))
print("NONSQ", sum(1 for r in rows if r["w"]!=r["h"]))
print("TEXTURES_FOLDER_RES", sorted(Counter(f'{r["w"]}x{r["h"]}' for r in rows if r["top"]=="textures").items(), key=lambda x:-x[1])[:20])
print("TEXTURES_FOLDER_FMT", Counter(r["fmt"] for r in rows if r["top"]=="textures").most_common())
print("LARGEST")
for r in sorted(rows, key=lambda r:-int(r["size"]))[:15]:
    print(round(int(r["size"])/2**20,2), r["rel"], r["w"], r["h"], r["fmt"], r["mips"])
# name flags
import re
flags = {"normal":r"(_n|_nm|_normal|_bump|_nrm)\.", "spec/gloss":r"(_s|_spec|_gloss|_sp)\.", "mask/alpha":r"_(mask|alpha|a)\.", "team/color":r"(team|color|player|tc)[_\.]", "env/cube":r"(env|cube|sky)"}
for k,pat in flags.items():
    hits=[r["rel"] for r in rows if re.search(pat, r["name"].lower())]
    print("FLAG", k, len(hits), hits[:6])
