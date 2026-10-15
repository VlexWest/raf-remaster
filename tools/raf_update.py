"""Update logic shared by the launcher (raf_launcher.py) and the installer's update mode.

Release check: GET https://api.github.com/repos/<repo>/releases/latest (3 s timeout), result cached in
<game>/.raf-remaster/update-cache.json for 6 h (1 h after a failed check). A private repository or a
missing release answers 404/403: that is "no update", silently, like being offline.
Download: the release asset RaF-Remaster-Setup.exe, https only (http only for a loopback test server
named in update.json), size checked against the API and a sanity range, sha256 from the asset
RaF-Remaster-Setup.exe.sha256 or a "sha256: <hex>" line in the release text. No hash = no update.
Install: the downloaded setup runs with --update <game dir> (raf_installer.run_update): it builds the
new version into a sibling folder from the original game, swaps the folders, copies the player's
own files over and only then deletes the old folder (rollback = the old folder, untouched until then).

Per-install override <game>/.raf-remaster/update.json (optional):
    {"repo": "owner/name"}             another GitHub repository
    {"disabled": true}                 never check
    {"api": "http://127.0.0.1:8123/latest", "test_answer": "update", "dry_run_game": "<file>",
     "download_dir": "<dir>"}          tests only: honoured only when "api" is a loopback URL
"""

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from raf_version import UPDATE_REPO, VERSION

STATE_DIR = ".raf-remaster"
CACHE_FILE = "update-cache.json"
OVERRIDE_FILE = "update.json"
INSTALL_FILE = "install.json"
SETUP_ASSET = "RaF-Remaster-Setup.exe"
HASH_ASSET = SETUP_ASSET + ".sha256"
LAUNCHER_EXE = "RaF Remaster.exe"
LAUNCHER_DIR = ".raf-launcher"  # PyInstaller contents directory of the launcher
GAME_EXE = "RiseAndFall.exe"
API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/latest"
CHECK_EVERY = 6 * 3600
RETRY_AFTER_ERROR = 3600
SNOOZE = 6 * 3600
TIMEOUT = 3.0
MIN_SIZE, MAX_SIZE = 5_000_000, 1_000_000_000
USER_AGENT = f"RaF-Remaster-Launcher/{VERSION}"


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------- versions


