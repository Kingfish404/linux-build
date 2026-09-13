#!/usr/bin/env python3
"""Audit release archives and exercise both OpenSBI boot paths in QEMU."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time
import distro_runtime
from release_common import DISTROS

FAILURES = ('Kernel panic', 'Oops:', 'Unable to handle kernel', 'BUG:',
            'No working init found', 'Attempted to kill init', 'rcu: INFO:')
BR_MARKERS = ['RAPT_ACCEPT_BEGIN', 'RAPT_CHILD_COUNT=100', 'RAPT_CHILD_PASS',
              'RAPT_SLEEP_BEGIN', 'RAPT_SLEEP_PASS', 'RAPT_ACCEPT_END']
BR_COMMAND = '''echo RAPT_ACCEPT_BEGIN; uname -a; p=$$; i=0; while [ "$i" -lt 100 ]; do /bin/sh -c '[ "$$" -ne "$1" ]' rapt-child "$p" || { echo RAPT_CHILD_FAIL; break; }; i=$((i+1)); done; echo RAPT_CHILD_COUNT=$i; [ "$i" -eq 100 ] && echo RAPT_CHILD_PASS; echo RAPT_SLEEP_BEGIN; cat /proc/uptime; if sleep 90; then echo RAPT_SLEEP_PASS; else echo RAPT_SLEEP_FAIL; fi; cat /proc/uptime; echo RAPT_ACCEPT_END\n'''


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def clean(text):
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).replace('\r', '')


def user_elf(rootfs, variant, bits):
    data = gzip.decompress(rootfs.read_bytes())
    wanted = {'init'} if variant == 'tiny_shell' else {'bin/busybox', 'usr/bin/busybox'}
    offset = 0
    found_elf = None
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError('rootfs is not a newc CPIO archive')
        size = int(header[54:62], 16)
        namesize = int(header[94:102], 16)
        name = data[offset + 110:offset + 110 + namesize - 1].decode()
        start = (offset + 110 + namesize + 3) & ~3
        body = data[start:start + size]
        offset = (start + size + 3) & ~3
        name = name.removeprefix('./').lstrip('/')
        if name.startswith(('lib/modules/', 'usr/lib/modules/')):
            raise ValueError('rootfs contains modules from the separate Buildroot kernel')
        if name == 'TRAILER!!!':
            break
        if name in wanted and body.startswith(b'\x7fELF'):
            if body[4] != (1 if bits == 32 else 2) or struct.unpack_from('<H', body, 18)[0] != 243:
                raise ValueError('rootfs ELF architecture differs from package')
            flags = struct.unpack_from('<I', body, 36 if bits == 32 else 48)[0]
            expected_float = 0 if variant == 'tiny_shell' else 4
            if flags & 6 != expected_float:
                raise ValueError('rootfs ELF float ABI differs from package variant')
            found_elf = {'path': name, 'bits': bits, 'flags': flags}
    if found_elf is not None:
        return found_elf
    raise ValueError('cannot find the variant user ELF in rootfs')


def extract_and_audit(archive, destination):
    expected_root = archive.name.removesuffix('.tar.gz')
    hashes = {}
    with tarfile.open(archive, 'r|gz') as tf:
        for member in tf:
            parts = Path(member.name).parts
            if member.isdir() and parts == (expected_root,):
                continue
            if not member.isfile() or len(parts) != 2 or parts[0] != expected_root or parts[1] in hashes:
                raise ValueError(f'unexpected archive member: {member.name}')
            output = destination / parts[1]
            h = hashlib.sha256()
            stream = tf.extractfile(member)
            with output.open('wb') as f:
                while block := stream.read(1024 * 1024):
                    h.update(block)
                    f.write(block)
            hashes[parts[1]] = h.hexdigest()
    manifest = json.loads((destination / 'manifest.json').read_text())
    if {name: h for name, h in hashes.items() if name != 'manifest.json'} != manifest['files']:
        raise ValueError('archive file hashes differ from manifest')
    source = json.loads((destination / 'kernel-source.json').read_text())
    version = manifest['kernel_version']
    expected_url = f'https://cdn.kernel.org/pub/linux/kernel/v{version.split(".")[0]}.x/linux-{version}.tar.xz'
    if (source['version'] != version or source['archive_url'] != expected_url or
            not re.fullmatch(r'[0-9a-f]{64}', source['sha256'])):
        raise ValueError('kernel source provenance differs from package')
    if manifest['variant'] in DISTROS:
        return distro_runtime.audit(destination, manifest)
    if manifest['variant'] == 'buildroot':
        rootfs = json.loads((destination / 'rootfs-manifest.json').read_text())
        if rootfs['identity'].get('schema') != 2 or not rootfs.get('busybox_required_features') or rootfs['rootfs_sha256'] != manifest['files']['initramfs.cpio.gz']:
            raise ValueError('rootfs provenance does not verify the BusyBox baseline')
    config = (destination / 'kernel.config').read_text().splitlines()
    for line in ('CONFIG_HZ=100', 'CONFIG_HZ_100=y', 'CONFIG_MMU=y',
                 'CONFIG_SERIAL_LITEUART=y', 'CONFIG_SERIAL_LITEUART_CONSOLE=y'):
        if line not in config:
            raise ValueError(f'missing required configuration: {line}')
    if ('CONFIG_FPU=y' in config) != (manifest['variant'] == 'buildroot'):
        raise ValueError('kernel FPU configuration differs from variant')
    if manifest['variant'] == 'buildroot' and 'CONFIG_FUTEX=y' not in config:
        raise ValueError('Buildroot is missing futex support')
    image = (destination / 'Image').read_bytes()
    payload = (destination / 'fw_payload.bin').read_bytes()
    if payload.find(image) != manifest['payload_kernel_offset']:
        raise ValueError('firmware contains a different kernel')
    offset, size = struct.unpack_from('<QQ', image, 8)
    if offset + max(size, len(image)) > manifest['fdt_offset']:
        raise ValueError('DTB overlaps kernel memory')
    if manifest['fdt_offset'] + 65536 > manifest['memory_mib'] * 1024 * 1024:
        raise ValueError('DTB exceeds the configured RAM')
    manifest['tested_user_elf'] = user_elf(destination / 'initramfs.cpio.gz', manifest['variant'], manifest['bits'])
    return manifest


class Guest:
    def __init__(self, command, log_path):
        self.command = command
        self.log = log_path.open('wb', buffering=0)
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.raw = bytearray()
        self.partial = ''
        self.events = {}
        self.started = time.monotonic()

    @property
    def text(self):
        return clean(self.raw.decode(errors='replace'))

    def read(self):
        if select.select([self.process.stdout], [], [], .1)[0]:
            data = os.read(self.process.stdout.fileno(), 65536)
            self.raw.extend(data)
            self.log.write(data)
            self.partial += data.decode(errors='replace')
            while '\n' in self.partial:
                line, self.partial = self.partial.split('\n', 1)
                line = clean(line)
                if line in BR_MARKERS + ['RAPT_BASELINE_PASS'] and line not in self.events:
                    self.events[line] = time.monotonic()
                if line in ('RAPT_CHILD_FAIL', 'RAPT_SLEEP_FAIL', 'RAPT_BASELINE_FAIL'):
                    raise RuntimeError(line)
            text = self.text
            if any(marker in text for marker in FAILURES):
                raise RuntimeError('kernel failure marker in guest log')
        if self.process.poll() is not None:
            raise RuntimeError(f'QEMU exited with {self.process.returncode}')

    def wait(self, predicate, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            self.read()
        raise TimeoutError(f'guest did not reach expected state within {timeout}s')

    def send(self, text):
        self.process.stdin.write(text.encode())
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log.close()


def tiny_network_and_exec(guest, files, bits, tiny=True):
    # Fetch and execute a real ELF to test the shell's clone/exec/wait wrappers.
    source = files / 'probe.S'
    source.write_text(""".section .text
