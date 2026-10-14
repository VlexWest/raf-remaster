"""Tiny software renderer for effect A/B tests: Direct3D 9 REF device (d3dref9.dll,
no GPU), D3DXCreateEffect from d3dx9_27 with the engine's flags, one quad.

Used by tools/check_shaders.py to render stock and overlay unit shaders with the same
inputs and compare pixels. 32-bit Python only (see fxcompile.ensure_py32).
"""
import ctypes
import struct

import fxcompile as fc

HR = ctypes.c_long
VP = ctypes.c_void_p

D3DDEVTYPE_REF = 2
D3DCREATE_SOFTWARE_VERTEXPROCESSING = 0x20
D3DFMT_A8R8G8B8 = 21
D3DFMT_D24S8 = 75
D3DPOOL_MANAGED = 1
D3DPT_TRIANGLESTRIP = 5
D3DCLEAR_TARGET, D3DCLEAR_ZBUFFER = 1, 2
D3DRS_FOGENABLE, D3DRS_FOGCOLOR, D3DRS_FOGTABLEMODE, D3DRS_FOGVERTEXMODE = 28, 34, 35, 140

# IDirect3DDevice9 slots
DEV_RELEASE, DEV_CREATETEXTURE, DEV_CREATERT = 2, 23, 28
DEV_GETRTDATA, DEV_CREATEOFFSCREEN, DEV_SETRT = 32, 36, 37
DEV_BEGINSCENE, DEV_ENDSCENE, DEV_CLEAR = 41, 42, 43
DEV_SETRS, DEV_DRAWPRIMUP, DEV_CREATEDECL, DEV_SETDECL = 57, 83, 86, 87
# ID3DXEffect slots (ID3DXBaseEffect 0..56 then ID3DXEffect)
FX_SETVALUE, FX_SETTEXTURE = 20, 52
FX_SETTECHNIQUE, FX_VALIDATETECHNIQUE = 58, 60
FX_BEGIN, FX_BEGINPASS, FX_COMMIT, FX_ENDPASS, FX_END = 63, 64, 65, 66, 67
# IDirect3DTexture9 / IDirect3DSurface9 slots
TEX_LOCKRECT, TEX_UNLOCKRECT = 19, 20
SURF_LOCKRECT, SURF_UNLOCKRECT = 13, 14


class _LockedRect(ctypes.Structure):
    _fields_ = [("Pitch", ctypes.c_int), ("pBits", VP)]


class _VertexElement(ctypes.Structure):
    _fields_ = [("Stream", ctypes.c_ushort), ("Offset", ctypes.c_ushort), ("Type", ctypes.c_ubyte),
                ("Method", ctypes.c_ubyte), ("Usage", ctypes.c_ubyte), ("UsageIndex", ctypes.c_ubyte)]


# full unit vertex: every element VS_INPUT may read
# (offset, D3DDECLTYPE, D3DDECLUSAGE, usage index)
UNIT_DECL = [(0, 2, 0, 0),    # POSITION float3
             (12, 2, 3, 0),   # NORMAL float3
             (24, 3, 1, 0),   # BLENDWEIGHT float4
             (40, 4, 2, 0),   # BLENDINDICES D3DCOLOR
             (44, 1, 5, 0),   # TEXCOORD0 float2
             (52, 1, 5, 1),   # TEXCOORD1 float2
             (60, 2, 7, 0),   # BINORMAL float3
             (72, 2, 6, 0),   # TANGENT float3
             (84, 4, 10, 0)]  # COLOR0 D3DCOLOR
UNIT_STRIDE = 88

# terrain / water vertex (Terrain Data Structures.fx VS_INPUT)
TERRAIN_DECL = [(0, 1, 0, 0),    # POSITION float2
                (8, 2, 3, 0),    # NORMAL0 float3
                (20, 3, 3, 1),   # NORMAL1 float4 (LOD weights)
                (36, 1, 5, 0),   # TEXCOORD0 float2 (mask uv)
                (44, 4, 10, 0),  # COLOR0 D3DCOLOR
                (48, 4, 2, 0)]   # BLENDINDICES0 D3DCOLOR (LOD index)
