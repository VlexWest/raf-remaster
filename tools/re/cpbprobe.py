"""cpbprobe.py <pid> [ids] : read dbcpbehavior records from the global array 0x00d2cd00 + id*0x38 (v4 i32, v7 i32, v12 f32)."""
import sys, struct
import memscan
h = memscan.openp(int(sys.argv[1]))
ids = [int(x) for x in (sys.argv[2].split(',') if len(sys.argv) > 2 else '1,2,6,7,11,28,29,88,97,98,114'.split(','))]
for i in ids:
    r = memscan.read(h, 0x00d2cd00 + i * 0x38, 0x38)
    f = struct.unpack('<14i', r); v12 = struct.unpack_from('<f', r, 48)[0]
    print(f"id {i:3d} (row {f[0]}, id {f[1]}): v4 {f[4]} v7 {f[7]} v12 {v12:g}")
