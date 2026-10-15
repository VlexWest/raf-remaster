"""End-to-end test of the auto update with the built dist/ (offline, local HTTP server, test registry).

    python tools/e2e_update.py [--stock "D:/Games/Rise and Fall"] [--scratch D:/raf-upd-e2e] [--keep]

1. dist/RaF-Remaster-Setup.exe --selftest installs a copy of the stock game into <scratch>/Rise and Fall
   Remaster (registry under HKCU\\Software\\RaF-Remaster-Installer-Test, shortcuts under <scratch>/links,
   no HD textures).
2. "The player" changes two settings in the test registry and adds a savegame.
3. A local server answers releases/latest with v<next> and serves the same setup exe + its .sha256.
   <install>/.raf-remaster/update.json points the launcher at it (test_answer=update, dry_run_game:
   the game is never started, the command line is written into <scratch>/dry.txt).
4. "RaF Remaster.exe" -hostgame "E2E Game" -playername "Tester" is started: it downloads, verifies and
   starts the setup in --update --headless mode, which rebuilds, swaps, carries files over and
   relaunches the launcher (--skip-check), which "starts" the game with the original arguments.
5. Checks: fingerprint unchanged, settings and save kept, launcher replaced, side folders gone,
   Uninstall.bat + uninstall entry for the final folder, game command with the arguments.
6. Cleanup: Uninstall.bat /quiet, test registry key, scratch folder (leftovers are listed).
The game itself is never started and nothing outside <scratch> and the test key is written.
"""

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import raf_update as ru  # noqa: E402
from raf_version import VERSION  # noqa: E402

TEST_KEY = r"Software\RaF-Remaster-Installer-Test"
GAME_KEY = TEST_KEY + r"\Rise and Fall"
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


