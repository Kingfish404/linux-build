# Roadmap: Toward a Minimal Modern RISC-V Linux Distribution

This document describes the gap between the current project state and a minimal,
modern, technically progressive RISC-V Linux distribution, along with the phased
development plan to close that gap.

## Design Philosophy

| Principle                          | Description                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Modern defaults**                | Prefer actively-maintained, well-designed software over legacy incumbents                                     |
| **musl + static-linking friendly** | Reduce runtime dependencies, minimise attack surface                                                          |
| **Immutable infrastructure**       | Read-only rootfs, state separated into a dedicated data partition; `system-unlock` escape hatch for debugging |
| **Declarative & reproducible**     | Builds and system configuration should be deterministic and auditable                                         |
| **Security by default**            | Landlock, seccomp-bpf, dm-verity — not afterthoughts but defaults                                             |
| **Pragmatism over dogma**          | Choose battle-tested technology; avoid out-of-tree or unmaintained code                                       |

## Current State Assessment

The project is a **RISC-V Linux build toolkit** positioned between a bare-metal
kernel boot experiment and a simple distribution.

| Component           | Current State                                                   | Maturity |
| ------------------- | --------------------------------------------------------------- | -------- |
| **Kernel**          | Linux 6.18.15, RV32/RV64 dual-arch, minimal ISA config          | ★★★★☆    |
| **Firmware / Boot** | OpenSBI (fw_payload / fw_dynamic), QEMU/Spike only              | ★★★☆☆    |
| **Root filesystem** | initramfs-only: ① bare `init_loop` dead-loop ② Buildroot rootfs | ★★☆☆☆    |
| **Userspace**       | Buildroot provides busybox + openssh/htop/strace                | ★★☆☆☆    |
| **Networking**      | QEMU NAT + SSH forwarding + 9P sharing                          | ★★★☆☆    |
| **Build system**    | Makefile, well organised, incremental builds, GitHub Release    | ★★★★☆    |
| **Documentation**   | Developer-oriented, covers build/config/debug                   | ★★★★☆    |

## Core Gaps

| #   | Gap                                 | Severity    | Modern Solution                                                        |
| --- | ----------------------------------- | ----------- | ---------------------------------------------------------------------- |
| 1   | **No persistent root filesystem**   | 🔴 Critical  | btrfs disk image, read-only rootfs subvolume + writable data subvolume |
| 2   | **No real init system**             | 🔴 Critical  | dinit — dependency-graph-driven, lightweight, used by Chimera Linux    |
| 3   | **No package manager**              | 🔴 Critical  | apk-tools 3.x — atomic transactions, SHA-256, musl-native              |
| 4   | **No bootable disk image**          | 🔴 Critical  | GPT disk image (ESP + rootfs), U-Boot UEFI, EFISTUB kernel             |
| 5   | **No real hardware support**        | 🟡 Important | U-Boot boot chain, device tree customisation, board-level support      |
| 6   | **No kernel module infrastructure** | 🟡 Important | `CONFIG_MODULES=y`, depmod/modprobe (kmod), `/lib/modules/` hierarchy  |
| 7   | **No device management**            | 🟡 Important | mdevd (skarnet) — synchronous, zero-systemd-dependency device manager  |
| 8   | **No user/permission model**        | 🟡 Important | Minimal `/etc/passwd` + `/etc/shadow`, doas for privilege escalation   |
| 9   | **No system update mechanism**      | 🟡 Important | btrfs subvolume A/B + atomic switch + automatic rollback               |
| 10  | **No installer**                    | 🟠 Useful    | SD card flash script, later TUI installer                              |
| 11  | **No logging**                      | 🟠 Useful    | syslog-ng — structured logging, zstd-compressed rotation               |
| 12  | **No CI/CD automated testing**      | 🟠 Useful    | GitHub Actions: build + QEMU smoke boot test                           |

## Bootable Disk Image: Gap Analysis

The most significant gap between the current project and a distribution that can
boot on real hardware (or via `qemu -drive`) is the absence of a disk image
pipeline. This section details every missing piece.

### Current Boot Chain (QEMU/Spike only)

