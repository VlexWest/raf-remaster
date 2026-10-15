"""Stub tests for the auto update (tools/raf_update.py, raf_launcher.py, raf_installer.run_update).

    python tools/test_updater.py

No game, no GitHub: a local HTTP server (127.0.0.1) plays the releases API and the download, the
registry tests use HKCU\\Software\\RaF-Remaster-Installer-Test\\unit (deleted afterwards), the
installer is replaced by a fake for the update flow. Covers: version compare, release text, hash
lines, cache + rate limit, offline / 404 / 403, override safety, download (good, bad hash, wrong
size, no hash, http refused), game-running check, carry-over plan, swap/unswap, run_update
(success, game running, original missing, build failure, swap failure, rollback after the swap),
registry keep + snapshot restore, install.json, launcher argument passing and start scripts.
"""

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raf_installer as ri  # noqa: E402
import raf_installer_text as rt  # noqa: E402
import raf_launcher as rl  # noqa: E402
import raf_patch as rp  # noqa: E402
import raf_update as ru  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


# ---------------------------------------------------------------- local server


class Server:
    """routes: path -> (status, bytes, headers)"""

    def __init__(self):
        self.routes, self.hits = {}, []
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                srv.hits.append(self.path)
                status, body, headers = srv.routes.get(self.path, (404, b"{}", {}))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def release_json(base, tag="v1.0.1", size=None, body="Changes\n- better AI", hash_asset=True):
    assets = [{"name": ru.SETUP_ASSET, "browser_download_url": base + "/dl/setup.exe", "size": size}]
    if hash_asset:
        assets.append({"name": ru.HASH_ASSET, "browser_download_url": base + "/dl/setup.sha256", "size": 90})
    return json.dumps({"tag_name": tag, "name": tag, "body": body, "html_url": base + "/rel", "assets": assets,
                       "draft": False, "prerelease": False}).encode()


# ---------------------------------------------------------------- pure functions


def check_versions():
    check(ru.parse_version("v1.2.3") == (1, 2, 3) and ru.parse_version("1.2") == (1, 2, 0), "parse vX.Y.Z and X.Y")
    check(ru.parse_version("v1.2.3-beta") is None and ru.parse_version("") is None, "pre-release / empty -> None")
    check(ru.is_newer("v1.0.1", "1.0.0") and ru.is_newer("v1.10.0", "1.9.9") and ru.is_newer("v2.0", "1.0"),
          "is_newer: patch, numeric minor, major")
    check(not ru.is_newer("v1.0.0", "1.0.0") and not ru.is_newer("v0.9.9", "1.0.0") and not ru.is_newer("x", "1.0.0"),
          "is_newer: same, older, garbage -> no")
    check(ru.norm("v1.0") == "1.0.0", "norm v1.0 -> 1.0.0")
    ex = ru.excerpt("## New\n**Bold** [link](http://x)\nsha256: " + "a" * 64 + "\n\n\n\nend")
    check(ex == "New\nBold link\n\nend", f"excerpt strips markdown + hash lines ({ex!r})")
    long = ru.excerpt("\n".join(f"line {i} " + "x" * 50 for i in range(60)), limit=300)
    check(len(long) < 320 and long.endswith("…"), "excerpt cuts long text at a line")
    hx = "ab" * 32
    check(ru.hash_from_text(f"{hx}  RaF-Remaster-Setup.exe\n") == hx, "hash: sha256sum format")
    check(ru.hash_from_text(f"Notes\nSHA256: {hx.upper()}\n") == hx, "hash: 'SHA256: <HEX>' line in the body")
    check(ru.hash_from_text(f"SHA256 (RaF-Remaster-Setup.exe) = {hx}") == hx, "hash: BSD format")
    check(ru.hash_from_text(f"commit {hx}") is None, "hash: an unrelated hex line is not taken")


