#!/usr/bin/env python3
"""Package a clean RV64 disk, matching kernel and OpenSBI for release tests."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib

from release_common import distro_inputs, package_name, sha, ROOT, DISTROS


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preset', type=Path, required=True)
    ap.add_argument('--disk', type=Path, required=True)
    ap.add_argument('--kernel-dir', type=Path, required=True)
    ap.add_argument('--firmware-dir', type=Path, required=True)
    ap.add_argument('--dist', type=Path, required=True)
    a = ap.parse_args()
    cfg = tomllib.loads(a.preset.read_text())
    variant = cfg['rootfs']['type']
    if cfg['target']['arch'] != 'riscv64' or variant not in DISTROS:
        ap.error('unsupported distribution target')
    name = package_name(a.preset, cfg, variant)
    rootfs = json.loads(a.disk.with_suffix('.json').read_text())
    if sha(a.disk) != rootfs['rootfs_sha256']:
        ap.error('release disk was modified since construction')
    if (sha(a.kernel_dir / 'arch/riscv/boot/Image') != rootfs['kernel_sha256'] or
            sha(a.firmware_dir / 'fw_dynamic.bin') != rootfs['firmware_sha256'] or
            sha(a.disk.with_suffix('.build.log')) != rootfs['build_log_sha256']):
        ap.error('kernel, firmware or provisioning log changed since clean disk construction')
    config = (a.kernel_dir / '.config').read_text().splitlines()
    required = ('CONFIG_FPU=y', 'CONFIG_RISCV_ISA_C=y', 'CONFIG_MMU=y', 'CONFIG_HZ=100',
                'CONFIG_EXT4_FS=y', 'CONFIG_VIRTIO_BLK=y', 'CONFIG_VIRTIO_NET=y',
                'CONFIG_DEVTMPFS_MOUNT=y', 'CONFIG_INITRAMFS_SOURCE=""')
    if any(line not in config for line in required):
        ap.error('kernel lacks required distribution disk configuration')
    built_version = (a.kernel_dir / 'include/config/kernel.release').read_text().strip()
    if built_version != cfg['kernel']['version']:
        ap.error(f'kernel version {built_version} differs from preset')
    m = {'schema': 2, 'preset': a.preset.stem, 'variant': variant, 'bits': 64,
         'kernel_version': built_version, 'kernel_hz': 100, 'memory_mib': cfg['boot']['memory'],
         'abi': 'lp64d', 'opensbi_isa': 'rv64imafdc_zicntr_zicsr_zifencei',
         'build_inputs': distro_inputs(a.preset), 'created': time.time(),
         'board_tested': False,
         'source_commit': subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip(),
         'opensbi_commit': subprocess.check_output(['git', '-C', ROOT / 'opensbi', 'rev-parse', 'HEAD'], text=True).strip()}
    a.dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='package-', dir=a.dist) as tmp:
        stage = Path(tmp) / name
        stage.mkdir()
        for src, dest in ((a.disk, 'rootfs.ext4'), (a.disk.with_suffix('.json'), 'rootfs-manifest.json'),
                          (a.disk.with_suffix('.build.log'), 'rootfs-build.log'),
                          (a.kernel_dir / 'arch/riscv/boot/Image', 'Image'),
                          (a.kernel_dir / 'vmlinux', 'vmlinux'),
                          (a.kernel_dir / '.config', 'kernel.config'),
                          (a.firmware_dir / 'fw_dynamic.bin', 'fw_dynamic.bin'),
                          (a.preset, 'preset.toml')):
            subprocess.run(['cp', '--sparse=always', src, stage / dest], check=True)
        source_record = a.kernel_dir / 'source/.linux-build-source.json'
        if source_record.is_file():
            shutil.copy2(source_record, stage / 'kernel-source.json')
        launch = '''#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec qemu-system-riscv64 -M virt -cpu rv64,h=false,sstc=false,svadu=false \\
  -m 1024M -nographic -bios fw_dynamic.bin -kernel Image \\
  -drive file=rootfs.ext4,format=raw,if=none,id=rootfs \\
  -device virtio-blk-device,drive=rootfs \\
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_PORT:-2222}-:22 \\
  -device virtio-net-device,netdev=net0 \\
  -append 'root=/dev/vda rootfstype=ext4 rw rootwait init=/sbin/raptor-init console=ttyS0 earlycon=sbi'
'''
        (stage / 'run-qemu.sh').write_text(launch)
        (stage / 'run-qemu.sh').chmod(0o755)
        (stage / 'README.md').write_text(f'''# {a.preset.stem} / Linux {built_version}

RV64GC/lp64d {variant} userspace with its upstream package repositories.
Run `./run-qemu.sh` (1 GiB RAM), press Enter for the serial root shell.
The serial root shell is for bring-up and has no login authentication.
SSH listens through localhost:2222 with password authentication disabled.
Provision an account and authorized key over the serial console before SSH use.

The raw ext4 disk is persistent: extract a fresh copy for a clean system.
Do not run two VMs on the same writable disk. Use `/bin/busybox poweroff` before
copying it. BusyBox init handles boot/reaping; services requiring systemd or
OpenRC need explicit integration. This is a QEMU disk release, not an embedded
firmware payload or a validated FPGA SD-card layout.

`manifest.json` hashes every supplied file; `rootfs-manifest.json` records the
clean disk, OCI build identity and installed package set. Test results and
archive SHA256 values are supplied alongside the release.
''')
        m['files'] = {p.name: sha(p) for p in sorted(stage.iterdir())}
        (stage / 'manifest.json').write_text(json.dumps(m, indent=2, sort_keys=True) + '\n')
        archive_tmp = Path(tmp) / (name + '.tar.gz')
        with tarfile.open(archive_tmp, 'w:gz') as archive:
            archive.add(stage, arcname=name)
        dest = a.dist / name
        if dest.exists():
            # Preserve prior artifacts instead of deleting them on rebuild.
            prior = a.dist / '.superseded'
            prior.mkdir(exist_ok=True)
            dest.rename(prior / (name + '-' + str(time.time_ns())))
        stage.rename(dest)
        os.replace(archive_tmp, a.dist / (name + '.tar.gz'))
    print(f'Packaged {name}')


if __name__ == '__main__':
    main()