```
OpenSBI (fw_payload / fw_dynamic)
  └→ Linux kernel Image (loaded by QEMU -bios / -kernel)
       └→ initramfs cpio.gz (RAM-only, no persistent storage)
            └→ init: dead-loop ELF  or  busybox (Buildroot)
```

- No disk image — rootfs exists only in RAM (initramfs)
- No bootloader — QEMU `-bios` flag directly loads firmware
- No UEFI support — no EFI System Partition, no EFISTUB
- No `switch_root` — init never transitions to a real root filesystem

### Target Boot Chain (real hardware / disk image)

```
OpenSBI (M-mode, ROM or SPI flash)
  └→ U-Boot SPL (optional, board-specific)
       └→ U-Boot (S-mode, EFI_LOADER=y)
            └→ EFI System Partition (FAT32)
                 └→ EFISTUB kernel Image  or  GRUB EFI
                      └→ root= on disk (ext4 / btrfs partition)
                           └→ dinit (PID 1) → services
```

### Missing Components

| Component             | What Is Needed                                                                                    | Severity    |
| --------------------- | ------------------------------------------------------------------------------------------------- | ----------- |
| U-Boot                | Cross-compile U-Boot for RISC-V with `CONFIG_EFI_LOADER=y`; add `make build_uboot` target         | 🔴 Critical  |
| GPT disk image        | Script to create GPT image: ESP (FAT32, ~256 MiB) + rootfs (ext4/btrfs) + optional data partition | 🔴 Critical  |
| ESP population        | Place `EFI/BOOT/BOOTRISCV64.EFI` (U-Boot or GRUB) and/or EFISTUB kernel Image into the FAT32 ESP  | 🔴 Critical  |
| Persistent rootfs     | Populate ext4/btrfs partition with Buildroot output (not cpio, actual directory tree)             | 🔴 Critical  |
| initramfs switch_root | Init script: mount rootfs → `fsck` → `switch_root /mnt/root /sbin/init`                           | 🔴 Critical  |
| Kernel config         | See table below                                                                                   | 🟡 Important |
| Device tree (real HW) | Board-specific `.dts`; U-Boot passes DTB to kernel via UEFI or appended                           | 🟡 Important |
| ISO generation        | `xorriso` / `grub-mkrescue` for UEFI-bootable `.iso`; primarily useful for optical/USB media      | 🟠 Useful    |

### Required Kernel Config Additions

| Config                      | Purpose                                                        |
| --------------------------- | -------------------------------------------------------------- |
| `CONFIG_EFI=y`              | UEFI runtime services support                                  |
| `CONFIG_EFI_STUB=y`         | Allow kernel Image to be loaded directly as an EFI application |
| `CONFIG_MODULES=y`          | Loadable kernel modules (essential for real hardware drivers)  |
| `CONFIG_EXT4_FS=y`          | ext4 root filesystem support                                   |
| `CONFIG_BTRFS_FS=y`         | btrfs root filesystem support (default target)                 |
| `CONFIG_VIRTIO_BLK=y`       | QEMU virtio block device (disk image boot in QEMU)             |
| `CONFIG_VIRTIO_NET=y`       | QEMU virtio network device                                     |
| `CONFIG_DEVTMPFS=y`         | Automatic `/dev` population                                    |
| `CONFIG_DEVTMPFS_MOUNT=y`   | Mount devtmpfs on `/dev` at boot                               |
| `CONFIG_AUTOFS_FS=y`        | Automount support (useful for removable media)                 |
| `CONFIG_VFAT_FS=y`          | FAT32 filesystem for reading the ESP                           |
| `CONFIG_NLS_CODEPAGE_437=y` | Code page for FAT                                              |
| `CONFIG_NLS_ISO8859_1=y`    | Character set for FAT                                          |

### Critical Path: Shortest Route to a Bootable Disk Image