def check_cache_and_offer(tmp: Path):
    game = tmp / "g1"
    (game / ".raf-remaster").mkdir(parents=True)
    calls = []

    def fetch_ok(url, timeout, test):
        calls.append(url)
        return {"tag": "v1.0.1", "body": "", "assets": [{"name": ru.SETUP_ASSET, "url": "https://x", "size": 9}]}

    def fetch_off(url, timeout, test):
        calls.append(url)
        raise ru.UpdateError("URLError: offline")

    ov = {"test": False}
    r = ru.check(game, now=1000, fetch=fetch_ok, override=ov)
    check(r["source"] == "net" and r["release"]["tag"] == "v1.0.1" and calls == [ru.API_TEMPLATE.format(
        repo="VlexWest/raf-remaster")], "first check goes to the GitHub API of VlexWest/raf-remaster")
    r = ru.check(game, now=1000 + 5 * 3600, fetch=fetch_ok, override=ov)
    check(r["source"] == "cache" and len(calls) == 1, "second check within 6 h uses the cache (rate limit)")
    r = ru.check(game, now=1000 + 6 * 3600 + 1, fetch=fetch_off, override=ov)
    check(r["source"] == "net" and r["error"] and r["release"] is None and len(calls) == 2,
          "after 6 h it asks again; offline -> error, no release")
    r = ru.check(game, now=1000 + 6 * 3600 + 1800, fetch=fetch_off, override=ov)
    check(r["source"] == "cache" and len(calls) == 2, "after an error: no new try within 1 h")
    r = ru.check(game, now=1000 + 6 * 3600 + 3601, fetch=fetch_ok, override=ov)
    check(r["source"] == "net" and r["release"], "after an error: new try after 1 h")
    r = ru.check(game, now=1000 + 6 * 3600 + 3602, fetch=fetch_ok, override=ov, force=True)
    check(r["source"] == "net" and len(calls) == 4, "force ignores the cache")

    def boom(url, timeout, test):
        raise ValueError("weird")

    r = ru.check(game, now=10 ** 10, fetch=boom, override=ov)
    check(r["release"] is None and "weird" in r["error"], "unexpected exception in the check -> no update, no crash")

    rel = {"tag": "v1.0.1", "assets": [{"name": ru.SETUP_ASSET}]}
    check(ru.to_offer(game, rel, "1.0.0", now=0) is rel, "offer: newer release with setup asset")
    check(ru.to_offer(game, rel, "1.0.1") is None and ru.to_offer(game, rel, "1.1.0") is None,
          "offer: not for the same or an older tag")
    check(ru.to_offer(game, {"tag": "v1.0.1", "assets": []}, "1.0.0") is None, "offer: not without the setup asset")
    ru.snooze(game, "v1.0.1", now=100)
    check(ru.to_offer(game, rel, "1.0.0", now=100 + 3600) is None and
          ru.to_offer(game, rel, "1.0.0", now=100 + 6 * 3600 + 1) is rel, "Later: snoozed for 6 h only")
    ru.skip_version(game, "v1.0.1")
    check(ru.to_offer(game, rel, "1.0.0", now=10 ** 10) is None, "Skip: that version is never offered again")
    check(ru.to_offer(game, dict(rel, tag="v1.0.2"), "1.0.0", now=10 ** 10) is not None, "Skip: a newer one is offered")

    (game / ".raf-remaster" / "update.json").write_text(json.dumps(
        {"api": "http://evil.example/latest", "test_answer": "update", "dry_run_game": "x", "repo": "a/b"}))
    o = ru.load_override(game)
    check(not o["test"] and "test_answer" not in o and "api" not in o and ru.api_url(o).endswith("/repos/a/b/releases/latest"),
          "override: test switches ignored unless the API is a loopback URL; repo override works")
    (game / ".raf-remaster" / "update.json").write_text(json.dumps({"repo": "../../x"}))
    check(ru.api_url(ru.load_override(game)) == ru.API_TEMPLATE.format(repo=ru.UPDATE_REPO), "override: bad repo ignored")
    (game / ".raf-remaster").chmod(0o555)  # no effect on Windows dirs; write_cache must not raise anyway
    check(ru.write_cache(tmp / "nonexistent" / "x", {}) in (True, False), "write_cache never raises")