def parse_version(s):
    """'v1.2.3' / '1.2.3' / '1.2' -> (1, 2, 3); anything else (pre-releases too) -> None."""
    m = re.fullmatch(r"\s*v?(\d+)\.(\d+)(?:\.(\d+))?\s*", str(s or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(tag, installed) -> bool:
    a, b = parse_version(tag), parse_version(installed)
    return a is not None and b is not None and a > b


def norm(tag) -> str:
    v = parse_version(tag)
    return ".".join(map(str, v)) if v else str(tag)


# ---------------------------------------------------------------- config + cache


def state_dir(game: Path) -> Path:
    return Path(game) / STATE_DIR


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False  # read-only install: the check simply runs again next time


def is_loopback(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def load_override(game: Path) -> dict:
    o = _read_json(state_dir(game) / OVERRIDE_FILE)
    test = isinstance(o.get("api"), str) and is_loopback(o["api"])
    if not test:  # test switches only work against a local test server
        for k in ("api", "test_answer", "dry_run_game", "download_dir"):
            o.pop(k, None)
    o["test"] = test
    return o


def api_url(override: dict) -> str:
    if override.get("api"):
        return override["api"]
    repo = override.get("repo") if re.fullmatch(r"[\w.-]+/[\w.-]+", str(override.get("repo", ""))) else UPDATE_REPO
    return API_TEMPLATE.format(repo=repo)


def read_cache(game: Path) -> dict:
    return _read_json(state_dir(game) / CACHE_FILE)


def write_cache(game: Path, cache: dict) -> bool:
    return _write_json(state_dir(game) / CACHE_FILE, cache)


def install_info(game: Path) -> dict:
    return _read_json(state_dir(game) / INSTALL_FILE)


def installed_version(game: Path) -> str:
    """install.json, else state.json (raf_patch writes "version"), else this build's VERSION."""
    v = install_info(game).get("version") or _read_json(state_dir(game) / "state.json").get("version")
    return str(v or VERSION)


def installed_fingerprint(game: Path) -> str:
    return str(_read_json(state_dir(game) / "state.json").get("fingerprint") or "?")


# ---------------------------------------------------------------- GitHub


def _allowed(url: str, test: bool) -> bool:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    return scheme == "https" or (test and scheme == "http" and is_loopback(url))


def _open(url: str, timeout: float, test: bool, accept="application/vnd.github+json"):
    if not _allowed(url, test):
        raise UpdateError(f"refusing {url.split(':')[0]} URL")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - scheme checked above
    if not _allowed(resp.geturl(), test):  # redirects too
        resp.close()
        raise UpdateError("redirected to a non-https URL")
    return resp


def fetch_latest(url: str, timeout: float = TIMEOUT, test: bool = False):
    """Minimal release dict, or None when there is no (visible) release (404/403: private repo,
    no release yet, rate limit). Network errors raise UpdateError."""
    try:
        with _open(url, timeout, test) as r:
            data = json.loads(r.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise UpdateError(f"HTTP {e.code}") from None
    except (OSError, ValueError) as e:  # URLError, timeout, DNS, bad JSON
        raise UpdateError(f"{type(e).__name__}: {e}") from None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    assets = [{"name": a.get("name"), "url": a.get("browser_download_url"), "size": a.get("size")}
              for a in data.get("assets") or [] if isinstance(a, dict)]
    return {"tag": str(data.get("tag_name") or ""), "name": str(data.get("name") or ""),
            "body": str(data.get("body") or "")[:20000], "html_url": str(data.get("html_url") or ""),
            "assets": assets}


def check(game: Path, now=None, force=False, fetch=fetch_latest, override=None) -> dict:
    """{"release": dict|None, "source": "cache"|"net", "error": str|None}. Uses the cache while it
    is fresh (6 h, 1 h after an error); force ignores it. Never raises."""
    now = time.time() if now is None else now
    override = load_override(game) if override is None else override
    cache = read_cache(game)
    age = now - float(cache.get("checked", 0) or 0)
    fresh = CHECK_EVERY if not cache.get("error") else RETRY_AFTER_ERROR
    if not force and "checked" in cache and 0 <= age < fresh:
        return {"release": cache.get("release"), "source": "cache", "error": cache.get("error")}
    try:
        rel, err = fetch(api_url(override), timeout=TIMEOUT, test=override.get("test", False)), None
    except UpdateError as e:
        rel, err = None, str(e)
    except Exception as e:  # noqa: BLE001 - never block the game start
        rel, err = None, f"{type(e).__name__}: {e}"
    cache.update(checked=now, release=rel, error=err)
    write_cache(game, cache)
    return {"release": rel, "source": "net", "error": err}


def to_offer(game: Path, release, installed: str, now=None):
    """The release to offer, or None (not newer, skipped, snoozed, or no setup asset)."""
    if not release or not is_newer(release.get("tag"), installed):
        return None
    if not any(a.get("name") == SETUP_ASSET for a in release.get("assets", [])):
        return None
    cache = read_cache(game)
    tag = norm(release["tag"])
    if cache.get("skip") == tag:
        return None
    now = time.time() if now is None else now
    if cache.get("snooze", {}).get("tag") == tag and now < float(cache["snooze"].get("until", 0)):
        return None
    return release


def skip_version(game: Path, tag: str) -> None:
    c = read_cache(game)
    c["skip"] = norm(tag)
    write_cache(game, c)


def snooze(game: Path, tag: str, now=None) -> None:
    c = read_cache(game)
    c["snooze"] = {"tag": norm(tag), "until": (time.time() if now is None else now) + SNOOZE}
    write_cache(game, c)


def excerpt(body: str, limit: int = 900) -> str:
    """Release text for the dialog: markdown marks dropped, hash lines dropped, cut at a line."""
    lines = []
    for line in (body or "").replace("\r", "").split("\n"):
        if re.search(r"(?i)\bsha-?256\b", line):
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"\*\*|__|`", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        text = text[:cut if cut > limit // 2 else limit].rstrip() + "\n…"
    return text


# ---------------------------------------------------------------- download + verify

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def hash_from_text(text: str):
    """'<hex>  RaF-Remaster-Setup.exe', 'sha256: <hex>', 'SHA256 (RaF-Remaster-Setup.exe) = <hex>'."""
    for line in (text or "").splitlines():
        m = HEX64.search(line)
        if m and (SETUP_ASSET.lower() in line.lower() or re.search(r"(?i)sha-?256", line)
                  or line.strip().lower() == m.group(0).lower()):
            return m.group(0).lower()
    return None


def expected_hash(release: dict, timeout: float = 10, test: bool = False):
    asset = next((a for a in release.get("assets", []) if a.get("name") == HASH_ASSET), None)
    if asset and asset.get("url"):
        try:
            with _open(asset["url"], timeout, test, accept="application/octet-stream") as r:
                h = hash_from_text(r.read(4096).decode("utf-8", "replace"))
            if h:
                return h
        except (OSError, UpdateError):
            pass
    return hash_from_text(release.get("body", ""))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_dir(override: dict) -> Path:
    if override.get("download_dir"):
        return Path(override["download_dir"])
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "RaF-Remaster-Update"


def cleanup_downloads(folder: Path) -> None:
    """Old setups from earlier updates (a running one is locked and stays)."""
    if not folder.is_dir():
        return
    for f in folder.iterdir():
        if f.is_file() and f.name.startswith("RaF-Remaster-Setup"):
            try:
                f.unlink()
            except OSError:
                pass


def download_setup(release: dict, folder: Path, progress=lambda done, total: None, cancel=lambda: False,
                   test: bool = False, timeout: float = 30) -> Path:
    """Download + verify the setup; returns its path. Raises UpdateError (partial file removed)."""
    asset = next((a for a in release.get("assets", []) if a.get("name") == SETUP_ASSET), None)
    if not asset or not asset.get("url"):
        raise UpdateError("the release has no setup file")
    size = asset.get("size")
    if not isinstance(size, int) or not MIN_SIZE <= size <= MAX_SIZE:
        raise UpdateError(f"implausible setup size {size}")
    want = expected_hash(release, test=test)
    if not want:
        raise UpdateError("the release carries no sha256 for the setup")
    folder.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^\w.-]", "_", norm(release.get("tag")))
    dest = folder / f"RaF-Remaster-Setup-{tag}.exe"
    part = dest.with_suffix(".part")
    h, done = hashlib.sha256(), 0
    try:
        with _open(asset["url"], timeout, test, accept="application/octet-stream") as r, open(part, "wb") as f:
            length = r.headers.get("Content-Length")
            if length is not None and int(length) != size:
                raise UpdateError(f"server size {length} != release size {size}")
            while True:
                if cancel():
                    raise UpdateError("cancelled")
                block = r.read(1 << 18)
                if not block:
                    break
                done += len(block)
                if done > size:
                    raise UpdateError("download larger than announced")
                h.update(block)
                f.write(block)
                progress(done, size)
        if done != size:
            raise UpdateError(f"download incomplete ({done} of {size} bytes)")
        if h.hexdigest() != want:
            raise UpdateError("sha256 mismatch: the download is damaged or not the published file")
        os.replace(part, dest)
        return dest
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"{type(e).__name__}: {e}") from None


# ---------------------------------------------------------------- processes (Windows)


def _processes():
    """[(pid, exe name)] via a Toolhelp snapshot."""
    import ctypes
    import ctypes.wintypes as wt

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (None, wt.HANDLE(-1).value):
        return []
    out = []
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _process_path(pid: int):
    import ctypes
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = wt.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def game_running(game: Path, processes=None, path_of=None) -> list:
    """PIDs of RiseAndFall.exe / the launcher started from this install. A process of that name
    whose path cannot be read counts as running (conservative)."""
    processes = _processes() if processes is None else processes
    path_of = _process_path if path_of is None else path_of
    root = os.path.normcase(os.path.abspath(game))
    hits = []
    for pid, name in processes:
        if name.lower() not in (GAME_EXE.lower(), LAUNCHER_EXE.lower()):
            continue
        p = path_of(pid)
        if p is None or os.path.normcase(os.path.dirname(os.path.abspath(p))) == root:
            hits.append(pid)
    return hits


def wait_pid(pid: int, timeout: float = 30) -> bool:
    """Wait until process pid has exited (True) or the timeout passed (False)."""
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        return True  # already gone
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), int(timeout * 1000)) == 0
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


# ---------------------------------------------------------------- swap + carry over

# never taken from the old folder: the new build provides them (or must not have them)
CARRY_SKIP_TOP = {STATE_DIR.lower(), LAUNCHER_DIR.lower(), LAUNCHER_EXE.lower(), "uninstall.bat", "shader.cache",
                  "remaster-licenses", "remaster.txt", "riseandfall remaster.bat", "host.bat", "join.bat",
                  "d3d9.dll", "dxvk.conf"}
CARRY_STATE_FILES = (OVERRIDE_FILE, CACHE_FILE)  # player's update settings (skip, override)


def _files(root: Path) -> dict:
    out = {}
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if d.lower() not in CARRY_SKIP_TOP]
        for f in files:
            rel = f if rel_dir == "." else os.path.join(rel_dir, f)
            out[rel.replace("\\", "/")] = os.path.join(dirpath, f)
    return out


