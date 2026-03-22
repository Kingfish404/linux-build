#!/usr/bin/env python3
"""gen-config.py — Parse system.toml and generate build configuration files.

Usage:
    scripts/gen-config.py <system.toml> [--out-dir DIR]

Outputs (written to --out-dir, default "."):
    .config.mk          — Makefile variable overrides (included by top-level Makefile)
    .config.kernel       — Kernel config fragment (applied via scripts/config)
    .config.buildroot    — Buildroot config fragment (applied by make_initramfs_buildroot)

The generated .config.mk is designed to be `-include`d by the Makefile BEFORE
any `?=` default assignments, so TOML values override defaults cleanly.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Architecture mapping
# ---------------------------------------------------------------------------

ARCH_MAP = {
    "riscv32": {
        "bits": 32,
        "fpu_isa":    "rv32imafd_zicntr_zicsr_zifencei",
        "nofpu_isa":  "rv32imac_zicntr_zicsr_zifencei",
        "fpu_abi":    "ilp32d",
        "nofpu_abi":  "ilp32",
    },
    "riscv64": {
        "bits": 64,
        "fpu_isa":    "rv64imafd_zicntr_zicsr_zifencei",
        "nofpu_isa":  "rv64imac_zicntr_zicsr_zifencei",
        "fpu_abi":    "lp64d",
        "nofpu_abi":  "lp64",
    },
}

# Kernel config keys that are always set based on the target architecture
KERNEL_ARCH_CONFIGS_RV32 = {
    "NONPORTABLE": True,
    "ARCH_RV64I":  False,
    "ARCH_RV32I":  True,
}

# Kernel config keys managed by the build system (toggled by target.fpu)
KERNEL_FPU_CONFIGS = {
    True:  {"FPU": True},
    False: {
        "FPU": False,
        "RISCV_ISA_ZAWRS":  False,
        "RISCV_ISA_ZBA":    False,
        "RISCV_ISA_ZBB":    False,
        "RISCV_ISA_ZBC":    False,
        "RISCV_ISA_ZICBOM": False,
        "RISCV_ISA_ZICBOZ": False,
    },
}

# ---------------------------------------------------------------------------
# Buildroot config generation
# ---------------------------------------------------------------------------

# Well-known Buildroot package symbols (upper-cased, BR2_PACKAGE_ prefix)
# We handle the common case; unknown packages get a best-effort mapping.
BUILDROOT_PKG_MAP = {
    "openssh":  "BR2_PACKAGE_OPENSSH",
    "wget":     "BR2_PACKAGE_WGET",
    "strace":   "BR2_PACKAGE_STRACE",
    "htop":     "BR2_PACKAGE_HTOP",
    "lsof":     "BR2_PACKAGE_LSOF",
    "file":     "BR2_PACKAGE_FILE",
    "tree":     "BR2_PACKAGE_TREE",
    "python3":  "BR2_PACKAGE_PYTHON3",
    "curl":     "BR2_PACKAGE_CURL",
    "git":      "BR2_PACKAGE_GIT",
    "bash":     "BR2_PACKAGE_BASH",
    "tmux":     "BR2_PACKAGE_TMUX",
    "vim":      "BR2_PACKAGE_VIM",
    "nano":     "BR2_PACKAGE_NANO",
    "rsync":    "BR2_PACKAGE_RSYNC",
    "iproute2": "BR2_PACKAGE_IPROUTE2",
}

BUILDROOT_SHELL_MAP = {
    "bash":    "BR2_SYSTEM_BIN_SH_BASH",
    "dash":    "BR2_SYSTEM_BIN_SH_DASH",
    "zsh":     "BR2_SYSTEM_BIN_SH_ZSH",
    "busybox": "BR2_SYSTEM_BIN_SH_BUSYBOX_ASH",
}


def pkg_symbol(name: str) -> str:
    """Map a package name to its BR2_PACKAGE_* symbol."""
    if name in BUILDROOT_PKG_MAP:
        return BUILDROOT_PKG_MAP[name]
    return f"BR2_PACKAGE_{name.upper().replace('-', '_')}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deep_get(d: dict, *keys: str, default: Any = None) -> Any:
    """Nested dict access with default."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def kconfig_line(key: str, val: Any) -> str:
    """Format a single kernel config line.

    val=True  → CONFIG_KEY=y
    val=False → # CONFIG_KEY is not set
    val=str   → CONFIG_KEY="str"
    val=int   → CONFIG_KEY=int
    """
    full = f"CONFIG_{key}" if not key.startswith("CONFIG_") else key
    if val is True:
        return f"{full}=y"
    if val is False:
        return f"# {full} is not set"
    if isinstance(val, int):
        return f"{full}={val}"
    return f'{full}="{val}"'


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def gen_make_config(cfg: dict) -> str:
    """Generate .config.mk content from parsed TOML."""
    arch_name = deep_get(cfg, "target", "arch", default="riscv64")
    fpu       = deep_get(cfg, "target", "fpu", default=False)
    arch      = ARCH_MAP.get(arch_name)
    if arch is None:
        print(f"ERROR: unsupported target.arch '{arch_name}'", file=sys.stderr)
        sys.exit(1)

    bits      = arch["bits"]
    isa       = arch["fpu_isa"] if fpu else arch["nofpu_isa"]
    abi       = arch["fpu_abi"] if fpu else arch["nofpu_abi"]
    kver      = deep_get(cfg, "kernel", "version", default="6.18.15")
    init      = deep_get(cfg, "rootfs", "init", default="loop")
    rootfs_ty = deep_get(cfg, "rootfs", "type", default="initramfs")
    compress  = deep_get(cfg, "rootfs", "compression", default="gzip")
    loader    = deep_get(cfg, "boot", "loader", default="qemu")
    mem       = deep_get(cfg, "boot", "memory", default=512)
    timeout   = deep_get(cfg, "boot", "timeout", default=0)
    ssh_port  = deep_get(cfg, "boot", "ssh_port", default=2222)

    lines = [
        "# Auto-generated by scripts/gen-config.py — DO NOT EDIT",
        f"# Source: $(SYSTEM)",
        "",
        f"BITS            := {bits}",
        f"KERNEL_VERSION  := {kver}",
        f"RISCV_ISA       := {isa}",
        f"RISCV_ABI       := {abi}",
        f"QEMU_MEM        := {mem}",
        f"QEMU_TIMEOUT    := {timeout if timeout else ''}",
        f"SSH_PORT        := {ssh_port}",
        "",
        f"# Derived from system.toml",
        f"SYSTEM_INIT     := {init}",
        f"SYSTEM_ROOTFS   := {rootfs_ty}",
        f"SYSTEM_COMPRESS := {compress}",
        f"SYSTEM_LOADER   := {loader}",
        f"SYSTEM_FPU      := {'y' if fpu else 'n'}",
    ]
    return "\n".join(lines) + "\n"