def check_http(tmp: Path):
    srv = Server()
    try:
        url = srv.url + "/repos/x/y/releases/latest"
        check(ru.fetch_latest(url, test=True) is None, "API 404 (private repo / no release) -> no update")
        srv.routes["/repos/x/y/releases/latest"] = (403, b'{"message":"rate limit"}', {})
        check(ru.fetch_latest(url, test=True) is None, "API 403 (rate limit) -> no update")
        srv.routes["/repos/x/y/releases/latest"] = (500, b"", {})
        try:
            ru.fetch_latest(url, test=True)
            check(False, "API 500 -> error")
        except ru.UpdateError:
            check(True, "API 500 -> error (cached as error, no dialog)")
        try:
            ru.fetch_latest(url, test=False)
            check(False, "plain http refused outside test mode")
        except ru.UpdateError as e:
            check("refusing" in str(e), "plain http refused outside test mode")
        try:
            ru.fetch_latest("http://127.0.0.1:9/x", timeout=1, test=True)
            check(False, "connection refused -> UpdateError")
        except ru.UpdateError:
            check(True, "connection refused (offline) -> UpdateError")
        t = time.time()
        try:
            ru.fetch_latest("https://raf-update-test.invalid/x", timeout=3)
        except ru.UpdateError:
            pass
        check(time.time() - t < 5, f"unresolvable host returns within the timeout ({time.time() - t:.1f} s)")

        payload = os.urandom(6_000_123)
        good = hashlib.sha256(payload).hexdigest()
        srv.routes["/repos/x/y/releases/latest"] = (200, release_json(srv.url, size=len(payload)), {})
        srv.routes["/dl/setup.exe"] = (200, payload, {})
        srv.routes["/dl/setup.sha256"] = (200, f"{good}  RaF-Remaster-Setup.exe\n".encode(), {})
        rel = ru.fetch_latest(url, test=True)
        check(rel["tag"] == "v1.0.1" and rel["assets"][0]["size"] == len(payload), "API 200 -> release parsed")
        dl = tmp / "dl"
        seen = []
        p = ru.download_setup(rel, dl, progress=lambda d, n: seen.append(d), test=True)
        check(p.is_file() and ru.sha256_file(p) == good and seen[-1] == len(payload) and not list(dl.glob("*.part")),
              "download: verified by the .sha256 asset, progress reported")
        try:
            ru.download_setup(rel, dl, test=False)
            check(False, "download over http refused outside test mode")
        except ru.UpdateError:
            check(True, "download over http refused outside test mode")
        srv.routes["/dl/setup.sha256"] = (200, ("0" * 64 + "  RaF-Remaster-Setup.exe\n").encode(), {})
        p.unlink()
        try:
            ru.download_setup(rel, dl, test=True)
            check(False, "bad hash refused")
        except ru.UpdateError as e:
            check("sha256" in str(e) and not list(dl.iterdir()), "bad hash: refused, partial file removed")
        srv.routes["/dl/setup.sha256"] = (404, b"", {})
        try:
            ru.download_setup(rel, dl, test=True)
            check(False, "no hash anywhere refused")
        except ru.UpdateError as e:
            check("sha256" in str(e), "no hash (asset missing, none in the text): refused")
        rel2 = dict(rel, body=f"Fixes\nsha256: {good}")
        check(ru.download_setup(rel2, dl, test=True).is_file(), "hash from the release text works")
        rel3 = json.loads(json.dumps(rel2))
        rel3["assets"][0]["size"] = len(payload) + 1
        try:
            ru.download_setup(rel3, dl, test=True)
            check(False, "size mismatch refused")
        except ru.UpdateError:
            check(True, "size different from the API value: refused")
        rel4 = json.loads(json.dumps(rel2))
        rel4["assets"][0]["size"] = 1000
        try:
            ru.download_setup(rel4, dl, test=True)
            check(False, "implausible size refused")
        except ru.UpdateError as e:
            check("implausible" in str(e), "implausible size (1 kB) refused before downloading")
        try:
            ru.download_setup(rel2, dl, cancel=lambda: True, test=True)
            check(False, "cancel")
        except ru.UpdateError as e:
            check(str(e) == "cancelled" and not list(dl.glob("*.part")), "cancel removes the partial file")
        ru.cleanup_downloads(dl)
        check(not list(dl.iterdir()), "old downloads are cleaned up")
    finally:
        srv.close()


def check_processes(tmp: Path):
    game = tmp / "Rise and Fall Remaster"
    procs = [(1, "RiseAndFall.exe"), (2, "explorer.exe"), (3, "RiseAndFall.exe"), (4, "RaF Remaster.exe")]
    paths = {1: r"D:\Games\Rise and Fall\RiseAndFall.exe", 3: str(game / "RiseAndFall.exe"), 4: None}
    check(ru.game_running(game, procs, paths.get) == [3, 4],
          "game_running: the remaster's game + unreadable launcher count, the original game does not")
    check(ru.game_running(game, [(1, "RiseAndFall.exe")], paths.get) == [], "game_running: original only -> free")
    check(isinstance(ru.game_running(game), list), "game_running works against the real process list")
    check(ru.wait_pid(999999, 1) is True, "wait_pid: a gone process returns at once")


def make_install(root: Path, files: dict, state: dict):
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    (root / ".raf-remaster").mkdir(parents=True, exist_ok=True)
    (root / ".raf-remaster" / "state.json").write_text(json.dumps(state))


