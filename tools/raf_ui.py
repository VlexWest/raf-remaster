"""Shared look of the setup and launcher windows (tkinter + ttk, no extra dependencies).

    root = raf_ui.window(title)               Tk root with icon, dark theme, fonts
    raf_ui.header(root, title, subtitle)      band with the emblem, title, subtitle and a gold rule
    raf_ui.Details(parent, label_show, label_hide)   collapsible raw log ("Details")
    raf_ui.ready(root, name, **handles)       calls DEMO_HOOK for the offline screenshot script

Palette: deep navy with gold/bronze, matching the emblem (tools/make_icon.py). The emblem files
(raf.ico, raf-header.png) are bundled under "ui" by build_installer.py; when they are missing
(unfrozen tests) the windows simply show no emblem.
"""

import os
import sys
from pathlib import Path

BG = "#101b30"
BAND = "#0a1222"
CARD = "#16243f"
FIELD = "#0c1528"
BORDER = "#2b3c5e"
TEXT = "#ece6d8"
MUTED = "#9aa7bf"
GOLD = "#d8ac4c"
GOLD_HI = "#ecc76f"
GOLD_LO = "#a77d2c"
OK = "#8fd19a"
BAD = "#ef8f7f"
FONT = "Segoe UI"
MONO = "Consolas"

DEMO_HOOK = None  # tools/ui_shots.py: fn(root, name, handles) after a window is laid out