def reg_get(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_set(path, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def delete_tree(path):
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


def serve(routes):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            status, body = routes.get(self.path, (404, b""))
            self.send_response(status)
            if status in (301, 302):
                self.send_header("Location", body.decode())
                body = b""
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main():
    args = sys.argv[1:]
    stock = Path(args[args.index("--stock") + 1]) if "--stock" in args else Path(r"D:\Games\Rise and Fall")
    scratch = Path(args[args.index("--scratch") + 1]) if "--scratch" in args else Path(r"D:\raf-upd-e2e")
    hd = "--hd" in args  # install with HD textures; the update must take them over instead of upscaling
    setup = REPO / "dist" / "RaF-Remaster-Setup.exe"
    sha_file = setup.with_name(setup.name + ".sha256")
    if scratch.exists():
        sys.exit(f"{scratch} exists; remove it first")
    if reg_get(GAME_KEY, "Full Screen Mode") is not None:
        sys.exit("test registry key in use (another selftest?)")
    inst = scratch / "Rise and Fall Remaster"
    scratch.mkdir(parents=True)
    t0 = time.time()
    try:
        # 1. install
        r = subprocess.run([str(setup), "--selftest", "--source", str(stock), "--target", str(inst),
                            "--test-root", str(scratch / "links"), "--lang", "en",
                            "--log", str(scratch / "install.log")] + ([] if hd else ["--no-hd"]))
        print(f"install: exit {r.returncode} after {time.time() - t0:.0f} s", flush=True)
        check(r.returncode in (0, 3), "selftest install finished (0 = fingerprint as expected, 3 = differs)")
        state0 = json.loads((inst / ".raf-remaster" / "state.json").read_text())
        info0 = json.loads((inst / ".raf-remaster" / "install.json").read_text(encoding="utf-8"))
        launcher = inst / ru.LAUNCHER_EXE
        check(launcher.is_file() and (inst / ru.LAUNCHER_DIR).is_dir(), "launcher installed next to the game")
        check(info0["version"] == VERSION and info0["test_root"] and info0["hd"] is hd,
              f"install.json: version {info0['version']}, test marker, HD {'on' if hd else 'off'}")
        if hd:
            check(all((inst / ".raf-remaster" / "hd" / n).is_file() for n in
                      ("key.txt", "manifest-hd-terrain.json", "manifest-hd-units.json")), "HD manifests + key saved")
        lnk = scratch / "links" / "Desktop" / "Rise and Fall Remaster.lnk"
        check(lnk.is_file(), "desktop shortcut written (into the test root)")
        check((inst / "REMASTER-NOTICE.txt").is_file() and
              (inst / "Remaster-Licenses" / "RaF-Remaster-Apache-2.0.txt").is_file(), "NOTICE + Apache license installed")
        fp0 = state0["fingerprint"]

        # 2. the player
        reg_set(GAME_KEY + r"\Graphics Settings", "Model Quality Level", 1)
        reg_set(GAME_KEY, "Remaster Camera Zoom", 150)
        (inst / "Users" / "default").mkdir(parents=True, exist_ok=True)
        (inst / "Users" / "default" / "e2e-save.sav").write_bytes(b"my save")
        launcher_stat0 = launcher.stat()
        uninstall_name = [n for n in os.listdir(scratch / "links" / "Startmenu" / "Rise and Fall Remaster")]

        # 3. server
        data = setup.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        check(sha_file.read_text().split()[0] == digest, "dist .sha256 file matches the setup")
        nxt = ".".join(map(str, (lambda v: (v[0], v[1], v[2] + 1))(ru.parse_version(VERSION))))
        routes = {}
        httpd, base = serve(routes)
        routes["/latest"] = (200, json.dumps({
            "tag_name": "v" + nxt, "name": "v" + nxt, "body": "E2E test release\n- nothing changes", "draft": False,
            "prerelease": False, "html_url": base, "assets": [
                {"name": ru.SETUP_ASSET, "browser_download_url": base + "/setup.exe", "size": len(data)},
                {"name": ru.HASH_ASSET, "browser_download_url": base + "/setup.sha256", "size": 90}]}).encode())
        routes["/setup.exe"] = (200, data)
        routes["/setup.sha256"] = (200, sha_file.read_bytes())
        dry = scratch / "dry.txt"
        (inst / ".raf-remaster" / "update.json").write_text(json.dumps(
            {"api": base + "/latest", "test_answer": "update", "dry_run_game": str(dry),
             "download_dir": str(scratch / "dl")}))

        # 4. launcher
        t1 = time.time()
        subprocess.run(f'"{launcher}" -hostgame "E2E Game" -playername "Tester"', cwd=str(inst))
        setup_log = dry.with_suffix(".setup.log")
        end = time.time() + 1800
        result = None
        while time.time() < end:
            text = setup_log.read_text(encoding="utf-8", errors="replace") if setup_log.exists() else ""
            if "\nDONE: " in text or "\nFAILED: " in text or "\nREFUSED: " in text:
                result = text
                break
            time.sleep(3)
        for _ in range(20):  # the relaunched launcher writes the dry-run line
            if dry.exists():
                break
            time.sleep(1)
        print(f"update: {time.time() - t1:.0f} s", flush=True)
        check(result is not None and "\nDONE: " in result, "update finished (DONE in the setup log)")
        if hd:
            check(result.count("taken over from the previous install") == 2, "both HD steps taken over, not upscaled")
        state1 = json.loads((inst / ".raf-remaster" / "state.json").read_text())
        info1 = json.loads((inst / ".raf-remaster" / "install.json").read_text(encoding="utf-8"))
        check(state1["fingerprint"] == fp0, f"fingerprint unchanged ({fp0} -> {state1['fingerprint']})")
        check(info1["install_dir_before"] == info0["install_dir_before"] and info1["test_root"] == info0["test_root"],
              "install.json carried its first-install values over")
        check(reg_get(GAME_KEY + r"\Graphics Settings", "Model Quality Level") == 1 and
              reg_get(GAME_KEY, "Remaster Camera Zoom") == 150, "player's graphics + zoom settings kept")
        check((inst / "Users" / "default" / "e2e-save.sav").read_bytes() == b"my save", "savegame kept")
        st = launcher.stat()
        check(launcher.is_file() and (st.st_ctime != launcher_stat0.st_ctime or st.st_ino != launcher_stat0.st_ino),
              "launcher replaced by the new build's copy")
        check(not ru.sibling(inst, ".raf-old").exists() and not ru.sibling(inst, ".raf-update").exists(),
              "no side folders left")
        bat = (inst / "Uninstall.bat").read_text(encoding="utf-8")
        check(f'rd /s /q "{inst}"' in bat and "RaF-Remaster-Installer-Test" in bat, "Uninstall.bat names the final folder + test key")
        check(reg_get(TEST_KEY + r"\Uninstall\RaF-Remaster", "InstallLocation") == str(inst),
              "uninstall entry points at the final folder")
        check(sorted(os.listdir(scratch / "links" / "Startmenu" / "Rise and Fall Remaster")) == sorted(uninstall_name),
              "start menu entries the same after the update")
        cmd = dry.read_text(encoding="utf-8").strip().splitlines() if dry.exists() else []
        check(len(cmd) == 1 and cmd[0] == f'"{inst / "RiseAndFall.exe"}" -datapath "Data\\" -redistpath "Redist\\" '
              '-hostgame "E2E Game" -playername "Tester"', f"game (dry run) started once with the arguments {cmd}")
        cache = ru.read_cache(inst)
        check(cache.get("release", {}).get("tag") == "v" + nxt, "update cache carried over")

        # 5b. the frozen launcher against the real GitHub API over TLS: the loopback test API redirects
        # to https://api.github.com/repos/<UPDATE_REPO>/releases/latest (private repo: 404 = no update)
        routes["/gh"] = (302, ru.API_TEMPLATE.format(repo=ru.UPDATE_REPO).encode())
        (inst / ".raf-remaster" / "update.json").write_text(json.dumps(
            {"api": base + "/gh", "dry_run_game": str(dry), "download_dir": str(scratch / "dl")}))
        (inst / ".raf-remaster" / ru.CACHE_FILE).unlink()
        t2 = time.time()
        subprocess.run(f'"{launcher}"', cwd=str(inst))
        cache = ru.read_cache(inst)
        print(f"github check: {time.time() - t2:.1f} s, cache {json.dumps(cache)[:300]}", flush=True)
        check("checked" in cache and (cache.get("error") is None or "SSL" not in str(cache.get("error"))),
              f"frozen launcher reached api.github.com over TLS (error: {cache.get('error')}, "
              f"release: {(cache.get('release') or {}).get('tag')})")
        check(len(dry.read_text(encoding="utf-8").strip().splitlines()) == 2, "game (dry run) started after the check")
        httpd.shutdown()
    finally:
        # 6. cleanup
        if "--keep" not in args:
            bat = inst / "Uninstall.bat"
            if bat.exists():
                r = subprocess.run(["cmd", "/c", str(bat), "/quiet"], capture_output=True)
                print(f"Uninstall.bat /quiet: exit {r.returncode}")
                for _ in range(20):
                    if not inst.exists():
                        break
                    time.sleep(0.5)
            delete_tree(TEST_KEY)
            shutil.rmtree(scratch, ignore_errors=True)
            left = [str(p) for p in (scratch, ru.sibling(inst, ".raf-old")) if p.exists()]
            try:
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY).Close()
                left.append("HKCU\\" + TEST_KEY)
            except FileNotFoundError:
                pass
            print("leftovers: " + (", ".join(left) or "none"))
            check(not left, "cleanup: scratch folder and test registry key removed")
    print(f"total {time.time() - t0:.0f} s")
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