def check_carry(tmp: Path):
    stock_files = {"RiseAndFall.exe": b"MZstock", "Data/db/a.dat": b"A", "Data/cfg.ini": b"stock cfg",
                   "Data/textures/t.dds": b"T"}
    old, new = tmp / "old", tmp / "new"
    make_install(old, dict(stock_files, **{"RiseAndFall.exe": b"MZold", "Data/db/a.dat": b"A-old",
                                           "Data/db/dropped.dat": b"D", "Users/default/save1.sav": b"S",
                                           "Data/cfg.ini": b"game rewrote", "shader.cache": b"C",
                                           "d3d9.dll": b"dxvk", "RaF Remaster.exe": b"old launcher",
                                           ".raf-launcher/x.dll": b"x", "REMASTER-README_EN.txt": b"r",
                                           "Data/scenarios/mine.scn": b"M"}),
                 {"managed": {"Data/db/a.dat": "ai", "Data/db/dropped.dat": "survival"}, "created": ["Data/db/dropped.dat"]})
    (old / ".raf-remaster" / "update.json").write_text("{}")
    (old / ".raf-remaster" / "update-cache.json").write_text('{"skip": "1.0.1"}')
    make_install(new, dict(stock_files, **{"RiseAndFall.exe": b"MZnew", "Data/db/a.dat": b"A-new",
                                           "RaF Remaster.exe": b"new launcher"}), {"managed": {"Data/db/a.dat": "ai"}})
    t = time.time() - 1000
    for root in (old, new):  # stock files copied with copy2 carry the stock mtime
        for rel in ("Data/textures/t.dds", "Data/cfg.ini"):
            os.utime(root / rel, (t, t))
    plan = ru.carry_plan(old, new, json.loads((old / ".raf-remaster/state.json").read_text()),
                         json.loads((new / ".raf-remaster/state.json").read_text()))
    check(sorted(plan) == ["Data/cfg.ini", "Data/scenarios/mine.scn", "Users/default/save1.sav"],
          f"carry plan: saves, own map, game-rewritten config; not managed/dropped/launcher/dxvk/cache ({plan})")
    ru.carry_over(old, new, plan, log=lambda s: None)
    check((new / "Users/default/save1.sav").read_bytes() == b"S" and (new / "Data/cfg.ini").read_bytes() == b"game rewrote"
          and (new / "RaF Remaster.exe").read_bytes() == b"new launcher" and not (new / "Data/db/dropped.dat").exists()
          and (new / ".raf-remaster/update-cache.json").read_text() == '{"skip": "1.0.1"}',
          "carry over: files copied, new launcher kept, skip setting kept")

    a, b, c = tmp / "sw-game", tmp / "sw-new", tmp / "sw-old"
    a.mkdir()
    (a / "v").write_text("old")
    b.mkdir()
    (b / "v").write_text("new")
    calls = []

    def flaky(x, y):
        calls.append((Path(x).name, Path(y).name))
        if len(calls) == 2:
            raise PermissionError("in use")
        os.rename(x, y)

    try:
        ru.swap(a, b, c, rename=flaky)
        check(False, "swap: failure of the second rename raises")
    except OSError:
        check((a / "v").read_text() == "old" and (b / "v").read_text() == "new" and not c.exists(),
              "swap: second rename fails -> first undone, old install in place")
    ru.swap(a, b, c)
    check((a / "v").read_text() == "new" and (c / "v").read_text() == "old", "swap: new in place, old kept aside")
    ru.unswap(a, tmp / "sw-failed", c)
    check((a / "v").read_text() == "old" and (tmp / "sw-failed" / "v").read_text() == "new", "unswap: rollback")


# ---------------------------------------------------------------- run_update with a fake installer


class FakeUI:
    def __init__(self, retry=(), dirs=()):
        self.lines, self.errors, self.done_msg = [], [], None
        self.retry, self.dirs = list(retry), list(dirs)

    def log(self, s):
        self.lines.append(str(s))

    def step(self, text, frac=None):
        pass

    def ask_retry(self, msg):
        self.lines.append("ASK " + msg)
        return self.retry.pop(0) if self.retry else False

    def ask_dir(self, msg):
        self.lines.append("ASKDIR " + msg)
        return self.dirs.pop(0) if self.dirs else None

    def error(self, msg):
        self.errors.append(msg)

    def done(self, msg):
        self.done_msg = msg


def fake_installer_factory(log, fail_run=False, fail_links=False):
    class FakeInstaller:
        def __init__(self, cfg, bundle, src, dst, **k):
            self.dst, self.src, self.k = Path(dst), Path(src), k
            log.append(("init", k))
            self.restored = False

        def run(self, links=True):
            log.append(("run", links))
            if fail_run:
                shutil.rmtree(self.dst, ignore_errors=True)  # what the real cleanup does
                raise SystemExit("builder failed")
            make_install(self.dst, {"RiseAndFall.exe": b"MZnew", "Data/db/a.dat": b"A-new", "RaF Remaster.exe": b"L2"},
                         {"managed": {"Data/db/a.dat": "ai"}, "fingerprint": "fp1"})
            return {"fingerprint": "fp1", "fingerprint_ok": True}

        def shortcuts_and_uninstall(self):
            log.append(("links", str(self.dst)))
            if fail_links:
                raise RuntimeError("shortcuts failed")

        def restore_snapshot(self):
            log.append(("restore",))

    return FakeInstaller