def asset_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui"
    env = os.environ.get("RAF_UI_ASSETS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "work" / "installer" / "ui"


def asset(name):
    p = asset_dir() / name
    return p if p.is_file() else None


def apply_theme(root):
    from tkinter import ttk

    root.configure(background=BG)
    st = ttk.Style(root)
    st.theme_use("clam")
    base = (FONT, 10)
    st.configure(".", background=BG, foreground=TEXT, font=base, bordercolor=BORDER, darkcolor=BG, lightcolor=BG,
                 troughcolor=FIELD, fieldbackground=FIELD, insertcolor=TEXT, selectbackground=GOLD_LO,
                 selectforeground=TEXT, focuscolor=GOLD)
    st.configure("TFrame", background=BG)
    st.configure("Band.TFrame", background=BAND)
    st.configure("Card.TFrame", background=CARD)
    st.configure("Rule.TFrame", background=GOLD)
    st.configure("TLabel", background=BG, foreground=TEXT)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("Ok.TLabel", foreground=OK)
    st.configure("Bad.TLabel", foreground=BAD)
    st.configure("Section.TLabel", foreground=GOLD, font=(FONT, 9, "bold"))
    st.configure("Card.TLabel", background=CARD)
    st.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    st.configure("CardOk.TLabel", background=CARD, foreground=OK)
    st.configure("CardBad.TLabel", background=CARD, foreground=BAD)
    st.configure("CardSection.TLabel", background=CARD, foreground=GOLD, font=(FONT, 9, "bold"))
    st.configure("BandTitle.TLabel", background=BAND, foreground=TEXT, font=(FONT, 17, "bold"))
    st.configure("BandSub.TLabel", background=BAND, foreground=GOLD, font=(FONT, 10))
    st.configure("BandSmall.TLabel", background=BAND, foreground=MUTED, font=(FONT, 9))
    st.configure("Big.TLabel", font=(FONT, 15, "bold"))
    st.configure("Finger.TLabel", background=FIELD, foreground=GOLD_HI, font=(MONO, 24, "bold"), padding=(18, 8),
                 borderwidth=1, relief="solid", bordercolor=GOLD_LO)

    st.configure("TButton", background=CARD, foreground=TEXT, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD,
                 padding=(14, 6), focuscolor=CARD, focusthickness=0)
    st.map("TButton", background=[("disabled", BG), ("pressed", FIELD), ("active", "#1f3156")],
           foreground=[("disabled", "#56627a")], bordercolor=[("active", GOLD_LO)])
    st.configure("Accent.TButton", background=GOLD, foreground="#1a1406", bordercolor=GOLD_LO, lightcolor=GOLD,
                 darkcolor=GOLD, font=(FONT, 10, "bold"), padding=(20, 7), focuscolor=GOLD)
    st.map("Accent.TButton", background=[("disabled", "#3d3522"), ("pressed", GOLD_LO), ("active", GOLD_HI)],
           foreground=[("disabled", "#8a7b55")], bordercolor=[("disabled", "#3d3522")],
           lightcolor=[("disabled", "#3d3522"), ("active", GOLD_HI)], darkcolor=[("disabled", "#3d3522"), ("active", GOLD_HI)])
    st.configure("Link.TButton", background=BG, foreground=MUTED, bordercolor=BG, lightcolor=BG, darkcolor=BG,
                 padding=(0, 2), focuscolor=BG)
    st.map("Link.TButton", background=[("active", BG), ("pressed", BG)], foreground=[("active", GOLD_HI)])

    st.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, bordercolor=BORDER, lightcolor=FIELD,
                 darkcolor=FIELD, padding=(6, 5))
    st.map("TEntry", bordercolor=[("focus", GOLD_LO)], lightcolor=[("focus", FIELD)])
    st.configure("TCombobox", fieldbackground=BAND, background=BAND, foreground=TEXT, arrowcolor=GOLD,
                 bordercolor=BORDER, lightcolor=BAND, darkcolor=BAND, padding=(6, 3))
    st.map("TCombobox", fieldbackground=[("readonly", BAND)], foreground=[("readonly", TEXT)],
           selectbackground=[("readonly", BAND)], selectforeground=[("readonly", TEXT)],
           background=[("active", BAND)], bordercolor=[("active", GOLD_LO), ("focus", GOLD_LO)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", GOLD_LO)
    root.option_add("*TCombobox*Listbox.font", base)
    for name, bg in (("TCheckbutton", BG), ("Card.TCheckbutton", CARD)):
        st.configure(name, background=bg, foreground=TEXT, indicatorbackground=FIELD, indicatorforeground=GOLD_HI,
                     indicatormargin=(0, 0, 8, 0), focuscolor=bg, padding=(0, 3))
        st.map(name, background=[("active", bg)], indicatorbackground=[("selected", FIELD), ("disabled", BG)],
               foreground=[("disabled", "#56627a")])
    _image_checkboxes(root, st)
    st.configure("Horizontal.TProgressbar", background=GOLD, troughcolor=FIELD, bordercolor=BORDER,
                 lightcolor=GOLD_HI, darkcolor=GOLD_LO, thickness=10)
    for sb in ("TScrollbar", "Vertical.TScrollbar"):
        st.configure(sb, background=BORDER, troughcolor=FIELD, bordercolor=FIELD, arrowcolor=MUTED,
                     lightcolor=BORDER, darkcolor=BORDER, gripcount=0, arrowsize=12)
        st.map(sb, background=[("pressed", GOLD_LO), ("active", "#3a4f78")],
               lightcolor=[("active", "#3a4f78")], darkcolor=[("active", "#3a4f78")])
    return st


def _image_checkboxes(root, st):
    """Gold tick boxes instead of clam's X (images from make_icon.py; clam's indicator without them)."""
    import tkinter as tk

    files = {k: asset(f"check-{k}.png") for k in ("on", "off", "on-dis", "off-dis")}
    if not all(files.values()):
        return
    try:
        imgs = {k: tk.PhotoImage(master=root, file=str(f)) for k, f in files.items()}
        root._raf_check_images = imgs  # keep references
        st.element_create("RaF.indicator", "image", imgs["off"],
                          ("disabled", "selected", imgs["on-dis"]), ("disabled", imgs["off-dis"]),
                          ("selected", imgs["on"]), border=0, sticky="w")
        layout = [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("RaF.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w",
                                   "children": [("Checkbutton.label", {"sticky": "nswe"})]})]})]
        for name in ("TCheckbutton", "Card.TCheckbutton"):
            st.layout(name, layout)
            st.configure(name, padding=(0, 3))
        st.configure("Checkbutton.label", padding=(8, 0, 0, 0))
    except Exception:  # noqa: BLE001 - fall back to the theme's own indicator
        pass


