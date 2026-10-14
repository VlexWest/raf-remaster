"""Group DDS files by filename prefix for the remaster inventory. Reads a CSV from dds_inventory.py.
Usage: python texture_groups.py <dds.csv>
"""
import csv, re, sys
from collections import OrderedDict

GROUPS = OrderedDict([
    ("terrain (trn_)", r"^trn_"),
    ("terrain-adjacent (sha_, grnd_)", r"^(sha_|grnd_)"),
    ("buildings (bld_, wall_, brg_)", r"^(bld_|wall_|brg_)"),
    ("units/animals/ships/siege (men_, cav_, anml_, spc_, gun_, nav_)", r"^(men_|cav_|anml_|spc_|gun_|nav_)"),
    ("vegetation (amb_, flo_, res_, speedtree/)", r"^(amb_|flo_|res_)"),
    ("sky/env cubes (*_cube_ldr, *envmap*, sky, cloud, light_)", r"(_cube_ldr|envmap|sky|cloud|^light_)"),
    ("effects (sfx_, fx_)", r"^(sfx_|fx_)"),
    ("UI (but_, cur_, 3dui_, ui_, frm_, sel_, circle, square, scenfull, miscicons, alphabox)", r"^(but_|cur_|3dui_|ui_|frm_|sel_|circle|square|scenfull|miscicons|alphabox)"),
    ("thumbnails (*_thumb*)", r"_thumb"),
    ("test/debug (*test*)", r"test"),
])

def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
    assigned = set()
    print("| group | files | MB |")
    print("|---|---|---|")
    for label, pat in GROUPS.items():
        hit = [r for r in rows if r["rel"] not in assigned and re.search(pat, r["name"], re.I)]
        if label.startswith("vegetation"):
            hit += [r for r in rows if r["top"] == "speedtree" and r["rel"] not in assigned and r not in hit]
        for r in hit:
            assigned.add(r["rel"])
        print(f"| {label} | {len(hit)} | {sum(int(r['size']) for r in hit)/2**20:.1f} |")
    rest = [r for r in rows if r["rel"] not in assigned]
    print(f"| other (bump maps not caught above, misc single-word names) | {len(rest)} | {sum(int(r['size']) for r in rest)/2**20:.1f} |")

if __name__ == "__main__":
    main()
