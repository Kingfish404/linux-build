# Kernel Configuration Details

## ISA and Config Tweaks (`build_linux`)

The base kernel build (`build_linux`) targets a plain **imac** ISA with **no FPU/D**, to
minimise CPU feature requirements.

| Config option                    | RV32         | RV64                |
| -------------------------------- | ------------ | ------------------- |
| `CONFIG_NONPORTABLE`             | enabled      | *(already default)* |
| `CONFIG_ARCH_RV64I`              | disabled     | *(already default)* |
| `CONFIG_ARCH_RV32I`              | enabled      | —                   |
| `CONFIG_FPU`                     | **disabled** | **disabled**        |
| `CONFIG_RISCV_ISA_ZAWRS`         | disabled     | disabled            |
| `CONFIG_RISCV_ISA_ZBA/ZBB/ZBC`   | disabled     | disabled            |
| `CONFIG_RISCV_ISA_ZICBOM/ZICBOZ` | disabled     | disabled            |

## Buildroot and FPU

The declarative build generates **two** kernel config fragments from each preset:

- `.config.kernel.minimal` \u2014 `CONFIG_FPU=n` (ISA `imac`). Applied by `build_linux`.
- `.config.kernel.buildroot` \u2014 `CONFIG_FPU=y` (ISA `imafd`). Applied by
  `package_buildroot` when assembling the Buildroot release, because Buildroot's
  default toolchain produces hard-float binaries (`lp64d` / `ilp32d` ABI).

| Variant   | `CONFIG_FPU` | Effective kernel ISA  | Userspace ABI   |
| --------- | ------------ | --------------------- | --------------- |
| Tiny shell | disabled    | rv32imac / rv64imac   | ilp32 / lp64    |
| Buildroot | **enabled**  | rv32imafd / rv64imafd | ilp32d / lp64d  |

> The tiny shell initramfs is unaffected and stays FPU-free.
> If you switch which fragment is applied on the same build tree, the kernel's
> `CONFIG_FPU` state will change accordingly.

## init Payload (`payload/tiny_shell.c`)

| Target | `-march=`                       | `-mabi=` |
| ------ | ------------------------------- | -------- |
| RV32   | `rv32ima_zicsr_zifencei_zicntr` | `ilp32`  |
| RV64   | `rv64imac_zicsr_zifencei`       | `lp64`   |

## OpenSBI ISA / XLEN

| Target | `PLATFORM_RISCV_ISA`             | `PLATFORM_RISCV_XLEN` |
| ------ | -------------------------------- | --------------------- |
| RV32   | `rv32imac_zicntr_zicsr_zifencei` | `32`                  |
| RV64   | `rv64imac_zicntr_zicsr_zifencei` | `64`                  |
