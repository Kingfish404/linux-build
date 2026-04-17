# linux-build

Scripts and Makefiles for building a minimal RISC-V Linux system, including:

- Linux kernel image (`arch/riscv/boot/Image`) and kernel ELF (`vmlinux`)
- A minimal initramfs with a bare `init_loop` ELF (minimal) or a full Buildroot rootfs
- OpenSBI firmware, optionally with the kernel image embedded as `FW_PAYLOAD`
- Spike (riscv-isa-sim) simulator, built from source

Both **32-bit (RV32)** and **64-bit (RV64)** targets are supported and can coexist in the same tree.
Each preset produces **both** a minimal (`init_loop`) and a Buildroot variant from a single TOML
description, so you can boot either without reconfiguring.

Builds can be run from any of the following host architectures:

| Host    | 32-bit target                        | 64-bit target                         |
| ------- | ------------------------------------ | ------------------------------------- |
| x86-64  | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`)  |
| aarch64 | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`)  |
| riscv64 | cross-compile (`riscv64-linux-gnu-`) | **native** (no cross-compiler needed) |

## Prerequisites

Run the provided helper script to install all required host packages (Debian/Ubuntu):

```bash
bash scripts/install-deps.sh
```

See [scripts/install-deps.sh](scripts/install-deps.sh) for the full list of packages and comments explaining each group.

## Quick Start

### Declarative build (recommended)

The declarative build system reads a TOML preset file and drives the entire
pipeline automatically:

```bash
# Download sources (only needed once)
make linux opensbi

# Configure from preset, build, and test — one pipeline
make configure SYSTEM=configs/qemu-rv64.toml
make build
make test                              # boots the minimal variant
make test_qemu_kernel_buildroot        # boots the Buildroot variant (when present)
```

A single preset generates configuration for both variants:

- **minimal** — `init_loop`-only initramfs, FPU disabled (`imac` ISA)
- **buildroot** — full busybox userspace, FPU enabled (`imafd` ISA), optional SSH + packages

Available presets in [configs/](configs/):

| Preset             | Arch | Memory | Packages (Buildroot)                    | Notes                                 |
| ------------------ | ---- | ------ | --------------------------------------- | ------------------------------------- |
| `qemu-rv64.toml`   | RV64 | 512 MB | openssh, strace, htop, lsof, file, tree | Default full preset                   |
| `qemu-rv32.toml`   | RV32 | 512 MB | openssh, strace, htop, lsof, file, tree | Default full preset                   |
| `qemu-rv64-s.toml` | RV64 | 256 MB | openssh                                 | Smaller, minimal package set          |
| `qemu-rv32-s.toml` | RV32 | 256 MB | openssh                                 | Smaller, minimal package set          |
| `qemu-rv32-m.toml` | RV32 | 256 MB | openssh                                 | Keeps `Zba/Zbb/Zbc` bit-manip enabled |

