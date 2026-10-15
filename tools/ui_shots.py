"""Screenshots of the setup and launcher windows, offline (no install, no download, no registry).

    python tools/ui_shots.py OUT_DIR [--lang ru,de,en]

Opens each window for about a second with demo data (raf_ui.DEMO_HOOK: the GPU probe, the game
search, the install and the download do not run), grabs it from the screen with PIL ImageGrab and
closes it. Also renders the emblem into OUT_DIR/icon (tools/make_icon.py) and points the windows at it.
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_icon  # noqa: E402
import raf_installer as ri  # noqa: E402
import raf_launcher as rl  # noqa: E402
import raf_ui as ui  # noqa: E402
from raf_installer_text import T, set_lang  # noqa: E402

CFG = {"remaster_version": "1.0.1", "game_version": "v1.15", "extra_bytes": 500_000_000,
       "extra_bytes_hd": 2_300_000_000}
SRC, DST = r"C:\Games\Rise and Fall", r"C:\Games\Rise and Fall Remaster"
GPU = {"verdict": {"dxvk": True, "hd": True, "name": "NVIDIA GeForce RTX 5050", "api": "1.4.312", "reason": ""}}
RELEASE = {"tag": "v1.0.1", "body": "Bugfix release.\n\n- No more console windows flashing during the install\n"
                                    "- New icon & a cleaner setup & update window"}
LOG = ["copy: 13160 files, 2.1 GB", "mips: building: python tools/build_textures.py ...", "mips: 86 textures",
       "hd-terrain: 116 textures (12 bump)", "prepared, running ESRGAN", "upscaled, encoding"]


def grab(root, path):
    from PIL import ImageGrab

    root.attributes("-topmost", True)
    root.update()
    hwnd = int(root.wm_frame(), 16)
    r = wt.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)):  # extended frame
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(path)
    print("shot", path)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    langs = sys.argv[sys.argv.index("--lang") + 1].split(",") if "--lang" in sys.argv else ["ru", "de", "en"]
    make_icon.write_all(out / "icon")
    os.environ["RAF_UI_ASSETS"] = str(out / "icon")
    sys.argv = [sys.argv[0]]

    for lang in langs:
        for screen in ("form", "progress", "done"):
            def hook(root, name, h, screen=screen, lang=lang):
                if name != "setup":
                    return
                h["src"].set(SRC)
                h["q"].put(("gpu", GPU))
                root.after(150, lambda: h["q"].put(("src", (SRC, True, T("chk_ok", gv="v1.15"), 2_100_000_000))))
                if screen == "progress":
                    h["st"]["busy"] = h["st"]["started"] = True
                    root.after(400, h["lock"])
                    for line in LOG:
                        h["q"].put(("log", line))
                    h["q"].put(("step", (T("step_build", label=T("f_hd-units"), i=3, n=11), 0.42)))
                    root.after(300, lambda: h["w"]["details"].toggle())
                if screen == "done":
                    h["st"]["started"] = True
                    h["dst"].set(DST)
                    for line in LOG:
                        h["q"].put(("log", line))
                    h["q"].put(("done", {"fingerprint": "40f38837c783", "fingerprint_ok": True, "dxvk": True}))
                root.after(1200, lambda: (grab(root, out / f"setup-{screen}-{lang}.png"), root.destroy()))

            ui.DEMO_HOOK = hook
            set_lang(lang)
            sys.argv = [sys.argv[0], "--lang", lang]
            ri.gui(cfg=CFG, bundle=Path("."))

        def uhook(root, name, h, lang=lang):
            h["q"].put(("step", (T("step_build", label=T("f_shaders"), i=6, n=11), 0.55)))
            for line in LOG:
                h["q"].put(("log", line))
            root.after(1200, lambda: (grab(root, out / f"update-{lang}.png"), root.destroy()))

        ui.DEMO_HOOK = uhook
        set_lang(lang)
        ri.update_gui(Path(DST), Path("."), CFG, "")

        def lhook(root, name, h, lang=lang):
            if name == "launcher-offer":
                root.after(1000, lambda: (grab(root, out / f"launcher-offer-{lang}.png"), h["pick"]("later")))
            else:
                h["st"].update(done=31_400_000, total=80_000_000)
                root.after(1000, lambda: (grab(root, out / f"launcher-download-{lang}.png"),
                                          h["st"].update(finished=True)))

        ui.DEMO_HOOK = lhook
        set_lang(lang)
        rl.ask_update(RELEASE, "1.0.0", "40f38837c783")
        rl.download_with_window(RELEASE, out, test=True)
    ui.DEMO_HOOK = None


if __name__ == "__main__":
    main()
