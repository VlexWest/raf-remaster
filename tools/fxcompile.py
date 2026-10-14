"""Offline D3D9 effect compiler harness for Rise and Fall .fx files.

Compiles an effect the way the game does (d3dx9_27.dll, D3DXCreateEffectCompiler +
CompileEffect) and, as a second opinion, with d3dcompiler_47 (D3DCompile, target fx_2_0).
Both DLLs are 32-bit for d3dx9_27, so this module must run on a 32-bit Python.
`ensure_py32()` re-executes the current script under one if needed.

Includes ("FX\\Units\\Include\\...") are resolved case-insensitively against a list of
Data roots, first match wins, so an overlay can be compiled on top of the stock files
without copying anything.

Nothing here writes to the game folder: the game's d3dx9_27.dll is only loaded.
"""
import ctypes
import os
import re
import struct
import subprocess
import sys
from ctypes import wintypes

PY32_SPEC = "cpython-3.12-windows-x86-none"


def ensure_py32():
    """Re-run this process under a 32-bit Python (uv-managed) if we are 64-bit."""
    if struct.calcsize("P") == 4:
        return
    exe = os.environ.get("RAF_PY32")
    if not exe:
        try:
            exe = subprocess.check_output(["uv", "python", "find", PY32_SPEC], text=True).strip()
        except Exception as e:  # noqa: BLE001
            sys.exit(f"need a 32-bit Python (set RAF_PY32 or `uv python install {PY32_SPEC}`): {e}")
    r = subprocess.call([exe, "-I"] + sys.argv)
    sys.exit(r)


# ---------------------------------------------------------------- COM helpers
HRESULT = ctypes.c_long