See [Declarative Build System](#declarative-build-system) for the `system.toml`
format and how to create custom presets.

### Build and test with Spike

```bash
make build_spike                              # build Spike from source -> spike-build/bin/spike
make configure SYSTEM=configs/qemu-rv32.toml && make build
make BITS=32 test_spike                       # auto-uses spike-build/bin/spike if present
```

### Build all default presets (32 + 64, minimal only)

```bash
make build_all
```

## Declarative Build System

The declarative build system lets you describe a target system in a TOML file
and build it with `make configure` / `make build` / `make test`.

### How it works

```
configs/qemu-rv64.toml                                  ← WHAT: describe target system
        |  make configure SYSTEM=...
        v
.config.mk                ← Makefile variable overrides
.config.kernel            ← shared kernel config fragment
.config.kernel.minimal    ← minimal variant kernel config
.config.kernel.buildroot  ← buildroot variant kernel config
.config.buildroot         ← Buildroot package config
        |  make build
        v
build{32,64}/                         ← kernel artefacts
initramfs{32,64}.cpio.gz              ← minimal initramfs
initramfs{32,64}-buildroot.cpio.gz    ← buildroot initramfs (when [buildroot] defined)
opensbi-build{32,64}/                 ← firmware with embedded minimal kernel
        |  make test
        v
QEMU or Spike boots the minimal variant (use test_qemu_kernel_buildroot for buildroot)
```

`make configure SYSTEM=<file>` runs [scripts/gen-config.py](scripts/gen-config.py)
which parses the TOML file and writes the generated fragments listed above. The
top-level Makefile `-include`s `.config.mk` so variables like `BITS`,
`SYSTEM_LOADER`, `QEMU_MEM`, `SSH_PORT`, etc. are set automatically.

### Declarative targets

| Target                    | Description                                                                                     |
| ------------------------- | ----------------------------------------------------------------------------------------------- |
| `configure SYSTEM=<file>` | Parse TOML preset -> generate `.config.{mk,kernel,kernel.minimal,kernel.buildroot,buildroot}`   |
| `build`                   | Build kernel + minimal initramfs + OpenSBI; also build Buildroot if `.config.buildroot` present |
| `test`                    | Boot the minimal variant in emulator (`test_qemu_kernel` or `test_spike`)                       |
| `clean_config`            | Remove all generated `.config.*` files                                                          |

All existing imperative targets (`build_linux`, `test_qemu`, etc.) remain fully
usable and automatically pick up `.config.mk` overrides when present.

## Build Targets

### Source acquisition

| Target      | Description                                      |
| ----------- | ------------------------------------------------ |
| `linux`     | Download and extract Linux kernel source tarball |
| `opensbi`   | Clone OpenSBI source repository                  |
| `buildroot` | Clone Buildroot source into `buildroot$(BITS)/`  |
| `spike_src` | Clone Spike (riscv-isa-sim) source into `spike/` |

### Kernel

| Target        | Description                                                                                      |
| ------------- | ------------------------------------------------------------------------------------------------ |
| `build_linux` | Configure (`defconfig` + `.config.kernel` + `.config.kernel.minimal`) and build the Linux kernel |

### Initramfs

| Target                           | Description                                                                      |
| -------------------------------- | -------------------------------------------------------------------------------- |
| `build_init`                     | Compile `payload/init_loop.c` into `payload/init` (bare ELF, no libc)            |
| `make_initramfs_simple`          | Build `init_loop`-only initramfs -> `initramfs$(BITS).cpio.gz`                   |
| `make_initramfs_buildroot`       | Build Buildroot rootfs (incremental) -> `initramfs$(BITS)-buildroot.cpio.gz`     |
| `make_initramfs_buildroot_clean` | Full clean Buildroot rebuild (`distclean` first — slow but guaranteed clean)     |
| `install_initramfs`              | Set `CONFIG_INITRAMFS_SOURCE` to the minimal cpio and rebuild the kernel Image   |
| `install_initramfs_buildroot`    | Set `CONFIG_INITRAMFS_SOURCE` to the Buildroot cpio and rebuild the kernel Image |
| `update_buildroot`               | Incremental Buildroot rebuild only (fastest iteration for package changes)       |
| `update_buildroot_full`          | Buildroot rebuild + re-embed initramfs into kernel + rebuild OpenSBI             |

### Firmware

| Target                      | Description                                                 |
| --------------------------- | ----------------------------------------------------------- |
| `build_opensbi`             | Build OpenSBI generic platform firmware (no kernel payload) |
| `build_opensbi_with_kernel` | Build OpenSBI with kernel `Image` embedded as `FW_PAYLOAD`  |
| `build_spike`               | Build Spike simulator from source into `spike-build/`       |

### Test

| Target                       | Description                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| `test_qemu`                  | Boot `fw_payload.bin` (OpenSBI + minimal kernel embedded) in QEMU                         |
| `test_qemu_kernel`           | Boot `fw_dynamic.bin` + separate kernel Image + minimal initramfs in QEMU                 |
| `test_qemu_buildroot`        | Like `test_qemu` but adds virtio-net + SSH forwarding (requires Buildroot embedded)       |
| `test_qemu_kernel_buildroot` | Like `test_qemu_kernel` but uses the Buildroot initramfs + SSH forwarding                 |
| `test_spike`                 | Boot `fw_payload.elf` in Spike (`spike-build/bin/spike` if built, else `spike` from PATH) |

### Package & release

| Target              | Description                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `package`           | Bundle rv$(BITS) minimal artifacts into `dist/linux-riscv-rv$(BITS)-<preset>-v*.tar.gz`             |
| `package_buildroot` | Bundle rv$(BITS) Buildroot artifacts into `dist/linux-riscv-rv$(BITS)-<preset>-buildroot-v*.tar.gz` |
| `package_all`       | Build minimal + buildroot tarballs for the current `BITS`                                           |
| `github_release`    | Create a GitHub Release and upload all tarballs in `dist/` (requires `gh` CLI)                      |
| `clean_packages`    | Remove `dist/` directory                                                                            |

> The `<preset>` component is taken from `SYSTEM_PRESET` in `.config.mk` (set by
> `make configure`); it is omitted from the tarball name if no preset is configured.

### Batch / housekeeping

| Target            | Description                                                          |
| ----------------- | -------------------------------------------------------------------- |
| `build_all`       | Build Linux + minimal initramfs + OpenSBI for both 32 and 64 bit     |
| `clean`           | Remove kernel, initramfs, opensbi, and payload build artefacts       |
| `clean_buildroot` | Remove Buildroot clone(s) (`buildroot32/`, `buildroot64/`)           |
| `clean_spike`     | Remove Spike source and build directories (`spike/`, `spike-build/`) |
| `clean_config`    | Remove generated `.config.*` files                                   |

## Variables

| Variable        | Default                 | Description                                                        |
| --------------- | ----------------------- | ------------------------------------------------------------------ |
| `BITS`          | `32`                    | Target bitness. Normally set by `make configure` via `.config.mk`. |
| `CROSS_COMPILE` | auto                    | Cross-compiler prefix, e.g. `riscv64-linux-gnu-`                   |
| `QEMU_MEM`      | `512`                   | QEMU guest RAM in MiB (overridden by preset `[boot].memory`)       |
| `QEMU_TIMEOUT`  | *(unset)*               | Auto-exit QEMU after this many seconds (uses `timeout(1)`)         |
| `SYSTEM`        | *(unset)*               | Path to system.toml preset for `make configure`                    |
| `SPIKE_MEM`     | `512`                   | Spike guest RAM in MiB                                             |
| `SSH_PORT`      | `2222`                  | Host port forwarded to guest port 22 (Buildroot QEMU targets only) |
| `SHARE_DIR`     | *(unset)*               | Host directory to share via 9P (Buildroot QEMU targets only)       |
| `SHARE_RO`      | *(unset)*               | Set to `1` to mount the 9P share read-only (prevents guest writes) |
| `TAG`           | `rv-v$(KERNEL_VERSION)` | Git tag for `github_release`                                       |

`CROSS_COMPILE` auto-detection rules:
- `BITS=32`: always `riscv64-linux-gnu-` regardless of host.
- `BITS=64` on riscv64 host: empty (native build).
- `BITS=64` on any other host: `riscv64-linux-gnu-`.

Override example (testing):
```bash
make BITS=64 test_qemu                                        # re-test 64-bit build
make BITS=64 CROSS_COMPILE=riscv64-unknown-linux-gnu- build_linux  # advanced: custom toolchain
```

### QEMU networking

See [docs/qemu-networking.md](docs/qemu-networking.md) for SSH access, 9P host directory
sharing, and tips on user-mode networking.

### Kernel and firmware config

See [docs/kernel-config.md](docs/kernel-config.md) for ISA selection, `CONFIG_FPU` handling,
and OpenSBI / init payload build settings.

### Buildroot customisation

All Buildroot-related variables and targets are defined in
[scripts/buildroot.mk](scripts/buildroot.mk) and included by the top-level `Makefile`,
so they can be invoked with `make` as usual (e.g. `make BITS=32 update_buildroot`).

See [docs/buildroot.md](docs/buildroot.md) for package management, incremental rebuild
workflow, and large-rootfs memory troubleshooting.

## Output Artefacts

32-bit and 64-bit outputs are fully isolated in separate directories and can coexist.
Minimal and Buildroot initramfs archives use distinct filenames so both can exist simultaneously.

| Path                                                       | Description                                |
| ---------------------------------------------------------- | ------------------------------------------ |
| `build32/arch/riscv/boot/Image`                            | RV32 uncompressed kernel image             |
| `build32/vmlinux`                                          | RV32 kernel ELF (with debug symbols)       |
| `build64/arch/riscv/boot/Image`                            | RV64 uncompressed kernel image             |
| `build64/vmlinux`                                          | RV64 kernel ELF (with debug symbols)       |
| `initramfs32/`                                             | RV32 initramfs staging directory (minimal) |
| `initramfs32.cpio.gz`                                      | RV32 minimal initramfs archive             |
| `initramfs32-buildroot.cpio.gz`                            | RV32 Buildroot initramfs archive           |
| `initramfs64/`                                             | RV64 initramfs staging directory (minimal) |
| `initramfs64.cpio.gz`                                      | RV64 minimal initramfs archive             |
| `initramfs64-buildroot.cpio.gz`                            | RV64 Buildroot initramfs archive           |
| `opensbi-build32/platform/generic/firmware/fw_payload.elf` | RV32 OpenSBI + kernel ELF                  |
| `opensbi-build32/platform/generic/firmware/fw_payload.bin` | RV32 OpenSBI + kernel binary               |
| `opensbi-build32/platform/generic/firmware/fw_dynamic.bin` | RV32 OpenSBI dynamic firmware              |
| `opensbi-build64/platform/generic/firmware/fw_payload.elf` | RV64 OpenSBI + kernel ELF                  |
| `opensbi-build64/platform/generic/firmware/fw_payload.bin` | RV64 OpenSBI + kernel binary               |
| `opensbi-build64/platform/generic/firmware/fw_dynamic.bin` | RV64 OpenSBI dynamic firmware              |
| `spike-build/bin/spike`                                    | Locally-built Spike RISC-V ISA simulator   |
| `dist/linux-riscv-rv*-<preset>-v*.tar.gz`                  | Minimal initramfs release tarballs         |
| `dist/linux-riscv-rv*-<preset>-buildroot-v*.tar.gz`        | Buildroot initramfs release tarballs       |

## Project Structure

```
.
├── Makefile                    # Top-level build orchestration (includes scripts/buildroot.mk)
├── README.md                   # This file
├── configs/
|   ├── qemu-rv64.toml          # Preset: RV64, full Buildroot toolbox (default)
|   ├── qemu-rv32.toml          # Preset: RV32, full Buildroot toolbox (default)
|   ├── qemu-rv64-s.toml        # Preset: RV64, smaller (256 MB, openssh only)
|   ├── qemu-rv32-s.toml        # Preset: RV32, smaller (256 MB, openssh only)
|   └── qemu-rv32-m.toml        # Preset: RV32, keeps Zba/Zbb/Zbc bit-manip enabled
├── docs/
|   ├── buildroot.md            # Buildroot customisation, iteration workflow, memory limits
|   ├── kernel-config.md        # Kernel ISA tweaks, OpenSBI settings, init payload
|   ├── qemu-networking.md      # QEMU networking, SSH, 9P host sharing
|   └── roadmap.md              # Development roadmap toward a minimal RISC-V Linux distribution
├── scripts/
|   ├── buildroot.mk            # Buildroot variables, targets, and packaging (included by Makefile)
|   ├── gen-config.py           # TOML -> .config.{mk,kernel,kernel.minimal,kernel.buildroot,buildroot}
|   ├── gen-package-readme.sh   # Generate README.md for release tarballs
|   └── install-deps.sh         # Install all host build dependencies (Debian/Ubuntu)
└── payload/
    ├── Makefile                # Builds init_loop ELF (supports BITS=32 and BITS=64)
    └── init_loop.c             # Minimal init process (infinite loop, no libc)
```

## References

- [Linux Kernel][linux] — the operating system kernel built and booted by this project.
- [OpenSBI][opensbi] — RISC-V Supervisor Binary Interface firmware used as the bootloader.
- [QEMU][qemu] — machine emulator used for `test_qemu` / `test_qemu_kernel` / `test_qemu_buildroot` targets.
- [Spike (riscv-isa-sim)][spike] — RISC-V ISA reference simulator used for `test_spike`.
- [Buildroot][buildroot] — embedded Linux build system used for the full rootfs initramfs.
- [RISC-V GNU Toolchain][riscv-gnu-toolchain] — cross-compiler toolchain (`riscv64-linux-gnu-`) used for all cross-compilation.

[linux]: https://www.kernel.org/
[opensbi]: https://github.com/riscv-software-src/opensbi
[qemu]: https://www.qemu.org/
[spike]: https://github.com/riscv-software-src/riscv-isa-sim
[buildroot]: https://buildroot.org/
[riscv-gnu-toolchain]: https://github.com/riscv-collab/riscv-gnu-toolchain
# linux-build

Scripts and Makefiles for building a minimal RISC-V Linux system, including:

- Linux kernel image (`arch/riscv/boot/Image`) and kernel ELF (`vmlinux`)
- A minimal initramfs with a bare `init_loop` ELF (simple) or a full Buildroot rootfs (complex)
- OpenSBI firmware, optionally with the kernel image embedded as `FW_PAYLOAD`
- Spike (riscv-isa-sim) simulator, built from source

Both **32-bit (RV32)** and **64-bit (RV64)** targets are supported and can coexist in the same tree.  
Builds can be run from any of the following host architectures:

| Host    | 32-bit target                        | 64-bit target                         |
| ------- | ------------------------------------ | ------------------------------------- |
| x86-64  | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`)  |
| aarch64 | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`)  |
| riscv64 | cross-compile (`riscv64-linux-gnu-`) | **native** (no cross-compiler needed) |

