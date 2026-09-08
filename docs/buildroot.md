# Buildroot rootfs

Buildroot targets are defined in [scripts/buildroot.mk](../scripts/buildroot.mk).
Run them through the root Makefile.

```bash
make configure SYSTEM=configs/qemu-rv64.toml
make package_buildroot
make test_qemu_buildroot
# Or load the same packaged kernel and rootfs separately:
make test_qemu_kernel_buildroot
# Fast shell with proc/sys/dev mounted, without services:
make test_qemu_buildroot_shell
```

`package_buildroot` resolves the rootfs cache, configures the independent
Buildroot kernel, embeds the rootfs, builds matching OpenSBI and packages the
exact files. The upstream Buildroot kernel/host-QEMU builds are disabled;
old modules from that unrelated kernel are removed during rootfs generation.
All supplied Buildroot presets use 256 MiB in QEMU and hard-float
userspace, requiring F/D support in both hardware and the board DTB.

Change `[buildroot.packages]` in the preset, rerun `make configure`, then run
`make package_buildroot`. The cache key includes the requested fragment,
Buildroot source identity and base defconfig. On a configuration change with
no cache entry, a clean rootfs build avoids retaining removed packages.

For low-level iteration, `make_initramfs_buildroot` and `update_buildroot`
perform incremental builds; they can retain files from removed packages.
`make_initramfs_buildroot_clean` performs a full clean build.
`update_buildroot_full` resolves the rootfs cache and rebuilds the independent
Buildroot kernel and its embedded firmware.

| Output | Path |
| --- | --- |
| Rootfs | `initramfs{32,64}-buildroot.cpio.gz` |
| Kernel | `buildroot{32,64}-kernel/` |
| Firmware | `opensbi-build{32,64}-buildroot/` |
| Release | `DIST_DIR/linux-riscv-rv{32,64}-<preset>-buildroot-v<version>.tar.gz` |

`BUILD_ROOT` relocates kernel and firmware output. Buildroot source/output
and generated `.config.*` files remain shared per checkout; serialize preset
configuration and builds. Package builds cache rootfs files under
`dist/.rootfs-cache` and serialize cache operations per XLEN.

QEMU targets support `SSH_PORT` (default 2222), `SHARE_DIR` and `SHARE_RO`.
Use `QEMU_MEM_BUILDROOT` to override Buildroot QEMU RAM. A package records the
RAM selected by its TOML preset, so edit `[buildroot].memory` when changing
release defaults.

Large rootfs additions may exceed RAM or the firmware's +63 MiB DTB boundary.
Packaging rejects a kernel whose memory extent overlaps that DTB. Increasing
RAM alone does not fix a DTB collision: choose a compatible relocation and
board handoff. Split loading an already embedded Image still retains its
embedded rootfs; it does not automatically shrink the Image.

For the full release workflow, see the root [README](../README.md). Run
`package_all` into a new `DIST_DIR`, then `release_ready`. Preparation produces
checksums and validation records; `github_release` is the separate publishing
step.

For runtime mounts, initialized fast-shell boot and the tinysh capability
comparison, see [Buildroot runtime coverage](../README.md#buildroot-runtime-and-tinysh-coverage).
