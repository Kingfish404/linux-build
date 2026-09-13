# RV64 Alpine and Debian root filesystems

These presets use upstream RV64GC/lp64d userspace and the project's own Linux
kernel and OpenSBI. Alpine uses musl and apk; Debian 13 (trixie) uses glibc and apt.
RV32 remains on the existing tiny-shell/Buildroot paths.

```sh
make configure SYSTEM=configs/qemu-rv64-alpine.toml
make build
make test

# Or:
make configure SYSTEM=configs/qemu-rv64-debian.toml
make build
make test
```

The host needs Skopeo (`SKOPEO=/path/to/skopeo` is supported), Python 3.11+,
fakeroot, GNU tar/cpio, e2fsprogs, QEMU system emulation and the existing
kernel/OpenSBI cross-toolchain. Skopeo downloads the official RV64 OCI base and
checks its blob hashes. An Alpine bootstrap initramfs then provisions the target
disk using apk/apt **inside a full-system RV64 QEMU guest**. Fakeroot preserves
numeric ownership and device nodes when making the initial disk.

No container daemon, host mounts, root build or host binfmt registrations are
needed. Never install or alter host execution handlers for this workflow.
Registry and official repository access are required. If HTTPS_PROXY points to
localhost, the guest uses QEMU's host gateway (10.0.2.2) for that proxy; this
setting is temporary and is not saved in the resulting rootfs.
Set `DISTRO_GUEST_PROXY=` to use direct guest access while keeping the host's
registry proxy, or set it to an explicit guest-reachable proxy URL.

## Configuration and artifacts

`[rootfs]` selects `type`, OCI `image`, `packages` and `size_mib`. The default bases
are official `alpine:3.23` and `debian:trixie-slim` images. Both publish riscv64
images. Package installation keeps their official repositories and signature
verification. A new build refreshes packages; tags and package repositories are
mutable, so this is not a bit-for-bit reproducible release pipeline. For stricter
pinning, select an OCI digest and a separately controlled repository snapshot.

| Artifact | Path relative to BUILD_ROOT |
| --- | --- |
| Persistent root disk | `<preset>/rootfs.ext4` |
| Build input record | `<preset>/rootfs.json` |
| Kernel output | `<preset>-kernel/` |
| Firmware output | `opensbi-build64-<preset>/` |

Both presets default to 1 GiB guest RAM. Alpine uses a 512 MiB sparse disk;
Debian uses a 2 GiB sparse disk. Disk capacity is not installed size or
RAM usage. The kernel boots `/dev/vda` directly with built-in virtio/ext4 drivers;
there is no embedded distribution initramfs or +63 MiB rootfs/DTB constraint.

`make build_distro_rootfs` first builds the kernel/OpenSBI needed for native
guest provisioning, then creates the disk. An existing disk with matching
build inputs is reused, preserving guest package installs. Changed inputs cause
an error instead of overwriting the disk. For a fresh build, use a new
`BUILD_ROOT` consistently for both build and test, or move the old disk and JSON
record aside. Re-running `make build` does not reset or upgrade an existing disk.
Do not boot the same writable disk in multiple QEMU instances simultaneously.

`make package` (or `package_distro`) builds a separate clean disk under
`BUILD_ROOT/release-rootfs/<preset>/`, checks its original hash, and packages it
with Image, vmlinux, kernel.config, OpenSBI, launch script and provenance.
It never packages the development guest disk. Both distro presets are included
in `package_all` / `release_ready`: 22 packages and 54 boot paths in the full
matrix. No distribution embedded firmware payload or board SD layout is generated.

## Runtime

Both presets use BusyBox init with a root serial bring-up shell, mounted
proc/sys/dev/devpts, and DHCP on eth0. Press Enter for the console. They do not
boot OpenRC or systemd. SSH starts if installed; host keys are created on first
boot. SSH password authentication is disabled. Provision an authorized key and
an account usable by sshd before connecting; the serial console is available
without authentication, like the existing bring-up shells.

```sh
# Alpine guest
apk update
apk add git python3

# Debian guest
apt update
apt install git python3

# Persist writes and shut down before copying the disk
sync
/bin/busybox poweroff
```

`SSH_PORT`, `SHARE_DIR`, and `SHARE_RO` use the existing QEMU options. To mount a
9P share, the kernel also needs built-in 9P drivers (enabled by the presets).
Service packages may install successfully but need explicit startup integration;
`systemctl` and `rc-service` are not provided as the boot service managers.
The retained BusyBox init handles child reaping and console respawning.

## Can Alpine replace Buildroot?

For RV64 command-line tools, SSH, networking and on-target package installation,
Alpine is a good default replacement. BusyBox can remain the init and shell, and
the existing custom kernel/firmware does not depend on Buildroot's libc.

It is not a drop-in replacement for all current artifacts:

- Existing Buildroot glibc-linked binaries must be rebuilt for musl, supplied
  with a separate compatible runtime, or run on Debian.
- Buildroot still supplies RV32 userspace, exact source-build configuration,
  and a compact preselected rootfs that boots without persistent storage.
- The current Buildroot release matrix exercises embedded firmware and split
  boot, filesystem/network helpers and process/timing behavior. New distro disk
  presets require their own runtime and hardware acceptance before retiring it.
- The QEMU distribution presets do not replicate the full FPGA peripheral
  configuration or board storage layout. Kernel drivers can be carried over,
  but this requires board-specific validation.

Keep Buildroot as the RV32 and compact firmware/bring-up option for now. Prefer
Alpine for RV64 package-managed tools, and Debian when glibc or Debian-specific
software is required. Remove the RV64 Buildroot path only after deciding that
its storage-independent firmware artifact and compatibility are no longer needed.

Upstream references: [Alpine official image](https://hub.docker.com/_/alpine),
[Debian official image](https://hub.docker.com/_/debian),
[Debian RV64 hardware support](https://www.debian.org/releases/trixie/riscv64/ch02s01.en.html).

## Validation

Run `python3 scripts/test-distro.py` for offline preset/routing, disk preservation,
and real ext4 ownership/link checks. The ext4 check needs fakeroot and e2fsprogs
and a host environment permitting fakeroot's IPC/preload operation.

`make release_ready` tests freshly extracted copies of every release archive.
For each distro it verifies 1 GiB RAM, kernel version, mounts, DNS/HTTPS,
installation and execution of jq from upstream, key-based SSH, then an actual
guest reboot. A second boot verifies a new boot ID and preservation of a test
file, package database/executable and SSH host/authorized keys. The published
archive remains pristine; the modified test disk is discarded. Test logs and
source/archive hashes are checked by the publication gate. A gate failure blocks
`make github_release`; the build/test workflow does not publish anything itself.

The authoritative results are the candidate's `test-results.json` and
`release-ready.json`, not merely the presence of these scripts. No FPGA
acceptance or size/boot-time comparison against Buildroot is implied.