## Prerequisites

Run the provided helper script to install all required host packages (Debian/Ubuntu):

```bash
bash scripts/install-deps.sh
```

See [scripts/install-deps.sh](scripts/install-deps.sh) for the full list of packages and comments explaining each group.

## Quick Start

### Declarative build (recommended)

The declarative build system reads a TOML preset file and drives the entire
pipeline automatically:

```bash
# Download sources (only needed once)
make linux opensbi

# Configure from preset, build, and test — one pipeline
make configure SYSTEM=configs/qemu-rv64-buildroot.toml
make build
make test
```

Available presets in `configs/`:

| Preset                     | Arch | Init    | Description               |
| -------------------------- | ---- | ------- | ------------------------- |
| `qemu-rv64-minimal.toml`   | RV64 | loop    | Minimal initramfs, no FPU |
| `qemu-rv32-minimal.toml`   | RV32 | loop    | Minimal initramfs, no FPU |
| `qemu-rv64-buildroot.toml` | RV64 | busybox | Buildroot + SSH + tools   |
| `qemu-rv32-buildroot.toml` | RV32 | busybox | Buildroot + SSH + tools   |

See [Declarative Build System](#declarative-build-system) for details on the
`system.toml` format and how to create custom presets.

### Simple initramfs (init_loop only)

> Prefer the declarative workflow above. These commands are for manual /
> advanced use where you want fine-grained control.

```bash
# Download sources (only needed once)
make linux opensbi

# Build (use declarative 'make configure && make build' instead)
make configure SYSTEM=configs/qemu-rv32-minimal.toml && make build

# Quick re-test with explicit bitness
make BITS=32 test_qemu
make BITS=64 test_qemu
```

### Buildroot initramfs (full userspace)

```bash
# Declarative (recommended)
make configure SYSTEM=configs/qemu-rv64-buildroot.toml && make build

# Quick re-test with explicit bitness
make BITS=64 test_qemu_buildroot
make BITS=32 test_qemu_buildroot
```

After the initial build, use `update_buildroot` for fast incremental rebuilds — see
[docs/buildroot.md](docs/buildroot.md) for the full iteration workflow, package customisation,
and memory-limit troubleshooting.

### Build and test with Spike

```bash
make build_spike                              # build Spike from source -> spike-build/bin/spike
make configure SYSTEM=configs/qemu-rv32-minimal.toml && make build
make BITS=32 test_spike                       # auto-uses spike-build/bin/spike if present
```

### Build everything (32 + 64, simple initramfs)

```bash
make build_all
```

## Declarative Build System

The declarative build system lets you describe a target system in a TOML file
and build it with `make configure` / `make build` / `make test`.

### How it works

```
configs/qemu-rv64-buildroot.toml          # ← WHAT: describe target system
        ↓  make configure
.config.mk  .config.kernel  .config.buildroot   # ← generated build configs
        ↓  make build
build64/  initramfs64-buildroot.cpio.gz  opensbi-build64/   # ← artifacts
        ↓  make test
QEMU boots with SSH + networking                            # ← running system
```

`make configure SYSTEM=<file>` runs `scripts/gen-config.py` which reads the TOML
file and generates:

| Generated file      | Purpose                                          |
| ------------------- | ------------------------------------------------ |
| `.config.mk`        | Makefile variable overrides (`-include`d at top) |
| `.config.kernel`    | Kernel Kconfig fragment (applied by `build`)     |
| `.config.buildroot` | Buildroot config fragment (when init = busybox)  |

### Declarative targets

| Target                    | Description                                                          |
| ------------------------- | -------------------------------------------------------------------- |
| `configure SYSTEM=<file>` | Parse TOML preset -> generate `.config.{mk,kernel,buildroot}`        |
| `build`                   | Full pipeline: kernel -> rootfs -> firmware (driven by `.config.mk`) |
| `test`                    | Boot in emulator per config (QEMU or Spike)                          |
| `clean_config`            | Remove generated `.config.*` files                                   |

All existing imperative targets (`build_linux`, `test_qemu`, etc.) remain fully
usable and automatically pick up `.config.mk` overrides when present.

## Build Targets

### Source acquisition

| Target      | Description                                      |
| ----------- | ------------------------------------------------ |
| `linux`     | Download and extract Linux kernel source tarball |
| `opensbi`   | Clone OpenSBI source repository                  |
| `buildroot` | Clone Buildroot source into `buildroot$(BITS)/`  |
| `spike_src` | Clone Spike (riscv-isa-sim) source into `spike/` |

### Kernel

| Target        | Description                                                 |
| ------------- | ----------------------------------------------------------- |
| `build_linux` | Configure (`defconfig` + tweaks) and build the Linux kernel |

### Initramfs

| Target                           | Description                                                                                           |
| -------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `build_init`                     | Compile `payload/init_loop.c` into `payload/init` (bare ELF, no libc)                                 |
| `make_initramfs_simple`          | Build `init_loop`-only initramfs -> `initramfs$(BITS).cpio.gz`                                        |
| `make_initramfs_buildroot`       | Build Buildroot rootfs (incremental) -> `initramfs$(BITS)-buildroot.cpio.gz`; re-enables `CONFIG_FPU` |
| `make_initramfs_buildroot_clean` | Full clean Buildroot rebuild (`distclean` first — slow but guaranteed clean)                          |
| `install_initramfs`              | Set `CONFIG_INITRAMFS_SOURCE` to simple initramfs cpio and rebuild kernel Image                       |
| `install_initramfs_buildroot`    | Set `CONFIG_INITRAMFS_SOURCE` to Buildroot cpio and rebuild kernel Image                              |
| `update_buildroot`               | Incremental Buildroot rebuild only (fastest iteration for package changes)                            |
| `update_buildroot_full`          | Buildroot rebuild + re-embed initramfs into kernel + rebuild OpenSBI                                  |

### Firmware

| Target                      | Description                                                 |
| --------------------------- | ----------------------------------------------------------- |
| `build_opensbi`             | Build OpenSBI generic platform firmware (no kernel payload) |
| `build_opensbi_with_kernel` | Build OpenSBI with kernel `Image` embedded as `FW_PAYLOAD`  |
| `build_spike`               | Build Spike simulator from source into `spike-build/`       |

### Test

| Target                       | Description                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| `test_qemu`                  | Boot `fw_payload.bin` (all-in-one firmware) in QEMU                                       |
| `test_qemu_kernel`           | Boot `fw_dynamic.bin` + separate kernel Image + initramfs in QEMU                         |
| `test_qemu_buildroot`        | Like `test_qemu` but adds virtio-net + SSH forwarding for Buildroot                       |
| `test_qemu_kernel_buildroot` | Like `test_qemu_kernel` but adds virtio-net + SSH forwarding for Buildroot                |
| `test_spike`                 | Boot `fw_payload.elf` in Spike (`spike-build/bin/spike` if built, else `spike` from PATH) |

### Package & release

| Target              | Description                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `package`           | Bundle rv$(BITS) simple initramfs artifacts into `dist/linux-riscv-rv$(BITS)-v*.tar.gz`    |
| `package_buildroot` | Bundle rv$(BITS) Buildroot artifacts into `dist/linux-riscv-rv$(BITS)-buildroot-v*.tar.gz` |
| `package_all`       | Build all tarballs (simple + buildroot, 32 + 64)                                           |
| `github_release`    | Create a GitHub Release and upload tarballs (requires `gh` CLI)                            |
| `clean_packages`    | Remove `dist/` directory                                                                   |

### Batch / housekeeping

| Target            | Description                                                          |
| ----------------- | -------------------------------------------------------------------- |
| `build_all`       | Build Linux + simple initramfs + OpenSBI for both 32 and 64 bit      |
| `clean`           | Remove kernel, initramfs, opensbi, and payload build artefacts       |
| `clean_buildroot` | Remove Buildroot clone(s) (`buildroot32/`, `buildroot64/`)           |
| `clean_spike`     | Remove Spike source and build directories (`spike/`, `spike-build/`) |

## Variables

| Variable        | Default              | Description                                                        |
| --------------- | -------------------- | ------------------------------------------------------------------ |
| `BITS`          | `32`                 | Internal: set by `make configure`.                                 |
| `CROSS_COMPILE` | auto                 | Cross-compiler prefix, e.g. `riscv64-linux-gnu-`                   |
| `QEMU_MEM`      | `512`                | QEMU guest RAM in MiB (simple initramfs targets)                   |
| `QEMU_TIMEOUT`  | *(unset)*            | Auto-exit QEMU after this many seconds (uses `timeout(1)`)         |
| `SYSTEM`        | *(unset)*            | Path to system.toml preset for `make configure`                    |
| `SPIKE_MEM`     | `512`                | Spike guest RAM in MiB                                             |
| `SSH_PORT`      | `2222`               | Host port forwarded to guest port 22 (buildroot QEMU targets only) |
| `SHARE_DIR`     | *(unset)*            | Host directory to share via 9P (buildroot QEMU targets only)       |
| `SHARE_RO`      | *(unset)*            | Set to `1` to mount 9P share read-only (prevents guest writes)     |
| `TAG`           | `v$(KERNEL_VERSION)` | Git tag for `github_release`                                       |

`CROSS_COMPILE` auto-detection rules:
- `BITS=32`: always `riscv64-linux-gnu-` regardless of host.
- `BITS=64` on riscv64 host: empty (native build).
- `BITS=64` on any other host: `riscv64-linux-gnu-`.

Override example (testing):
```bash
make BITS=64 test_qemu                                        # re-test 64-bit build
make BITS=64 CROSS_COMPILE=riscv64-unknown-linux-gnu- build_linux  # advanced: custom toolchain
```

### QEMU networking

See [docs/qemu-networking.md](docs/qemu-networking.md) for SSH access, 9P host directory
sharing, and tips on user-mode networking.

### Kernel and firmware config

See [docs/kernel-config.md](docs/kernel-config.md) for ISA selection, `CONFIG_FPU` handling,
and OpenSBI / init payload build settings.

### Buildroot customisation

All Buildroot-related variables and targets are defined in
[`scripts/buildroot.mk`](scripts/buildroot.mk) and included by the top-level `Makefile`,
so they can be invoked with `make` as usual (e.g. `make BITS=32 update_buildroot`).

See [docs/buildroot.md](docs/buildroot.md) for package management, incremental rebuild
workflow, and large-rootfs memory troubleshooting.

## Output Artefacts

32-bit and 64-bit outputs are fully isolated in separate directories and can coexist.
Simple and Buildroot initramfs archives use distinct filenames so both can exist simultaneously.

| Path                                                       | Description                               |
| ---------------------------------------------------------- | ----------------------------------------- |
| `build32/arch/riscv/boot/Image`                            | RV32 uncompressed kernel image            |
| `build32/vmlinux`                                          | RV32 kernel ELF (with debug symbols)      |
| `build64/arch/riscv/boot/Image`                            | RV64 uncompressed kernel image            |
| `build64/vmlinux`                                          | RV64 kernel ELF (with debug symbols)      |
| `initramfs32/`                                             | RV32 initramfs staging directory (simple) |
| `initramfs32.cpio.gz`                                      | RV32 simple initramfs archive             |
| `initramfs32-buildroot.cpio.gz`                            | RV32 Buildroot initramfs archive          |
| `initramfs64/`                                             | RV64 initramfs staging directory (simple) |
| `initramfs64.cpio.gz`                                      | RV64 simple initramfs archive             |
| `initramfs64-buildroot.cpio.gz`                            | RV64 Buildroot initramfs archive          |
| `opensbi-build32/platform/generic/firmware/fw_payload.elf` | RV32 OpenSBI + kernel ELF                 |
| `opensbi-build32/platform/generic/firmware/fw_payload.bin` | RV32 OpenSBI + kernel binary              |
| `opensbi-build32/platform/generic/firmware/fw_dynamic.bin` | RV32 OpenSBI dynamic firmware             |
| `opensbi-build64/platform/generic/firmware/fw_payload.elf` | RV64 OpenSBI + kernel ELF                 |
| `opensbi-build64/platform/generic/firmware/fw_payload.bin` | RV64 OpenSBI + kernel binary              |
| `opensbi-build64/platform/generic/firmware/fw_dynamic.bin` | RV64 OpenSBI dynamic firmware             |
| `spike-build/bin/spike`                                    | Locally-built Spike RISC-V ISA simulator  |
| `dist/linux-riscv-rv*-v*.tar.gz`                           | Simple initramfs release tarballs         |
| `dist/linux-riscv-rv*-buildroot-v*.tar.gz`                 | Buildroot initramfs release tarballs      |

## Project Structure

```
.
├── Makefile                    # Top-level build orchestration (includes scripts/buildroot.mk)
├── README.md                   # This file
├── configs/
|   ├── qemu-rv64-minimal.toml  # Preset: RV64 minimal initramfs
|   ├── qemu-rv32-minimal.toml  # Preset: RV32 minimal initramfs
|   ├── qemu-rv64-buildroot.toml# Preset: RV64 Buildroot + SSH + tools
|   └── qemu-rv32-buildroot.toml# Preset: RV32 Buildroot + SSH + tools
├── docs/
|   ├── buildroot.md            # Buildroot customisation, iteration workflow, memory limits
|   ├── kernel-config.md        # Kernel ISA tweaks, OpenSBI settings, init payload
|   ├── qemu-networking.md      # QEMU networking, SSH, 9P host sharing
|   └── roadmap.md              # Development roadmap toward a minimal RISC-V Linux distribution
├── scripts/
|   ├── buildroot.mk            # Buildroot variables, targets, and packaging (included by Makefile)
|   ├── gen-config.py           # TOML -> .config.{mk,kernel,buildroot} generator
|   ├── gen-package-readme.sh   # Generate README.md for release tarballs
|   └── install-deps.sh         # Install all host build dependencies (Debian/Ubuntu)
└── payload/
    ├── Makefile                # Builds init_loop ELF (supports BITS=32 and BITS=64)
    └── init_loop.c             # Minimal init process (infinite loop, no libc)
```

## References

- [Linux Kernel][linux] — the operating system kernel built and booted by this project.
- [OpenSBI][opensbi] — RISC-V Supervisor Binary Interface firmware used as the bootloader.
- [QEMU][qemu] — machine emulator used for `test_qemu` / `test_qemu_kernel` / `test_qemu_buildroot` targets.
- [Spike (riscv-isa-sim)][spike] — RISC-V ISA reference simulator used for `test_spike`.
- [Buildroot][buildroot] — embedded Linux build system used for the full rootfs initramfs.
- [RISC-V GNU Toolchain][riscv-gnu-toolchain] — cross-compiler toolchain (`riscv64-linux-gnu-`) used for all cross-compilation.

[linux]: https://www.kernel.org/
[opensbi]: https://github.com/riscv-software-src/opensbi
[qemu]: https://www.qemu.org/
[spike]: https://github.com/riscv-software-src/riscv-isa-sim
[buildroot]: https://buildroot.org/
[riscv-gnu-toolchain]: https://github.com/riscv-collab/riscv-gnu-toolchain