```
Step 1  Compile U-Boot for RISC-V (EFI_LOADER=y)
        └→ new Makefile targets: uboot, build_uboot

Step 2  Kernel config: enable EFI_STUB + EXT4 + VIRTIO_BLK + MODULES + DEVTMPFS
        └→ extend gen-config.py to emit these for rootfs.type = "disk"

Step 3  Disk image generation script
        └→ scripts/gen-disk-image.sh (or Python):
           dd → sgdisk (GPT) → mkfs.fat (ESP) → mkfs.ext4 (rootfs)
           → mount & populate → umount
        └→ new Makefile target: make disk_image

Step 4  Populate ESP: kernel Image as EFISTUB  (EFI/BOOT/BOOTRISCV64.EFI)
        or place U-Boot EFI app + kernel beside it

Step 5  Populate rootfs partition with Buildroot directory tree
        (extract rootfs.tar instead of rootfs.cpio.gz)

Step 6  Write initramfs init or kernel cmdline root=/dev/vda2
        to mount the disk rootfs and switch_root

Step 7  QEMU verification:
        qemu-system-riscv64 -M virt -m 512M \
          -bios opensbi/fw_dynamic.bin \
          -drive file=disk.img,format=raw,id=hd0 \
          -device virtio-blk-device,drive=hd0 \
          -kernel Image  (or let U-Boot in ESP load it)

Step 8  Same disk.img can be dd'd to SD card for real RISC-V boards
```

### Mapping to Roadmap Phases

| Capability                           | Phase              | Task           | Status        |
| ------------------------------------ | ------------------ | -------------- | ------------- |
| U-Boot compilation + integration     | Phase 1 (promoted) | 1.0            | ❌ Not started |
| GPT disk image generation            | Phase 1            | 1.1            | ❌ Not started |
| Persistent root filesystem           | Phase 1            | 1.2 – 1.3      | ❌ Not started |
| initramfs with `switch_root`         | Phase 1            | 1.4            | ❌ Not started |
| Kernel config for disk boot          | Phase 1            | 1.1 (sub-task) | ❌ Not started |
| QEMU virtio-blk disk boot            | Phase 1            | 1.7            | ❌ Not started |
| dinit init system                    | Phase 2            | 2.1            | ❌ Not started |
| Kernel module support                | Phase 2            | 2.4            | ❌ Not started |
| Board-level BSP (VisionFive 2, etc.) | Phase 4            | 4.6 – 4.7      | ❌ Not started |
| SD card / NVMe installer             | Phase 4            | 4.8            | ❌ Not started |
| Downloadable `.img.zst` images       | Phase 5            | 5.4            | ❌ Not started |

## Technology Stack

### Verified Component Selections

Every component below has been checked for: actively maintained status, RISC-V support,
musl compatibility, and in-tree Linux kernel support (as of Linux 6.18, March 2026).

| Layer              | Component                                      | Why                                                                                                  |
| ------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **libc**           | musl                                           | 10x smaller than glibc, static-link friendly, Alpine/Chimera proven                                  |
| **Init**           | dinit                                          | C++, dependency graph, readiness notification, Chimera/eweOS default, Apache-2.0                     |
| **Device mgmt**    | mdevd + libudev-zero                           | skarnet synchronous device manager + udev-compat API, zero systemd deps                              |
| **Coreutils**      | busybox (initial) → uutils/coreutils (gradual) | uutils v0.6.0, 22.8k stars, CI has riscv64+musl build; busybox as fallback                           |
| **Shell**          | bash (interactive default) + dash (`/bin/sh`)  | POSIX compat mandatory for system scripts; nushell available as optional package                     |
| **Filesystem**     | btrfs (default) + ext4 (fallback)              | btrfs: in-kernel stable, COW, snapshots, zstd compression; ext4 fallback for SD-card/low-RAM targets |
| **Package mgmt**   | apk-tools 3.x                                  | C, musl-native (built for Alpine), atomic transactions, SHA-256 verification                         |
| **TLS/Crypto**     | OpenSSL 3.x                                    | Industry standard, best upstream ecosystem compat; Alpine switched back from LibreSSL (2023)         |
| **Networking**     | dhcpcd (wired) + iwd (WiFi, Phase 4)           | dhcpcd is C, lightweight; iwd deferred to hardware phase                                             |
| **DNS**            | unbound or stubby                              | C, native DoT support, no Go dependency                                                              |
| **Logging**        | syslog-ng                                      | Structured logging, zstd rotation, mature                                                            |
| **Privilege**      | doas                                           | OpenBSD project, C, minimal, well-audited                                                            |
| **Security**       | Landlock LSM + seccomp-bpf + dm-verity         | All in-kernel stable subsystems                                                                      |
| **Containers**     | crun (Phase 4)                                 | Pure C OCI runtime, Fedora/RHEL production use                                                       |
| **Compression**    | zstd everywhere                                | Kernel, initramfs, packages, btrfs transparent compression                                           |
| **Boot**           | OpenSBI → U-Boot (UEFI) → EFISTUB kernel       | Standard UEFI boot path for real hardware                                                            |
| **Rust CLI tools** | ripgrep, fd (Phase 2→4 gradual)                | Cross-compile verified; introduced incrementally via package repo                                    |