.globl _start
_start:
.option push
.option norelax
li a0, 1
la a1, message
li a2, 16
li a7, 64
ecall
li a0, 37
li a7, 93
ecall
.option pop
.section .rodata
message: .ascii "RAPT_EXEC_CHILD\\n"
""")
    subprocess.run(['riscv64-linux-gnu-gcc', f'-march=rv{bits}ima',
                    '-mabi=' + ('ilp32' if bits == 32 else 'lp64'),
                    '-nostdlib', '-static', '-Wl,-e,_start', str(source),
                    '-o', str(files / 'probe')], check=True, capture_output=True)
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(files)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    prompt = 'tinysh# ' if tiny else '# '
    commands = [('ping 10.0.2.2' if tiny else 'ping -c 3 10.0.2.2', '3/3 replies' if tiny else '3 packets received'),
                (f'fetch 10.0.2.2 {server.server_port} /probe /tmp/probe', 'saved '),
                ('run /tmp/probe', 'exit 37')]
    if not tiny:
        commands.append((f"printf 'GET /probe HTTP/1.0\\r\\n\\r\\n' | nc -w 5 10.0.2.2 {server.server_port} > /tmp/nc-http; grep -q '200 OK' /tmp/nc-http && echo RAPT_NC_PASS", 'RAPT_NC_PASS'))
    checked = []
    try:
        for command, expected in commands:
            offset = len(guest.raw)
            guest.send(command + '\n')
            guest.wait(lambda: clean(guest.raw[offset:].decode(errors='replace')).endswith(prompt), 30)
            output = clean(guest.raw[offset:].decode(errors='replace'))
            if expected not in output or 'failed' in output.lower():
                raise RuntimeError(f'tiny network/exec check failed: {command}: {output}')
            if command.startswith('run ') and '\nRAPT_EXEC_CHILD\n' not in output:
                raise RuntimeError('downloaded child did not execute')
            if expected == 'RAPT_NC_PASS' and '\nRAPT_NC_PASS\n' not in output:
                raise RuntimeError('BusyBox nc transfer failed')
            checked.append(command)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return checked


def buildroot_capabilities(guest):
    # Keep each line below BusyBox ash's default 1024-byte editing buffer.
    groups = [
        "grep -q '^processor' /proc/cpuinfo; grep -q '^MemTotal:' /proc/meminfo; "
        "cat /proc/uptime >/dev/null; test -d /sys/devices; test -d /proc/self/fd; "
        "uname -a >/dev/null; uptime >/dev/null; free >/dev/null; ps >/dev/null; df >/dev/null",
        "test -c /dev/null; test -c /dev/zero; test -c /dev/console; "
        "grep -q ' /proc proc ' /proc/mounts; grep -q ' /sys sysfs ' /proc/mounts; "
        "grep -q ' /dev devtmpfs ' /proc/mounts; grep -q ' /dev/pts devpts ' /proc/mounts",
        'for c in pwd cd ls cat cp touch mkdir rm rmdir mount sync uname uptime free sleep '
        'run clear reboot poweroff exit ifconfig ping nc fetch ps top df du dmesg; '
        'do command -v "$c" >/dev/null; done',
        "mkdir -p /tmp/raptor-baseline; echo RAPT_FILE_DATA >/tmp/raptor-baseline/source; "
        "cp /tmp/raptor-baseline/source /tmp/raptor-baseline/copy; "
        "cmp /tmp/raptor-baseline/source /tmp/raptor-baseline/copy; "
        "rm /tmp/raptor-baseline/source /tmp/raptor-baseline/copy; rmdir /tmp/raptor-baseline",
    ]
    for index, script in enumerate(groups):
        marker = f'RAPT_BASELINE_STEP_{index}'
        offset = len(guest.raw)
        guest.send("if /bin/sh -ec " + shlex.quote(script) + f"; then echo {marker}; else echo RAPT_BASELINE_FAIL; fi\n")
        guest.wait(lambda: '\n' + marker + '\n' in clean(guest.raw[offset:].decode(errors='replace'))
                   and guest.text.endswith('# '), 30)
    return {'proc_cpuinfo': True, 'sysfs': True, 'devtmpfs': True, 'devpts': True,
            'tinysh_command_baseline': True, 'filesystem_operations': True}


def boot(files, manifest, mode, timeout, log_path):
    bits = manifest['bits']
    variant = manifest['variant']
    qemu = shutil.which(f'qemu-system-riscv{bits}')
    if not qemu:
        raise RuntimeError(f'QEMU RV{bits} is unavailable')
    command = [qemu, '-M', 'virt', '-m', f'{manifest["memory_mib"]}M', '-smp', '1',
               '-cpu', f'rv{bits},h=false,sstc=false,svadu=false', '-nographic', '-no-reboot',
               '-netdev', 'user,id=net0', '-device', 'virtio-net-device,netdev=net0']
    if mode in ('split', 'shell'):
        command += ['-bios', str(files / 'fw_dynamic.bin'), '-kernel', str(files / 'Image'),
                    '-initrd', str(files / 'initramfs.cpio.gz'), '-append',
                    'root=/dev/ram rdinit=' + ('/sbin/raptor-shell' if mode == 'shell' else '/init') + ' console=ttyS0 earlycon=sbi' + (' ip=dhcp' if variant == 'tiny_shell' or mode == 'shell' else '')]
    else:
        # Exercise the actual README single-file command: no separate kernel or
        # initrd may hide a corrupt embedded payload or relocation collision.
        command += ['-bios', str(files / 'fw_payload.bin')]
    result = {'mode': mode, 'command': command, 'started': time.time(), 'pass': False}
    guest = Guest(command, log_path)
    try:
        ready = (lambda: guest.text.endswith('tinysh# ')) if variant == 'tiny_shell' else (
            lambda: re.search(r'(?:^|\n)[^\n]*' + ('# $' if mode == 'shell' else 'login: $'), guest.text) is not None)
        guest.wait(ready, timeout)
        result['boot_wall_seconds'] = time.monotonic() - guest.started
        if mode == 'split' and variant == 'tiny_shell':
            result['network_exec_commands'] = tiny_network_and_exec(guest, files, bits)
        if mode == 'shell':
            result['capabilities'] = buildroot_capabilities(guest)
            result['network_exec_commands'] = tiny_network_and_exec(guest, files, bits, tiny=False)
        if mode == 'payload':
            if variant == 'buildroot':
                offset = len(guest.raw)
                guest.send('root\n')
                guest.wait(lambda: re.search(r'(?:^|\n)[^\n]*# $', clean(guest.raw[offset:].decode(errors='replace'))) is not None, 30)
                result['capabilities'] = buildroot_capabilities(guest)
                result['network_exec_commands'] = tiny_network_and_exec(guest, files, bits, tiny=False)
                guest.send(BR_COMMAND)
                guest.wait(lambda: 'RAPT_ACCEPT_END' in guest.events, max(timeout, 150))
                if any(marker not in guest.events for marker in BR_MARKERS):
                    raise RuntimeError('missing functional acceptance markers')
                positions = [guest.events[m] for m in BR_MARKERS]
                if positions != sorted(positions):
                    raise RuntimeError('acceptance markers arrived out of order')
                elapsed = guest.events['RAPT_SLEEP_PASS'] - guest.events['RAPT_SLEEP_BEGIN']
                if elapsed < 89:
                    raise RuntimeError('90-second sleep returned too early')
                result.update(child_processes=100, sleep_wall_seconds=elapsed, events=guest.events)
            else:
                checks = [('uname', 'Linux'), ('touch /tmp/raptor-release-check', None),
                          ('ls /tmp', 'raptor-release-check'), ('rm /tmp/raptor-release-check', None),
                          ('sleep 2', None), ('echo RAPT_TINY_END', 'RAPT_TINY_END')]
                result['commands'] = []
                for command_text, expected in checks:
                    offset = len(guest.raw)
                    start = time.monotonic()
                    guest.send(command_text + '\n')
                    guest.wait(lambda: clean(guest.raw[offset:].decode(errors='replace')).endswith('tinysh# '), 15)
                    output = clean(guest.raw[offset:].decode(errors='replace'))
                    elapsed = time.monotonic() - start
                    if expected and expected not in output:
                        raise RuntimeError(f'tiny shell check failed: {command_text}')
                    if command_text == 'sleep 2' and elapsed < 1.8:
                        raise RuntimeError('tiny shell sleep returned too early')
                    if 'failed' in output.lower() or 'unknown command' in output.lower():
                        raise RuntimeError(f'tiny shell command error: {command_text}')
                    result['commands'].append({'command': command_text, 'wall_seconds': elapsed})
        result['pass'] = True
    finally:
        guest.close()
        result['finished'] = time.time()
        result['uart_sha256'] = digest(log_path)
        log_path.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def test_one(archive, timeout, log_dir):
    name = archive.name.removesuffix('.tar.gz')
    result = {'archive': archive.name, 'archive_sha256': digest(archive), 'pass': False, 'boots': []}
    try:
        with tempfile.TemporaryDirectory(prefix='raptor-package-') as temp:
            files = Path(temp)
            manifest = extract_and_audit(archive, files)
            result.update(preset=manifest['preset'], variant=manifest['variant'], bits=manifest['bits'],
                          kernel_version=manifest['kernel_version'], user_elf=manifest['tested_user_elf'],
                          kernel_hz=manifest['kernel_hz'], memory_mib=manifest['memory_mib'])
            if manifest['variant'] in DISTROS:
                result['boots'] = distro_runtime.test(files, manifest, timeout, log_dir, name, Guest)
            else:
                for mode in (('split', 'payload', 'shell') if manifest['variant'] == 'buildroot' else ('split', 'payload')):
                    result['boots'].append(boot(files, manifest, mode, timeout, log_dir / (name + '-' + mode + '.log')))
            if digest(archive) != result['archive_sha256']:
                raise ValueError('archive changed during testing')
            result['pass'] = True
    except Exception as error:
        result['error'] = str(error)
    (log_dir / (name + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(('PASS ' if result['pass'] else 'FAIL ') + name + (': ' + result['error'] if 'error' in result else ''), flush=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dist', type=Path, default=Path('dist'))
    ap.add_argument('--timeout', type=float, default=120)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--match', default='*.tar.gz', help='archive glob for focused reruns')
    a = ap.parse_args()
    if a.timeout <= 0 or a.jobs < 1:
        ap.error('timeout and jobs must be positive')
    archives = sorted(a.dist.glob(a.match))
    if not archives:
        ap.error('no matching archives')
    run_dir = a.dist / 'test-logs' / time.strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=False)
    summary = {'started': time.time(), 'test_runner_sha256': digest(Path(__file__)), 'scope': 'QEMU and archive validation, not FPGA acceptance',
               'test_dependencies': {p: digest(Path(__file__).parent / p) for p in ('distro_runtime.py', 'release_common.py')},
               'log_dir': str(run_dir), 'results': [], 'pass': False}
    print(f'Testing {len(archives)} archives: firmware paths, Buildroot shell, distro installation/reboot persistence', flush=True)
    with ThreadPoolExecutor(max_workers=a.jobs) as executor:
        futures = [executor.submit(test_one, p, a.timeout, run_dir) for p in archives]
        for future in as_completed(futures):
            summary['results'].append(future.result())
            (run_dir / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    summary['results'].sort(key=lambda r: r['archive'])
    summary['pass'] = all(r['pass'] for r in summary['results'])
    summary['finished'] = time.time()
    (run_dir / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    (a.dist / 'test-results.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