def check_run_update(tmp: Path):
    rt.set_lang("en")
    stock = tmp / "stock"
    stock.mkdir()
    cfg = {"remaster_version": "1.0.1"}
    probe = lambda: {"verdict": {"dxvk": True, "hd": True}}  # noqa: E731
    orig_inst, orig_qc, orig_start = ri.Installer, ri.quick_check, ri.start_installed
    ri.quick_check = lambda p, c: (Path(p).resolve() == stock.resolve(), "x")
    started = []
    ri.start_installed = lambda d, tail="": started.append((str(d), tail))
    try:
        def fresh(name):
            g = tmp / name
            make_install(g, {"RiseAndFall.exe": b"MZold", "Users/default/save.sav": b"S", "RaF Remaster.exe": b"L1"},
                         {"managed": {}, "fingerprint": "fp1", "features": ["hd-units"]})
            (g / ".raf-remaster" / "install.json").write_text(json.dumps(
                {"version": "1.0.0", "stock": str(stock), "hd": True, "desktop": False, "startmenu": True,
                 "lang": "en", "install_dir_before": None, "test_root": str(tmp / "links")}))
            return g

        # success
        g, log, ui = fresh("u1"), [], FakeUI()
        ri.Installer = fake_installer_factory(log)
        code = ri.run_update(g, ui, tmp / "bundle", cfg, relaunch='-hostgame "A"', probe=probe, running=lambda d: [])
        init = log[0][1]
        check(code == 0 and (g / "RiseAndFall.exe").read_bytes() == b"MZnew" and (g / "Users/default/save.sav").exists()
              and (g / "RaF Remaster.exe").read_bytes() == b"L2" and not ru.sibling(g, ".raf-old").exists()
              and not ru.sibling(g, ".raf-update").exists(),
              "update: new version in place, save kept, launcher replaced, side folders gone")
        check(init["update_info"]["_dir"] == str(g.resolve()) and init["test_root"] == str(tmp / "links")
              and init["desktop"] is False and init["hd"] is True and ("run", False) in log
              and ("links", str(g.resolve())) in log, "update: options from install.json, links written for the final folder")
        check(started == [(str(g.resolve()), '-hostgame "A"')], "update: game started again with the launcher arguments")
        check("fp1" in ui.done_msg and "changed" not in ui.done_msg, "update: same fingerprint, no warning")

        g, log, ui = fresh("u1b"), [], FakeUI()
        ri.Installer = fake_installer_factory(log)
        started.clear()
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [], launch="dry-run-only")
        check(code == 0 and not started, "headless update never starts the real game (no dry-run override)")

        # game running
        g, log, ui = fresh("u2"), [], FakeUI(retry=[True, False])
        started.clear()
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [42])
        check(code == 2 and not log and (g / "RiseAndFall.exe").read_bytes() == b"MZold" and not started
              and sum(1 for line in ui.lines if line.startswith("ASK ")) == 2,
              "game running: asks (retry), then refuses; nothing touched")

        # original moved: browse
        g, log = fresh("u3"), []
        moved = tmp / "stock-moved"
        moved.mkdir()
        ri.quick_check = lambda p, c: (Path(p).resolve() == moved.resolve(), "x")
        ui = FakeUI(dirs=[str(moved)])
        ri.Installer = fake_installer_factory(log)
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [], launch=False)
        check(code == 0 and log and any(line.startswith("ASKDIR") for line in ui.lines),
              "original moved: asks for the folder and updates from there")
        g, log, ui = fresh("u3b"), [], FakeUI()
        ri.Installer = fake_installer_factory(log)
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [], launch=False)
        check(code == 2 and not log, "original missing and not chosen: refused, nothing built")
        ri.quick_check = lambda p, c: (Path(p).resolve() == stock.resolve(), "x")

        # build failure
        g, log, ui = fresh("u4"), [], FakeUI()
        ri.Installer = fake_installer_factory(log, fail_run=True)
        started.clear()
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [])
        check(code == 1 and (g / "RiseAndFall.exe").read_bytes() == b"MZold" and not started
              and not ru.sibling(g, ".raf-update").exists() and "previous version is unchanged" in ui.errors[0],
              "build failure: old install untouched, error shown, game not started")

        # swap failure (folder in use), no retry
        g, log, ui = fresh("u5"), [], FakeUI()
        ri.Installer = fake_installer_factory(log)

        def locked(a, b):
            raise PermissionError("in use")

        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [], rename=locked)
        check(code == 1 and (g / "RiseAndFall.exe").read_bytes() == b"MZold" and ("restore",) in log
              and not ru.sibling(g, ".raf-update").exists(), "swap fails: registry restored, new folder removed")

        # failure after the swap -> rollback
        g, log, ui = fresh("u6"), [], FakeUI()
        ri.Installer = fake_installer_factory(log, fail_links=True)
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [])
        check(code == 1 and (g / "RiseAndFall.exe").read_bytes() == b"MZold" and (g / "Users/default/save.sav").exists()
              and ("restore",) in log and not ru.sibling(g, ".raf-failed").exists()
              and not ru.sibling(g, ".raf-old").exists(), "failure after the swap: previous version back in place")

        # crash between the two renames -> recovered on the next run
        g, log, ui = fresh("u7"), [], FakeUI()
        os.rename(g, ru.sibling(g, ".raf-old"))
        ri.Installer = fake_installer_factory(log)
        code = ri.run_update(g, ui, tmp / "bundle", cfg, probe=probe, running=lambda d: [], launch=False)
        check(code == 0 and (g / "Users/default/save.sav").exists(), "half-done swap of an earlier run is recovered")

        # not a remaster folder
        ui = FakeUI()
        (tmp / "plain").mkdir()
        check(ri.run_update(tmp / "plain", ui, tmp / "bundle", cfg, probe=probe, running=lambda d: []) == 2,
              "not a remaster install: refused")

        # old install without install.json
        g = tmp / "u8"
        make_install(g, {"RiseAndFall.exe": b"MZold"}, {"fingerprint": "f", "stock": str(stock), "features": ["mips"],
                                                         "dxvk": False, "version": "1.0"})
        bat = ri.uninstall_bat(g, r"Software\T\Rise and Fall", {}, "D:\\Games\\Rise and Fall\\", [], None, r"Software\T\U")
        (g / "Uninstall.bat").write_text(bat, encoding="utf-8")
        info = ri.read_update_info(g)
        check(info["stock"] == str(stock) and info["hd"] is False and info["force_native"] is True
              and info["install_dir_before"] == "D:\\Games\\Rise and Fall\\",
              "install from before install.json: options rebuilt from state.json and Uninstall.bat")
    finally:
        ri.Installer, ri.quick_check, ri.start_installed = orig_inst, orig_qc, orig_start


