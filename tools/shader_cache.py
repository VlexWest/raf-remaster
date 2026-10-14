"""Print what the engine wrote to shader.cache: the defines it compiles effects with and
how often each permutation flag was used (read-only).

Usage: python tools/shader_cache.py "<game_dir>/shader.cache"

In-game check: after a skirmish with the overlay installed, k_IsNormalMapped should be
counted for effect 20 (units). If it is 0 while units are on screen, the engine has
dropped normal maps (flag needs pixel shader 2.0 caps) and units use the vertex-normal
per-pixel path only.
"""
import collections
import sys

from check_shaders import parse_shader_cache


def main():
    defines, records = parse_shader_cache(sys.argv[1])
    for k, v in defines.items():
        print(f"{k} = {v}")
    print(f"{len(records)} permutation records")
    per_effect = collections.Counter(eff for eff, _, _ in records)
    print("records per effect id:", dict(sorted(per_effect.items())))
    flags = collections.Counter(f for eff, _, fl in records if eff == 20 for f in fl)
    print("unit effect (id 20) flag counts:")
    for f, n in flags.most_common():
        print(f"  {f}: {n}")


if __name__ == "__main__":
    main()
