# linux-build

Scripts and Makefiles for building a small RISC-V Linux system, including:

- Linux kernel image (`arch/riscv/boot/Image`) and kernel ELF (`vmlinux`)
- A tiny shell initramfs, with `payload/tiny_shell.c` built as `/init`
- An optional Buildroot initramfs with BusyBox, SSH, and extra packages
- OpenSBI firmware, optionally with the kernel image embedded as `FW_PAYLOAD`
- Spike (`riscv-isa-sim`) built from source

Both 32-bit (RV32) and 64-bit (RV64) targets are supported and can coexist in the same tree. Each TOML preset can generate a tiny shell kernel/initramfs path and, when `[buildroot]` is present, a Buildroot path.

| Host    | 32-bit target                        | 64-bit target                        |
| ------- | ------------------------------------ | ------------------------------------ |
| x86-64  | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`) |
| aarch64 | cross-compile (`riscv64-linux-gnu-`) | cross-compile (`riscv64-linux-gnu-`) |
| riscv64 | cross-compile (`riscv64-linux-gnu-`) | native build by default              |

## Prerequisites

Install host packages on Debian/Ubuntu:

```bash
bash scripts/install-deps.sh
```

See [scripts/install-deps.sh](scripts/install-deps.sh) for the package list.

## Quick Start

```bash
# Download sources once
make linux opensbi

# Configure from a preset, build, and boot the tiny shell initramfs
make configure SYSTEM=configs/qemu-rv32-fast.toml
make build
make test
```

Expected guest prompt:

```text
tinysh: initramfs shell ready. Type 'help'.
tinysh#
```

The QEMU tiny-shell test attaches a virtio network device and uses kernel DHCP
autoconfiguration. Network status and connectivity can be checked without a
userspace DHCP client:

```text
tinysh# ifconfig
eth0: UP RUNNING
        inet 10.0.2.15
        netmask 255.255.255.0
