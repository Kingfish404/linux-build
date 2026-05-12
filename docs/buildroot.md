# Buildroot Rootfs Guide

This document covers building, customising, and troubleshooting the Buildroot-based
initramfs used by this project.

> **Makefile structure:** All Buildroot-related variables and targets live in
> [`scripts/buildroot.mk`](../scripts/buildroot.mk), which is `include`-d by the top-level
> `Makefile`. You still invoke every target via `make` as usual — the split is purely for
> maintainability.

## Quick Start

```bash
# Configure from preset (generates .config.{mk,kernel*,buildroot})
make configure SYSTEM=configs/qemu-rv64.toml

# Full build (builds both the tiny shell and the Buildroot variants)
make build

# Or step-by-step:
make BITS=64 build_linux make_initramfs_buildroot install_initramfs_buildroot build_opensbi_with_kernel
make BITS=64 test_qemu_buildroot
```

## Fast Iteration After Editing a Preset

After the initial build, you only need to rebuild Buildroot when changing packages.
The **fastest path** uses QEMU's split-load mode (separate kernel + initramfs), which
avoids re-embedding the initramfs into the kernel and rebuilding OpenSBI:

```bash
# Edit configs/qemu-rv64.toml (change [buildroot.packages]), then:
make configure SYSTEM=configs/qemu-rv64.toml   # regenerate .config.buildroot
make BITS=64 update_buildroot              # incremental Buildroot rebuild only
make BITS=64 test_qemu_kernel_buildroot    # boot with separate kernel + initramfs
```

If you need the all-in-one `fw_payload.bin` (for `test_qemu_buildroot` or Spike):

```bash
make BITS=32 update_buildroot_full         # Buildroot + re-embed initramfs + OpenSBI
make BITS=32 test_qemu_buildroot
```

For a completely clean Buildroot rebuild (e.g. after removing packages):

```bash
make BITS=32 make_initramfs_buildroot_clean
```

> **Incremental vs clean rebuild:** `make_initramfs_buildroot` is incremental — it only
> rebuilds packages that changed. This is much faster but may leave stale files when
> *removing* packages. Use `make_initramfs_buildroot_clean` for a guaranteed-clean rootfs.

## Customising Packages

Package selection is defined in the TOML preset file under `[buildroot.packages]`.
Running `make configure` generates `.config.buildroot` from those declarations.

Example preset (`configs/qemu-rv64.toml`):

```toml
[buildroot.packages]
include = [
    "openssh",
    "wget",
    "strace",
    "htop",
    "lsof",
    "file",
    "tree",
]
```

The generated `.config.buildroot` is a Kconfig fragment appended on
top of Buildroot's `qemu_riscv{32,64}_virt_defconfig`. It controls:

- **Output format** — cpio + gzip/zstd
- **Extra packages** — mapped from the `include` list
- **Shell** — optionally set via `[buildroot.packages] shell = "bash"`
- **Root password** — optionally set via `root_password = "root"`

To add or remove packages, edit the TOML preset, then rebuild:

```bash
make configure SYSTEM=configs/qemu-rv64.toml   # regenerate config
make BITS=64 update_buildroot                   # fast incremental path
```

### FPU / ABI Note

The two variants use different kernel configurations generated from the TOML preset:

- `.config.kernel.minimal` disables `CONFIG_FPU` (kernel ISA `imac`) — used by the tiny shell kernel build.
- `.config.kernel.buildroot` enables `CONFIG_FPU` (kernel ISA `imafd`) — applied by
  `package_buildroot` when assembling the Buildroot release, because Buildroot's default
  toolchain targets the hard-float `lp64d` / `ilp32d` ABI. The tiny shell initramfs
  is unaffected and stays FPU-free.

## Large Rootfs and Memory Limits

When adding large packages (e.g. `BR2_PACKAGE_PYTHON3=y`), the compressed
initramfs can grow to 40–55 MB. Because `install_initramfs` **embeds** the
cpio archive into the kernel Image, the resulting Image can reach 65–80 MB.
After QEMU loads this Image the kernel must decompress the initramfs into RAM,
requiring roughly **2–3× the compressed size** of additional memory.

With the default `QEMU_MEM=512` (512 MiB) the memory map looks like:

```
0x80000000  OpenSBI firmware      (~512 KB)
0x80200000  Kernel Image           ~70 MB (with embedded initramfs)
            Kernel data structures, page tables …
            initramfs decompression buffer  ~100-150 MB
            Userspace …
0x9FFFFFFF  RAM top (512 MB)
```

This can cause an out-of-memory kernel panic or an incomplete rootfs.

### Recommended: Split-Load Mode

Keep the kernel and initramfs as separate files so the kernel Image stays small
(~10 MB) and QEMU loads the cpio archive directly without duplicating it. This
is also faster to iterate because neither the kernel nor OpenSBI needs to be
rebuilt after a Buildroot change:

```bash
make BITS=64 update_buildroot                           # incremental Buildroot rebuild
make BITS=64 QEMU_MEM=1024 test_qemu_kernel_buildroot  # split-load, 1 GiB RAM
```

### Alternative: Increase QEMU Memory

If you must use the all-in-one `fw_payload.bin` boot path, increase QEMU memory:

```bash
make BITS=64 QEMU_MEM=1024 update_buildroot_full
make BITS=64 QEMU_MEM=1024 test_qemu_buildroot
```

## Build Targets Reference

| Target                           | Description                                                                                    |
| -------------------------------- | ---------------------------------------------------------------------------------------------- |
| `make_initramfs_buildroot`       | Build Buildroot rootfs (incremental) -> `initramfs$(BITS)-buildroot.cpio.gz`                   |
| `make_initramfs_buildroot_clean` | Full clean Buildroot rebuild (`distclean` first — slow but guaranteed clean)                   |
| `install_initramfs_buildroot`    | Embed Buildroot cpio into kernel Image (`CONFIG_INITRAMFS_SOURCE`)                             |
| `update_buildroot`               | Incremental Buildroot rebuild only (fastest iteration for package changes)                     |
| `update_buildroot_full`          | Buildroot rebuild + re-embed initramfs into kernel + rebuild OpenSBI                           |
| `package_buildroot`              | Bundle Buildroot artifacts into `dist/linux-riscv-rv$(BITS)-<preset>-buildroot-v*.tar.gz`      |
| `clean_buildroot`                | Remove Buildroot clone(s) (`buildroot32/`, `buildroot64/`)                                     |

## Output Paths

Buildroot initramfs outputs are separate from the tiny shell initramfs, so both
can coexist without overwriting each other:

| Path                            | Description                 |
| ------------------------------- | --------------------------- |
| `initramfs32.cpio.gz`           | Tiny shell initramfs (RV32) |
| `initramfs32-buildroot.cpio.gz` | Buildroot initramfs (RV32)  |
| `initramfs64.cpio.gz`           | Tiny shell initramfs (RV64) |
| `initramfs64-buildroot.cpio.gz` | Buildroot initramfs (RV64)  |

### Packaging

Release tarballs for the two variants are named distinctly; the `<preset>` component
comes from the configured `SYSTEM_PRESET` (set by `make configure`):

```bash
# Package tiny shell initramfs
make BITS=32 package            # -> dist/linux-riscv-rv32-<preset>-v<ver>.tar.gz

# Package Buildroot variant
make BITS=32 package_buildroot  # -> dist/linux-riscv-rv32-<preset>-buildroot-v<ver>.tar.gz

# Package both variants for the current BITS
make package_all
```
