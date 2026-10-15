"""Child processes without console windows.

The setup and the launcher are windowed exes (no console of their own), so every console program
they start (texconv, realesrgan-ncnn-vulkan, powershell, tasklist, git, the Vulkan probe) would
open a console window of its own: one flash per texture during an HD install.

    NO_WINDOW            CREATE_NO_WINDOW on Windows, 0 elsewhere; OR it into creationflags
    flags(extra=0)       extra | NO_WINDOW
    install()            makes every later subprocess.Popen (run, call, check_output, ...) add it

CREATE_NO_WINDOW only affects console programs; Windows ignores it for GUI programs (the game, the
setup started by the launcher), so it is safe on every call. No STARTUPINFO SW_HIDE: that would also
hide the first window of a GUI program such as the game.
"""

import os
import subprocess

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_OWN_CONSOLE = 0x00000010 | 0x00000008  # CREATE_NEW_CONSOLE, DETACHED_PROCESS: the caller wants its own


def flags(extra: int = 0) -> int:
    return extra | NO_WINDOW


def install() -> None:
    """Hook subprocess.Popen once: CREATE_NO_WINDOW is added to whatever flags a caller passes."""
    if not NO_WINDOW or getattr(subprocess.Popen.__init__, "_raf_no_window", False):
        return
    orig = subprocess.Popen.__init__

    def init(self, *a, **k):
        cf = k.get("creationflags") or 0
        if len(a) >= 14:  # creationflags given positionally (no caller here does that)
            cf = a[13] or 0
            a = a[:13] + (cf if cf & _OWN_CONSOLE else cf | NO_WINDOW,) + a[14:]
        elif not cf & _OWN_CONSOLE:
            k["creationflags"] = cf | NO_WINDOW
        orig(self, *a, **k)

    init._raf_no_window = True
    init._raf_orig = orig
    subprocess.Popen.__init__ = init


def uninstall() -> None:
    """Tests only."""
    cur = subprocess.Popen.__init__
    if getattr(cur, "_raf_no_window", False):
        subprocess.Popen.__init__ = cur._raf_orig
