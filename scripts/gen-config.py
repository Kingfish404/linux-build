#!/usr/bin/env python3
"""gen-config.py — Parse system.toml and generate build configuration files.

Usage:
    scripts/gen-config.py <system.toml> [--out-dir DIR]

Outputs (written to --out-dir, default "."):
    .config.mk                — Makefile variable overrides (included by top-level Makefile)
    .config.kernel            — Shared kernel config fragment (arch-derived)
    .config.kernel.minimal    — Minimal variant kernel config (from [minimal.kernel.config])
    .config.kernel.buildroot  — Buildroot variant kernel config (from [buildroot.kernel.config])
    .config.buildroot         — Buildroot package config fragment

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
# Architecture mapping (factual derivation from arch + fpu)
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

# Kernel config keys derived from target architecture (not user-configurable)
KERNEL_ARCH_CONFIGS_RV32 = {
    "NONPORTABLE": True,
    "ARCH_RV64I":  False,
    "ARCH_RV32I":  True,
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

    val=True  -> CONFIG_KEY=y
    val=False -> # CONFIG_KEY is not set
    val=str   -> CONFIG_KEY="str"
    val=int   -> CONFIG_KEY=int
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

def gen_make_config(cfg: dict, preset_name: str) -> str:
    """Generate .config.mk content from parsed TOML."""
    arch_name = deep_get(cfg, "target", "arch", default="riscv64")
    arch      = ARCH_MAP.get(arch_name)
    if arch is None:
        print(f"ERROR: unsupported target.arch '{arch_name}'", file=sys.stderr)
        sys.exit(1)

    bits = arch["bits"]

    # Per-variant FPU settings from TOML
    minimal_fpu   = deep_get(cfg, "minimal", "fpu", default=False)
    buildroot_fpu = deep_get(cfg, "buildroot", "fpu", default=True)

    # ISA/ABI derived from arch + per-variant fpu
    isa     = arch["fpu_isa"] if minimal_fpu else arch["nofpu_isa"]
    abi     = arch["fpu_abi"] if minimal_fpu else arch["nofpu_abi"]
    isa_br  = arch["fpu_isa"] if buildroot_fpu else arch["nofpu_isa"]
    abi_br  = arch["fpu_abi"] if buildroot_fpu else arch["nofpu_abi"]

    kver      = deep_get(cfg, "kernel", "version", default="6.18.29")
    rootfs_ty = deep_get(cfg, "rootfs", "type", default="initramfs")
    compress  = deep_get(cfg, "rootfs", "compression", default="gzip")
    loader    = deep_get(cfg, "boot", "loader", default="qemu")
    mem       = deep_get(cfg, "boot", "memory", default=512)
    timeout   = deep_get(cfg, "boot", "timeout", default=0)
    ssh_port  = deep_get(cfg, "buildroot", "ssh_port", default=2222)

    lines = [
        "# Auto-generated by scripts/gen-config.py — DO NOT EDIT",
        f"# Source: {preset_name}",
        "",
        f"SYSTEM_PRESET   := {preset_name}",
        f"BITS            := {bits}",
        f"KERNEL_VERSION  := {kver}",
        "",
        f"# Minimal variant ISA/ABI (derived from [minimal].fpu={minimal_fpu})",
        f"RISCV_ISA       := {isa}",
        f"RISCV_ABI       := {abi}",
        "",
        f"# Buildroot variant ISA/ABI (derived from [buildroot].fpu={buildroot_fpu})",
        f"RISCV_ISA_BUILDROOT := {isa_br}",
        f"RISCV_ABI_BUILDROOT := {abi_br}",
        "",
        f"QEMU_MEM        := {mem}",
        f"QEMU_TIMEOUT    := {timeout if timeout else ''}",
        f"SSH_PORT        := {ssh_port}",
        "",
        f"# Derived from system.toml",
        f"SYSTEM_ROOTFS   := {rootfs_ty}",
        f"SYSTEM_COMPRESS := {compress}",
        f"SYSTEM_LOADER   := {loader}",
    ]
    return "\n".join(lines) + "\n"


def gen_kernel_config(cfg: dict) -> str:
    """Generate shared kernel config fragment (arch-derived + [kernel.config]).

    This file contains architecture-specific overrides and any shared
    [kernel.config] entries.  Variant-specific configs (FPU, ISA extensions)
    are in separate .config.kernel.{minimal,buildroot} files.
    """
    arch_name = deep_get(cfg, "target", "arch", default="riscv64")
    user_cfg  = deep_get(cfg, "kernel", "config", default={})

    lines = [
        "# Auto-generated shared kernel config — DO NOT EDIT",
        "# Source: system.toml  ->  applied via scripts/config",
        "",
    ]

    # Architecture-specific configs (derived from target.arch)
    if arch_name == "riscv32":
        lines.append("# --- RV32 arch overrides ---")
        for k, v in KERNEL_ARCH_CONFIGS_RV32.items():
            lines.append(kconfig_line(k, v))
        lines.append("")

    # Compression-related configs
    compress = deep_get(cfg, "rootfs", "compression", default="gzip")
    if compress == "zstd":
        lines.append("# --- zstd compression ---")
        lines.append(kconfig_line("RD_ZSTD", True))
        lines.append(kconfig_line("INITRAMFS_COMPRESSION_ZSTD", True))
        lines.append("")

    # Shared user overrides from [kernel.config]
    if user_cfg:
        lines.append("# --- User overrides from [kernel.config] ---")
        for k, v in user_cfg.items():
            lines.append(kconfig_line(k, v))
        lines.append("")

    return "\n".join(lines) + "\n"


def gen_variant_kernel_config(cfg: dict, variant: str) -> str:
    """Generate a per-variant kernel config fragment.

    Reads [<variant>.kernel.config] from the TOML and translates each
    key-value pair into a CONFIG_* line.
    """
    variant_cfg = deep_get(cfg, variant, "kernel.config", default=None)
    # TOML parses "kernel.config" key inside [variant] as a dotted key,
    # but under [variant.kernel.config] it's a nested table.
    if variant_cfg is None:
        variant_cfg = deep_get(cfg, variant, "kernel", "config", default={})

    lines = [
        f"# Auto-generated {variant} kernel config — DO NOT EDIT",
        f"# Source: system.toml [{variant}.kernel.config]",
        "",
    ]

    if variant_cfg:
        for k, v in variant_cfg.items():
            lines.append(kconfig_line(k, v))
        lines.append("")

    return "\n".join(lines) + "\n"


def gen_buildroot_config(cfg: dict) -> str:
    """Generate Buildroot config fragment from TOML [buildroot.packages]."""
    compress   = deep_get(cfg, "rootfs", "compression", default="gzip")
    packages   = deep_get(cfg, "buildroot", "packages", "include", default=[])
    shell      = deep_get(cfg, "buildroot", "packages", "shell", default=None)
    root_pw    = deep_get(cfg, "buildroot", "packages", "root_password", default=None)

    lines = [
        "# Auto-generated Buildroot config fragment — DO NOT EDIT",
        "# Source: system.toml  ->  applied on top of qemu_riscv*_virt_defconfig",
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
    kver = deep_get(cfg, "kernel", "version", default="?")
    pkgs = deep_get(cfg, "buildroot", "packages", "include", default=[])
    minimal_fpu   = deep_get(cfg, "minimal", "fpu", default=False)
    buildroot_fpu = deep_get(cfg, "buildroot", "fpu", default=True)

    bits = ARCH_MAP.get(arch, {}).get("bits", "?")
    isa_min = ARCH_MAP.get(arch, {}).get("fpu_isa" if minimal_fpu else "nofpu_isa", "?")
    isa_br  = ARCH_MAP.get(arch, {}).get("fpu_isa" if buildroot_fpu else "nofpu_isa", "?")

    print(f"  Target:     {arch} (rv{bits})")
    print(f"  Minimal:    {isa_min} (FPU={'on' if minimal_fpu else 'off'})")
    print(f"  Buildroot:  {isa_br} (FPU={'on' if buildroot_fpu else 'off'})")
    print(f"  Kernel:     {kver}")
    if pkgs:
        print(f"  Packages:   {', '.join(pkgs)}")
    print(f"  Generated:  {out_dir / '.config.mk'}")
    print(f"              {out_dir / '.config.kernel'}")
    print(f"              {out_dir / '.config.kernel.minimal'}")
    print(f"              {out_dir / '.config.kernel.buildroot'}")
    if "buildroot" in cfg:
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
    preset_name = args.system_toml.stem  # e.g. "qemu-rv32" from "configs/qemu-rv32.toml"
    (out / ".config.mk").write_text(gen_make_config(cfg, preset_name))

    # Write .config.kernel (shared arch-derived config)
    (out / ".config.kernel").write_text(gen_kernel_config(cfg))

    # Write per-variant kernel config fragments
    (out / ".config.kernel.minimal").write_text(gen_variant_kernel_config(cfg, "minimal"))
    (out / ".config.kernel.buildroot").write_text(gen_variant_kernel_config(cfg, "buildroot"))

    # Write .config.buildroot when a [buildroot] section exists
    # (even with empty packages — base buildroot with busybox is still useful)
    if "buildroot" in cfg:
        (out / ".config.buildroot").write_text(gen_buildroot_config(cfg))
    else:
        # Remove stale buildroot config if no [buildroot] section
        br = out / ".config.buildroot"
        if br.exists():
            br.unlink()

    print(f"✓ Configuration generated from {args.system_toml}")
    print_summary(cfg, out)


if __name__ == "__main__":
    main()
