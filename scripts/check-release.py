#!/usr/bin/env python3
"""Require a complete, current, tested release matrix before publication."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dist', type=Path, required=True)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    dist = a.dist.resolve()
    expected = {}
    for p in sorted((root / 'configs').glob('*.toml')):
        c = tomllib.loads(p.read_text())
        bits = int(c['target']['arch'].removeprefix('riscv'))
        for variant in ['tiny_shell'] + (['buildroot'] if 'buildroot' in c else []):
            prefix = f'linux-riscv-{p.stem}' if variant == 'tiny_shell' else f'linux-riscv-rv{bits}-{p.stem}-buildroot'
            expected[f'{prefix}-v{c["kernel"]["version"]}.tar.gz'] = (p, c, bits, variant)
    assert set(expected) == {p.name for p in dist.glob('*.tar.gz')}, 'archive set differs from current preset matrix'
    tests_path = dist / 'test-results.json'
    tests = json.loads(tests_path.read_text())
    assert tests['pass'], 'package tests failed'
    assert tests.get('test_runner_sha256') == sha(root / 'scripts/test-packages.py'), 'test runner changed; rerun tests'
    rows = tests['results']
    assert len(rows) == len(expected) and {r['archive'] for r in rows} == set(expected), 'test coverage is incomplete'
    results = {r['archive']: r for r in rows}
    archives = {}
    for name, (preset, cfg, bits, variant) in expected.items():
        archive = dist / name
        digest = sha(archive)
        result = results[name]
        assert result['pass'] and result['archive_sha256'] == digest, f'{name}: archive changed after testing'
        with tarfile.open(archive, 'r:gz') as tf:
            m = json.load(tf.extractfile(name.removesuffix('.tar.gz') + '/manifest.json'))
        assert (m['preset'], m['bits'], m['variant'], m['kernel_version'], m['kernel_hz']) == (preset.stem, bits, variant, cfg['kernel']['version'], 100), f'{name}: manifest mismatch'
        assert m['build_inputs'] and m['build_inputs'].get(str(preset.relative_to(root))) == sha(preset), f'{name}: preset changed'
        for path, h in m['build_inputs'].items():
            assert sha(root / path) == h, f'{name}: build input changed: {path}'
        boots = result['boots']
        modes = {'split', 'payload', 'shell'} if variant == 'buildroot' else {'split', 'payload'}
        assert len(boots) == len(modes) and {b['mode'] for b in boots} == modes, f'{name}: missing boot path'
        for b in boots:
            assert b['pass'], f'{name}: boot failed'
            if b['mode'] == 'split' and variant == 'tiny_shell':
                assert len(b.get('network_exec_commands', [])) == 3, f'{name}: missing network/exec checks'
            logdir = Path(tests['log_dir'])
            if not logdir.is_absolute():
                logdir = root / logdir
            log = logdir / (name.removesuffix('.tar.gz') + '-' + b['mode'] + '.log')
            assert sha(log) == b['uart_sha256'], f'{name}: boot log changed'
            assert f'Linux version {m["kernel_version"]} ' in log.read_text(errors='replace'), f'{name}: booted kernel version differs from package'
            if b['mode'] in ('payload', 'shell') and variant == 'buildroot':
                assert all(b.get('capabilities', {}).get(k) for k in ('proc_cpuinfo', 'sysfs', 'devtmpfs', 'devpts', 'tinysh_command_baseline', 'filesystem_operations')), f'{name}: missing runtime baseline'
                assert len(b.get('network_exec_commands', [])) == 4, f'{name}: missing networking/execution baseline'
            if b['mode'] == 'payload' and variant == 'buildroot':
                assert b['child_processes'] == 100 and b['sleep_wall_seconds'] >= 89, f'{name}: missing functional acceptance'
            if b['mode'] == 'payload' and variant == 'tiny_shell':
                assert any(c['command'] == 'sleep 2' and c['wall_seconds'] >= 1.8 for c in b['commands']), f'{name}: missing sleep check'
        archives[name] = digest
    checksums = ''.join(f'{h}  {name}\n' for name, h in sorted(archives.items()))
    source = {str(p.relative_to(root)): sha(p) for p in sorted(root.glob('scripts/*.py'))}
    source.update({str(p.relative_to(root)): sha(p) for p in [root / 'README.md', root / 'Makefile', root / 'scripts/buildroot.mk', *sorted((root / 'configs').glob('*.toml')), *sorted((root / 'docs').glob('*.md'))]})
    record = {'schema': 1, 'ready': True, 'package_count': len(archives), 'boot_paths': sum(len(r['boots']) for r in rows),
              'board_tested': False, 'published': False, 'archives': archives,
              'test_results_sha256': sha(tests_path), 'source_files': source}
    if a.write:
        (dist / 'SHA256SUMS').write_text(checksums)
        table = '\n'.join(f'| {p.stem} | RV{bits} | {variant} | {c["kernel"]["version"]} |' for p,c,bits,variant in expected.values())
        notes = f'''# Raptor-compatible RISC-V Linux candidate

{len(archives)} packages, each verified through separate Image/initramfs and embedded OpenSBI payload boot paths in QEMU.

All presets use HZ=100. Tiny shell kernels use soft-float userspace; Buildroot kernels enable F/D for ilp32d/lp64d userspace. Tiny fast presets use 64 MiB in QEMU; all Buildroot variants and other presets use 256 MiB.

The build separates tiny and Buildroot kernel/firmware output, validates the embedded Image and DTB relocation at +63 MiB, and caches root filesystems by configuration. RV32 tiny shell uses time64 sleep/poll and waitid for child reaping.

Buildroot also provides an initialized fast shell at `/sbin/raptor-shell`, BusyBox nc, and tinysh-compatible fetch/run helpers. `/proc/cpuinfo`, sysfs, devtmpfs, devpts and command availability are tested in both full init and fast shell modes. Direct `rdinit=/bin/sh` bypasses initialization and is not a complete runtime environment.

Validation includes archive hashes, kernel configuration, userspace ELF ABI, two boot paths per tiny package and three per Buildroot package, tiny filesystem/sleep, ping and downloaded ELF execution checks, and 100 child processes plus a 90-second sleep for each Buildroot payload. See test-results.json and test-logs for the exact results. SHA256SUMS identifies the tested archives.

| Preset | Architecture | Variant | Linux |
| --- | --- | --- | --- |
{table}

These are QEMU-tested firmware/kernel/rootfs packages. FPGA acceptance has not been performed on this candidate. Board use requires the matching Raptor bitstream, stage0 and LiteX DTB with accurate XLEN, ISA (including F/D for Buildroot), RAM, peripherals and timer frequency. No board stage0 or SD-card filesystem image is included.
'''
        (dist / 'release-notes.md').write_text(notes)
        record['release_notes_sha256'] = sha(dist / 'release-notes.md')
        (dist / 'release-ready.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    else:
        previous = json.loads((dist / 'release-ready.json').read_text())
        assert (dist / 'SHA256SUMS').read_text() == checksums, 'checksums changed'
        assert previous.pop('release_notes_sha256') == sha(dist / 'release-notes.md'), 'release notes changed'
        assert previous == record, 'readiness record stale; run release_ready again'
    print(f"Release candidate ready: {len(archives)} packages / {record['boot_paths']} QEMU boot paths. FPGA not tested; not published.")


if __name__ == '__main__':
    main()