def gen_kernel_config(cfg: dict) -> str:
    """Generate kernel config fragment from TOML."""
    arch_name = deep_get(cfg, "target", "arch", default="riscv64")
    fpu       = deep_get(cfg, "target", "fpu", default=False)
    user_cfg  = deep_get(cfg, "kernel", "config", default={})

    lines = [
        "# Auto-generated kernel config fragment — DO NOT EDIT",
        "# Source: system.toml  →  applied via scripts/config",
        "",
    ]

    # Architecture-specific configs
    if arch_name == "riscv32":
        lines.append("# --- RV32 arch overrides ---")
        for k, v in KERNEL_ARCH_CONFIGS_RV32.items():
            lines.append(kconfig_line(k, v))
        lines.append("")

    # FPU / ISA extension configs
    lines.append("# --- FPU / ISA ---")
    for k, v in KERNEL_FPU_CONFIGS[fpu].items():
        lines.append(kconfig_line(k, v))
    lines.append("")

    # Compression-related configs
    compress = deep_get(cfg, "rootfs", "compression", default="gzip")
    if compress == "zstd":
        lines.append("# --- zstd compression ---")
        lines.append(kconfig_line("RD_ZSTD", True))
        lines.append(kconfig_line("INITRAMFS_COMPRESSION_ZSTD", True))
        lines.append("")

    # User overrides from [kernel.config]
    if user_cfg:
        lines.append("# --- User overrides from [kernel.config] ---")
        for k, v in user_cfg.items():
            lines.append(kconfig_line(k, v))
        lines.append("")

    return "\n".join(lines) + "\n"


