"""RaF Remaster.exe: checks for a remaster update, then starts the game (frozen by build_installer.py,
PyInstaller onedir with the contents folder .raf-launcher next to the exe).

    RaF Remaster.exe [game arguments]      e.g. -hostgame "Name" -playername "Me" -pid "1" -pass "raf"
    RaF Remaster.exe --check-updates       check now, also says "up to date"
    RaF Remaster.exe --skip-check [args]   start the game without a check (used after an update)
Unfrozen (tests): python tools/raf_launcher.py --game <dir> [...]

The game always starts with -datapath "Data\\" -redistpath "Redist\\" plus the launcher's own
arguments, passed on verbatim (the game reads values between the first pair of quotes).
Nothing is installed without the player clicking "Update now"; offline, a private repository or any
error just starts the game.
"""

import base64
import ctypes
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import raf_proc
import raf_update as ru
from raf_installer_text import T, detect_lang, set_lang

APP = "Rise and Fall Remaster"
OWN_FLAGS = ("--skip-check", "--check-updates")
GAME_ARGS = '-datapath "Data\\" -redistpath "Redist\\"'


def game_dir(argv) -> Path:
    if "--game" in argv[:-1]:
        return Path(argv[argv.index("--game") + 1]).resolve()
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def raw_args() -> str:
    """The command line after the program name, exactly as typed (quotes kept)."""
    try:
        line = ctypes.windll.kernel32.GetCommandLineW
        line.restype = ctypes.c_wchar_p
        cmd = line()
    except Exception:  # noqa: BLE001
        cmd = None
    if not cmd:
        return subprocess.list2cmdline(sys.argv[1:])
    return split_program(cmd)


def split_program(cmd: str) -> str:
    """Drop argv[0] (Windows rules: quoted up to the next quote, else up to whitespace)."""
    cmd = cmd.lstrip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        rest = "" if end < 0 else cmd[end + 1:]
    else:
        parts = cmd.split(None, 1)
        rest = parts[1] if len(parts) > 1 else ""
    return rest.lstrip()


def strip_own(tail: str):
    """(flags, rest): leading launcher flags (--skip-check, --check-updates, --game <dir> for tests)."""
    flags = set()
    while True:
        for f in OWN_FLAGS:
            if tail == f or tail.startswith(f + " "):
                flags.add(f)
                tail = tail[len(f):].lstrip()
                break
        else:
            if tail.startswith("--game "):  # unfrozen tests only
                rest = tail[7:].lstrip()
                if rest.startswith('"'):
                    end = rest.find('"', 1)
                    tail = rest[end + 1:].lstrip()
                else:
                    tail = (rest.split(None, 1) + [""])[1]
                continue
            return flags, tail


def game_command(game: Path, tail: str) -> str:
    return f'"{game / ru.GAME_EXE}" {GAME_ARGS}' + (f" {tail}" if tail else "")


def start_game(game: Path, tail: str, override: dict) -> None:
    cmd = game_command(game, tail)
    if override.get("dry_run_game"):  # tests (loopback override only): record instead of starting
        with open(override["dry_run_game"], "a", encoding="utf-8") as f:
            f.write(cmd + "\n")
        return
    subprocess.Popen(cmd, cwd=str(game), close_fds=True, creationflags=raf_proc.NO_WINDOW)


def setup_command(setup: Path, game: Path, tail: str, lang: str, headless_log=None) -> list:
    cmd = [str(setup), "--update", str(game), "--wait-pid", str(os.getpid()), "--lang", lang,
           "--relaunch-b64", base64.urlsafe_b64encode(tail.encode("utf-8")).decode("ascii") or "-"]
    if headless_log:
        cmd += ["--headless", "--log", str(headless_log)]
    return cmd


# ---------------------------------------------------------------- dialogs (tkinter, only when needed)


def _tk_root(title=None):
    import raf_ui as ui

    root = ui.window(title or T("upd_title", app=APP))
    root.attributes("-topmost", True)
    root.resizable(False, False)
    return root


def ask_update(release: dict, installed: str, fp: str) -> str:
    """'update' | 'later' | 'skip' (window closed = later)."""
    import tkinter as tk
    from tkinter import ttk

    import raf_ui as ui

    root = _tk_root()
    answer = {"v": "later"}
    new = ru.norm(release["tag"])
    ui.header(root, APP, T("upd_head"))
    frm = ttk.Frame(root, padding=(24, 16, 24, 20))
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=T("upd_available", new=new, cur=installed), font=(ui.FONT, 12, "bold"),
              wraplength=540, justify="left").pack(anchor="w")
    text = ru.excerpt(release.get("body", ""))
    if text:
        ttk.Label(frm, text=T("upd_changes").rstrip(":").upper(), style="Section.TLabel").pack(anchor="w",
                                                                                         pady=(14, 4))
        box = tk.Text(frm, width=66, height=min(14, max(4, text.count("\n") + 2)), wrap="word",
                      font=(ui.FONT, 10), relief="flat", background=ui.CARD, foreground=ui.TEXT, borderwidth=0,
                      highlightthickness=0, padx=12, pady=8)
        box.insert("1.0", text)
        box.configure(state="disabled")
        box.pack(anchor="w", fill="x")
    ttk.Label(frm, text=T("upd_mp", cur=installed, fp=fp), wraplength=540, justify="left",
              style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(18, 0))

    def pick(v):
        answer["v"] = v
        root.destroy()

    ttk.Button(btns, text=T("btn_skip"), style="Link.TButton", command=lambda: pick("skip")).pack(side="left")
    ttk.Button(btns, text=T("btn_later"), command=lambda: pick("later")).pack(side="right")
    b = ttk.Button(btns, text=T("btn_update"), style="Accent.TButton", command=lambda: pick("update"))
    b.pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", lambda: pick("later"))
    b.focus_set()
    root.after(200, lambda: root.attributes("-topmost", False))
    ui.center(root)
    ui.ready(root, "launcher-offer", pick=pick)
    root.mainloop()
    return answer["v"]


