#!/usr/bin/env python3
"""Build the runtime nanoMuse Desktop carries for the hands: a one-folder PyInstaller build of
`nanomuse` (serve, chat, the hub, this computer's screen and hands — `nanomuse mcp` is what the
desktop's preset points at) at harness/desktop/runtime/, where electron-builder picks it up as
an extra resource.

    python scripts/desktop-app/build-runtime.py            # from a venv with .[hands] and pyinstaller
    python scripts/desktop-app/build-runtime.py --check    # then start it once and ask /api/health
    python scripts/desktop-app/build-runtime.py --target build/runtime   # somewhere else

Needs: the repository's Python environment with `pip install -e ".[hands]" pyinstaller`.
The web app must already be built into nanomuse/server/static (it is committed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "desktop-app" / "nanomuse_runtime.spec"


def _clear_dir(path: Path) -> None:
    # A process the check just terminated can keep its working directory pinned a beat
    # after wait() returns; retry briefly rather than leave the probe's directories behind.
    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.05)


WORK = ROOT / "build" / "runtime-pyi"
DIST = ROOT / "build" / "runtime-dist"
TARGET = ROOT / "harness" / "desktop" / "runtime"


def run(*cmd: str, **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def build(target: Path) -> Path:
    shutil.rmtree(DIST, ignore_errors=True)
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        str(SPEC),
        cwd=str(ROOT),
    )
    built = DIST / "nanomuse"
    exe = built / ("nanomuse.exe" if sys.platform == "win32" else "nanomuse")
    if not exe.exists():
        raise SystemExit(f"PyInstaller produced nothing at {exe}")
    shutil.rmtree(target, ignore_errors=True)
    # Keep PyInstaller's relative library aliases and macOS framework layout intact.
    shutil.copytree(built, target, symlinks=True)
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) // (1024 * 1024)
    print(f"runtime: {target} ({size} MB)")
    return target / exe.name


def check(exe: Path) -> None:
    """Start the bundled runtime once, wait for /api/health, stop it.

    Started the way a launcher might: from an unrelated, empty working directory with only the
    data directory named. Everything the runtime writes — the workspace included — must land
    under that data directory (0.1.20/0.1.21 on Windows created ``./workspace`` wherever the
    shell happened to start it and died when that was not writable).
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    home = ROOT / "build" / "runtime-check-home"
    cwd = ROOT / "build" / "runtime-check-cwd"
    for d in (home, cwd):
        _clear_dir(d)
    cwd.mkdir(parents=True)
    env = dict(os.environ, NANOMUSE_DATA_DIR=str(home), PYTHONUTF8="1")
    for key in (
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL",
        "NANOMUSE_WORKSPACE",
    ):
        env.pop(key, None)
    # A startup log can exceed a pipe's capacity before the server listens.
    # A regular file also lets the timeout read diagnostics without waiting for EOF.
    # the health check is a call to this machine: the environment's proxy has no part in it
    # (a machine behind one polled the proxy instead and never saw the runtime come up)
    from nanomuse.local_http import local_open

    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            [str(exe), "serve", "--no-qr", "--no-auth", "--port", str(port)],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with local_open(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                        body = json.loads(r.read())
                        if body.get("ok"):
                            print("health:", body)
                            with local_open(f"http://127.0.0.1:{port}/", timeout=2) as r2:
                                page = r2.read()
                                assert (
                                    b'<div id="root"' in page
                                    or b"<div id=root" in page
                                    or len(page) > 200
                                )
                            assert (home / "workspace").is_dir(), "workspace not under the data dir"
                            assert not (cwd / "workspace").exists(), "workspace created in the cwd"
                            print("the app is served; the bundled runtime works")
                            return
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 4000))
            out = log.read(4000).decode("utf-8", errors="replace")
            raise SystemExit(f"the bundled runtime did not come up:\n{out}")
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
            for d in (home, cwd):
                _clear_dir(d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="start it once and ask /api/health")
    ap.add_argument(
        "--check-only", action="store_true", help="only check the runtime already built"
    )
    ap.add_argument(
        "--target",
        default=str(TARGET),
        help="where the built runtime goes (default harness/desktop/runtime)",
    )
    args = ap.parse_args()
    target = Path(args.target)
    if not target.is_absolute():
        target = ROOT / target
    if args.check_only:
        exe = target / ("nanomuse.exe" if sys.platform == "win32" else "nanomuse")
    else:
        exe = build(target)
    if args.check or args.check_only:
        check(exe)


if __name__ == "__main__":
    main()
