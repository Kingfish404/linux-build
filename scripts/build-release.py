#!/usr/bin/env python3
"""Build a complete release matrix without mixing variants or deleting old releases."""
import argparse
import hashlib
import json
import subprocess
import time
import tomllib
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dist', type=Path, required=True)
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--build-root', type=Path)
    ap.add_argument('--resume', action='store_true', help='reuse packages only when their recorded build inputs match')
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error('jobs must be positive')
    root = Path(__file__).resolve().parents[1]
    dist = args.dist.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    logs = dist / 'build-logs'
    logs.mkdir(exist_ok=True)
    build_root = (args.build_root or root / 'dist/.release-work').resolve()
    configs = [(p, tomllib.loads(p.read_text())) for p in (root / 'configs').glob('*.toml')]
    def order(item):
        p, cfg = item
        suffix = p.stem.removeprefix('qemu-' + cfg['target']['arch'].replace('riscv', 'rv'))
        return (tuple(int(x) for x in cfg['kernel']['version'].split('.')), cfg['target']['arch'],
                {'': 0, '-s': 1, '-m': 2, '-fast': 3, '-latest': 4}.get(suffix, 5))
    configs.sort(key=order)
    status = {'started': time.time(), 'expected_packages': sum(1 + ('buildroot' in c) for _, c in configs),
              'build_root': str(build_root), 'packages': [], 'pass': False}
    def save():
        (dist / 'build-result.json').write_text(json.dumps(status, indent=2) + '\n')
    save()
    for config, cfg in configs:
        bits = int(cfg['target']['arch'].removeprefix('riscv'))
        with (logs / (config.stem + '-configure.log')).open('w') as log:
            subprocess.run(['make', 'configure', 'SYSTEM=' + str(config)], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        variants = ['tiny_shell'] + (['buildroot'] if 'buildroot' in cfg else [])
        for variant in variants:
            name = (f'linux-riscv-{config.stem}-v{cfg["kernel"]["version"]}' if variant == 'tiny_shell'
                    else f'linux-riscv-rv{bits}-{config.stem}-buildroot-v{cfg["kernel"]["version"]}')
            archive = dist / (name + '.tar.gz')
            manifest_path = dist / name / 'manifest.json'
            item = {'preset': config.stem, 'variant': variant, 'archive': archive.name, 'started': time.time()}
            status['packages'].append(item)
            if args.resume and archive.exists() and manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                if all((root / p).is_file() and sha(root / p) == h for p, h in manifest['build_inputs'].items()):
                    item.update(returncode=0, reused=True, sha256=sha(archive), finished=time.time())
                    print(f'REUSE {name}', flush=True)
                    save()
                    continue
            target = 'package' if variant == 'tiny_shell' else 'package_buildroot'
            cmd = ['make', f'NPROC={args.jobs}', 'BUILD_ROOT=' + str(build_root), 'DIST_DIR=' + str(dist), target]
            item.update(command=cmd, log=str(logs / (name + '.log')))
            print(f'BUILD [{len(status["packages"])}/{status["expected_packages"]}] {name}', flush=True)
            save()
            with Path(item['log']).open('w') as log:
                item['returncode'] = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT).returncode
            item['finished'] = time.time()
            if item['returncode']:
                status['finished'] = time.time()
                save()
                print(f'FAILED {name}: {item["log"]}', flush=True)
                return 1
            item['sha256'] = sha(archive)
            save()
            print(f'DONE {name}', flush=True)
    expected = {item['archive'] for item in status['packages']}
    actual = {p.name for p in dist.glob('*.tar.gz')}
    if actual != expected:
        raise RuntimeError(f'candidate archive set differs from matrix: extra={actual - expected}, missing={expected - actual}')
    status.update(pass_=True, finished=time.time())
    status['pass'] = status.pop('pass_')
    save()
    print(f'Built {len(expected)} packages in {dist}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