tinysh# ping 10.0.2.2
3/3 replies
```

The freestanding shell provides these built-in commands:

```text
filesystem: pwd cd ls cat cp touch mkdir rm rmdir mount sync
system:     uname uptime free sleep run clear reboot poweroff exit
network:    ifconfig ping nc fetch
```

`ifconfig [IFACE]` defaults to `eth0`. `ping` accepts a numeric IPv4 address and
sends three ICMP echo requests. `nc IPv4 PORT` opens a TCP client connection,
while `nc -l PORT` accepts one TCP connection; both modes relay data between the
console and socket until EOF. `fetch IPv4 PORT /REMOTE_PATH LOCAL_PATH` downloads
an HTTP/1.0 response, checks `Content-Length` when supplied, and creates an
executable file. `run PATH [ARG...]` starts it as a child, reports its exit status,
and returns to the shell. Absolute and relative paths containing `/` can also be
executed directly. For example:

```text
tinysh# fetch 10.0.2.2 8000 /probe /tmp/probe
saved 2040 bytes to /tmp/probe
tinysh# run /tmp/probe
downloaded ELF executed
exit 37
tinysh# cd /tmp
tinysh# ./probe
downloaded ELF executed
exit 37
```

DNS lookup and TLS are intentionally not included. Use `fetch` only on a trusted
network: it provides transport, not authenticity. Downloaded ELF files must match
the active RV32/RV64 ISA and ABI; statically linked binaries are the portable
default unless their interpreter and shared libraries are also present.

The shell remains a single static `/init` binary, but its source is split by
responsibility under [payload/](payload/): the REPL entry point, command table,
network commands, HTTP transfer and execution, syscall ABI, and common utilities
are compiled as separate objects.

To boot the Buildroot initramfs after a preset with `[buildroot]` has been built:

```bash
make test_qemu_kernel_buildroot
```

## Presets

Available presets live in [configs/](configs/):

| Preset             | Arch | Memory | Buildroot packages                      | Notes                                     |
| ------------------ | ---- | ------ | --------------------------------------- | ----------------------------------------- |
| `qemu-rv32-fast`   | RV32 | 64 MB  | openssh                                 | Aggressively trimmed tiny shell boot path |
| `qemu-rv64-fast`   | RV64 | 64 MB  | openssh                                 | Aggressively trimmed tiny shell boot path |
| `qemu-rv32`        | RV32 | 512 MB | openssh, strace, htop, lsof, file, tree | Default RV32 preset                       |
| `qemu-rv64`        | RV64 | 512 MB | openssh, strace, htop, lsof, file, tree | Default RV64 preset                       |
| `qemu-rv32-s`      | RV32 | 256 MB | openssh                                 | Smaller RV32 preset                       |
| `qemu-rv64-s`      | RV64 | 256 MB | openssh                                 | Smaller RV64 preset                       |
| `qemu-rv32-m`      | RV32 | 256 MB | openssh                                 | Keeps selected bit-manip extensions       |
| `qemu-rv64-m`      | RV64 | 256 MB | openssh                                 | Keeps selected bit-manip extensions       |
| `qemu-rv32-latest` | RV32 | 512 MB | openssh, strace, htop, lsof, file, tree | Latest-kernel hardware bring-up preset    |
| `qemu-rv64-latest` | RV64 | 512 MB | openssh, strace, htop, lsof, file, tree | Latest-kernel hardware bring-up preset    |

## Declarative Build System

`make configure SYSTEM=<file>` runs [scripts/gen-config.py](scripts/gen-config.py) and writes generated fragments:

| Generated file             | Purpose                                                       |
| -------------------------- | ------------------------------------------------------------- |
| `.config.mk`               | Makefile variable overrides (`BITS`, `QEMU_MEM`, preset name) |
| `.config.kernel`           | Shared kernel Kconfig fragment                                |
| `.config.kernel.minimal`   | Tiny shell kernel fragment, FPU disabled                      |
| `.config.kernel.buildroot` | Buildroot kernel fragment, FPU enabled when needed            |
| `.config.buildroot`        | Buildroot package/rootfs fragment, when `[buildroot]` exists  |

Build flow:

```text
configs/<preset>.toml
        | make configure SYSTEM=...
        v
.config.mk + Kconfig fragments
        | make build
        v
build{32,64}/ + initramfs{32,64}.cpio.gz + opensbi-build{32,64}/
        | make test
        v
