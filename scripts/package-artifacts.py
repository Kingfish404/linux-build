#!/usr/bin/env python3
"""Package the exact kernel, configuration and firmware from a build directory."""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def config_values(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            result[key] = value
    return result


def readme(m):
    bits = m['bits']
    fpu = m['variant'] == 'buildroot'
    isa = f'rv{bits}imafdc' if fpu else f'rv{bits}imac'
    runtime = '''## Buildroot runtime

Normal `/init` performs the complete initialization and service startup.
For a fast shell with working `/proc/cpuinfo`, `/sys`, `/dev` and `/dev/pts`,
use `rdinit=/sbin/raptor-shell` instead of `rdinit=/init` in the split command
above (or in board DTB bootargs); add `ip=dhcp` for kernel DHCP in this
service-free mode. This mounts runtime filesystems and starts
ash without services. Direct `rdinit=/bin/sh` skips those mounts.

The package enables BusyBox networking including `nc`, plus tinysh-compatible
`fetch IPv4 PORT /PATH FILE` and `run PATH [ARGS...]` helpers. BusyBox utilities
use their usual syntax, e.g. `mount -t TYPE SOURCE TARGET`, `ping -c 3 IPv4`
and `nc -l -p PORT`. A bare shell can run `/sbin/raptor-mounts` to mount the
runtime filesystems. Buildroot also provides normal shell scripting and
process/storage tools. Full init and the initialized fast shell are validated
separately by the release tests.

''' if fpu else ''
    return f'''# Linux {m['kernel_version']} — {m['preset']} / {m['variant']}

| Field | Value |
| --- | --- |
| Config | `{m['preset']}` |
| Kernel ISA | `{isa}` baseline; optional extensions follow the supplied DTB |
| OpenSBI ISA | `{m['opensbi_isa']}` |
| ABI | `{m['abi']}` |
| Variant | {m['variant']} |
| Kernel HZ | {m['kernel_hz']} |
| QEMU RAM | {m['memory_mib']} MiB |
| Kernel load address | `{m['kernel_address']}` |
| DTB relocation address | `{m['fdt_address']}` |

The complete configuration is in `kernel.config`; `manifest.json` records
file hashes, input versions and the firmware layout. Buildroot uses hard-float
userspace and requires both F/D hardware and a DTB that advertises them.
The tiny shell is a freestanding soft-float `/init`.

## Files

- `Image`, `vmlinux`: kernel binary and ELF.
- `fw_payload.bin`, `fw_payload.elf`: OpenSBI with this exact Image embedded.
- `fw_dynamic.bin`: OpenSBI for a separate Image/initramfs handoff.
- `initramfs.cpio.gz`: this variant's root filesystem.
- `kernel.config`, `preset.toml`, `manifest.json`: build configuration and provenance.

## QEMU

Complete payload (the embedded root filesystem starts `/init`):

```sh
qemu-system-riscv{bits} -M virt -m {m['memory_mib']}M -nographic \\
  -cpu rv{bits},h=false,sstc=false,svadu=false \\
  -bios fw_payload.bin -netdev user,id=net0 \\
  -device virtio-net-device,netdev=net0
```

Separate Image and root filesystem:

```sh
qemu-system-riscv{bits} -M virt -m {m['memory_mib']}M -nographic \\
  -cpu rv{bits},h=false,sstc=false,svadu=false \\
  -bios fw_dynamic.bin -kernel Image -initrd initramfs.cpio.gz \\
  -append 'root=/dev/ram rdinit=/init console=ttyS0 earlycon=sbi{'' if fpu else ' ip=dhcp'}' \\
  -netdev user,id=net0 -device virtio-net-device,netdev=net0
```

{runtime}## Raptor FPGA integration

HZ=100 targets the current 50 MHz Raptor workload. Supply the board-generated
LiteX DTB and stage0 with matching XLEN, ISA, RAM, MMIO and actual timebase.
`timebase-frequency` describes the hardware timer, not HZ. The payload's DTB
relocation must remain outside the kernel's memory extent. These files do not
contain a board-specific stage0 or an SD-card filesystem image.

QEMU results are recorded by the release validation and do not establish FPGA
or peripheral acceptance. Use the matching board bitstream; in particular,
RV64 Buildroot requires F/D to be advertised in the board DTB as well as
implemented in the core. Exit QEMU with Ctrl-A X.
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dist', type=Path, required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--kernel-dir', type=Path, required=True)
    ap.add_argument('--firmware-dir', type=Path, required=True)
    ap.add_argument('--initramfs', type=Path, required=True)
    ap.add_argument('--preset', type=Path, required=True)
    ap.add_argument('--variant', choices=('tiny_shell', 'buildroot'), required=True)
    ap.add_argument('--isa', required=True)
    ap.add_argument('--abi', required=True)
    ap.add_argument('--fdt-offset', type=lambda s: int(s, 0), required=True)
    a = ap.parse_args()
    if Path(a.name).name != a.name or a.name in ('.', '..'):
        ap.error('package name must be a basename')
    root = Path(__file__).resolve().parents[1]
    preset = tomllib.loads(a.preset.read_text())
    bits = int(preset['target']['arch'].removeprefix('riscv'))
    cfg = config_values(a.kernel_dir / '.config')
    hz = int(cfg['CONFIG_HZ'])
    if hz != preset['kernel']['config']['HZ']:
        ap.error('built HZ differs from the preset')
    fpu = cfg.get('CONFIG_FPU') == 'y'
    if fpu != (a.variant == 'buildroot'):
        ap.error('kernel FPU configuration differs from the packaged variant')
    for symbol in ('CONFIG_SERIAL_LITEUART', 'CONFIG_SERIAL_LITEUART_CONSOLE', 'CONFIG_MMU'):
        if cfg.get(symbol) != 'y':
            ap.error(f'{symbol} is required for the Raptor image')
    if a.variant == 'buildroot' and cfg.get('CONFIG_FUTEX') != 'y':
        ap.error('Buildroot must retain futex support')
    if a.variant == 'buildroot':
        rootfs_record = json.loads((root / f'initramfs{bits}-buildroot.manifest.json').read_text())
        if rootfs_record['identity'].get('schema') != 2 or not rootfs_record.get('busybox_required_features'):
            ap.error('rootfs predates the verified BusyBox configuration policy; rebuild it')
        if rootfs_record['rootfs_sha256'] != sha(a.initramfs):
            ap.error('rootfs differs from its build provenance')
    image = (a.kernel_dir / 'arch/riscv/boot/Image').read_bytes()
    text_offset, memory_size = struct.unpack_from('<QQ', image, 8)
    firmware = (a.firmware_dir / 'fw_payload.bin').read_bytes()
    payload_offset = firmware.find(image)
    if payload_offset != text_offset:
        ap.error('OpenSBI does not contain the expected Image at its load offset')
    memory = (preset.get('buildroot', {}).get('memory', 1024) if a.variant == 'buildroot'
              else preset['boot']['memory'])
    if text_offset + max(memory_size, len(image)) > a.fdt_offset or a.fdt_offset + 65536 > memory * 1024 * 1024:
        ap.error('kernel/DTB layout exceeds the declared RAM or overlaps')
    inputs = {}
    source_files = [root / 'Makefile', root / 'scripts/gen-config.py', root / 'scripts/buildroot.mk',
                    root / 'scripts/prepare-opensbi.py', root / 'scripts/package-artifacts.py',
                    root / 'scripts/ensure-rootfs.py', root / 'scripts/prepare-linux.py', a.preset.resolve()]
    source_files += [p for p in (root / 'payload').iterdir() if p.suffix in ('.c', '.h') or p.name == 'Makefile']
    source_files += [root / 'rootfs/busybox.fragment']
    source_files += [p for p in (root / 'rootfs/overlay').rglob('*') if p.is_file()]
    for p in source_files:
        inputs[str(p.resolve().relative_to(root))] = sha(p)
    m = {'schema': 1, 'preset': a.preset.stem, 'variant': a.variant, 'bits': bits,
         'kernel_version': preset['kernel']['version'], 'kernel_hz': hz, 'memory_mib': memory,
         'kernel_address': hex(0x80000000 + text_offset),
         'kernel_memory_end': hex(0x80000000 + text_offset + max(memory_size, len(image))),
         'kernel_memory_size': memory_size, 'payload_kernel_offset': payload_offset,
         'fdt_offset': a.fdt_offset, 'fdt_address': hex(0x80000000 + a.fdt_offset),
         'opensbi_isa': a.isa, 'abi': a.abi, 'build_inputs': inputs,
         'source_commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
         'opensbi_commit': subprocess.check_output(['git', '-C', str(root / 'opensbi'), 'rev-parse', 'HEAD'], text=True).strip(),
         'created': time.time(), 'board_tested': False}
    a.dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='package-', dir=a.dist) as temp:
        stage = Path(temp) / a.name
        stage.mkdir()
        for name in ('fw_payload.bin', 'fw_payload.elf', 'fw_dynamic.bin'):
            shutil.copy2(a.firmware_dir / name, stage / name)
        shutil.copy2(a.kernel_dir / 'arch/riscv/boot/Image', stage / 'Image')
        shutil.copy2(a.kernel_dir / 'vmlinux', stage / 'vmlinux')
        shutil.copy2(a.kernel_dir / '.config', stage / 'kernel.config')
        shutil.copy2(a.initramfs, stage / 'initramfs.cpio.gz')
        shutil.copy2(a.preset, stage / 'preset.toml')
        source_record = a.kernel_dir / 'source/.linux-build-source.json'
        if source_record.is_file():
            shutil.copy2(source_record, stage / 'kernel-source.json')
        rootfs_manifest = root / f'initramfs{bits}-buildroot.manifest.json'
        if a.variant == 'buildroot' and rootfs_manifest.exists():
            shutil.copy2(rootfs_manifest, stage / 'rootfs-manifest.json')
        (stage / 'README.md').write_text(readme(m))
        m['files'] = {p.name: sha(p) for p in sorted(stage.iterdir())}
        (stage / 'manifest.json').write_text(json.dumps(m, indent=2, sort_keys=True) + '\n')
        archive_tmp = Path(temp) / (a.name + '.tar.gz')
        with tarfile.open(archive_tmp, 'w:gz') as archive:
            archive.add(stage, arcname=a.name)
        destination = a.dist / a.name
        if destination.exists():
            prior = a.dist / '.superseded'
            prior.mkdir(exist_ok=True)
            destination.rename(prior / (a.name + '-' + str(time.time_ns())))
        shutil.move(str(stage), destination)
        os.replace(archive_tmp, a.dist / (a.name + '.tar.gz'))
    print(f'Package ready: {a.dist / (a.name + ".tar.gz")} (HZ={hz}, FPU={fpu})')


if __name__ == '__main__':
    main()
