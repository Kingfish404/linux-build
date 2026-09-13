#!/usr/bin/env python3
"""Offline regression checks for distro selection and ownership-preserving disks."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('distro', ROOT / 'scripts/build-distro.py')
distro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distro)


class DistributionTests(unittest.TestCase):
    def test_all_presets_and_switching(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # Reuse one directory to check that a distro removes stale Buildroot selection.
            presets = [ROOT / 'configs/qemu-rv64.toml', *sorted((ROOT / 'configs').glob('*.toml'))]
            for preset in presets:
                subprocess.run([sys.executable, ROOT / 'scripts/gen-config.py', preset,
                                '--out-dir', out], check=True, capture_output=True)
                cfg = tomllib.loads(preset.read_text())
                self.assertEqual(cfg['boot']['memory'], 1024)
                self.assertEqual(cfg['kernel']['version'], '7.2.5' if 'latest' in preset.stem else '6.18.51')
                if 'buildroot' in cfg:
                    self.assertEqual(cfg['buildroot']['memory'], 1024)
                self.assertEqual((out / '.config.buildroot').exists(), 'buildroot' in cfg)
                if cfg['rootfs']['type'] in ('alpine', 'debian'):
                    mk = (out / '.config.mk').read_text()
                    self.assertIn('KERNEL_VARIANT := distro', mk)
                    self.assertIn('RISCV_ABI := lp64d', mk)
                    fragment = (out / '.config.kernel.distro').read_text()
                    for setting in ('FPU=y', 'VIRTIO_BLK=y', 'EXT4_FS=y', 'INITRAMFS_SOURCE=""'):
                        self.assertIn('CONFIG_' + setting, fragment)
                    resolved = subprocess.run(
                        ['make', '-s', '--no-print-directory', f'PWD_DIR={out}',
                         '--eval=print_distro_vars:;@echo $(KERNEL_VARIANT) $(RISCV_ISA) $(RISCV_ABI)',
                         'print_distro_vars'], cwd=ROOT, check=True,
                        capture_output=True, text=True).stdout
                    self.assertEqual(resolved.strip(),
                                     'distro rv64imafdc_zicntr_zicsr_zifencei lp64d')

    def test_make_boot_routing(self):
        for name in ('alpine', 'debian'):
            result = subprocess.run(['make', '-n', 'test', f'SYSTEM_ROOTFS={name}',
                                     f'SYSTEM_PRESET=qemu-rv64-{name}', 'BITS=64',
                                     'KERNEL_VARIANT=distro'], cwd=ROOT,
                                    check=True, capture_output=True, text=True)
            self.assertIn('root=/dev/vda', result.stdout)
            self.assertIn(f'qemu-rv64-{name}/rootfs.ext4', result.stdout)
            self.assertNotIn('-initrd ', result.stdout)

    def test_clean_build_keeps_downloads(self):
        result = subprocess.run(['make', '-n', 'BITS=64', 'clean_buildroot_outputs'],
                                cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertNotIn(' distclean', result.stdout)
        for line in result.stdout.splitlines():
            if 'rm -' in line:
                self.assertNotIn('/dl', line)

    def test_recipes_and_invalid_packages(self):
        for name, package_cmd in (('alpine', 'apk add'), ('debian', 'apt_retry install')):
            cfg = distro.load_config(ROOT / f'configs/qemu-rv64-{name}.toml')
            self.assertIn(package_cmd, distro.provision_script(cfg))
            self.assertIn('riscv64', distro.provision_script(cfg))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.toml'
            p.write_text('[target]\narch="riscv64"\n[rootfs]\ntype="alpine"\n'
                         'image="alpine:3.23"\nsize_mib=512\npackages=["curl;false"]\n')
            with self.assertRaises(ValueError):
                distro.load_config(p)

    def test_existing_disk_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / 'rootfs.ext4'
            disk.write_bytes(b'guest data')
            with self.assertRaises(ValueError):
                distro.build(ROOT / 'configs/qemu-rv64-alpine.toml', disk,
                             Path('/nonexistent-kernel'), Path('/nonexistent-firmware'))
            self.assertEqual(disk.read_bytes(), b'guest data')

    def test_pristine_check_and_release_matrix(self):
        from release_common import matrix
        rows = list(matrix())
        self.assertEqual(len(rows), 22)
        self.assertEqual(sum(row[2] in ('alpine', 'debian') for row in rows), 2)
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / 'rootfs.ext4'
            disk.write_bytes(b'guest changes')
            preset = ROOT / 'configs/qemu-rv64-alpine.toml'
            h = hashlib.sha256(preset.read_bytes() + Path(distro.__file__).read_bytes())
            for p in sorted(distro.RUNTIME.iterdir()):
                h.update(p.name.encode() + p.read_bytes())
            disk.with_suffix('.json').write_text(json.dumps({'inputs_sha256': h.hexdigest(),
                                                           'rootfs_sha256': 'original'}))
            distro.build(preset, disk, Path('/missing'), Path('/missing'))
            with self.assertRaisesRegex(ValueError, 'modified since construction'):
                distro.build(preset, disk, Path('/missing'), Path('/missing'), pristine=True)
            self.assertEqual(disk.read_bytes(), b'guest changes')
            gate = subprocess.run([sys.executable, ROOT / 'scripts/check-release.py', '--dist', tmp],
                                  capture_output=True, text=True)
            self.assertNotEqual(gate.returncode, 0)
            self.assertIn('archive set differs', gate.stderr)
            self.assertFalse((Path(tmp) / 'release-ready.json').exists())

    @unittest.skipUnless(all(shutil.which(t) for t in ('fakeroot', 'mke2fs', 'debugfs', 'tar')),
                         'ext4 tools required')
    def test_ext4_preserves_ownership_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            archive, disk = work / 'rootfs.tar', work / 'rootfs.ext4'
            with tarfile.open(archive, 'w') as tf:
                entry = tarfile.TarInfo('owned')
                entry.uid, entry.gid, entry.mode, entry.size = 123, 456, 0o640, 4
                tf.addfile(entry, io.BytesIO(b'test'))
                link = tarfile.TarInfo('link')
                link.type, link.linkname = tarfile.SYMTYPE, '/owned'
                tf.addfile(link)
            subprocess.run(['fakeroot', sys.executable, ROOT / 'scripts/build-distro.py',
                            '--make-ext4', archive, disk, '128', work], check=True)
            stat = subprocess.run(['debugfs', '-R', 'stat /owned', disk],
                                  check=True, capture_output=True, text=True).stdout
            self.assertRegex(stat, r'User:\s+123\s+Group:\s+456')
            self.assertIn('0640', stat)
            stat = subprocess.run(['debugfs', '-R', 'stat /link', disk],
                                  check=True, capture_output=True, text=True).stdout
            self.assertIn('symlink', stat)
            self.assertIn('/owned', stat)


if __name__ == '__main__':
    unittest.main()