def gen_buildroot_config(cfg: dict) -> str:
    """Generate Buildroot config fragment from TOML."""
    init       = deep_get(cfg, "rootfs", "init", default="loop")
    compress   = deep_get(cfg, "rootfs", "compression", default="gzip")
    packages   = deep_get(cfg, "rootfs", "packages", "include", default=[])
    shell      = deep_get(cfg, "rootfs", "packages", "shell", default=None)
    root_pw    = deep_get(cfg, "rootfs", "packages", "root_password", default=None)

    lines = [
        "# Auto-generated Buildroot config fragment — DO NOT EDIT",
        "# Source: system.toml  →  applied on top of qemu_riscv*_virt_defconfig",
        "",
        "# --- Output format ---",
        "BR2_TARGET_ROOTFS_CPIO=y",
    ]

    if compress == "zstd":
        lines.append("BR2_TARGET_ROOTFS_CPIO_ZSTD=y")
    else:
        lines.append("BR2_TARGET_ROOTFS_CPIO_GZIP=y")

    lines.extend([
        "# Disable ext2 image (only need cpio)",
        "# BR2_TARGET_ROOTFS_EXT2 is not set",
        "",
    ])

    # Shell
    if shell and shell in BUILDROOT_SHELL_MAP:
        sym = BUILDROOT_SHELL_MAP[shell]
        lines.append(f"# --- Shell ---")
        lines.append(f"{sym}=y")
        # If switching to bash, also pull the bash package
        if shell == "bash":
            lines.append("BR2_PACKAGE_BASH=y")
        lines.append("")

    # Packages
    if packages:
        lines.append("# --- Packages ---")
        for pkg in sorted(packages):
            lines.append(f"{pkg_symbol(pkg)}=y")
        lines.append("")

    # Root password
    if root_pw:
        lines.append("# --- System ---")
        lines.append(f'BR2_TARGET_GENERIC_ROOT_PASSWD="{root_pw}"')
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(cfg: dict, out_dir: Path) -> None:
    """Pretty-print what was generated."""
    arch = deep_get(cfg, "target", "arch", default="?")
    fpu  = deep_get(cfg, "target", "fpu", default=False)
    init = deep_get(cfg, "rootfs", "init", default="?")
    kver = deep_get(cfg, "kernel", "version", default="?")
    pkgs = deep_get(cfg, "rootfs", "packages", "include", default=[])

    bits = ARCH_MAP.get(arch, {}).get("bits", "?")
    isa  = ARCH_MAP.get(arch, {}).get("fpu_isa" if fpu else "nofpu_isa", "?")

    print(f"  Target:     {arch} (rv{bits}, {'FPU' if fpu else 'no-FPU'})")
    print(f"  ISA:        {isa}")
    print(f"  Kernel:     {kver}")
    print(f"  Init:       {init}")
    if pkgs:
        print(f"  Packages:   {', '.join(pkgs)}")
    print(f"  Generated:  {out_dir / '.config.mk'}")
    print(f"              {out_dir / '.config.kernel'}")
    if init == "busybox":
        print(f"              {out_dir / '.config.buildroot'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate build config from system.toml")
    parser.add_argument("system_toml", type=Path, help="Path to system.toml")
    parser.add_argument("--out-dir", type=Path, default=Path("."),
                        help="Output directory (default: .)")
    args = parser.parse_args()

    if not args.system_toml.exists():
        print(f"ERROR: {args.system_toml} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.system_toml, "rb") as f:
        cfg = tomllib.load(f)

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    # Write .config.mk
    (out / ".config.mk").write_text(gen_make_config(cfg))

    # Write .config.kernel
    (out / ".config.kernel").write_text(gen_kernel_config(cfg))

    # Write .config.buildroot (only when using Buildroot)
    init = deep_get(cfg, "rootfs", "init", default="loop")
    if init == "busybox":
        (out / ".config.buildroot").write_text(gen_buildroot_config(cfg))
    else:
        # Remove stale buildroot config if switching away
        br = out / ".config.buildroot"
        if br.exists():
            br.unlink()

    print(f"✓ Configuration generated from {args.system_toml}")
    print_summary(cfg, out)


if __name__ == "__main__":
    main()