def download_with_window(release: dict, folder: Path, test: bool):
    """Download in a thread under a small progress window. Returns (path or None, error or None)."""
    import tkinter as tk
    from tkinter import ttk

    import raf_ui as ui

    root = _tk_root()
    st = {"done": 0, "total": 1, "result": None, "error": None, "cancel": False, "finished": False}
    ui.header(root, APP, T("upd_dl_head") + f" · {ru.norm(release['tag'])}")
    frm = ttk.Frame(root, padding=(24, 16, 24, 20))
    frm.pack(fill="both", expand=True)
    label = tk.StringVar(value=T("upd_download", done=0, total=0))
    ttk.Label(frm, textvariable=label, width=60).pack(anchor="w")
    bar = ttk.Progressbar(frm, maximum=1000, length=480)
    bar.pack(fill="x", pady=(8, 14))
    ttk.Button(frm, text=T("btn_cancel"), command=lambda: st.update(cancel=True)).pack(anchor="e")
    root.protocol("WM_DELETE_WINDOW", lambda: st.update(cancel=True))

    def work():
        try:
            st["result"] = ru.download_setup(release, folder, progress=lambda d, t: st.update(done=d, total=t),
                                             cancel=lambda: st["cancel"], test=test)
        except ru.UpdateError as e:
            st["error"] = str(e)
        except Exception as e:  # noqa: BLE001
            st["error"] = f"{type(e).__name__}: {e}"
        st["finished"] = True

    def poll():
        label.set(T("upd_download", done=st["done"] / 1e6, total=st["total"] / 1e6))
        bar.configure(value=int(1000 * st["done"] / max(st["total"], 1)))
        if st["finished"]:
            root.destroy()
        else:
            root.after(100, poll)

    ui.center(root)
    if ui.DEMO_HOOK:  # offline screenshots: no download
        ui.ready(root, "launcher-download", st=st)
    else:
        threading.Thread(target=work, daemon=True).start()
    poll()
    root.mainloop()
    return st["result"], st["error"]


def message(text: str, error=False) -> None:
    MB_ICONERROR, MB_ICONINFO, MB_TOPMOST = 0x10, 0x40, 0x40000
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP, (MB_ICONERROR if error else MB_ICONINFO) | MB_TOPMOST)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- main


def log_path() -> Path:
    return Path(os.environ.get("TEMP", ".")) / "RaF-Remaster-Launcher.log"


def log(s: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + s + "\n")
    except OSError:
        pass


def run(argv, tail: str) -> int:
    game = game_dir(argv)
    flags, tail = strip_own(tail)
    override = ru.load_override(game)
    info = ru.install_info(game)
    set_lang(info.get("lang") or detect_lang())
    installed = ru.installed_version(game)
    if "--skip-check" in flags or override.get("disabled"):
        start_game(game, tail, override)
        return 0
    folder = ru.download_dir(override)
    ru.cleanup_downloads(folder)
    force = "--check-updates" in flags
    res = ru.check(game, force=force, override=override)
    log(f"{game}: installed {installed}, check {res['source']}, error {res['error']}, "
        f"latest {(res['release'] or {}).get('tag')}")
    offer = ru.to_offer(game, res["release"], installed) if not force else (
        res["release"] if res["release"] and ru.is_newer(res["release"].get("tag"), installed) else None)
    if offer is None:
        if force:
            message(T("upd_check_failed", msg=res["error"]) if res["error"] else T("upd_none", cur=installed),
                    error=bool(res["error"]))
        start_game(game, tail, override)
        return 0
    answer = override.get("test_answer") or ask_update(offer, installed, ru.installed_fingerprint(game))
    log(f"offer {offer['tag']}: {answer}")
    if answer == "skip":
        ru.skip_version(game, offer["tag"])
    elif answer == "update":
        if override.get("test"):
            try:
                setup, err = ru.download_setup(offer, folder, test=True), None
            except ru.UpdateError as e:
                setup, err = None, str(e)
        else:
            setup, err = download_with_window(offer, folder, test=False)
        if setup:
            hl = Path(override["dry_run_game"]).with_suffix(".setup.log") if override.get("dry_run_game") else None
            cmd = setup_command(setup, game, tail, info.get("lang") or detect_lang(), hl)
            log("starting " + subprocess.list2cmdline(cmd))
            subprocess.Popen(cmd, cwd=str(folder), close_fds=True, creationflags=raf_proc.NO_WINDOW)
            return 0  # the setup waits for this process, updates, then starts the game
        log(f"download failed: {err}")
        if err != "cancelled":
            message(T("upd_err_download", msg=err), error=True)
    else:
        ru.snooze(game, offer["tag"])
    start_game(game, tail, override)
    return 0


def main() -> int:
    raf_proc.install()  # windowed exe: no console window for any child
    argv = sys.argv[1:]
    tail = raw_args() if getattr(sys, "frozen", False) else subprocess.list2cmdline(argv)
    try:
        return run(argv, tail)
    except Exception:  # noqa: BLE001 - the game must start whatever the updater does
        log(traceback.format_exc())
        game = game_dir(argv)
        try:
            start_game(game, strip_own(tail)[1], ru.load_override(game))
        except Exception:  # noqa: BLE001
            log(traceback.format_exc())
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