# ---------------------------------------------------------------- registry (test key)

TEST_KEY = ri.TEST_ROOT_KEY + r"\unit"


def reg_get(name):
    import winreg

    path, val = rp._reg_split(name)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, val)[0]
    except OSError:
        return None


def delete_tree(path):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                delete_tree(path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def check_registry(tmp: Path):
    old_key = rp.REG_KEY
    rp.REG_KEY = TEST_KEY
    try:
        game = tmp / "reg"
        (game / ".raf-remaster").mkdir(parents=True)
        q = "Graphics Settings/Model Quality Level"
        rp.set_registry(game, {q: 3, "Remaster Camera Zoom": 200})  # first install: ultra + zoom
        saved = json.loads((game / ".raf-remaster/registry.json").read_text())
        check(reg_get(q) == 3 and saved[q] is None, "first apply writes the value and saves the pre-remaster state")
        rp.set_registry(game, {q: 1})  # the player lowers it in game (same effect)
        rp.set_registry(game, {q: 3, "Network Adapter": 2}, keep=[q])
        check(reg_get(q) == 1 and reg_get("Network Adapter") == 2, "update (keep): player's value stays, adapter re-picked")
        rp.set_registry(game, {q: 3, "Wait for VSync": 1}, keep=[q, "Wait for VSync"])
        check(reg_get("Wait for VSync") == 1, "update (keep): a value the patcher never managed is written")
        rp.set_registry(game, {q: 3})
        check(reg_get(q) == 3, "plain apply (no keep) still resets as before")

        # Installer snapshot + restore around apply (update mode)
        rp.set_registry(game, {q: 1})
        ins = ri.Installer({"zoom": 2.0}, tmp, tmp, game, test_root=tmp / "links", log=lambda s: None,
                           update_info={"_dir": str(game)})
        fake = types.SimpleNamespace(set_registry=rp.set_registry, _reg_split=rp._reg_split, _reg_restore=rp._reg_restore)
        ins.rp = fake
        ins._snapshot_registry()
        fake.set_registry(game, {q: 3, "Full Screen Mode": 1})
        check(reg_get(q) == 3 and ins.reg_snapshot == {q: 1, "Full Screen Mode": None}, "snapshot taken before apply writes")
        ins.restore_snapshot()
        check(reg_get(q) == 1 and reg_get("Full Screen Mode") is None, "failed update: values from before the update back")
    finally:
        rp.REG_KEY = old_key
        delete_tree(TEST_KEY)
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY).Close()
        check(False, "test registry key removed")
    except FileNotFoundError:
        check(True, "test registry key removed")


