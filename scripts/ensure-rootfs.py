#!/usr/bin/env python3
"""Cache Buildroot outputs by architecture, source identity and requested config."""
import argparse
import fcntl
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bits', type=int, choices=(32, 64), required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    (root / 'dist').mkdir(exist_ok=True)
    lock = (root / 'dist' / f'.rootfs-rv{a.bits}.lock').open('a+')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    source = root / f'buildroot{a.bits}'
    config = a.config.resolve().read_bytes()
    baseline = {str(p.relative_to(root)): digest(p) for p in sorted((root / 'rootfs').rglob('*')) if p.is_file()}
    identity = {'schema': 2, 'bits': a.bits, 'fragment_sha256': hashlib.sha256(config).hexdigest(),
                'source_commit': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
                'source_diff_sha256': hashlib.sha256(subprocess.check_output(['git', '-C', str(source), 'diff', 'HEAD'])).hexdigest(),
                'defconfig_sha256': digest(source / f'configs/qemu_riscv{a.bits}_virt_defconfig'),
                'runtime_baseline': baseline}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache_root = root / 'dist/.rootfs-cache'
    cache = cache_root / key
    output = root / f'initramfs{a.bits}-buildroot.cpio.gz'
    legacy_stamp = root / f'initramfs{a.bits}-buildroot.stamp'
    config_md5 = hashlib.md5(config).hexdigest()
    if (cache / 'manifest.json').exists():
        prior = json.loads((cache / 'manifest.json').read_text())
        if not prior.get('busybox_required_features') or not prior.get('busybox_config_sha256'):
            cache.rename(cache.with_name(cache.name + '.superseded-' + str(time.time_ns())))
            print('Rebuilding a cache without verified BusyBox configuration')
    if (cache / 'manifest.json').exists():
        record = json.loads((cache / 'manifest.json').read_text())
        if (record['identity'] != identity or digest(cache / 'initramfs.cpio.gz') != record['rootfs_sha256']
                or digest(cache / 'busybox.config') != record['busybox_config_sha256']):
            raise RuntimeError(f'rootfs cache integrity failure: {cache}')
        shutil.copy2(cache / 'initramfs.cpio.gz', output)
        legacy_stamp.write_text(config_md5 + '\n')
        shutil.copy2(cache / 'manifest.json', root / f'initramfs{a.bits}-buildroot.manifest.json')
        print(f'Using verified RV{a.bits} rootfs cache {key[:12]}')
        return
    started = time.time()
    # Removed packages require a clean target filesystem; Buildroot incremental
    # builds do not uninstall them. Reuse the toolchain only for an unchanged config.
    source_stamp = source / '.raptor-rootfs-config'
    if source_stamp.exists():
        same_config = source_stamp.read_text().strip() == config_md5
    else:
        built_image = source / 'output/images/rootfs.cpio.gz'
        same_config = (output.exists() and built_image.exists() and legacy_stamp.exists()
                       and legacy_stamp.read_text().strip() == config_md5
                       and digest(output) == digest(built_image))
    if not same_config and source_stamp.exists():
        # Adding the runtime overlay/BusyBox fragment or enabling packages does
        # not require discarding the toolchain. Removing/changing selections does.
        previous_md5 = source_stamp.read_text().strip()
        for requested in cache_root.glob('*/requested.config'):
            old = requested.read_bytes()
            if hashlib.md5(old).hexdigest() != previous_md5:
                continue
            def values(data):
                return dict(line.split('=', 1) for line in data.decode().splitlines()
                            if line.startswith('BR2_') and '=' in line)
            before, after = values(old), values(config)
            integration = {'BR2_ROOTFS_OVERLAY', 'BR2_PACKAGE_BUSYBOX_CONFIG_FRAGMENT_FILES'}
            same_config = (all(after.get(k) == v for k, v in before.items() if k not in integration)
                           and all(k in before or k in integration or
                                   (k.startswith('BR2_PACKAGE_') and v == 'y')
                                   for k, v in after.items()))
            break
    target = 'make_initramfs_buildroot' if same_config else 'make_initramfs_buildroot_clean'
    subprocess.run(['make', f'BITS={a.bits}', f'NPROC={a.jobs}',
                    'BUILDROOT_CFG=' + str(a.config.resolve()), target], cwd=root, check=True)
    source_stamp.write_text(config_md5 + '\n')
    busybox_configs = list((source / 'output/build').glob('busybox-*/.config'))
    if len(busybox_configs) != 1:
        raise RuntimeError('expected one configured BusyBox build')
    busybox_config = busybox_configs[0]
    actual_features = set(busybox_config.read_text().splitlines())
    required = [line for line in (root / 'rootfs/busybox.fragment').read_text().splitlines()
                if line.startswith('CONFIG_')]
    missing = [line for line in required if line not in actual_features]
    if missing:
        raise RuntimeError(f'BusyBox did not apply required features: {missing}')
    record = {'identity': identity, 'rootfs_sha256': digest(output),
              'actual_config_sha256': digest(source / '.config'),
              'busybox_config_sha256': digest(busybox_config),
              'busybox_required_features': required, 'started': started,
              'finished': time.time(), 'build_target': target}
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rootfs-', dir=cache_root) as temp:
        staging = Path(temp)
        shutil.copy2(output, staging / 'initramfs.cpio.gz')
        shutil.copy2(source / '.config', staging / 'buildroot.config')
        shutil.copy2(busybox_config, staging / 'busybox.config')
        (staging / 'requested.config').write_bytes(config)
        (staging / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
        shutil.copytree(staging, cache)
    shutil.copy2(cache / 'manifest.json', root / f'initramfs{a.bits}-buildroot.manifest.json')
    print(f'Cached RV{a.bits} rootfs {key[:12]}')


if __name__ == '__main__':
    main()
