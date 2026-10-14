"""peek.py <pid> <hexaddr> [count] [fmt f|I] : read count dwords."""
import sys, struct
sys.path.insert(0, 'work/scripts'); import memscan
h = memscan.openp(int(sys.argv[1])); a = int(sys.argv[2], 16); n = int(sys.argv[3]) if len(sys.argv) > 3 else 1
f = sys.argv[4] if len(sys.argv) > 4 else 'f'
d = memscan.read(h, a, 4 * n); print([round(x, 4) if f == 'f' else x for x in struct.unpack(f'<{n}{f}', d)])