### Rejected or Deferred Selections

| Original Proposal                            | Status                 | Reason                                                                                                                                      |
| -------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **bcachefs**                                 | 🔴 Rejected             | Removed from Linux 6.18 kernel (Sept 2025). Now out-of-tree DKMS only — unacceptable risk for root filesystem                               |
| **nushell as default**                       | 🔴 Rejected as default  | Not POSIX-compatible; system scripts depend on `/bin/sh`. Available as optional package                                                     |
| **Custom content-addressed package manager** | 🔴 Rejected             | 6-12 month dev cycle, highest failure risk for distro projects. apk-tools 3.x provides atomic transactions already                          |
| **podman**                                   | 🟡 Deferred to Phase 4+ | Go runtime + musl cross-compile unreliable on RISC-V                                                                                        |
| **dnscrypt-proxy**                           | 🔴 Rejected             | Go, musl cross-compile issues. Replaced by unbound/stubby (C)                                                                               |
| **LibreSSL**                                 | 🔴 Rejected             | Alpine Linux switched back to OpenSSL in 2023 after years of patching upstream compat issues. Maintenance burden outweighs cleaner codebase |
| **rustls replacing OpenSSL**                 | 🟡 Partial              | C ecosystem (openssh, curl) hard-depends on OpenSSL API. Use OpenSSL 3.x for C, rustls for Rust-native projects                             |
| **Full uutils replacement**                  | 🟡 Gradual              | GNU compat gaps may break build scripts. Phase 2 as optional, Phase 4 as default after testing                                              |

## Key Design Tradeoffs

| Decision                                                         | Alternative Considered                                                                                                                                                                                                            | Rationale |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| **OpenSSL 3.x over LibreSSL**                                    | LibreSSL has cleaner code, but Alpine dropped it in 2023 after years of patching upstream compat gaps. OpenSSL 3.x provider architecture is the safer long-term bet for ecosystem compat.                                         |
| **btrfs default + ext4 fallback**                                | btrfs COW causes write amplification on SD cards and doubles RAM pressure on low-memory SBCs. ext4 profile available for constrained targets.                                                                                     |
| **Dual-partition A/B (Phase 1) → btrfs subvolume A/B (Phase 3)** | Subvolume A/B is more elegant but couples boot infrastructure to btrfs internals early. Starting with simple dual partitions avoids premature complexity; migrate once package management matures.                                |
| **`system-unlock` escape hatch**                                 | Strict immutable rootfs is more secure but can brick a device during development. `system-unlock` remounts rw + stamps a flag; next boot warns until re-sealed. Balances security with operability.                               |
| **musl over glibc**                                              | musl is 10x smaller, static-link friendly, proven by Alpine/Chimera. Tradeoffs: no `nsswitch.conf` (breaks LDAP/NIS), `dlopen` locale loading absent, some pthread edge-case differences. Acceptable for a minimal RISC-V distro. |
| **dinit over s6-rc**                                             | s6-rc is more battle-tested (skarnet ecosystem). dinit has simpler service notation, wider community adoption (Chimera, eweOS), and active development.                                                                           |
| **dash as `/bin/sh`**                                            | Faster than bash for script execution. Risk: some scripts use bashisms. Mitigated by linting CI with `checkbashisms`; bash remains the interactive default.                                                                       |

## Architecture Overview

