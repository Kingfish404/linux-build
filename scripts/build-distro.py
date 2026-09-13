#!/usr/bin/env python3
"""Build RV64 root disks inside QEMU; never execute foreign code on the host.

Skopeo verifies OCI blobs. An Alpine bootstrap initramfs mounts the target disk
and runs its package manager in chroot inside a full RV64 VM. No container daemon
or binfmt_misc registration is used.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
import tomllib
from release_common import sha

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'rootfs/distro'
SEED_IMAGE = 'docker.io/library/alpine:3.23'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def load_config(preset):
    cfg = tomllib.loads(preset.read_text())
    fs = cfg['rootfs']
    if cfg['target']['arch'] != 'riscv64' or fs['type'] not in ('alpine', 'debian'):
        raise ValueError('requires an Alpine/Debian riscv64 preset')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./:@_-]*', fs['image']):
        raise ValueError('invalid OCI image reference')
    if not isinstance(fs['size_mib'], int) or fs['size_mib'] < 128:
        raise ValueError('rootfs.size_mib must be an integer >= 128')
    packages = fs.get('packages', [])
    if not isinstance(packages, list) or any(
        not isinstance(p, str) or not re.fullmatch(r'[a-z0-9][a-z0-9+_.-]*', p)
        for p in packages
    ):
        raise ValueError('rootfs.packages must contain plain package names')
    return cfg


def provision_script(cfg):
    packages = ' '.join(cfg['rootfs'].get('packages', []))
    if cfg['rootfs']['type'] == 'alpine':
        install = f'''test "$(apk --print-arch)" = riscv64
apk add --no-cache busybox openssh {packages}
apk info -v | sort > /var/lib/raptor/build-packages.txt'''
    else:
        install = f'''test "$(dpkg --print-architecture)" = riscv64
# Retry complete acquisitions as well as connections; some proxies return 502.
apt_retry() {{
    for attempt in 1 2 3; do
        apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 "$@" && return 0
        [ "$attempt" -lt 3 ] || return 1
        sleep 2
    done
}}
apt_retry update
DEBIAN_FRONTEND=noninteractive apt_retry install -y --no-install-recommends busybox-static openssh-server {packages}
apt-get clean
rm -rf /var/lib/apt/lists/*
dpkg-query -W > /var/lib/raptor/build-packages.txt'''
    return f'''#!/bin/sh
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
mkdir -p /var/lib/raptor
{install}
for applet in init udhcpc ip ifconfig mount grep reboot poweroff; do
    /bin/busybox --list | grep -qx "$applet" || {{ echo "Missing required BusyBox applet: $applet"; exit 1; }}
done
mkdir -p /proc /sys /dev /run /tmp /root /etc/ssh
chmod 1777 /tmp
rm -f /etc/ssh/ssh_host_*
printf 'PermitRootLogin prohibit-password\\nPasswordAuthentication no\\nKbdInteractiveAuthentication no\\n' > /etc/ssh/sshd_config
# Enable key-based root access once authorized_keys is provisioned; no SSH passwords.
passwd -d root
chmod 755 /sbin/raptor-init /etc/init.d/raptor-boot /etc/raptor-udhcpc.script
'''


def fetch_image(reference, destination, skopeo):
    run([skopeo, 'copy', '--retry-times', '3', '--override-arch', 'riscv64',
         '--override-os', 'linux', 'docker://' + reference, 'dir:' + str(destination)])
    mp = destination / 'manifest.json'
    manifest = json.loads(mp.read_text())
    # Official minimal bases are single-layer. Do not silently mishandle
    # whiteouts in arbitrary multi-layer custom images.
    if len(manifest['layers']) != 1:
        raise ValueError('expected an official single-layer minimal base image')
    for desc in [manifest['config'], *manifest['layers']]:
        algorithm, digest = desc['digest'].split(':')
        if algorithm != 'sha256' or sha(destination / digest) != digest:
            raise ValueError('OCI blob integrity failure')
    config = json.loads((destination / manifest['config']['digest'].split(':')[1]).read_text())
    if (config['architecture'], config['os']) != ('riscv64', 'linux'):
        raise ValueError('upstream image is not linux/riscv64')
    return destination / manifest['layers'][0]['digest'].split(':')[1], {
        'reference': reference, 'manifest_sha256': sha(mp),
        'config_digest': manifest['config']['digest'], 'layer_digest': manifest['layers'][0]['digest']}


def guest_proxy():
    if 'DISTRO_GUEST_PROXY' in os.environ:
        return os.environ['DISTRO_GUEST_PROXY']
    value = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or ''
    if not value:
        return ''
    url = urlsplit(value)
    if url.hostname in ('localhost', '127.0.0.1'):
        auth = url.netloc.rsplit('@', 1)[0] + '@' if '@' in url.netloc else ''
        value = urlunsplit((url.scheme, auth + '10.0.2.2' + (f':{url.port}' if url.port else ''),
                           url.path, url.query, url.fragment))
    return value


def extract(archive, tree):
    tree.mkdir()
    run(['tar', '--extract', '--file', archive, '--directory', tree,
         '--numeric-owner', '--same-owner', '--same-permissions'])


def disk_from_tree(tree, destination, size_mib):
    with destination.open('xb') as f:
        f.truncate(size_mib * 1024 * 1024)
    run(['mke2fs', '-q', '-t', 'ext4', '-F', '-m', '0', '-L', 'rootfs', '-d', tree, destination])


def make_ext4(archive, destination, size_mib, work):
    tree = work / 'tree'
    extract(archive, tree)
    disk_from_tree(tree, destination, size_mib)


def prepare_guest(work):
    """One fakeroot session preserves numeric ownership and device nodes."""
    meta = json.loads((work / 'prepare.json').read_text())
    cfg = meta['cfg']
    tree, seed = work / 'tree', work / 'seed'
    extract(meta['base_layer'], tree)
    extract(meta['seed_layer'], seed)
    for src, dest in (('raptor-init', 'sbin/raptor-init'), ('raptor-boot', 'etc/init.d/raptor-boot'),
                      ('inittab', 'etc/inittab'), ('udhcpc.script', 'etc/raptor-udhcpc.script')):
        dst = tree / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RUNTIME / src, dst)
        dst.chmod(0o755 if src != 'inittab' else 0o644)
    (seed / 'provision.sh').write_text(provision_script(cfg))
    bootstrap = '''#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /mnt /dev/pts
mount -t devpts devpts /dev/pts
ifconfig lo up
ifconfig eth0 10.0.2.15 netmask 255.255.255.0 up
route add default gw 10.0.2.2
'''
    if meta['proxy']:
        bootstrap += 'export http_proxy=' + shlex.quote(meta['proxy']) + '\nexport https_proxy="$http_proxy"\n'
    bootstrap += '''provision() {
    mount -t ext4 /dev/vda /mnt || return 1
    mkdir -p /mnt/proc /mnt/sys /mnt/dev /mnt/tmp
    mount -t proc proc /mnt/proc || return 1
    mount -t sysfs sysfs /mnt/sys || return 1
    mount --bind /dev /mnt/dev || return 1
    printf 'nameserver 10.0.2.3\\n' > /mnt/etc/resolv.conf
    cp /provision.sh /mnt/tmp/raptor-provision.sh
    chroot /mnt /bin/sh /tmp/raptor-provision.sh || return 1
    rm /mnt/tmp/raptor-provision.sh
    sync
    umount /mnt/dev /mnt/sys /mnt/proc || return 1
    umount /mnt || return 1
}
if provision; then echo RAPT_PROVISION_PASS; else echo RAPT_PROVISION_FAIL; fi
sync
poweroff -f
'''
    (seed / 'init').write_text(bootstrap)
    (seed / 'init').chmod(0o755)
    for d in ('proc', 'sys', 'dev', 'mnt', 'tmp'):
        (seed / d).mkdir(exist_ok=True)
    run(['mknod', '-m', '600', seed / 'dev/console', 'c', '5', '1'])
    files = [b'.'] + [str(p.relative_to(seed)).encode() for p in sorted(seed.rglob('*'))]
    raw = run(['cpio', '-o', '-H', 'newc', '--null'], cwd=seed,
              input=b'\0'.join(files) + b'\0', capture_output=True).stdout
    (work / 'seed.cpio.gz').write_bytes(gzip.compress(raw, mtime=0))
    disk_from_tree(tree, work / 'rootfs.ext4', cfg['rootfs']['size_mib'])


def build(preset, output, kernel, firmware, skopeo='skopeo', pristine=False):
    cfg = load_config(preset)
    h = hashlib.sha256(preset.read_bytes() + Path(__file__).read_bytes())
    for p in sorted(RUNTIME.iterdir()):
        h.update(p.name.encode() + p.read_bytes())
    fingerprint = h.hexdigest()
    manifest = output.with_suffix('.json')
    if output.exists():
        if manifest.exists() and json.loads(manifest.read_text()).get('inputs_sha256') == fingerprint:
            if pristine and json.loads(manifest.read_text()).get('rootfs_sha256') != sha(output):
                raise ValueError('release disk modified since construction; choose a clean build directory')
            print(f'Reusing {output} (guest changes preserved)')
            return
        raise ValueError(f'{output} already exists with different inputs; choose a new BUILD_ROOT or move it aside')
    for tool in (skopeo, 'fakeroot', 'tar', 'mke2fs', 'cpio', 'qemu-system-riscv64', 'debugfs'):
        if not shutil.which(tool):
            raise ValueError(f'missing host tool: {tool}')
    if not kernel.is_file() or not firmware.is_file():
        raise ValueError('build the distro kernel and OpenSBI before provisioning the rootfs')
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix('.build.log')
    with tempfile.TemporaryDirectory(prefix='.distro-', dir=output.parent) as tmp:
        work = Path(tmp)
        base, provenance = fetch_image(cfg['rootfs']['image'], work / 'base', skopeo)
        if cfg['rootfs']['image'] == SEED_IMAGE:
            seed, seed_provenance = base, provenance
        else:
            seed, seed_provenance = fetch_image(SEED_IMAGE, work / 'bootstrap', skopeo)
        (work / 'prepare.json').write_text(json.dumps({'cfg': cfg, 'base_layer': str(base),
                    'seed_layer': str(seed), 'proxy': guest_proxy()}))
        run(['fakeroot', sys.executable, Path(__file__).resolve(), '--prepare-guest', work])
        disk = work / 'rootfs.ext4'
        command = ['qemu-system-riscv64', '-M', 'virt', '-m', '1024M', '-nographic',
                   '-cpu', 'rv64,h=false,sstc=false,svadu=false',
                   '-bios', firmware, '-kernel', kernel, '-initrd', work / 'seed.cpio.gz',
                   '-drive', f'file={disk},format=raw,if=none,id=rootfs',
                   '-device', 'virtio-blk-device,drive=rootfs',
                   '-netdev', 'user,id=net0', '-device', 'virtio-net-device,netdev=net0',
                   '-append', 'rdinit=/init console=ttyS0 earlycon=sbi']
        print(f'Provisioning {cfg["rootfs"]["type"]} in RV64 QEMU; log: {log}', flush=True)
        with log.open('wb') as stream:
            run(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        text = log.read_text(errors='replace').replace('\r', '')
        if '\nRAPT_PROVISION_PASS\n' not in text or 'RAPT_PROVISION_FAIL' in text or 'Kernel panic' in text:
            raise ValueError(f'guest provisioning failed; inspect {log}')
        run(['e2fsck', '-fn', disk], stdout=subprocess.DEVNULL)
        inventory = run(['debugfs', '-R', 'cat /var/lib/raptor/build-packages.txt', disk],
                        capture_output=True, text=True).stdout
        if not inventory.strip():
            raise ValueError('missing guest package inventory')
        record = {'schema': 2, 'preset': preset.name, 'inputs_sha256': fingerprint,
                  'base_image': provenance, 'bootstrap_image': seed_provenance,
                  'rootfs': cfg['rootfs'], 'platform': 'linux/riscv64',
                  'rootfs_sha256': sha(disk), 'packages': inventory.splitlines(),
                  'builder': 'qemu-system-riscv64', 'build_log_sha256': sha(log),
                  'kernel_sha256': sha(kernel), 'firmware_sha256': sha(firmware)}
        os.link(disk, output)
        manifest.write_text(json.dumps(record, indent=2) + '\n')
        print(f'Created clean disk {output}', flush=True)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == '--make-ext4':
        make_ext4(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), Path(sys.argv[5]))
        return
    if len(sys.argv) == 3 and sys.argv[1] == '--prepare-guest':
        prepare_guest(Path(sys.argv[2]))
        return
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preset', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--kernel', type=Path)
    ap.add_argument('--firmware', type=Path)
    ap.add_argument('--skopeo', default='skopeo')
    ap.add_argument('--pristine', action='store_true')
    ap.add_argument('--print-provision', action='store_true')
    a = ap.parse_args()
    if a.print_provision:
        print(provision_script(load_config(a.preset)))
    else:
        if not a.kernel or not a.firmware:
            ap.error('--kernel and --firmware are required')
        build(a.preset.resolve(), a.output.resolve(), a.kernel.resolve(), a.firmware.resolve(), a.skopeo, a.pristine)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        sys.exit(f'ERROR: {e}')