TERRAIN_STRIDE = 52


def terrain_vertex(xy, normal, mask_uv, color=0xFF808080, lod=(1, 0, 0, 0)):
    return struct.pack("<2f3f4f2fII", *xy, *normal, *lod, *mask_uv, color, 0)


def unit_vertex(pos, normal, uv, binormal=(1, 0, 0), tangent=(0, 1, 0), color=0xFFFFFFFF,
                weights=(1, 0, 0, 0), indices=0):
    return struct.pack("<3f3f4fI2f2f3f3fI", *pos, *normal, *weights, indices, *uv, *uv, *binormal, *tangent, color)


class RefDevice:
    def __init__(self, d3dx_path, size=64):
        self.size = size
        self.dx = fc.D3DX27(d3dx_path)
        d3d9 = ctypes.WinDLL("d3d9.dll")
        d3d9.Direct3DCreate9.restype = VP
        self.d3d = d3d9.Direct3DCreate9(32)
        pp = fc._PresentParams()
        pp.BackBufferWidth = pp.BackBufferHeight = size
        pp.BackBufferFormat = D3DFMT_A8R8G8B8
        pp.Windowed = 1
        pp.SwapEffect = 1
        pp.EnableAutoDepthStencil = 1
        pp.AutoDepthStencilFormat = D3DFMT_D24S8
        pp.hDeviceWindow = ctypes.windll.user32.GetDesktopWindow()
        dev = VP()
        create = fc._vcall(self.d3d, 16, HR, ctypes.c_uint, ctypes.c_int, VP, ctypes.c_ulong,
                           ctypes.POINTER(fc._PresentParams), ctypes.POINTER(VP))
        hr = create(self.d3d, 0, D3DDEVTYPE_REF, pp.hDeviceWindow, D3DCREATE_SOFTWARE_VERTEXPROCESSING,
                    ctypes.byref(pp), ctypes.byref(dev))
        if hr < 0:
            raise RuntimeError(f"REF device: hr=0x{hr & 0xffffffff:08x}")
        self.dev = dev.value
        rt = VP()
        hr = fc._vcall(self.dev, DEV_CREATERT, HR, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                       ctypes.c_ulong, ctypes.c_int, ctypes.POINTER(VP), VP)(
            self.dev, size, size, D3DFMT_A8R8G8B8, 0, 0, 1, ctypes.byref(rt), None)
        if hr < 0:
            raise RuntimeError(f"CreateRenderTarget hr=0x{hr & 0xffffffff:08x}")
        self.rt = rt.value
        fc._vcall(self.dev, DEV_SETRT, HR, ctypes.c_ulong, VP)(self.dev, 0, self.rt)
        self.decls = {"unit": (self._decl(UNIT_DECL), UNIT_STRIDE),
                      "terrain": (self._decl(TERRAIN_DECL), TERRAIN_STRIDE)}
        self.textures = []

    def _decl(self, elements):
        els = (_VertexElement * (len(elements) + 1))()
        for i, (off, typ, usage, idx) in enumerate(elements):
            els[i] = _VertexElement(0, off, typ, 0, usage, idx)
        els[len(elements)] = _VertexElement(0xFF, 0, 17, 0, 0, 0)  # D3DDECL_END
        decl = VP()
        hr = fc._vcall(self.dev, DEV_CREATEDECL, HR, VP, ctypes.POINTER(VP))(
            self.dev, ctypes.cast(els, VP), ctypes.byref(decl))
        if hr < 0:
            raise RuntimeError(f"CreateVertexDeclaration hr=0x{hr & 0xffffffff:08x}")
        return decl.value

    def cube_texture(self, size, rgba_fn):
        """A8R8G8B8 cube map, one level, rgba_fn(face, x, y) -> (r, g, b, a)."""
        f = self.dx.dll.D3DXCreateCubeTexture
        f.restype = HR
        f.argtypes = [VP, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                      ctypes.POINTER(VP)]
        tex = VP()
        hr = f(self.dev, size, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, ctypes.byref(tex))
        if hr < 0:
            raise RuntimeError(f"D3DXCreateCubeTexture hr=0x{hr & 0xffffffff:08x}")
        lock = fc._vcall(tex.value, 19, HR, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_LockedRect), VP,
                         ctypes.c_ulong)
        unlock = fc._vcall(tex.value, 20, HR, ctypes.c_int, ctypes.c_uint)
        for face in range(6):
            lr = _LockedRect()
            lock(tex.value, face, 0, ctypes.byref(lr), None, 0)
            for y in range(size):
                row = b"".join(bytes((b, g, r, a)) for r, g, b, a in (rgba_fn(face, x, y) for x in range(size)))
                ctypes.memmove(lr.pBits + y * lr.Pitch, row, len(row))
            unlock(tex.value, face, 0)
        self.textures.append(tex.value)
        return tex.value

    def texture(self, w, h, rgba_fn):
        """A8R8G8B8 texture, one level, rgba_fn(x, y) -> (r, g, b, a) bytes."""
        f = self.dx.dll.D3DXCreateTexture
        f.restype = HR
        f.argtypes = [VP, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int,
                      ctypes.c_int, ctypes.POINTER(VP)]
        tex = VP()
        hr = f(self.dev, w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, ctypes.byref(tex))
        if hr < 0:
            raise RuntimeError(f"D3DXCreateTexture hr=0x{hr & 0xffffffff:08x}")
        lr = _LockedRect()
        fc._vcall(tex.value, TEX_LOCKRECT, HR, ctypes.c_uint, ctypes.POINTER(_LockedRect), VP, ctypes.c_ulong)(
            tex.value, 0, ctypes.byref(lr), None, 0)
        for y in range(h):
            row = b"".join(bytes((b, g, r, a)) for r, g, b, a in (rgba_fn(x, y) for x in range(w)))
            ctypes.memmove(lr.pBits + y * lr.Pitch, row, len(row))
        fc._vcall(tex.value, TEX_UNLOCKRECT, HR, ctypes.c_uint)(tex.value, 0)
        self.textures.append(tex.value)
        return tex.value

    def effect(self, src_path, defines, roots):
        f = self.dx.dll.D3DXCreateEffect
        f.restype = HR
        f.argtypes = [VP, ctypes.c_char_p, ctypes.c_uint, VP, VP, ctypes.c_ulong, VP,
                      ctypes.POINTER(VP), ctypes.POINTER(VP)]
        src = open(src_path, "rb").read()
        inc = fc.IncludeHandler(roots)
        mac, _keep = fc._macros(defines)
        eff, errs = VP(), VP()
        hr = f(self.dev, src, len(src), ctypes.cast(mac, VP), ctypes.cast(inc.ptr, VP), fc.ENGINE_FLAGS, None,
               ctypes.byref(eff), ctypes.byref(errs))
        msg = fc._buffer_bytes(errs.value).rstrip(b"\0").decode("latin1")
        fc._release(errs.value)
        if hr < 0:
            raise RuntimeError(f"D3DXCreateEffect failed: {msg}")
        return eff.value

    def render(self, eff, technique, params, textures, vertices, fog=None, layout="unit"):
        """Draw a triangle strip with every pass of `technique`; return (w, h, RGBA bytes)."""
        d = self.dev
        fc._vcall(d, DEV_CLEAR, HR, ctypes.c_ulong, VP, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float,
                  ctypes.c_ulong)(d, 0, None, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xFF000000, 1.0, 0)
        setrs = fc._vcall(d, DEV_SETRS, HR, ctypes.c_int, ctypes.c_ulong)
        if fog is not None:
            setrs(d, D3DRS_FOGENABLE, 1)
            setrs(d, D3DRS_FOGCOLOR, fog)
            setrs(d, D3DRS_FOGTABLEMODE, 0)
            setrs(d, D3DRS_FOGVERTEXMODE, 0)
        else:
            setrs(d, D3DRS_FOGENABLE, 0)
        hr = fc._vcall(eff, FX_SETTECHNIQUE, HR, ctypes.c_char_p)(eff, technique.encode())
        if hr < 0:
            raise RuntimeError(f"SetTechnique({technique}) hr=0x{hr & 0xffffffff:08x}")
        hr = fc._vcall(eff, FX_VALIDATETECHNIQUE, HR, ctypes.c_char_p)(eff, technique.encode())
        if hr < 0:
            raise RuntimeError(f"ValidateTechnique({technique}) hr=0x{hr & 0xffffffff:08x}")
        setv = fc._vcall(eff, FX_SETVALUE, HR, ctypes.c_char_p, VP, ctypes.c_uint)
        for name, vals in params.items():
            if isinstance(vals, int) and not isinstance(vals, bool):
                data = struct.pack("<i", vals)
            else:
                data = struct.pack(f"<{len(vals)}f", *vals)
            buf = ctypes.create_string_buffer(data, len(data))
            setv(eff, name.encode(), buf, len(data))  # unknown names fail quietly, as in the engine
        sett = fc._vcall(eff, FX_SETTEXTURE, HR, ctypes.c_char_p, VP)
        for name, tex in textures.items():
            sett(eff, name.encode(), tex)
        decl, stride = self.decls[layout]
        fc._vcall(d, DEV_SETDECL, HR, VP)(d, decl)
        fc._vcall(d, DEV_BEGINSCENE, HR)(d)
        npass = ctypes.c_uint()
        fc._vcall(eff, FX_BEGIN, HR, ctypes.POINTER(ctypes.c_uint), ctypes.c_ulong)(eff, ctypes.byref(npass), 0)
        vb = b"".join(vertices)
        vbuf = ctypes.create_string_buffer(vb, len(vb))
        for p in range(npass.value):
            fc._vcall(eff, FX_BEGINPASS, HR, ctypes.c_uint)(eff, p)
            fc._vcall(d, DEV_DRAWPRIMUP, HR, ctypes.c_int, ctypes.c_uint, VP, ctypes.c_uint)(
                d, D3DPT_TRIANGLESTRIP, len(vertices) - 2, vbuf, stride)
            fc._vcall(eff, FX_ENDPASS, HR)(eff)
        fc._vcall(eff, FX_END, HR)(eff)
        fc._vcall(d, DEV_ENDSCENE, HR)(d)
        return self.read_rt(), npass.value

    def read_rt(self):
        lr = _LockedRect()
        hr = fc._vcall(self.rt, SURF_LOCKRECT, HR, ctypes.POINTER(_LockedRect), VP, ctypes.c_ulong)(
            self.rt, ctypes.byref(lr), None, 0x10)  # D3DLOCK_READONLY
        if hr < 0:
            raise RuntimeError(f"LockRect(RT) hr=0x{hr & 0xffffffff:08x}")
        n = self.size
        out = bytearray()
        for y in range(n):
            row = ctypes.string_at(lr.pBits + y * lr.Pitch, n * 4)
            for x in range(n):
                b, g, r, a = row[4 * x:4 * x + 4]
                out += bytes((r, g, b, a))
        fc._vcall(self.rt, SURF_UNLOCKRECT, HR)(self.rt)
        return bytes(out)

    @staticmethod
    def pixel(img, size, x, y):
        o = 4 * (y * size + x)
        return tuple(img[o:o + 4])