```
┌───────────────────────────────────────────────────────┐
│                    User Interface                     │
│  bash (default) · dash (/bin/sh) · nushell (optional) │
│  uutils-coreutils (Phase 2→4 gradual)                 │
│  ripgrep · fd · openssh                               │
├───────────────────────────────────────────────────────┤
│                    Package Management                 │
│  apk-tools 3.x (atomic · SHA-256 · musl-native)       │
├───────────────────────────────────────────────────────┤
│                    System Services                    │
│  dinit (PID 1) · mdevd (devices) · dhcpcd (network)   │
│  unbound/stubby (DoT DNS) · syslog-ng (logging)       │
│  crun (OCI runtime, Phase 4) · doas (privilege)       │
├───────────────────────────────────────────────────────┤
│                    Security                           │
│  Landlock LSM · seccomp-bpf · dm-verity               │
├───────────────────────────────────────────────────────┤
│                    Filesystem                         │
│  btrfs (default) · ext4 (fallback profile)            │
│  read-only rootfs + writable data partition/subvolume │
├───────────────────────────────────────────────────────┤
│                    Kernel                             │
│  Linux 6.18+ · musl libc · RISC-V (RV64GC / RV32)     │
│  CONFIG_MODULES · cgroups v2 · namespaces             │
├───────────────────────────────────────────────────────┤
│                    TLS / Crypto                       │
│  OpenSSL 3.x (C ecosystem) · rustls (Rust ecosystem)  │
├───────────────────────────────────────────────────────┤
│                    Firmware / Boot                    │
│  OpenSBI → U-Boot (UEFI) → EFISTUB kernel             │
│  dual-partition A/B (P1) → btrfs subvol A/B (P3)      │
├───────────────────────────────────────────────────────┤
│                    Hardware                           │
│  QEMU virt · Spike · VisionFive 2 · Milk-V Jupiter    │
└───────────────────────────────────────────────────────┘
```

## Phased Development Plan

### Phase 0: Build System Modernisation (0 → 3 weeks)

| Task                         | Description                                                                                                                                                                                                                                                                                                       |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0.1 Switch to musl toolchain | Cross toolchain from `riscv64-linux-gnu-` (glibc) to `riscv64-linux-musl-`; update Buildroot config                                                                                                                                                                                                               |
| 0.2 zstd replaces gzip       | initramfs `.cpio.zst`, `CONFIG_INITRAMFS_COMPRESSION_ZSTD`, package format `.tar.zst`                                                                                                                                                                                                                             |
| ~~0.3 Declarative build~~    | **Done.** `system.toml` presets in `configs/` describe target (arch, kernel, rootfs type, packages, boot); `make configure SYSTEM=configs/<preset>.toml` generates `.config.{mk,kernel,buildroot}`; `make build` and `make test` drive the full pipeline from those generated files. See `scripts/gen-config.py`. |
| 0.4 CI/CD pipeline           | GitHub Actions: build + QEMU smoke boot test + artifact upload; every commit verified bootable                                                                                                                                                                                                                    |
| 0.5 Reproducible builds      | Lock all source hashes (kernel, OpenSBI, toolchain) in `lock.toml`; bit-for-bit reproducibility                                                                                                                                                                                                                   |

### Phase 1: Bootable Disk Image + Immutable Root (3 → 8 weeks)

**Goal**: produce a GPT disk image (`.img`) that boots in QEMU via virtio-blk
and can be `dd`'d to an SD card for real RISC-V hardware.