def carry_plan(old: Path, new: Path, old_state: dict, new_state: dict) -> list:
    """Relative paths to copy from the old install into the new one: the player's own files
    (saves, profiles, logs, own maps) and game-written changes to files the remaster does not patch.
    Files the old remaster version installed (managed/created) are never taken over: a dropped
    overlay file would otherwise survive and change the gameplay fingerprint."""
    old_managed = {r.lower() for r in old_state.get("managed", {})} | {r.lower() for r in old_state.get("created", [])}
    new_managed = {r.lower() for r in new_state.get("managed", {})} | {r.lower() for r in new_state.get("created", [])}
    new_patched = new_managed | {"riseandfall.exe", "dx9rasterizer.dll"}
    plan = []
    new_files = {k.lower(): v for k, v in _files(new).items()}
    for rel, src in sorted(_files(old).items()):
        low = rel.lower()
        if low.split("/")[0] in CARRY_SKIP_TOP or low in old_managed or low.startswith("remaster-readme_"):
            continue
        dst = new_files.get(low)
        if dst is None:
            plan.append(rel)
            continue
        if low in new_patched:
            continue  # the new version's file wins
        a, b = os.stat(src), os.stat(dst)
        if a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime):
            continue  # both copies of the same stock file
        if sha256_file(Path(src)) != sha256_file(Path(dst)):
            plan.append(rel)  # e.g. a config file the game rewrote
    return plan


def carry_over(old: Path, new: Path, plan, log=print) -> int:
    for rel in plan:
        dst = new / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old / rel, dst)
    for name in CARRY_STATE_FILES:
        if (old / STATE_DIR / name).is_file():
            (new / STATE_DIR).mkdir(parents=True, exist_ok=True)
            shutil.copy2(old / STATE_DIR / name, new / STATE_DIR / name)
    log(f"carried over {len(plan)} files from the previous version")
    return len(plan)


def sibling(game: Path, suffix: str) -> Path:
    return game.parent / (game.name + suffix)


def swap(game: Path, new: Path, old_bak: Path, rename=os.rename) -> None:
    """game -> old_bak, new -> game. If the second rename fails the first is undone."""
    rename(game, old_bak)
    try:
        rename(new, game)
    except OSError:
        rename(old_bak, game)
        raise


def unswap(game: Path, failed: Path, old_bak: Path, rename=os.rename) -> None:
    """Rollback after a swap: the new folder goes to `failed`, the old one back to its place."""
    rename(game, failed)
    rename(old_bak, game)
