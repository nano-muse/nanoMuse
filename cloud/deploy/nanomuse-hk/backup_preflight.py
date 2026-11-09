#!/usr/bin/env python3
"""Check space available to the relay before allocating a database snapshot."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

BUSINESS_RESERVE = 5 * 1024**3


def database_budget(source: Path) -> int:
    """Include uncheckpointed growth without opening or checkpointing SQLite."""
    info = source.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise ValueError("invalid_database_file")
    size = info.st_size
    try:
        wal = source.with_name(source.name + "-wal").stat(follow_symlinks=False)
    except FileNotFoundError:
        return size
    if not stat.S_ISREG(wal.st_mode):
        raise ValueError("invalid_wal_file")
    return size + wal.st_size


def inspect_capacity(source: Path, destination: Path) -> dict:
    size = database_budget(source)
    # The snapshot can coexist with a rollback journal or its compressed output.
    # f_bavail excludes root-reserved blocks: the container writes as an ordinary UID.
    required = 2 * size + BUSINESS_RESERVE
    filesystems: dict[int, Path] = {}
    for path in (source.parent, destination):
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("invalid_backup_directory")
        filesystems.setdefault(info.st_dev, path)
    available = []
    for path in filesystems.values():
        space = os.statvfs(path)
        if space.f_frsize <= 0 or space.f_bavail < 0:
            raise ValueError("invalid_space_metadata")
        available.append(space.f_bavail * space.f_frsize)
    return {
        "status": "allowed" if min(available) >= required else "insufficient_space",
        "database_and_wal_bytes": size,
        "required_bytes_per_filesystem": required,
        "available_bytes": available,
        "business_reserve_bytes": BUSINESS_RESERVE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_capacity(args.source, args.destination)
    except OSError as error:
        result = {"status": "refused", "reason": "filesystem_error", "errno": error.errno}
    except ValueError as error:
        result = {"status": "refused", "reason": str(error)}
    allowed = result["status"] == "allowed"
    print(json.dumps({"check": "relay_backup_capacity", **result}), file=sys.stdout if allowed else sys.stderr)
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