| Task                             | Description                                                                                                                                                                                                   |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0 U-Boot integration           | Cross-compile U-Boot for RISC-V (`qemu-riscv64_smode_defconfig` + `CONFIG_EFI_LOADER=y`); new targets `make uboot` / `make build_uboot`; boot chain: OpenSBI → U-Boot (UEFI) → EFISTUB kernel                 |
| 1.1 GPT disk image generation    | `make disk_image`: create GPT image via `sgdisk`/`sfdisk` — ESP (FAT32, 256 MiB) + rootfs-A (ext4/btrfs) + rootfs-B + data partition; `scripts/gen-disk-image.sh`                                             |
| 1.2 Root filesystem              | Default: btrfs with transparent zstd compression (`CONFIG_BTRFS_FS=y`). Fallback: ext4 profile for SD-card / low-RAM targets (avoid COW write amplification). Populate from Buildroot `rootfs.tar` (not cpio) |
| 1.3 Immutable root + overlay     | `/` mounted read-only; `/etc`, `/var` via overlayfs mapped to writable data partition                                                                                                                         |
| 1.4 Modern initramfs             | Minimal init script (or Rust binary): mount rootfs → `fsck` → verify integrity → `switch_root /mnt/root /sbin/init`                                                                                           |
| 1.5 Dual-partition A/B boot      | Two rootfs partitions (A/B); U-Boot selects active slot via `boot_slot` env, mark good on success, auto-rollback on failure. Simple and filesystem-agnostic — no btrfs subvolume dependency at this stage     |
| 1.6 `system-unlock` escape hatch | `system-unlock` remounts rootfs read-write for emergency debugging; stamps `/data/.unlocked` flag, warns on next boot to re-seal                                                                              |
| 1.7 QEMU virtio-blk boot         | `make test_disk`: `qemu-system-riscv64 -M virt -drive file=disk.img,format=raw -device virtio-blk-device,...`; verify persistence + immutable root + overlay writes + A/B rollback                            |
| 1.8 Kernel config for disk boot  | Enable `EFI`, `EFI_STUB`, `MODULES`, `EXT4_FS`, `BTRFS_FS`, `VIRTIO_BLK`, `DEVTMPFS`, `DEVTMPFS_MOUNT`, `VFAT_FS`, `NLS_CODEPAGE_437`, `NLS_ISO8859_1` via `gen-config.py` when `rootfs.type = "disk"`        |
| 1.9 gen-config.py disk support   | Extend TOML schema: `rootfs.type = "disk"` triggers disk image pipeline; `boot.loader = "uboot"` selects U-Boot firmware; generate appropriate `.config.kernel` and `.config.mk`                              |

**Milestone artifact**: `make configure SYSTEM=configs/qemu-rv64-disk.toml && make build && make test` boots from a self-contained `disk.img` with persistent rootfs.

### Phase 2: Modern Userspace (8 → 16 weeks)

| Task                            | Description                                                                                                       |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 2.1 dinit init system           | Integrate dinit as PID 1: write core service definitions (networking, syslog, sshd, mdevd), dependency-graph boot |
| 2.2 mdevd + libudev-zero        | Replace udev/eudev: mdevd for synchronous device management + libudev-zero for compat API                         |
| 2.3 uutils/coreutils (optional) | Cross-compile Rust uutils for RISC-V musl; install alongside busybox, user can switch via PATH                    |
| 2.4 Kernel module support       | `CONFIG_MODULES=y`, build depmod/modprobe (kmod), `/lib/modules/` hierarchy                                       |
| 2.5 Structured logging          | syslog-ng with structured output, zstd-compressed rotation, `/var/log/`                                           |
| 2.6 Network stack               | dhcpcd for wired networking; unbound/stubby for DoT DNS resolution                                                |
| 2.7 User/permission model       | Minimal `/etc/passwd` `/etc/shadow` `/etc/group`, non-root user, doas for privilege escalation                    |
| 2.8 Rust CLI tools (batch 1)    | Package ripgrep (`rg`) and fd for the target; available as optional installs                                      |

### Phase 3: Package Management + System Updates (16 → 24 weeks)

| Task                            | Description                                                                                                                                                                                                                                         |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1 apk-tools 3.x integration   | Cross-compile apk-tools for RISC-V musl target; configure as system package manager                                                                                                                                                                 |
| 3.2 Package build framework     | `APKBUILD` recipes for each package; cross-compile + musl static/dynamic linking                                                                                                                                                                    |
| 3.3 Package repository + index  | Static HTTP repository (GitHub Releases / S3); signed index, incremental sync                                                                                                                                                                       |
| 3.4 Base package set            | Core ~50 packages: musl, busybox, bash, dash, dinit, kmod, iproute2, openssl, openssh, curl, git                                                                                                                                                    |
| 3.5 Declarative system config   | `system.toml` describes complete system state (packages, services, users, network); `system-rebuild` atomically applies                                                                                                                             |
| 3.6 btrfs subvolume A/B upgrade | Migrate from Phase 1 dual-partition A/B to btrfs subvolume A/B; `system-upgrade`: download new rootfs → write to standby subvolume → reboot → verify → mark good → old subvolume retained for rollback. ext4 profile stays on dual-partition scheme |
| 3.7 OpenSSL 3.x integration     | Verify OpenSSL 3.x across all C packages (openssh, curl, etc.); enable provider-based crypto architecture                                                                                                                                           |

### Phase 4: Security Hardening + Containers + Real Hardware (24 → 34 weeks)

