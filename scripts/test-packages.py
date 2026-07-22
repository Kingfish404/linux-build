#!/usr/bin/env python3
"""Boot every packaged kernel in QEMU and wait for a userspace-ready marker."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


READY_MARKERS = {
    "tiny_shell": ("tinysh: initramfs shell ready",),
    "buildroot": ("Welcome to Buildroot", "buildroot login:"),
}
FAILURE_MARKERS = (
    "Kernel panic - not syncing",
    "No working init found",
    "Attempted to kill init",
)


def archive_metadata(archive: Path) -> tuple[int, str]:
    with tarfile.open(archive, "r:gz") as package:
        readmes = [member for member in package.getmembers()
                   if member.isfile() and Path(member.name).name == "README.md"]
        if len(readmes) != 1:
            raise ValueError(f"expected one README.md, found {len(readmes)}")
        source = package.extractfile(readmes[0])
        if source is None:
            raise ValueError("cannot read README.md")
        readme = source.read().decode("utf-8", errors="replace")

    bits_match = re.search(r"\| Kernel ISA \| `rv(32|64)", readme)
    variant_match = re.search(r"\| Variant \| (tiny_shell|buildroot) \|", readme)
    if bits_match is None or variant_match is None:
        raise ValueError("README.md lacks Kernel ISA or Variant metadata")
    return int(bits_match.group(1)), variant_match.group(1)


def extract_boot_files(archive: Path, destination: Path) -> tuple[Path, Path, Path]:
    required = {"Image": destination / "Image",
                "initramfs.cpio.gz": destination / "initramfs.cpio.gz",
                "fw_dynamic.bin": destination / "fw_dynamic.bin"}
    found: set[str] = set()

    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            basename = Path(member.name).name
            if not member.isfile() or basename not in required:
                continue
            if basename in found:
                raise ValueError(f"duplicate {basename} in archive")
            source = package.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read {basename}")
            with required[basename].open("wb") as output:
                shutil.copyfileobj(source, output)
            found.add(basename)

    missing = required.keys() - found
    if missing:
        raise ValueError(f"missing {', '.join(sorted(missing))}")
    return (required["Image"], required["initramfs.cpio.gz"],
            required["fw_dynamic.bin"])


def boot_package(archive: Path, timeout_seconds: float, log_path: Path) -> None:
    bits, variant = archive_metadata(archive)
    qemu = shutil.which(f"qemu-system-riscv{bits}")
    if qemu is None:
        raise RuntimeError(f"qemu-system-riscv{bits} not found")

    with tempfile.TemporaryDirectory(prefix="linux-package-test-") as temp_name:
        image, initramfs, firmware = extract_boot_files(archive, Path(temp_name))
        command = [
            qemu, "-M", "virt", "-m", "1024M", "-nographic", "-no-reboot",
            "-bios", str(firmware),
            "-kernel", str(image), "-initrd", str(initramfs),
            "-netdev", "user,id=net0",
            "-device", "virtio-net-device,netdev=net0",
            "-append", "root=/dev/ram rdinit=/init console=ttyS0 ip=dhcp",
        ]
        start = time.monotonic()
        output = ""
        with log_path.open("wb") as log_file:
            process = subprocess.Popen(command, stdout=log_file,
                                       stderr=subprocess.STDOUT)
            try:
                while True:
                    log_file.flush()
                    output = log_path.read_text(encoding="utf-8", errors="replace")
                    if any(marker in output for marker in READY_MARKERS[variant]):
                        elapsed = time.monotonic() - start
                        print(f"PASS ({elapsed:.1f}s, rv{bits}, {variant})")
                        return
                    failure = next((marker for marker in FAILURE_MARKERS
                                    if marker in output), None)
                    if failure is not None:
                        raise RuntimeError(f"guest failure: {failure}")
                    return_code = process.poll()
                    if return_code is not None:
                        raise RuntimeError(f"QEMU exited with status {return_code}")
                    if time.monotonic() - start >= timeout_seconds:
                        raise TimeoutError(
                            f"no {variant} ready marker within {timeout_seconds:g}s")
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--timeout", type=float, default=30,
                        help="per-package boot timeout in seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    archives = sorted(args.dist.glob("*.tar.gz"))
    if not archives:
        print(f"ERROR: no release tarballs found in {args.dist}", file=sys.stderr)
        return 1

    log_dir = args.dist / "test-logs"
    shutil.rmtree(log_dir, ignore_errors=True)
    log_dir.mkdir(parents=True)
    print(f"Testing {len(archives)} packages with a {args.timeout:g}s timeout each")

    for index, archive in enumerate(archives, 1):
        log_path = log_dir / f"{archive.name.removesuffix('.tar.gz')}.log"
        print(f"[{index}/{len(archives)}] {archive.name}: ", end="", flush=True)
        try:
            boot_package(archive, args.timeout, log_path)
        except (OSError, RuntimeError, TimeoutError, ValueError, tarfile.TarError) as error:
            print(f"FAIL ({error})")
            print(f"Boot log: {log_path}", file=sys.stderr)
            return 1

    print(f"All {len(archives)} packaged kernels reached userspace.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())