QEMU or Spike boots /init from payload/tiny_shell.c
```

## Build Targets

### Source

| Target      | Description                                      |
| ----------- | ------------------------------------------------ |
| `linux`     | Download and extract Linux kernel source tarball |
| `opensbi`   | Clone OpenSBI source repository                  |
| `buildroot` | Clone Buildroot source into `buildroot$(BITS)/`  |
| `spike_src` | Clone Spike source into `spike/`                 |

### Kernel And Initramfs

| Target                           | Description                                                                       |
| -------------------------------- | --------------------------------------------------------------------------------- |
| `build_linux`                    | Configure and build Linux with shared + tiny shell kernel fragments               |
| `build_init`                     | Compile `payload/tiny_shell.c` into `payload/init_shell`                          |
| `make_initramfs_tiny_shell`      | Build `initramfs$(BITS).cpio.gz` with `/init` and required device nodes           |
| `install_initramfs`              | Set `CONFIG_INITRAMFS_SOURCE` to the tiny shell cpio and rebuild the kernel Image |
| `make_initramfs_buildroot`       | Build Buildroot rootfs incrementally into `initramfs$(BITS)-buildroot.cpio.gz`    |
| `make_initramfs_buildroot_clean` | Full clean Buildroot rebuild (`distclean` first)                                  |
| `install_initramfs_buildroot`    | Set `CONFIG_INITRAMFS_SOURCE` to the Buildroot cpio and rebuild the kernel Image  |
| `update_buildroot`               | Incremental Buildroot rebuild only                                                |
| `update_buildroot_full`          | Buildroot rebuild + re-embed initramfs + rebuild OpenSBI                          |

### Firmware And Test

| Target                       | Description                                                          |
| ---------------------------- | -------------------------------------------------------------------- |
| `build_opensbi`              | Build OpenSBI generic platform firmware                              |
| `build_opensbi_with_kernel`  | Build OpenSBI with kernel `Image` embedded as `FW_PAYLOAD`           |
| `build_spike`                | Build Spike simulator into `spike-build/`                            |
| `test_qemu`                  | Boot `fw_payload.bin` in QEMU                                        |
| `test_qemu_kernel`           | Boot `fw_dynamic.bin` + separate kernel Image + tiny shell initramfs |
| `test_qemu_buildroot`        | Boot Buildroot via `fw_payload.bin` with networking                  |
| `test_qemu_kernel_buildroot` | Boot separate kernel + Buildroot initramfs with networking           |
| `test_spike`                 | Boot `fw_payload.elf` in Spike                                       |

### Package And Housekeeping

| Target              | Description                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `package`           | Bundle rv$(BITS) tiny shell artifacts into `dist/linux-riscv-rv$(BITS)-<preset>-v*.tar.gz`          |
| `package_buildroot` | Bundle rv$(BITS) Buildroot artifacts into `dist/linux-riscv-rv$(BITS)-<preset>-buildroot-v*.tar.gz` |
| `package_all`       | Clean `dist/`, then build and package tiny shell + Buildroot for every `configs/*.toml` preset      |
| `test_all`          | Timeout-boot every package in `dist/` and verify its userspace reaches the serial console           |
| `github_release`    | Create a GitHub Release and upload tarballs from `dist/` (requires `gh`)                            |
| `clean_packages`    | Remove `dist/`                                                                                      |
| `build_all`         | Build Linux + tiny shell initramfs + OpenSBI for RV32 and RV64                                      |
| `clean`             | Remove kernel, initramfs, OpenSBI, and payload build artifacts                                      |
| `clean_buildroot`   | Remove Buildroot clone directories                                                                  |
| `clean_spike`       | Remove Spike source and build directories                                                           |
| `clean_config`      | Remove generated `.config.*` files                                                                  |

## Variables

| Variable               | Default                   | Description                                                     |
| ---------------------- | ------------------------- | --------------------------------------------------------------- |
| `BITS`                 | `32`                      | Target bitness, normally set by `.config.mk`                    |
| `CROSS_COMPILE`        | auto                      | Cross-compiler prefix, e.g. `riscv64-linux-gnu-`                |
| `HOSTCC`               | `cc`                      | Host compiler for Linux `usr/gen_init_cpio.c`                   |
| `QEMU_MEM`             | `512`                     | QEMU guest RAM in MiB, overridden by preset `[boot].memory`     |
| `QEMU_TIMEOUT`         | unset                     | Auto-exit QEMU after this many seconds using `timeout(1)`       |
| `PACKAGE_TEST_TIMEOUT` | `30`                      | Per-package QEMU boot timeout used by `test_all`, in seconds    |
| `SYSTEM`               | unset                     | TOML preset path for `make configure`                           |
| `SPIKE_MEM`            | `512`                     | Spike guest RAM in MiB                                          |
| `SSH_PORT`             | `2222`                    | Host port forwarded to guest port 22 for Buildroot QEMU targets |
| `SHARE_DIR`            | unset                     | Host directory shared with Buildroot guests via 9P              |
| `SHARE_RO`             | unset                     | Set to `1` to mount the 9P share read-only                      |
| `TAG`                  | `rv-v<qemu-rv64 version>` | Git tag for `github_release`; set explicitly to override it     |

Recommended release flow:

```bash
make package_all
make test_all
make github_release
```

`test_all` uses each archive's packaged `fw_dynamic.bin`, `Image`, and
`initramfs.cpio.gz`. Successful and failed serial logs are written under
`dist/test-logs/`; a timeout, kernel panic, missing package file, or absent
userspace-ready marker fails the target.

## Buildroot

All Buildroot-specific targets live in [scripts/buildroot.mk](scripts/buildroot.mk) and are included by the top-level [Makefile](Makefile). See [docs/buildroot.md](docs/buildroot.md) for package selection, fast incremental rebuilds, networking, and large-rootfs memory notes.

## Kernel Configuration

See [docs/kernel-config.md](docs/kernel-config.md) for ISA selection, `CONFIG_FPU` handling, and payload build settings.

The tiny shell path uses `rv32imac` / `rv64imac` with FPU disabled. The Buildroot path may use `rv32imafd` / `rv64imafd` because Buildroot's default RISC-V toolchains use hard-float ABIs.

## Output Artifacts

| Path                                                       | Description                   |
| ---------------------------------------------------------- | ----------------------------- |
| `build32/arch/riscv/boot/Image`                            | RV32 kernel image             |
| `build32/vmlinux`                                          | RV32 kernel ELF               |
| `build64/arch/riscv/boot/Image`                            | RV64 kernel image             |
| `build64/vmlinux`                                          | RV64 kernel ELF               |
| `initramfs32.cpio.gz`                                      | RV32 tiny shell initramfs     |
| `initramfs64.cpio.gz`                                      | RV64 tiny shell initramfs     |
| `initramfs32-buildroot.cpio.gz`                            | RV32 Buildroot initramfs      |
| `initramfs64-buildroot.cpio.gz`                            | RV64 Buildroot initramfs      |
| `opensbi-build32/platform/generic/firmware/fw_payload.elf` | RV32 OpenSBI + kernel ELF     |
| `opensbi-build32/platform/generic/firmware/fw_payload.bin` | RV32 OpenSBI + kernel binary  |
| `opensbi-build32/platform/generic/firmware/fw_dynamic.bin` | RV32 OpenSBI dynamic firmware |
| `opensbi-build64/platform/generic/firmware/fw_payload.elf` | RV64 OpenSBI + kernel ELF     |
| `opensbi-build64/platform/generic/firmware/fw_payload.bin` | RV64 OpenSBI + kernel binary  |
| `opensbi-build64/platform/generic/firmware/fw_dynamic.bin` | RV64 OpenSBI dynamic firmware |
| `spike-build/bin/spike`                                    | Locally built Spike simulator |
| `dist/linux-riscv-rv*-<preset>-v*.tar.gz`                  | Tiny shell release tarball    |
| `dist/linux-riscv-rv*-<preset>-buildroot-v*.tar.gz`        | Buildroot release tarball     |

## Project Structure

```text
.
├── Makefile                    # Top-level build orchestration
├── README.md                   # Project overview and target reference
├── configs/                    # TOML presets
├── docs/                       # Detailed guides and roadmap
├── scripts/
│   ├── buildroot.mk            # Buildroot targets included by Makefile
│   ├── gen-config.py           # TOML -> generated Make/Kconfig fragments
│   ├── gen-package-readme.sh   # Release tarball README generator
│   └── install-deps.sh         # Debian/Ubuntu dependency installer
└── payload/
    ├── Makefile                # Builds the tiny shell payload
    └── tiny_shell.c            # Freestanding `/init` shell
```

## References

- [Linux Kernel][linux]
- [OpenSBI][opensbi]
- [QEMU][qemu]
- [Spike (riscv-isa-sim)][spike]
- [Buildroot][buildroot]
- [RISC-V GNU Toolchain][riscv-gnu-toolchain]

[linux]: https://www.kernel.org/
[opensbi]: https://github.com/riscv-software-src/opensbi
[qemu]: https://www.qemu.org/
[spike]: https://github.com/riscv-software-src/riscv-isa-sim
[buildroot]: https://buildroot.org/
[riscv-gnu-toolchain]: https://github.com/riscv-collab/riscv-gnu-toolchain