| Task                              | Description                                                                                                                      |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 4.1 dm-verity boot chain          | Read-only rootfs + dm-verity integrity verification, tamper-proof boot                                                           |
| 4.2 seccomp-bpf default policies  | Each dinit service definition includes seccomp syscall whitelist; minimal-privilege execution                                    |
| 4.3 Landlock LSM sandboxing       | Per-service filesystem access isolation via declarative Landlock policy files                                                    |
| 4.4 crun OCI runtime              | Lightweight C OCI container runtime; rootless-first, cgroups v2 native                                                           |
| 4.5 U-Boot board-specific configs | Board-level U-Boot defconfigs (VisionFive 2, Milk-V Jupiter); SPL chain for SPI/eMMC boot (basic U-Boot UEFI moved to Phase 1.0) |
| 4.6 StarFive VisionFive 2 BSP     | Board support: device tree, SD card flash script, GPIO/I2C driver validation                                                     |
| 4.7 Milk-V Jupiter BSP            | Spacemit K1 SoC support (kernel DT, PCIe/USB debugging)                                                                          |
| 4.8 SD card / NVMe installer      | `make flash SD=/dev/sdX`: partition + write firmware + rootfs, plug-and-play; reuses disk image from Phase 1.1                   |
| 4.9 uutils as default             | After sufficient testing, switch default coreutils from busybox to uutils                                                        |
| 4.10 Self-hosting verification    | Compile all packages on the distribution itself using Rust + C toolchain on musl                                                 |

### Phase 5: Distribution Identity + Community (34 → 48 weeks)

| Task                               | Description                                                                                                            |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 5.1 Distribution naming + branding | `/etc/os-release`, boot splash, MOTD, logo                                                                             |
| 5.2 TUI installer                  | Rust-based TUI installer (like `archinstall`): disk partitioning → rootfs deploy → user creation → network config      |
| 5.3 Documentation site             | mdbook static site: install guide, package management, porting guide, architecture docs                                |
| 5.4 Downloadable images            | `.img.zst` disk images (GPT, from Phase 1.1), dd-writable to SD card; UEFI-bootable `.iso` via `xorriso` for USB media |
| 5.5 Package contribution guide     | Community can submit APKBUILD PRs; CI auto-cross-compiles + tests + publishes to repository                            |

## Milestone Overview

```
Current ── P0 ──── P1 ────────── P2 ──── P3 ──── P4 ──── P5
           Build    Disk image    Modern  Pkg     HW +    Distro
           Modern.  +U-Boot+rootfs user   mgmt    Security identity

"kernel    "musl    "bootable     "dinit  "apk    "VF2    "shippable
 boot       +zstd   .img via       +Rust   +atomic flash   independent
 experiment +CI"    UEFI/U-Boot"  tools"  updates" boot"  distribution"

    ▼
████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ → goal
~10%                                                      100%
```

**Key milestone: Phase 1 completion** = the first time the project produces a
standalone `.img` file bootable in both QEMU (`-drive file=disk.img`) and on
real RISC-V hardware (via `dd if=disk.img of=/dev/sdX`).

## Positioning Among Existing Distributions

| Distribution          | Philosophy                   | What We Borrow                 | How We Differ                                                        |
| --------------------- | ---------------------------- | ------------------------------ | -------------------------------------------------------------------- |
| **Chimera Linux**     | musl + dinit + BSD userspace | musl + dinit selection         | Rust tooling instead of BSD utils; btrfs immutable root              |
| **Alpine Linux**      | musl + minimal + apk         | musl + apk maturity            | Immutable root, btrfs snapshots, Landlock defaults                   |
| **Void Linux**        | runit + musl + xbps          | musl-first philosophy          | dinit (more modern than runit), apk-tools 3.x                        |
| **Fedora Silverblue** | Immutable rootfs + OSTree    | Immutable root concept         | btrfs subvolumes instead of OSTree; musl instead of glibc            |
| **NixOS**             | Declarative + reproducible   | Declarative system config idea | Vastly simpler (TOML, not Nix language); conventional package format |

**Unique positioning**: RISC-V first + musl + dinit + btrfs immutable root +
Landlock/seccomp defaults + apk-tools 3.x — no existing distribution combines all of these.
