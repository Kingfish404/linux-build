# Kernel configuration

Each preset generates a shared fragment plus separate minimal and Buildroot
fragments. `configure_kernel` starts from the Linux defconfig (with the RV32
base fragment for RV32), applies the shared fragment and exactly one variant,
then resolves dependencies with `olddefconfig`. Inspect the resulting
`kernel.config` in a package for effective settings.

| Variant | Kernel ISA baseline | Userspace ABI | Kernel FPU |
| --- | --- | --- | --- |
| Tiny RV32 / RV64 | rv32imac / rv64imac | ilp32 / lp64 | disabled |
| Buildroot RV32 / RV64 | rv32imafdc / rv64imafdc | ilp32d / lp64d | enabled |

Optional kernel ISA paths depend on the preset and runtime DTB. The `-m`
presets retain selected bit-manipulation support; other presets disable it.
All presets use HZ=100, MMU and LiteX UART support. Buildroot retains futex
support. A configured ISA path, an implemented core extension and successful
board execution are separate facts.

Tiny and Buildroot kernels have independent output directories. Use
`make package` or `make package_buildroot` to assemble the matching variant;
`KERNEL_VARIANT=buildroot` explicitly selects that variant for lower-level
kernel and firmware commands.

The shared kernel fragment explicitly enables `CONFIG_RISCV_ISA_C`, and the
Buildroot fragment enables `BR2_RISCV_ISA_RVC` for both RV32 and RV64.

The freestanding RV32 `/init` uses `rv32imac_zicsr_zifencei_zicntr` / `ilp32`;
RV64 uses `rv64imac_zicsr_zifencei` / `lp64`. RV32 time-related syscalls use
time64 layouts and numbers. Child reaping uses waitid on RV32 and wait4 on RV64.

OpenSBI ISA and ABI are recorded separately in each package manifest. The
firmware preparation checks the Image load offset (4 MiB RV32, 2 MiB RV64),
its full memory extent, and DTB relocation at +63 MiB. Changing payload or
layout rebuilds the actual embedded firmware. A different board memory layout
must keep the DTB outside the kernel and inside RAM.
