"""Release acceptance for writable upstream disks, using full-system QEMU only."""
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from release_common import sha

CHECKS = ('memory_1g', 'kernel_version', 'runtime_mounts', 'dns', 'https',
          'package_install', 'package_execution', 'ssh_key_login', 'clean_reboot')
PERSISTENCE = ('memory_1g', 'kernel_version', 'runtime_mounts', 'new_boot_id',
               'file_persistence', 'package_persistence', 'ssh_key_persistence', 'clean_reboot')


def audit(files, m):
    cfg = (files / 'kernel.config').read_text().splitlines()
    for line in ('CONFIG_HZ=100', 'CONFIG_HZ_100=y', 'CONFIG_MMU=y', 'CONFIG_FPU=y',
                 'CONFIG_RISCV_ISA_C=y', 'CONFIG_EXT4_FS=y', 'CONFIG_VIRTIO_BLK=y',
                 'CONFIG_VIRTIO_NET=y', 'CONFIG_DEVTMPFS_MOUNT=y', 'CONFIG_INITRAMFS_SOURCE=""'):
        if line not in cfg:
            raise ValueError('missing distro kernel setting: ' + line)
    if m['bits'] != 64 or m['abi'] != 'lp64d' or m['memory_mib'] != 1024:
        raise ValueError('distro requires RV64GC/lp64d and 1 GiB')
    r = json.loads((files / 'rootfs-manifest.json').read_text())
    for key, member in (('rootfs_sha256', 'rootfs.ext4'), ('kernel_sha256', 'Image'),
                        ('firmware_sha256', 'fw_dynamic.bin'), ('build_log_sha256', 'rootfs-build.log')):
        if r[key] != m['files'][member]:
            raise ValueError('rootfs provenance mismatch: ' + key)
    if r['builder'] != 'qemu-system-riscv64' or not r['packages']:
        raise ValueError('missing native provisioning evidence')
    for path in ('/bin/busybox', '/usr/bin/busybox'):
        dest = files / 'audited-busybox'
        subprocess.run(['debugfs', '-R', f'dump {path} {dest}', files / 'rootfs.ext4'],
                       check=True, capture_output=True)
        if dest.exists():
            body = dest.read_bytes()
            if body[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', body, 18)[0] != 243:
                raise ValueError('distro BusyBox is not an RV64 ELF')
            flags = struct.unpack_from('<I', body, 48)[0]
            if flags & 6 != 4:
                raise ValueError('distro BusyBox is not lp64d')
            m['tested_user_elf'] = {'path': path, 'bits': 64, 'flags': flags}
            return m
    raise ValueError('cannot inspect distro BusyBox ELF')


def command(guest, script, timeout=60):
    marker = 'RAPT_' + uuid.uuid4().hex
    offset = len(guest.raw)
    # Subshell + set -e ensures no failed intermediate assertion is hidden.
    guest.send('( set -eu; ' + script + " ); rc=$?; printf '\\n%s=%s\\n' " + marker + ' "$rc"\n')
    pattern = re.compile(r'^' + marker + r'=(\d+)$', re.M)
    def output():
        return guest.raw[offset:].decode(errors='replace').replace('\r', '')
    guest.wait(lambda: pattern.search(output()) is not None, timeout)
    text = output()
    if pattern.search(text).group(1) != '0':
        raise RuntimeError('guest command failed: ' + text[-3000:])
    return text


def reboot(guest, timeout):
    guest.send('/bin/busybox reboot\n')
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            guest.read()
        except RuntimeError:
            if guest.process.poll() != 0:
                raise
            remaining = guest.process.stdout.read()
            guest.raw.extend(remaining)
            guest.log.write(remaining)
            if 'reboot: Restarting system' not in guest.text:
                raise RuntimeError('QEMU exited without guest reboot evidence')
            return
    raise TimeoutError('guest did not reboot cleanly')


def proxy_export():
    value = (os.environ['DISTRO_GUEST_PROXY'] if 'DISTRO_GUEST_PROXY' in os.environ else
             os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy'))
    if not value:
        return 'true'
    url = urlsplit(value)
    if url.hostname in ('127.0.0.1', 'localhost'):
        auth = url.netloc.rsplit('@', 1)[0] + '@' if '@' in url.netloc else ''
        value = urlunsplit((url.scheme, auth + '10.0.2.2' + (f':{url.port}' if url.port else ''),
                           url.path, url.query, url.fragment))
    return 'export http_proxy=' + shlex.quote(value) + '; export https_proxy="$http_proxy"'


def test(files, m, timeout, log_dir, name, Guest):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    key = files / 'test-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key], check=True)
    public = key.with_suffix('.pub').read_text().strip()
    token = uuid.uuid4().hex
    boot_id = None
    boots = []
    qemu = ['qemu-system-riscv64', '-M', 'virt', '-m', '1024M', '-nographic', '-no-reboot',
            '-cpu', 'rv64,h=false,sstc=false,svadu=false', '-bios', str(files / 'fw_dynamic.bin'),
            '-kernel', str(files / 'Image'), '-drive', f'file={files / "rootfs.ext4"},format=raw,if=none,id=rootfs',
            '-device', 'virtio-blk-device,drive=rootfs', '-netdev', f'user,id=net0,hostfwd=tcp:127.0.0.1:{port}-:22',
            '-device', 'virtio-net-device,netdev=net0', '-append',
            'root=/dev/vda rootfstype=ext4 rw rootwait init=/sbin/raptor-init console=ttyS0 earlycon=sbi']
    for mode in ('disk', 'persistence'):
        log = log_dir / (name + '-' + mode + '.log')
        guest = Guest(qemu, log)
        checks = {}
        row = {'mode': mode, 'pass': False, 'command': qemu, 'checks': checks}
        try:
            guest.wait(lambda: 'Raptor distribution ready:' in guest.text or 'RAPT_BOOT_FAILED' in guest.text, timeout)
            if 'RAPT_BOOT_FAILED' in guest.text:
                raise RuntimeError('distribution startup failed')
            guest.send('\n')
            guest.wait(lambda: guest.text.rstrip().endswith('#'), timeout)
            command(guest, "awk '/^MemTotal:/ { if ($2 < 900000 || $2 > 1048576) exit 1; found=1 } END {if (!found) exit 1}' /proc/meminfo")
            checks['memory_1g'] = True
            command(guest, 'test "$(uname -r)" = ' + shlex.quote(m['kernel_version']))
            checks['kernel_version'] = True
            command(guest, "grep -q ' / ext4 rw' /proc/mounts; grep -q ' /proc proc ' /proc/mounts; "
                    "grep -q ' /sys sysfs ' /proc/mounts; grep -q ' /dev devtmpfs ' /proc/mounts; "
                    "grep -q ' /dev/pts devpts ' /proc/mounts; test -c /dev/null; test -d /proc/self/fd")
            checks['runtime_mounts'] = True
            pkg_check = ('apk info -e jq' if m['variant'] == 'alpine' else
                         "dpkg-query -W -f='${Status}' jq | grep -qx 'install ok installed'")
            if mode == 'disk':
                out = command(guest, "printf '\\nBOOT_ID=%s\\n' \"$(cat /proc/sys/kernel/random/boot_id)\"")
                boot_id = re.search(r'^BOOT_ID=([a-f0-9-]+)$', out, re.M).group(1)
                host = 'dl-cdn.alpinelinux.org' if m['variant'] == 'alpine' else 'deb.debian.org'
                command(guest, '/bin/busybox nslookup ' + host)
                checks['dns'] = True
                # Exports live only in the test shell and are not saved to the disk.
                command(guest, 'stty -echo')
                guest.send(proxy_export() + '\n')
                command(guest, 'stty echo')
                command(guest, f'curl -fLsS --max-time 60 https://{host}/ -o /dev/null', 90)
                checks['https'] = True
                command(guest, '! command -v jq')
                install = ('apk add --no-cache jq' if m['variant'] == 'alpine' else
                           'apt-get update -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 && DEBIAN_FRONTEND=noninteractive apt-get install -y -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 --no-install-recommends jq')
                command(guest, install + '; ' + pkg_check, max(timeout, 900))
                checks['package_install'] = True
                command(guest, "test \"$(jq -nr '21*2')\" = 42")
                checks['package_execution'] = True
                command(guest, 'mkdir -p /root/.ssh; chmod 700 /root/.ssh; printf "%s\\n" ' + shlex.quote(public) +
                        ' > /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys; printf "%s\\n" ' + token +
                        ' > /root/release-persistence; sha256sum /etc/ssh/ssh_host_* > /root/release-hostkey-hashes; sync')
            else:
                command(guest, 'test "$(cat /proc/sys/kernel/random/boot_id)" != ' + boot_id)
                checks['new_boot_id'] = True
                command(guest, 'test "$(cat /root/release-persistence)" = ' + token)
                checks['file_persistence'] = True
                command(guest, pkg_check + '; test "$(jq -nr \'21*2\')" = 42')
                checks['package_persistence'] = True
                command(guest, 'sha256sum -c /root/release-hostkey-hashes')
            ssh = subprocess.run(['ssh', '-i', str(key), '-p', str(port), '-o', 'BatchMode=yes',
                                  '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=accept-new',
                                  '-o', f'UserKnownHostsFile={files / "known_hosts"}',
                                  'root@127.0.0.1', 'id -u'], capture_output=True, text=True, timeout=30)
            if ssh.returncode or ssh.stdout.strip() != '0':
                raise RuntimeError('SSH key login failed: ' + ssh.stderr)
            checks['ssh_key_login' if mode == 'disk' else 'ssh_key_persistence'] = True
            reboot(guest, timeout)
            checks['clean_reboot'] = True
            row['pass'] = True
        finally:
            guest.close()
            row['uart_sha256'] = sha(log)
        boots.append(row)
    return boots