def _vcall(obj, index, restype, *args_types):
    """Return a callable for vtable slot `index` of COM object pointer `obj` (stdcall)."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *args_types)
    return proto(vtbl[index])


def _release(obj):
    if obj:
        _vcall(obj, 2, ctypes.c_ulong)(obj)


def _buffer_bytes(buf):
    if not buf:
        return b""
    ptr = _vcall(buf, 3, ctypes.c_void_p)(buf)
    size = _vcall(buf, 4, ctypes.c_ulong)(buf)
    return ctypes.string_at(ptr, size)


class _Macro(ctypes.Structure):
    _fields_ = [("Name", ctypes.c_char_p), ("Definition", ctypes.c_char_p)]


def _macros(defines):
    arr = (_Macro * (len(defines) + 1))()
    keep = []
    for i, (k, v) in enumerate(defines.items()):
        kb, vb = k.encode(), str(v).encode()
        keep += [kb, vb]
        arr[i].Name, arr[i].Definition = kb, vb
    arr[len(defines)].Name = None
    arr[len(defines)].Definition = None
    return arr, keep


# ---------------------------------------------------------------- include handler
class DataRoots:
    """Case-insensitive lookup of 'FX\\...' paths over several Data roots (first wins)."""

    def __init__(self, roots):
        self.maps = []
        for root in roots:
            m = {}
            for dp, _, fns in os.walk(root):
                for fn in fns:
                    p = os.path.join(dp, fn)
                    m[os.path.relpath(p, root).replace("\\", "/").lower()] = p
            self.maps.append(m)

    def find(self, rel):
        key = rel.replace("\\", "/").lower().lstrip("/")
        for m in self.maps:
            if key in m:
                return m[key]
        return None


_OPEN = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint))
_CLOSE = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p)


class _IncludeVtbl(ctypes.Structure):
    _fields_ = [("Open", _OPEN), ("Close", _CLOSE)]


class _Include(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_IncludeVtbl))]


class IncludeHandler:
    """ID3DXInclude / ID3DInclude (same vtable layout: Open, Close)."""

    def __init__(self, roots):
        self.roots = roots
        self.opened = {}
        self.used = []
        self.missing = []
        self._open = _OPEN(self._on_open)
        self._close = _CLOSE(self._on_close)
        self.vtbl = _IncludeVtbl(self._open, self._close)
        self.obj = _Include(ctypes.pointer(self.vtbl))

    def _on_open(self, this, typ, name, parent, pp_data, p_bytes):
        rel = name.decode("latin1")
        path = self.roots.find(rel)
        if not path:
            self.missing.append(rel)
            return -2147467259  # E_FAIL
        data = open(path, "rb").read()
        buf = ctypes.create_string_buffer(data, len(data))
        addr = ctypes.addressof(buf)
        self.opened[addr] = buf
        self.used.append(path)
        pp_data[0] = addr
        p_bytes[0] = len(data)
        return 0

    def _on_close(self, this, data):
        self.opened.pop(data, None)
        return 0

    @property
    def ptr(self):
        return ctypes.byref(self.obj)


# ---------------------------------------------------------------- d3dx9_27
class D3DXEffectDesc(ctypes.Structure):
    _fields_ = [("Creator", ctypes.c_char_p), ("Parameters", ctypes.c_uint),
                ("Techniques", ctypes.c_uint), ("Functions", ctypes.c_uint)]


class D3DXParameterDesc(ctypes.Structure):
    _fields_ = [("Name", ctypes.c_char_p), ("Semantic", ctypes.c_char_p), ("Class", ctypes.c_int),
                ("Type", ctypes.c_int), ("Rows", ctypes.c_uint), ("Columns", ctypes.c_uint),
                ("Elements", ctypes.c_uint), ("Annotations", ctypes.c_uint),
                ("StructMembers", ctypes.c_uint), ("Flags", ctypes.c_ulong), ("Bytes", ctypes.c_uint)]


class D3DXTechniqueDesc(ctypes.Structure):
    _fields_ = [("Name", ctypes.c_char_p), ("Passes", ctypes.c_uint), ("Annotations", ctypes.c_uint)]


class D3DXPassDesc(ctypes.Structure):
    _fields_ = [("Name", ctypes.c_char_p), ("Annotations", ctypes.c_uint),
                ("pVertexShaderFunction", ctypes.c_void_p), ("pPixelShaderFunction", ctypes.c_void_p)]


# ID3DXBaseEffect / ID3DXEffectCompiler vtable slots (d3dx9effect.h, 2004-2005 SDKs)
V_GETDESC, V_GETPARAMDESC, V_GETTECHDESC, V_GETPASSDESC = 3, 4, 5, 6
V_GETPARAM, V_GETTECH, V_GETPASS, V_GETANNOT = 8, 12, 14, 18
V_GETSTRING = 51
V_COMPILEEFFECT = 59
PARAM_TYPE_STRING = 4  # D3DXPT_STRING


class D3DX27:
    def __init__(self, dll_path):
        os.add_dll_directory(os.path.dirname(dll_path)) if hasattr(os, "add_dll_directory") else None
        self.dll = ctypes.WinDLL(dll_path)
        self.dll.D3DXCreateEffectCompiler.restype = HRESULT
        self.dll.D3DXCreateEffectCompiler.argtypes = [
            ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        self.dll.D3DXGetShaderInputSemantics.restype = HRESULT
        self.dll.D3DXGetShaderInputSemantics.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                         ctypes.POINTER(ctypes.c_uint)]
        self.dll.D3DXDisassembleShader.restype = HRESULT
        self.dll.D3DXDisassembleShader.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p,
                                                   ctypes.POINTER(ctypes.c_void_p)]

    def disassemble(self, code_ptr):
        out = ctypes.c_void_p()
        hr = self.dll.D3DXDisassembleShader(code_ptr, 0, None, ctypes.byref(out))
        if hr < 0:
            return None
        txt = _buffer_bytes(out.value).rstrip(b"\0").decode("latin1")
        _release(out.value)
        return txt

    def input_semantics(self, code_ptr):
        """Vertex inputs a shader reads, as sorted 'USAGE#index' strings."""
        arr = (ctypes.c_uint * 128)()
        n = ctypes.c_uint(0)
        if self.dll.D3DXGetShaderInputSemantics(code_ptr, arr, ctypes.byref(n)) < 0:
            return None
        names = {0: "POSITION", 1: "BLENDWEIGHT", 2: "BLENDINDICES", 3: "NORMAL", 4: "PSIZE",
                 5: "TEXCOORD", 6: "TANGENT", 7: "BINORMAL", 8: "TESSFACTOR", 9: "POSITIONT",
                 10: "COLOR", 11: "FOG", 12: "DEPTH", 13: "SAMPLE"}
        return sorted(f"{names.get(arr[2 * i], arr[2 * i])}{arr[2 * i + 1]}" for i in range(n.value))

    def create_effect(self, device, src_path, defines, roots, flags=None):
        """D3DXCreateEffect on a device, as the engine does. Returns (ok, errors)."""
        flags = ENGINE_FLAGS if flags is None else flags
        f = self.dll.D3DXCreateEffect
        f.restype = HRESULT
        f.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        src = open(src_path, "rb").read()
        inc = IncludeHandler(roots)
        mac, _keep = _macros(defines)
        eff, errs = ctypes.c_void_p(), ctypes.c_void_p()
        hr = f(device, src, len(src), ctypes.cast(mac, ctypes.c_void_p), ctypes.cast(inc.ptr, ctypes.c_void_p),
               flags, None, ctypes.byref(eff), ctypes.byref(errs))
        msg = _buffer_bytes(errs.value).rstrip(b"\0").decode("latin1")
        _release(errs.value)
        _release(eff.value)
        return hr >= 0 and bool(eff.value), msg + ("" if hr >= 0 else f"\nD3DXCreateEffect hr=0x{hr & 0xffffffff:08x}")

    def compile_effect(self, src_path, defines, roots, flags=None):
        """Returns dict(ok, errors, blob, interface, shaders)."""
        flags = ENGINE_FLAGS if flags is None else flags
        src = open(src_path, "rb").read()
        inc = IncludeHandler(roots)
        mac, _keep = _macros(defines)
        comp, errs = ctypes.c_void_p(), ctypes.c_void_p()
        hr = self.dll.D3DXCreateEffectCompiler(src, len(src), ctypes.cast(mac, ctypes.c_void_p),
                                               ctypes.cast(inc.ptr, ctypes.c_void_p), flags,
                                               ctypes.byref(comp), ctypes.byref(errs))
        res = {"ok": False, "errors": _buffer_bytes(errs.value).rstrip(b"\0").decode("latin1"),
               "blob": b"", "interface": None, "shaders": [], "includes": inc.used,
               "missing_includes": inc.missing}
        _release(errs.value)
        if hr < 0 or not comp.value:
            res["errors"] = (res["errors"] + f"\nD3DXCreateEffectCompiler hr=0x{hr & 0xffffffff:08x}").strip()
            return res
        c = comp.value
        try:
            eff, errs2 = ctypes.c_void_p(), ctypes.c_void_p()
            hr = _vcall(c, V_COMPILEEFFECT, HRESULT, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(ctypes.c_void_p))(c, flags, ctypes.byref(eff), ctypes.byref(errs2))
            msg = _buffer_bytes(errs2.value).rstrip(b"\0").decode("latin1")
            _release(errs2.value)
            if msg:
                res["errors"] = (res["errors"] + "\n" + msg).strip()
            if hr < 0:
                res["errors"] = (res["errors"] + f"\nCompileEffect hr=0x{hr & 0xffffffff:08x}").strip()
                return res
            res["blob"] = _buffer_bytes(eff.value)
            _release(eff.value)
            res["interface"] = self._interface(c)
            res["shaders"] = self._shaders(res["blob"])
            res["ok"] = res["blob"][:4] == b"\x01\x09\xff\xfe"
            if not res["ok"]:
                res["errors"] += "\nunexpected effect blob magic " + res["blob"][:4].hex()
        finally:
            _release(c)
        return res

    # -- interface description through the compiler's ID3DXBaseEffect methods
    def _annotations(self, c, h, count):
        out = []
        get_annot = _vcall(c, V_GETANNOT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
        pdesc = _vcall(c, V_GETPARAMDESC, HRESULT, ctypes.c_void_p, ctypes.POINTER(D3DXParameterDesc))
        gets = _vcall(c, V_GETSTRING, HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p))
        for i in range(count):
            ha = get_annot(c, h, i)
            d = D3DXParameterDesc()
            pdesc(c, ha, ctypes.byref(d))
            val = None
            if d.Type == PARAM_TYPE_STRING:
                s = ctypes.c_char_p()
                if gets(c, ha, ctypes.byref(s)) >= 0 and s.value is not None:
                    val = s.value.decode("latin1")
            out.append((d.Name.decode() if d.Name else "", d.Type, val))
        return out

    def _interface(self, c):
        desc = D3DXEffectDesc()
        _vcall(c, V_GETDESC, HRESULT, ctypes.POINTER(D3DXEffectDesc))(c, ctypes.byref(desc))
        get_param = _vcall(c, V_GETPARAM, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
        pdesc = _vcall(c, V_GETPARAMDESC, HRESULT, ctypes.c_void_p, ctypes.POINTER(D3DXParameterDesc))
        get_tech = _vcall(c, V_GETTECH, ctypes.c_void_p, ctypes.c_uint)
        tdesc = _vcall(c, V_GETTECHDESC, HRESULT, ctypes.c_void_p, ctypes.POINTER(D3DXTechniqueDesc))
        get_pass = _vcall(c, V_GETPASS, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
        passdesc = _vcall(c, V_GETPASSDESC, HRESULT, ctypes.c_void_p, ctypes.POINTER(D3DXPassDesc))
        params = []
        for i in range(desc.Parameters):
            h = get_param(c, None, i)
            d = D3DXParameterDesc()
            if pdesc(c, h, ctypes.byref(d)) < 0:
                params.append(("?", i))
                continue
            params.append({
                "name": d.Name.decode() if d.Name else "",
                "semantic": d.Semantic.decode() if d.Semantic else "",
                "class": d.Class, "type": d.Type, "rows": d.Rows, "cols": d.Columns,
                "elements": d.Elements, "struct_members": d.StructMembers,
                "annotations": self._annotations(c, h, d.Annotations),
            })
        techs = []
        for i in range(desc.Techniques):
            h = get_tech(c, i)
            d = D3DXTechniqueDesc()
            tdesc(c, h, ctypes.byref(d))
            passes = []
            for j in range(d.Passes):
                hp = get_pass(c, h, j)
                pd = D3DXPassDesc()
                passdesc(c, hp, ctypes.byref(pd))
                passes.append(pd.Name.decode() if pd.Name else "")
            techs.append({"name": d.Name.decode() if d.Name else "", "passes": passes,
                          "annotations": self._annotations(c, h, d.Annotations)})
        return {"creator": desc.Creator.decode() if desc.Creator else "", "parameters": params,
                "techniques": techs, "functions": desc.Functions}

    # -- find shader bytecode inside the fx_2_0 blob and disassemble each one
    _VER = re.compile(rb"(?=([\x00-\x03][\x01-\x03]\xfe\xff|[\x00-\x03][\x01-\x03]\xff\xff))")

    def _shaders(self, blob):
        out = []
        seen_end = -1
        for m in self._VER.finditer(blob):
            off = m.start()
            if off < seen_end or off % 4:
                continue
            ver = struct.unpack_from("<I", blob, off)[0]
            major, minor = (ver >> 8) & 0xff, ver & 0xff
            if not (1 <= major <= 3):
                continue
            # the dword before the shader is its byte size in an fx_2_0 blob
            if off < 4:
                continue
            size = struct.unpack_from("<I", blob, off - 4)[0]
            if size < 8 or off + size > len(blob) or size % 4:
                continue
            end_tok = struct.unpack_from("<I", blob, off + size - 4)[0]
            if end_tok != 0x0000FFFF:
                continue
            buf = ctypes.create_string_buffer(blob[off:off + size], size)
            txt = self.disassemble(ctypes.addressof(buf)) or ""
            prof = ("vs" if (ver >> 16) == 0xFFFE else "ps") + (f"_{major}_x" if minor == 1 and major == 2 else f"_{major}_{minor}")
            inputs = self.input_semantics(ctypes.addressof(buf)) if prof.startswith("vs") else None
            m2 = re.search(r"//\s*approximately (\d+) instruction slots used(?: \((\d+) texture, (\d+) arithmetic\))?", txt)
            out.append({"profile": prof, "bytes": size, "inputs": inputs,
                        "slots": int(m2.group(1)) if m2 else None,
                        "tex": int(m2.group(2)) if m2 and m2.group(2) else None,
                        "arith": int(m2.group(3)) if m2 and m2.group(3) else None})
            seen_end = off + size
        return out


# ---------------------------------------------------------------- D3D9 NULLREF device
# The engine calls D3DXCreateEffectFromFileA(device, file, defines, its own include
# handler, Flags = 0x20 (D3DXSHADER_PARTIALPRECISION), NULL pool, ...)
# (DX9Rasterizer.dll 0x10010f58..0x10010f79). The stock water effect only fits the
# vs_1_1 slot limit with that flag, so every check uses it.
ENGINE_FLAGS = 0x20


class _PresentParams(ctypes.Structure):
    _fields_ = [("BackBufferWidth", ctypes.c_uint), ("BackBufferHeight", ctypes.c_uint),
                ("BackBufferFormat", ctypes.c_int), ("BackBufferCount", ctypes.c_uint),
                ("MultiSampleType", ctypes.c_int), ("MultiSampleQuality", ctypes.c_ulong),
                ("SwapEffect", ctypes.c_int), ("hDeviceWindow", ctypes.c_void_p), ("Windowed", ctypes.c_int),
                ("EnableAutoDepthStencil", ctypes.c_int), ("AutoDepthStencilFormat", ctypes.c_int),
                ("Flags", ctypes.c_ulong), ("FullScreen_RefreshRateInHz", ctypes.c_uint),
                ("PresentationInterval", ctypes.c_uint)]


def create_nullref_device():
    """A D3D9 NULLREF device (no rendering, no GPU work) so D3DXCreateEffect can run."""
    d3d9 = ctypes.WinDLL("d3d9.dll")
    d3d9.Direct3DCreate9.restype = ctypes.c_void_p
    d3d = d3d9.Direct3DCreate9(32)
    if not d3d:
        return None
    pp = _PresentParams()
    pp.BackBufferWidth = pp.BackBufferHeight = 16
    pp.Windowed = 1
    pp.SwapEffect = 1
    pp.hDeviceWindow = ctypes.windll.user32.GetDesktopWindow()
    dev = ctypes.c_void_p()
    create = _vcall(d3d, 16, HRESULT, ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                    ctypes.POINTER(_PresentParams), ctypes.POINTER(ctypes.c_void_p))
    hr = create(d3d, 0, 4, pp.hDeviceWindow, 0x20, ctypes.byref(pp), ctypes.byref(dev))  # NULLREF, SW VP
    return dev.value if hr >= 0 else None


# ---------------------------------------------------------------- d3dcompiler_47
D3DCOMPILE_ENABLE_BACKWARDS_COMPATIBILITY = 1 << 12


class D3DCompiler47:
    def __init__(self, dll_path=None):
        self.dll = ctypes.WinDLL(dll_path or "d3dcompiler_47.dll")
        f = self.dll.D3DCompile
        f.restype = HRESULT
        f.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                      ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]

    def compile_effect(self, src_path, defines, roots,
                       flags=D3DCOMPILE_ENABLE_BACKWARDS_COMPATIBILITY | ENGINE_FLAGS):
        src = open(src_path, "rb").read()
        inc = IncludeHandler(roots)
        mac, _keep = _macros(defines)
        code, errs = ctypes.c_void_p(), ctypes.c_void_p()
        hr = self.dll.D3DCompile(src, len(src), os.path.basename(src_path).encode("latin1"),
                                 ctypes.cast(mac, ctypes.c_void_p), ctypes.cast(inc.ptr, ctypes.c_void_p),
                                 None, b"fx_2_0", flags, 0, ctypes.byref(code), ctypes.byref(errs))
        msg = _buffer_bytes(errs.value).rstrip(b"\0").decode("latin1")
        blob = _buffer_bytes(code.value)
        _release(errs.value)
        _release(code.value)
        return {"ok": hr >= 0 and bool(blob), "errors": msg + ("" if hr >= 0 else f"\nhr=0x{hr & 0xffffffff:08x}"),
                "bytes": len(blob)}


def interface_key(iface):
    """Normalise an interface description for stock-vs-ours comparison."""
    params = {}
    for p in iface["parameters"]:
        if isinstance(p, tuple):
            continue
        params[p["name"]] = (p["semantic"], p["class"], p["type"], p["rows"], p["cols"], p["elements"],
                             p["struct_members"], tuple(p["annotations"]))
    techs = {t["name"]: (tuple(t["passes"]), tuple(t["annotations"])) for t in iface["techniques"]}
    return params, techs


def diff_interface(stock, ours):
    """List of human-readable differences (empty means compatible)."""
    sp, st = interface_key(stock)
    op, ot = interface_key(ours)
    out = []
    for n in sorted(set(sp) | set(op)):
        if n not in op:
            out.append(f"parameter removed: {n}")
        elif n not in sp:
            out.append(f"parameter added: {n} {op[n][:1]}")
        elif sp[n] != op[n]:
            out.append(f"parameter changed: {n} {sp[n]} -> {op[n]}")
    for n in sorted(set(st) | set(ot)):
        if n not in ot:
            out.append(f"technique removed: {n}")
        elif n not in st:
            out.append(f"technique added: {n}")
        elif st[n] != ot[n]:
            out.append(f"technique changed: {n} {st[n]} -> {ot[n]}")
    return out