def check_finish_files(tmp: Path):
    bundle = tmp / "fbundle"
    (bundle / "licenses").mkdir(parents=True)
    (bundle / "launcher" / ".raf-launcher").mkdir(parents=True)
    (bundle / "launcher" / "RaF Remaster.exe").write_bytes(b"L")
    (bundle / "launcher" / ".raf-launcher" / "python3.dll").write_bytes(b"P")
    (bundle / "NOTICE").write_text("notice")
    for lang in ("DE", "RU", "EN"):
        (bundle / f"README_{lang}.txt").write_text(lang)
    dst = tmp / "fdst"
    (dst / ".raf-remaster" / "build").mkdir(parents=True)
    rt.set_lang("ru")
    ins = ri.Installer({"remaster_version": "1.0.0"}, bundle, tmp / "stock", dst, hd=False, desktop=False,
                       test_root=tmp / "links", log=lambda s: None, force_native=True)
    ins.build = dst / ".raf-remaster" / "build"
    ins.install_dir_before = "D:\\Old\\"
    ins.result["fingerprint"] = "abc"
    ins.finish_files()
    info = json.loads((dst / ".raf-remaster" / "install.json").read_text(encoding="utf-8"))
    check((dst / "RaF Remaster.exe").is_file() and (dst / ".raf-launcher" / "python3.dll").is_file()
          and (dst / "REMASTER-NOTICE.txt").read_text() == "notice", "finish_files: launcher + NOTICE in the game folder")
    check(info["version"] == "1.0.0" and info["hd"] is False and info["force_native"] is True and info["lang"] == "ru"
          and info["desktop"] is False and info["install_dir_before"] == "D:\\Old\\" and info["fingerprint"] == "abc"
          and info["test_root"] == str(tmp / "links") and Path(info["stock"]).is_absolute(),
          "install.json: version, stock, options, language, Install Directory, test marker")
    check(ru.installed_version(dst) == "1.0.0" and ru.installed_version(tmp) == ri.VERSION, "installed_version")
    rt.set_lang("en")


# ---------------------------------------------------------------- launcher


def check_launcher(tmp: Path):
    check(rl.split_program('"C:\\G\\RaF Remaster.exe" -hostgame "A B" -pid "1"') == '-hostgame "A B" -pid "1"',
          "launcher: quoted program name dropped, arguments verbatim")
    check(rl.split_program("launcher.exe   -joinbyip \"1.2.3.4\"") == '-joinbyip "1.2.3.4"', "launcher: unquoted name")
    check(rl.split_program('"x.exe"') == "", "launcher: no arguments")
    check(rl.strip_own('--skip-check -hostgame "A"') == ({"--skip-check"}, '-hostgame "A"'), "launcher: own flag stripped")
    check(rl.strip_own('--game "D:\\a b" --check-updates') == ({"--check-updates"}, ""), "launcher: --game (tests) stripped")
    cmd = rl.game_command(Path(r"D:\G"), '-hostgame "Name" -playername "Me"')
    check(cmd == '"D:\\G\\RiseAndFall.exe" -datapath "Data\\" -redistpath "Redist\\" -hostgame "Name" -playername "Me"',
          "launcher: game command = data paths + passed arguments")
    sc = rl.setup_command(Path("s.exe"), Path("D:/G"), '-x "a"', "de")
    import base64

    check(sc[1:3] == ["--update", str(Path("D:/G"))] and "--wait-pid" in sc and
          base64.urlsafe_b64decode(sc[sc.index("--relaunch-b64") + 1]).decode() == '-x "a"',
          "launcher: setup command carries game dir, pid and the arguments (base64)")

    srv = Server()
    popen = []
    orig_popen, orig_msg, orig_ask = rl.subprocess.Popen, rl.message, rl.ask_update
    rl.subprocess.Popen = lambda cmd, **k: popen.append(cmd)
    msgs = []
    rl.message = lambda text, error=False: msgs.append(text)
    asked = []
    try:
        game = tmp / "lg"
        (game / ".raf-remaster").mkdir(parents=True)
        (game / ".raf-remaster" / "state.json").write_text('{"fingerprint": "fp9", "version": "1.0.0"}')
        dry = tmp / "lg-dry.txt"
        ov = {"api": srv.url + "/latest", "dry_run_game": str(dry), "download_dir": str(tmp / "lg-dl")}
        (game / ".raf-remaster" / "update.json").write_text(json.dumps(ov))

        def launch(args="", answer=None):
            o = dict(ov, **({"test_answer": answer} if answer else {}))
            (game / ".raf-remaster" / "update.json").write_text(json.dumps(o))
            return rl.run(["--game", str(game)], args)

        # 404 (private repo): straight to the game
        launch('-hostgame "Name"')
        check(dry.read_text().splitlines()[-1].endswith('-redistpath "Redist\\" -hostgame "Name"') and not popen,
              "launcher: API 404 -> game starts with the arguments, no dialog")
        n_hits = len(srv.hits)
        launch()
        check(len(srv.hits) == n_hits and len(dry.read_text().splitlines()) == 2, "launcher: second start uses the cache")
        # newer release, player says Later via the dialog stub
        payload = os.urandom(5_100_000)
        srv.routes["/latest"] = (200, release_json(srv.url, size=len(payload)), {})
        srv.routes["/dl/setup.exe"] = (200, payload, {})
        srv.routes["/dl/setup.sha256"] = (200, hashlib.sha256(payload).hexdigest().encode() + b"  RaF-Remaster-Setup.exe", {})
        (game / ".raf-remaster" / "update-cache.json").unlink()
        rl.ask_update = lambda rel, cur, fp: asked.append((rel["tag"], cur, fp)) or "later"
        launch()
        check(asked == [("v1.0.1", "1.0.0", "fp9")] and len(dry.read_text().splitlines()) == 3,
              "launcher: newer release -> dialog with installed version + fingerprint; Later -> game starts")
        launch()
        check(len(asked) == 1, "launcher: Later -> not asked again for 6 h")
        c = ru.read_cache(game)
        c.pop("snooze")
        ru.write_cache(game, c)
        rl.ask_update = lambda rel, cur, fp: asked.append(1) or "skip"
        launch()
        launch()
        check(len(asked) == 2 and ru.read_cache(game)["skip"] == "1.0.1", "launcher: Skip -> never asked for 1.0.1 again")
        c = ru.read_cache(game)
        c.pop("skip")
        ru.write_cache(game, c)
        # bad hash -> message, game starts, no setup run
        srv.routes["/dl/setup.sha256"] = (200, b"0" * 64 + b"  RaF-Remaster-Setup.exe", {})
        lines = len(dry.read_text().splitlines())
        launch('-joinbyip "1.2.3.4"', answer="update")
        check(not popen and msgs and "sha256" in msgs[-1] and len(dry.read_text().splitlines()) == lines + 1,
              "launcher: Update with a bad hash -> error message, no setup started, game starts")
        # good hash -> setup started, game NOT started by the launcher
        srv.routes["/dl/setup.sha256"] = (200, hashlib.sha256(payload).hexdigest().encode(), {})
        lines = len(dry.read_text().splitlines())
        launch('-joinbyip "1.2.3.4"', answer="update")
        check(len(popen) == 1 and popen[0][1] == "--update" and "--headless" in popen[0]
              and len(dry.read_text().splitlines()) == lines, "launcher: Update -> verified setup started, game left to it")
        # --check-updates when up to date
        srv.routes["/latest"] = (200, release_json(srv.url, tag="v1.0.0", size=len(payload)), {})
        launch("--check-updates")
        check(msgs and msgs[-1] == rt.T("upd_none", cur="1.0.0"), "launcher: --check-updates says 'up to date'")
        # disabled
        (game / ".raf-remaster" / "update.json").write_text('{"disabled": true}')
        hits = len(srv.hits)
        rl.subprocess.Popen = lambda cmd, **k: popen.append(cmd)
        rl.run(["--game", str(game)], "")
        check(len(srv.hits) == hits and isinstance(popen[-1], str) and popen[-1].startswith('"'),
              "launcher: disabled in update.json -> no request, game started directly")
    finally:
        rl.subprocess.Popen, rl.message, rl.ask_update = orig_popen, orig_msg, orig_ask
        srv.close()


