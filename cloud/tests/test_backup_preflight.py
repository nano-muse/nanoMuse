"""A failed scheduled backup must not consume the relay's remaining disk space."""

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).parents[1] / "deploy" / "nanomuse-hk"
SPEC = importlib.util.spec_from_file_location("backup_preflight", DEPLOY / "backup_preflight.py")
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture
def locations(tmp_path):
    source = tmp_path / "relay" / "data" / "cloud.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"database fixture")
    destination = tmp_path / "backups"
    destination.mkdir()
    return source, destination


def space(available):
    return SimpleNamespace(f_frsize=1, f_bavail=available, f_bfree=10**15)


def test_root_reserved_space_does_not_make_the_container_backup_safe(monkeypatch, locations):
    monkeypatch.setattr(preflight.os, "statvfs", lambda _: space(0), raising=False)
    result = preflight.inspect_capacity(*locations)
    assert result["status"] == "insufficient_space"
    assert result["available_bytes"] == [0]


@pytest.mark.parametrize("delta,allowed", [(-1, False), (0, True), (1, True)])
def test_budget_boundary_includes_wal_and_business_headroom(monkeypatch, locations, delta, allowed):
    source, destination = locations
    source.with_name("cloud.db-wal").write_bytes(b"uncheckpointed growth")
    size = len(b"database fixture") + len(b"uncheckpointed growth")
    monkeypatch.setattr(preflight.os, "statvfs", lambda _: space(2 * size + 5 * 1024**3 + delta), raising=False)
    result = preflight.inspect_capacity(source, destination)
    assert (result["status"] == "allowed") is allowed
    assert result["database_and_wal_bytes"] == size


def test_a_separate_full_destination_is_also_rejected(monkeypatch, locations):
    source, destination = locations
    real_stat = Path.stat

    def separate_device(path, **kwargs):
        info = real_stat(path, **kwargs)
        return SimpleNamespace(st_dev=-1, st_mode=info.st_mode) if path == destination else info

    monkeypatch.setattr(Path, "stat", separate_device)
    monkeypatch.setattr(preflight.os, "statvfs", lambda path: space(0 if path == destination else 10**15), raising=False)
    assert preflight.inspect_capacity(source, destination)["status"] == "insufficient_space"


def test_missing_database_is_not_a_zero_size_backup(locations):
    source, destination = locations
    with pytest.raises(FileNotFoundError):
        preflight.inspect_capacity(source.with_name("missing.db"), destination)


def test_nonregular_database_is_refused(locations):
    source, destination = locations
    with pytest.raises(ValueError, match="invalid_database_file"):
        preflight.inspect_capacity(source.parent, destination)


def test_unreadable_space_metadata_fails_closed(monkeypatch, locations):
    def unavailable(_):
        raise OSError("unavailable")

    monkeypatch.setattr(preflight.os, "statvfs", unavailable, raising=False)
    with pytest.raises(OSError):
        preflight.inspect_capacity(*locations)


@pytest.mark.skipif(os.name == "nt" or not shutil.which("flock"), reason="The deployed backup uses a POSIX shell and flock")
def test_shell_stops_before_docker_or_retention_when_capacity_is_low(tmp_path, locations):
    source, destination = locations
    relay = source.parent.parent
    old_backup = destination / "cloud-old.db.gz"
    old_backup.write_bytes(b"keep this recovery point")
    commands = tmp_path / "bin"
    commands.mkdir()
    docker_marker = tmp_path / "docker-was-called"
    docker = commands / "docker"
    docker.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(docker_marker))}\nexit 99\n")
    docker.chmod(0o755)
    wrapper = tmp_path / "low_space.py"
    wrapper.write_text(
        "import os, runpy, sys\nfrom types import SimpleNamespace\n"
        "os.statvfs = lambda _: SimpleNamespace(f_frsize=4096, f_bavail=0, f_bfree=10**10)\n"
        "sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    python = commands / "python3"
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(wrapper))} "$@"\n')
    python.chmod(0o755)
    result = subprocess.run(
        ["sh", str(DEPLOY / "backup.sh")],
        env={
            **os.environ,
            "PATH": str(commands) + os.pathsep + os.environ.get("PATH", ""),
            "RELAY_DIR": str(relay),
            "BACKUP_DIR": str(destination),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "insufficient_space"
    assert not docker_marker.exists()
    assert old_backup.read_bytes() == b"keep this recovery point"
    assert not list(source.parent.glob(".backup-*.db*"))


@pytest.mark.skipif(os.name == "nt" or not shutil.which("flock"), reason="The deployed backup uses a POSIX shell and flock")
def test_a_second_backup_is_refused_before_copying(locations):
    import fcntl

    source, destination = locations
    relay = source.parent.parent
    with (relay / ".backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            ["sh", str(DEPLOY / "backup.sh")],
            env={**os.environ, "RELAY_DIR": str(relay), "BACKUP_DIR": str(destination)},
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert result.returncode == 1
    assert result.stderr.strip() == "backup: another backup is running"
    assert not list(source.parent.glob(".backup-*.db*"))
