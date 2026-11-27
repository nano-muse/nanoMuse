"""Verify the PRoot executables and Alpine shell shipped in an arm64 APK."""

import argparse
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Literal
from zipfile import BadZipFile, ZipFile


def check_elf(data: bytes, name: str, *, arm32: bool = False) -> None:
    # ELF class, little-endian encoding and e_machine must agree with the ABI.
    elf_class, machine, header_size = (1, 40, 52) if arm32 else (2, 183, 64)
    if (
        len(data) < header_size
        or data[:6] != b"\x7fELF" + bytes([elf_class, 1])
        or int.from_bytes(data[18:20], "little") != machine
    ):
        raise ValueError(f"{name}: expected an {'ARM' if arm32 else 'AArch64'} ELF executable")


def verify_sandbox(apk: Path) -> None:
    with ZipFile(apk) as archive:
        for name in (
            "lib/arm64-v8a/libproot.so",
            "lib/arm64-v8a/libproot-loader.so",
            "lib/arm64-v8a/libproot-loader32.so",
            "assets/proot-aarch64",
        ):
            data = archive.read(name)
            check_elf(data, name, arm32=name.endswith("loader32.so"))
            if name.endswith(("libproot.so", "proot-aarch64")) and b"--native-offload" not in data:
                raise ValueError(f"{name}: missing the PRoot native offload extension")

        # RootfsManager prefers the gzip asset. AAPT can also package it as a plain tar.
        asset = "assets/alpine-minirootfs.tar.gz"
        if asset not in archive.namelist():
            asset = "assets/alpine-minirootfs.tar"
        mode: Literal["r:gz", "r:"] = "r:gz" if asset.endswith(".gz") else "r:"
        with archive.open(asset) as stream, tarfile.open(fileobj=stream, mode=mode) as rootfs:
            members = {str(PurePosixPath(m.name)): m for m in rootfs}
            shell = members["bin/sh"]
            if not shell.issym() or shell.linkname not in ("/bin/busybox", "busybox"):
                raise ValueError(f"{asset}: expected the Alpine /bin/sh link to BusyBox")
            for path in ("bin/busybox", "lib/ld-musl-aarch64.so.1"):
                entry = members[path]
                if not entry.isfile() or not (entry.mode & 0o111):
                    raise ValueError(f"{asset}: {path} must be executable")
                executable = rootfs.extractfile(entry)
                assert executable is not None  # entry is a regular file
                with executable:
                    check_elf(executable.read(64), path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    try:
        verify_sandbox(args.apk)
    except (BadZipFile, OSError, EOFError, KeyError, tarfile.TarError, ValueError) as exc:
        print(f"{args.apk}: invalid arm64 sandbox: {exc}", file=sys.stderr)
        return 1
    print(f"{args.apk}: verified arm64 PRoot, loaders and Alpine shell")
    return 0


if __name__ == "__main__":
    sys.exit(main())
