#!/usr/bin/env python3
"""Download kernel.org tarballs, verify published SHA256, and extract atomically."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--version', required=True)
    ap.add_argument('--source-root', type=Path, required=True)
    a = ap.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', a.version):
        ap.error('expected major.minor.patch version')
    root = a.source_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / ('linux-' + a.version)
    if target.is_dir():
        print(f'{target} already exists, skipping download')
        return
    name = target.name + '.tar.xz'
    url = f'https://cdn.kernel.org/pub/linux/kernel/v{a.version.split(".")[0]}.x/'
    sums = subprocess.check_output(['curl', '-fsSL', '--retry', '3', '--max-time', '120',
                                    url + 'sha256sums.asc'], text=True)
    matches = re.findall(r'^([0-9a-f]{64})\s+' + re.escape(name) + r'$', sums, re.M)
    if len(matches) != 1:
        raise RuntimeError('kernel.org checksum not found')
    archive = root / name
    if not archive.exists():
        partial = root / (name + '.partial')
        subprocess.run(['curl', '-fL', '--retry', '3', '--max-time', '900',
                        '-o', partial, url + name], check=True)
        partial.rename(archive)
    h = hashlib.sha256()
    with archive.open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    if h.hexdigest() != matches[0]:
        raise RuntimeError(f'kernel checksum mismatch: {archive}; existing file preserved')
    with tempfile.TemporaryDirectory(prefix='.linux-', dir=root) as tmp:
        subprocess.run(['tar', '-xf', archive, '-C', tmp], check=True)
        unpacked = Path(tmp) / target.name
        (unpacked / '.linux-build-source.json').write_text(json.dumps(
            {'version': a.version, 'archive_url': url + name, 'sha256': h.hexdigest()}, indent=2) + '\n')
        unpacked.rename(target)
    print(f'Verified and extracted {target}')


if __name__ == '__main__':
    main()
