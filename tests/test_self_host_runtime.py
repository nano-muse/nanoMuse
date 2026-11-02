"""The optional two-stack setup uses stopped containers and stops on failed setup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="self-host setup runs in Bash")
FAKE = r"""
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["SETUP_LOG"], "a") as log:
    log.write(json.dumps([name, args, os.environ.get("NANOMUSE_RUNTIME_BIND"),
                          os.environ.get("NANOMUSE_RUNTIME_PORT")]) + "\n")
mode = os.environ.get("SETUP_FAILURE", "")
if name == "docker":
    if args[:1] == ["compose"]:
        if "ps" in args:
            if args[-1] == "relay":
                print("relay-container")
            elif "-a" in args:
                print("runtime-container")
        if "--no-start" in args and mode == "create":
            sys.exit(1)
        if "start" in args and mode == "start":
            sys.exit(1)
    elif args[:2] == ["network", "connect"]:
        if mode in {"network", "already-joined", "similar-network"}:
            sys.exit(1)
    elif args[:1] == ["inspect"]:
        print("relay_default" if args[-1] == "relay-container" else "relay_default_extra" if mode == "similar-network" else "" if mode == "network" else "relay_default")
elif name == "curl" and mode == "health" and "/api/health" in args[-1]:
    sys.exit(1)
"""


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for folder in ("scripts", "cloud", "config", "bin"):
        (tmp_path / folder).mkdir()
    shutil.copyfile(ROOT / "scripts/self-host.sh", tmp_path / "scripts/self-host.sh")
    for name in ("cloud/.env.example", "config/config.example.toml", ".env.example"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SETUP_LOG", str(log))
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    for name in ("docker", "curl", "sleep"):
        command = tmp_path / "bin" / name
        command.write_text(f"#!{sys.executable}\n" + FAKE, encoding="utf-8")
        command.chmod(0o755)

    def run(*args: str, failure: str = "", answers: str = "\n" * 20):
        log.write_text("")
        monkeypatch.setenv("SETUP_FAILURE", failure)
        result = subprocess.run(
            ["bash", "scripts/self-host.sh", *args],
            cwd=tmp_path,
            input=answers,
            text=True,
            capture_output=True,
            timeout=30,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    return tmp_path, run


def test_runtime_is_created_joined_then_started_and_retains_token(setup) -> None:
    root, run = setup
    result, calls = run("--local", "--with-runtime")
    assert result.returncode == 0
    create = next(i for i, c in enumerate(calls) if "--no-start" in c[1])
    joined = next(i for i, c in enumerate(calls) if c[1][:2] == ["network", "connect"])
    start = next(i for i, c in enumerate(calls) if "start" in c[1])
    assert create < joined < start
    assert calls[create][2:] == ["127.0.0.1", "8788"]
    assert calls[joined][1][-1] == "runtime-container"
    assert (root / "config/config.toml").is_file()
    before = (root / ".env").read_text()
    result, _ = run("--local", "--with-runtime", failure="already-joined")
    assert result.returncode == 0
    assert (root / ".env").read_text() == before


@pytest.mark.parametrize("failure", ["create", "network", "similar-network", "start", "health"])
def test_failed_runtime_setup_never_claims_success(setup, failure: str) -> None:
    _, run = setup
    result, calls = run("--local", "--with-runtime", failure=failure)
    assert result.returncode != 0
    assert "  Runtime   " not in result.stdout
    if failure in {"create", "network", "similar-network"}:
        assert not any("start" in c[1] for c in calls)


def test_domain_does_not_publish_the_plain_http_runtime(setup) -> None:
    _, run = setup
    result, calls = run("--with-runtime", answers="relay.example.com\n" + "\n" * 20)
    assert result.returncode == 0
    assert next(c for c in calls if "--no-start" in c[1])[2:] == ["127.0.0.1", "8788"]


def test_an_explicit_bind_address_is_also_used_for_health(setup) -> None:
    _, run = setup
    result, calls = run("--local", "--bind", "192.0.2.10", "--runtime-port", "9000")
    assert result.returncode == 0
    assert next(c for c in calls if "--no-start" in c[1])[2:] == ["192.0.2.10", "9000"]
    assert any(c[0] == "curl" and c[1][-1] == "http://192.0.2.10:9000/api/health" for c in calls)


@pytest.mark.parametrize("port", ["0", "65536", "999999999999999999999"])
def test_invalid_runtime_port_fails_before_docker(setup, port: str) -> None:
    _, run = setup
    result, calls = run("--local", "--runtime-port", port)
    assert result.returncode != 0
    assert not calls


def test_relay_only_does_not_write_runtime_config(setup) -> None:
    root, run = setup
    result, calls = run("--local")
    assert result.returncode == 0
    assert not (root / "config/config.toml").exists()
    assert not (root / ".env").exists()
    assert not any("--no-start" in c[1] for c in calls)


def test_conflicting_ports_fail_before_building(setup) -> None:
    _, run = setup
    result, calls = run("--local", "--port", "08787", "--runtime-port", "8787")
    assert result.returncode != 0
    assert not any("build" in c[1] or "--build" in c[1] for c in calls)


def test_no_start_leaves_runtime_untouched(setup) -> None:
    root, run = setup
    result, calls = run("--local", "--with-runtime", "--no-start")
    assert result.returncode == 0
    assert not (root / ".env").exists()
    assert not (root / "config/config.toml").exists()
    assert not any("build" in c[1] or "--build" in c[1] for c in calls)


def test_existing_config_directory_is_kept(setup) -> None:
    root, run = setup
    directory = root / "config/config.toml"
    directory.mkdir()
    (directory / "keep").write_text("existing data")
    result, calls = run("--local", "--with-runtime")
    assert result.returncode != 0
    assert (directory / "keep").read_text() == "existing data"
    assert "rmdir" in result.stderr and "rm -rf" not in result.stderr
    assert not any("build" in c[1] or "--build" in c[1] for c in calls)