def dark_title_bar(root):
    """Windows 10 1809+/11: dark caption matching the header band (ignored where unsupported)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new id, then the pre-20H1 id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        r, g, b = (int(BAND[i:i + 2], 16) for i in (1, 3, 5))
        color = ctypes.c_int(r | g << 8 | b << 16)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)  # caption colour (Win 11)
    except Exception:  # noqa: BLE001
        pass


def set_icon(root):
    ico = asset("raf.ico")
    if ico:
        try:
            root.iconbitmap(default=str(ico))
        except Exception:  # noqa: BLE001 - an icon must never stop the setup
            pass


def window(title, minsize=None):
    import tkinter as tk

    if os.name == "nt":
        try:  # sharp text on scaled displays (raf_patch sets it later anyway)
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    root.title(title)
    set_icon(root)
    apply_theme(root)
    dark_title_bar(root)
    if minsize:
        root.minsize(*minsize)
    return root


def header(parent, title, subtitle=None, right=None):
    """Band across the top: emblem, title, subtitle; `right(frame)` may add widgets on the right."""
    import tkinter as tk
    from tkinter import ttk

    band = ttk.Frame(parent, style="Band.TFrame", padding=(18, 12, 18, 12))
    band.pack(fill="x", side="top")
    png = asset("raf-header-40.png") if _small(parent) else asset("raf-header.png")
    if png:
        try:
            img = tk.PhotoImage(file=str(png))
            lbl = ttk.Label(band, image=img, style="BandTitle.TLabel")
            lbl.image = img
            lbl.pack(side="left", padx=(0, 14))
        except Exception:  # noqa: BLE001
            pass
    txt = ttk.Frame(band, style="Band.TFrame")
    txt.pack(side="left", fill="y")
    ttk.Label(txt, text=title, style="BandTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(txt, text=subtitle, style="BandSub.TLabel").pack(anchor="w")
    if right:
        box = ttk.Frame(band, style="Band.TFrame")
        box.pack(side="right", anchor="n")
        right(box)
    ttk.Frame(parent, style="Rule.TFrame", height=2).pack(fill="x", side="top")
    return band


def _small(widget):
    return bool(getattr(widget.winfo_toplevel(), "_raf_small_header", False))


class Details:
    """'Details' toggle with the raw log underneath, collapsed by default."""

    def __init__(self, parent, show, hide, height=10, expanded=False):
        import tkinter as tk
        from tkinter import ttk

        self.show_text, self.hide_text = show, hide
        self.frame = ttk.Frame(parent)
        self.btn = ttk.Button(self.frame, style="Link.TButton", command=self.toggle)
        self.btn.pack(anchor="w")
        self.body = ttk.Frame(self.frame)
        self.text = tk.Text(self.body, height=height, wrap="word", state="disabled", font=(MONO, 9),
                            background=FIELD, foreground="#c8cfdc", insertbackground=TEXT, relief="flat",
                            borderwidth=0, highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=BORDER, padx=8, pady=6, selectbackground=GOLD_LO)
        sb = ttk.Scrollbar(self.body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.expanded = not expanded
        self.toggle()

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.body.pack(fill="both", expand=True, pady=(4, 0))
            self.btn.configure(text="▾  " + self.hide_text)
        else:
            self.body.pack_forget()
            self.btn.configure(text="▸  " + self.show_text)

    def append(self, line):
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def set_labels(self, show, hide):
        self.show_text, self.hide_text = show, hide
        self.btn.configure(text=("▾  " + hide) if self.expanded else ("▸  " + show))


def center(root):
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    x = max(0, (root.winfo_screenwidth() - w) // 2)
    y = max(0, (root.winfo_screenheight() - h) // 3)
    root.geometry(f"+{x}+{y}")


def ready(root, name, **handles):
    if DEMO_HOOK:
        DEMO_HOOK(root, name, handles)
