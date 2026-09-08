#!/usr/bin/env python3
"""Validate payload placement and invalidate OpenSBI outputs when flags change."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--kernel', type=Path, required=True)
    ap.add_argument('--bits', type=int, choices=(32, 64), required=True)
    ap.add_argument('--isa', required=True)
    ap.add_argument('--cross-compile', default='riscv64-linux-gnu-')
    ap.add_argument('--fdt-offset', type=lambda s: int(s, 0), required=True)
    a = ap.parse_args()
    kernel = a.kernel.resolve()
    image = kernel.read_bytes()
    if len(image) < 64 or image[48:53] != b'RISCV':
        ap.error('kernel is not a RISC-V Image')
    text_offset, memory_size = struct.unpack_from('<QQ', image, 8)
    expected = 0x400000 if a.bits == 32 else 0x200000
    if text_offset != expected:
        ap.error(f'Image load offset {text_offset:#x} differs from generic OpenSBI {expected:#x}')
    if a.fdt_offset < text_offset + max(memory_size, len(image)):
        ap.error('DTB relocation overlaps kernel memory (including BSS)')
    if a.fdt_offset % 8:
        ap.error('DTB relocation must be 8-byte aligned')
    output = a.output.resolve()
    source = Path(__file__).resolve().parents[1] / 'opensbi'
    if output in (source, source.parent, Path('/')):
        ap.error('OpenSBI output must be a separate build directory')
    compiler = a.cross_compile + 'gcc'
    identity = {'bits': a.bits, 'isa': a.isa, 'compiler': shutil.which(compiler),
                'compiler_version': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]}
    inputs = {'schema': 1, 'identity': identity, 'kernel': str(kernel),
              'kernel_sha256': hashlib.sha256(image).hexdigest(),
              'fdt_offset': a.fdt_offset}
    stamp = output / '.build-inputs.json'
    previous = json.loads(stamp.read_text()) if stamp.exists() else {}
    if previous.get('identity') != identity:
        # Only remove generated OpenSBI trees, preserving unrelated output records.
        for name in ('platform', 'lib'):
            shutil.rmtree(output / name, ignore_errors=True)
        print('OpenSBI compiler/ISA changed: rebuilding generated objects')
    elif previous != inputs:
        for suffix in ('o', 'elf', 'bin'):
            (output / 'platform/generic/firmware' / ('fw_payload.' + suffix)).unlink(missing_ok=True)
        print('OpenSBI payload layout changed: rebuilding payload')
    output.mkdir(parents=True, exist_ok=True)
    (output / '.build-inputs.pending.json').write_text(json.dumps(inputs, indent=2) + '\n')
    print(f'Kernel memory ends at +{text_offset + max(memory_size, len(image)):#x}; DTB at +{a.fdt_offset:#x}')


if __name__ == '__main__':
    main()