def check_bats(tmp: Path):
    d = tmp / "bats"
    d.mkdir()
    (d / "REMASTER.txt").write_bytes(b"fp\r\n")
    for name, text in (("Host.bat", rp.HOST_BAT), ("Join.bat", rp.JOIN_BAT), ("Run.bat", rp.LAUNCH_BAT)):
        (d / name).write_bytes(text.replace('start "" ', "echo CMD ").replace("\n", "\r\n").encode("ascii"))

    def run(name, *args):
        out = subprocess.run(["cmd", "/c", str(d / name), *args], capture_output=True, text=True, cwd=d).stdout
        return [line[4:] for line in out.splitlines() if line.startswith("CMD ")]

    check(run("Host.bat", "Game", "Me") == ['RiseAndFall.exe -datapath "Data\\" -redistpath "Redist\\" -hostgame "Game" '
                                            '-playername "Me" -pid "1" -pass "raf"'],
          "Host.bat without launcher: game directly with data paths")
    (d / "RaF Remaster.exe").write_bytes(b"")
    check(run("Host.bat", "Game", "Me") == ['"RaF Remaster.exe" -hostgame "Game" -playername "Me" -pid "1" -pass "raf"'],
          "Host.bat with launcher: through the launcher, arguments unchanged")
    check(run("Join.bat", "1.2.3.4", "Me") == ['"RaF Remaster.exe" -joinbyip "1.2.3.4" -playername "Me" -pid "2" -pass "raf"'],
          "Join.bat with launcher")
    check(run("Run.bat") == ['"RaF Remaster.exe" '], "start script with launcher")


def main():
    rt.set_lang("en")
    check_versions()
    tmp = Path(tempfile.mkdtemp(prefix="raf-upd-test-"))
    try:
        check_cache_and_offer(tmp)
        check_http(tmp)
        check_processes(tmp)
        check_carry(tmp)
        check_run_update(tmp)
        check_registry(tmp)
        check_finish_files(tmp)
        check_launcher(tmp)
        check_bats(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
