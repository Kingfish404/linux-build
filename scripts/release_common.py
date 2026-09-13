"""Release matrix and source fingerprints shared by packaging and its gate."""
import hashlib
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DISTROS = ('alpine', 'debian')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def variants(cfg):
    kind = cfg.get('rootfs', {}).get('type')
    return [kind] if kind in DISTROS else ['tiny_shell'] + (['buildroot'] if 'buildroot' in cfg else [])


def package_name(preset, cfg, variant):
    bits = cfg['target']['arch'].removeprefix('riscv')
    prefix = (f'linux-riscv-{preset.stem}' if variant == 'tiny_shell' or variant in DISTROS
              else f'linux-riscv-rv{bits}-{preset.stem}-buildroot')
    return f'{prefix}-v{cfg["kernel"]["version"]}'


def matrix():
    for p in sorted((ROOT / 'configs').glob('*.toml')):
        cfg = tomllib.loads(p.read_text())
        for variant in variants(cfg):
            yield p, cfg, variant, package_name(p, cfg, variant)


def distro_inputs(preset):
    files = [ROOT / 'Makefile', preset.resolve(), ROOT / 'scripts/distro.mk',
             ROOT / 'scripts/gen-config.py', ROOT / 'scripts/build-distro.py',
             ROOT / 'scripts/package-distro.py', ROOT / 'scripts/release_common.py',
             ROOT / 'scripts/prepare-linux.py']
    files.extend(p for p in (ROOT / 'rootfs/distro').iterdir() if p.is_file())
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(files)}
