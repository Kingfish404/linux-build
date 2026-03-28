#!/usr/bin/env bash
# Generate a README.md for a release tarball.
# Usage: gen-package-readme.sh <BITS> <KERNEL_VERSION> <RISCV_ISA> <RISCV_ABI> [simple|buildroot] [PRESET]
set -euo pipefail

BITS="$1"
KERNEL_VERSION="$2"
RISCV_ISA="$3"
RISCV_ABI="$4"
VARIANT="${5:-simple}"   # "simple" (init_loop) or "buildroot" (full rootfs)
PRESET="${6:-}"          # config preset name (e.g. "qemu-rv32")

if [[ "$VARIANT" == "buildroot" ]]; then
  # Buildroot userspace uses hard-float ABI, so the kernel has CONFIG_FPU enabled.
  # The effective ISA for the kernel is imafd (imac + F/D extensions).
  TITLE_ISA="rv${BITS}imafd"
  TITLE_SUFFIX="Buildroot rootfs (FPU enabled)"
  INITRAMFS_DESC="Buildroot full root filesystem (cpio + gzip) — includes bash, openssh, htop, etc."
  FPU_NOTE="Buildroot userspace is compiled with hard-float ABI (\`ilp32d\` / \`lp64d\`), so **CONFIG_FPU is enabled** in this kernel. The effective kernel ISA is \`rv${BITS}imafd\` (not just \`imac\`)."
  QEMU_MEM="1024M"
  QEMU_NET_LINE=$'\\\n    -netdev user,id=net0,hostfwd=tcp::2222-:22 \\\n    -device virtio-net-device,netdev=net0'
  QEMU_SSH_NOTE=$'\nSSH into guest: \`ssh root@localhost -p 2222\`'
else
  TITLE_ISA="rv${BITS}imac"
  TITLE_SUFFIX="simple initramfs (no FPU)"
  INITRAMFS_DESC="Minimal root filesystem with init_loop only (cpio + gzip)"
  FPU_NOTE="FPU is disabled; your toolchain should target \`rv${BITS}imac\` / \`${RISCV_ABI}\`."
  QEMU_MEM="512M"
  QEMU_NET_LINE=""
  QEMU_SSH_NOTE=""
fi

cat <<EOF
# Linux ${KERNEL_VERSION} for RISC-V ${TITLE_ISA} — ${TITLE_SUFFIX}

| Field   | Value |
|---------|-------|
| Config  | \`${PRESET:-default}\` |
| Kernel ISA | \`${TITLE_ISA}\` (OpenSBI ISA: \`${RISCV_ISA}\`) |
| ABI     | \`${RISCV_ABI}\` |
| Variant | ${VARIANT} |
| Build   | $(date +%Y-%m-%d) |

## Files

| File | Description |
|------|-------------|
| \`fw_payload.bin\` | OpenSBI firmware with Linux kernel embedded — QEMU one-shot boot |
| \`fw_payload.elf\` | OpenSBI + kernel ELF for Spike simulator |
| \`fw_dynamic.bin\` | OpenSBI dynamic firmware (use alongside a separate kernel \`Image\`) |
| \`Image\` | Linux kernel image (${TITLE_ISA}) |
| \`initramfs.cpio.gz\` | ${INITRAMFS_DESC} |
| \`vmlinux\` | Unstripped kernel ELF with debug symbols — for use with GDB / JTAG |

## Quickstart

### 1. QEMU — single-file boot with \`fw_payload.bin\` (simplest)

\`\`\`bash
qemu-system-riscv${BITS} -M virt -m ${QEMU_MEM} -nographic \\
    -bios fw_payload.bin${QEMU_NET_LINE}
\`\`\`
${QEMU_SSH_NOTE}

### 2. QEMU — separate kernel + initramfs (\`fw_dynamic\` + \`Image\`)

\`\`\`bash
qemu-system-riscv${BITS} -M virt -m ${QEMU_MEM} -nographic \\
    -bios fw_dynamic.bin \\
    -kernel Image \\
    -initrd initramfs.cpio.gz \\
    -append "root=/dev/ram rdinit=/init console=ttyS0 earlycon=sbi"${QEMU_NET_LINE}
\`\`\`

### 3. Spike — ISA simulator

\`\`\`bash
spike --isa=${RISCV_ISA} -m512 fw_payload.elf
\`\`\`

## Notes

- ${FPU_NOTE}
- Press **Ctrl-A X** to quit QEMU.
- Spike requires riscv-isa-sim with rv${BITS} support.
  Build guide: <https://github.com/riscv-software-src/riscv-isa-sim>
EOF
