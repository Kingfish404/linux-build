SHELL := /bin/bash
PWD_DIR=$(abspath .)

# ---------------------------------------------------------------------------
# Declarative build: include generated config if present.
# Run `make configure SYSTEM=configs/<preset>.toml` to generate .config.mk
# from a system.toml file.  All variables below use ?= so the generated
# config wins when present.
# ---------------------------------------------------------------------------
-include $(PWD_DIR)/.config.mk

KERNEL_VERSION ?= 6.18.20

# Internal: target bitness, set automatically by .config.mk (default: 32)
BITS ?= 32

# Host architecture detection
HOST_ARCH := $(shell uname -m)

# Cross-compiler and target ISA selection based on BITS and HOST_ARCH:
#   32-bit: always cross-compile with riscv64-linux-gnu- (works on any host)
#   64-bit: cross-compile with riscv64-linux-gnu- unless running natively on riscv64
ifeq ($(BITS),64)
  ifeq ($(HOST_ARCH),riscv64)
    CROSS_COMPILE ?=
  else
    CROSS_COMPILE ?= riscv64-linux-gnu-
  endif
  RISCV_XLEN  := 64
  RISCV_ISA   := rv64imac_zicntr_zicsr_zifencei
  RISCV_ABI   := lp64
else
  BITS         := 32
  CROSS_COMPILE ?= riscv64-linux-gnu-
  RISCV_XLEN  := 32
  RISCV_ISA   := rv32imac_zicntr_zicsr_zifencei
  RISCV_ABI   := ilp32
endif

# Declarative build variables (set by .config.mk or defaults)
SYSTEM_PRESET   ?=
SYSTEM_ROOTFS   ?= initramfs
SYSTEM_COMPRESS ?= gzip
SYSTEM_LOADER   ?= qemu

# Buildroot variant ISA/ABI (set by .config.mk, defaults match RISCV_ISA/ABI)
RISCV_ISA_BUILDROOT ?= $(RISCV_ISA)
RISCV_ABI_BUILDROOT ?= $(RISCV_ABI)

# Per-bitness output directories so 32 and 64 builds coexist
OBJDIR         := $(PWD_DIR)/build$(BITS)
OPENSBI_OBJDIR := $(PWD_DIR)/opensbi-build$(BITS)

# Per-bitness initramfs outputs (simple = init_loop)
INITRAMFS_DIR  := $(PWD_DIR)/initramfs$(BITS)
INITRAMFS_CPIO := $(PWD_DIR)/initramfs$(BITS).cpio.gz

# Spike (riscv-isa-sim) source and build directories
SPIKE_DIR   := $(PWD_DIR)/spike
SPIKE_BUILD := $(PWD_DIR)/spike-build
# Use the locally-built spike when available, fall back to PATH
SPIKE       := $(if $(wildcard $(SPIKE_BUILD)/bin/spike),$(SPIKE_BUILD)/bin/spike,spike)

NPROC     := $(shell nproc)
QEMU_MEM     ?= 512
# Optional: set QEMU_TIMEOUT=N (seconds) to auto-exit after N seconds.
# Default is empty (run until Ctrl-C or guest halts).
QEMU_TIMEOUT ?=
SPIKE_MEM    ?= 512

# Prefix command with timeout if QEMU_TIMEOUT is set
IF_TIMEOUT = $(if $(QEMU_TIMEOUT),timeout $(QEMU_TIMEOUT),)

# Derive kernel major version for download URL (e.g. 6.18.15 → v6.x, 7.0.1 → v7.x)
KERNEL_MAJOR := v$(firstword $(subst ., ,$(KERNEL_VERSION))).x

# Release package name and output tarball path
# Include config preset name when available (e.g. linux-riscv-rv32-qemu-rv32-v6.18.20)
ifneq ($(SYSTEM_PRESET),)
  RELEASE_NAME    := linux-riscv-rv$(BITS)-$(SYSTEM_PRESET)-v$(KERNEL_VERSION)
else
  RELEASE_NAME    := linux-riscv-rv$(BITS)-v$(KERNEL_VERSION)
endif
RELEASE_TARBALL := $(PWD_DIR)/dist/$(RELEASE_NAME).tar.gz
# Staging directory under dist/ (cleaned after tarball is created)
RELEASE_STAGING := $(PWD_DIR)/dist/$(RELEASE_NAME)

# Linux kernel source directory (versioned so multiple kernels can coexist)
LINUX_DIR := $(PWD_DIR)/linux/linux-$(KERNEL_VERSION)

# All kernel make invocations use a separate output dir via O=
KERNEL_MAKE := make -C $(LINUX_DIR) O=$(OBJDIR) ARCH=riscv CROSS_COMPILE=$(CROSS_COMPILE) -j$(NPROC)
# scripts/config wrapper that operates on the per-bitness .config
KCONFIG := $(LINUX_DIR)/scripts/config --file $(OBJDIR)/.config

# ---------------------------------------------------------------------------
# Shorthand paths (used throughout targets and error checks)
# ---------------------------------------------------------------------------
KERNEL_IMAGE   := $(OBJDIR)/arch/riscv/boot/Image
FW_PAYLOAD_BIN := $(OPENSBI_OBJDIR)/platform/generic/firmware/fw_payload.bin
FW_PAYLOAD_ELF := $(OPENSBI_OBJDIR)/platform/generic/firmware/fw_payload.elf
FW_DYNAMIC_BIN := $(OPENSBI_OBJDIR)/platform/generic/firmware/fw_dynamic.bin

# Common OpenSBI make arguments (shared by build_opensbi and build_opensbi_with_kernel)
OPENSBI_MAKE = make -C opensbi \
	O=$(OPENSBI_OBJDIR) \
	PLATFORM_RISCV_ISA=$(RISCV_ISA) \
	CROSS_COMPILE=$(CROSS_COMPILE) \
	PLATFORM_RISCV_XLEN=$(RISCV_XLEN) \
	PLATFORM=generic \
	-j$(NPROC)

# Error-check helpers
#   $(call require,file,hint)      — assert a file exists
#   $(call require_cmd,cmd,hint)   — assert a command is in PATH
define require
	@test -f $(1) || (echo "ERROR: $(notdir $(1)) not found. $(2)" && false)
endef
define require_cmd
	@command -v $(1) >/dev/null 2>&1 || (echo "ERROR: '$(1)' not found. $(2)" && false)
endef

# QEMU kernel boot arguments (split-load mode: fw_dynamic + separate Image + initramfs)
QEMU_KERNEL_ARGS = \
	-bios $(FW_DYNAMIC_BIN) \
	-kernel $(KERNEL_IMAGE) \
	-initrd $(INITRAMFS_CPIO) \
	-append "root=/dev/ram rdinit=/init console=ttyS0 earlycon=sbi"

# ---------------------------------------------------------------------------
# Buildroot targets and variables (uses variables defined above)
# ---------------------------------------------------------------------------
include scripts/buildroot.mk

# Default target: show usage
.DEFAULT_GOAL := help

help:
	@echo "PWD:           $(PWD_DIR)"
	@echo "Kernel:        $(KERNEL_VERSION)"
	@echo "Host arch:     $(HOST_ARCH)"
	@echo "Target bits:   $(BITS)"
	@echo "Cross-compile: $(if $(CROSS_COMPILE),$(CROSS_COMPILE),(native))"
	@echo "Kernel objdir: $(OBJDIR)"
	@echo "Initramfs:     $(INITRAMFS_CPIO)"
	@echo "Config:        $(if $(wildcard $(PWD_DIR)/.config.mk),.config.mk loaded,(none — use 'make configure'))"
	@echo ""
	@echo "--- Declarative Build (recommended) ---"
	@echo "  configure SYSTEM=<toml>      - Parse system.toml → generate .config.{mk,kernel,buildroot}"
	@echo "  build                        - Full build driven by .config.mk (kernel+rootfs+firmware)"
	@echo "  test                         - Boot in emulator per config (QEMU or Spike)"
	@echo "  clean_config                 - Remove generated .config.* files"
	@echo ""
	@echo "  Available presets:"
	@for f in configs/*.toml; do echo "    $$f"; done 2>/dev/null
	@echo ""
	@echo "--- Source ---"
	@echo "  linux                        - Download and extract Linux kernel source"
	@echo "  opensbi                      - Clone OpenSBI source"
	@echo "  buildroot                    - Clone Buildroot source ($(BITS)-bit)"
	@echo "  spike_src                    - Clone Spike (riscv-isa-sim) source"
	@echo ""
	@echo "--- Kernel ---"
	@echo "  build_linux                  - Build Linux kernel (rv$(BITS)imac no-FPU)"
	@echo ""
	@echo "--- Initramfs ---"
	@echo "  make_initramfs_simple        - Build init_loop initramfs ($(BITS)-bit)"
	@echo "  make_initramfs_buildroot     - Build Buildroot initramfs (incremental)"
	@echo "  make_initramfs_buildroot_clean- Full clean Buildroot rebuild (slow)"
	@echo "  install_initramfs            - Embed simple INITRAMFS_CPIO into kernel and rebuild"
	@echo "  install_initramfs_buildroot  - Embed Buildroot CPIO into kernel and rebuild"
	@echo "  update_buildroot             - Rebuild Buildroot only (fastest iteration)"
	@echo "  update_buildroot_full        - Rebuild Buildroot + re-embed + OpenSBI"
	@echo "  build_init                   - Build the init_loop ELF ($(BITS)-bit)"
	@echo ""
	@echo "--- Firmware ---"
	@echo "  build_opensbi                - Build OpenSBI only ($(BITS)-bit)"
	@echo "  build_opensbi_with_kernel    - Build OpenSBI + kernel FW_PAYLOAD ($(BITS)-bit)"
	@echo "  build_spike                  - Build Spike simulator from source"
	@echo ""
	@echo "--- Test ---"
	@echo "  test_qemu                    - Boot fw_payload.bin in QEMU ($(BITS)-bit)"
	@echo "  test_qemu_kernel             - Boot kernel+initramfs separately in QEMU ($(BITS)-bit)"
	@echo "  test_spike                   - Boot fw_payload.elf in Spike ($(BITS)-bit) [auto-uses local build]"
	@echo "  Spike binary: $(SPIKE)"
	@echo ""
	@echo "--- Batch ---"
	@echo "  build_all                    - Build Linux + OpenSBI for both 32 and 64 bit"
	@echo "  clean                        - Remove all build artefacts"
	@echo ""
	@echo "--- Package & Release ---"
	@echo "  package                      - Bundle rv$(BITS) simple artifacts → $(RELEASE_TARBALL)"
	@echo "  package_buildroot            - Bundle rv$(BITS) buildroot artifacts → $(BUILDROOT_RELEASE_TARBALL)"
	@echo "  package_all                  - Bundle rv32 + rv64 tarballs (simple + buildroot)"
	@echo "  github_release               - Create GitHub Release and upload tarballs (requires gh CLI)"
	@echo "  clean_packages               - Remove release tarballs from workspace"
	@echo ""
	@echo "Examples:"
	@echo "  make configure SYSTEM=configs/qemu-rv64.toml && make build && make test"
	@echo "  make configure SYSTEM=configs/qemu-rv32.toml && make build && make test"
	@echo "  make test_qemu_kernel_buildroot     # boot buildroot variant"
	@echo "  make BITS=64 test_qemu              # quick re-test with explicit bitness"
	@echo "  make BITS=32 test_spike              # test a specific arch in Spike"
	@echo "  make package_all"
	@echo "  make github_release TAG=v$(KERNEL_VERSION)"

# Alias so 'make all' also prints help (use build_all for actual builds)
all: help

# ---------------------------------------------------------------------------
# Declarative build targets
# ---------------------------------------------------------------------------
#
# make configure SYSTEM=configs/<preset>.toml   — parse TOML → .config.{mk,kernel,buildroot}
# make build                                    — full build driven by .config.mk
# make test                                     — boot in QEMU/Spike per config
# make clean_config                             — remove generated .config.* files
#
# All existing imperative targets (build_linux, test_qemu, etc.) remain usable
# and automatically pick up .config.mk overrides when present.
# ---------------------------------------------------------------------------

# Path to system.toml (set on command line: make configure SYSTEM=...)
SYSTEM ?=

configure:
	@if [ -z "$(SYSTEM)" ]; then \
		echo "Usage: make configure SYSTEM=configs/<preset>.toml"; \
		echo ""; \
		echo "Available presets:"; \
		ls -1 configs/*.toml 2>/dev/null | sed 's/^/  /'; \
		false; \
	fi
	python3 scripts/gen-config.py $(SYSTEM) --out-dir $(PWD_DIR)
	@echo ""
	@echo "Next: make build"

# Apply generated kernel config fragment via scripts/config
# Usage: $(call apply_kconfig_fragment,/path/to/fragment)
define apply_kconfig_fragment
	@if [ -f $(1) ]; then \
		echo "Applying kernel config fragment: $(1)"; \
		while IFS= read -r line; do \
			case "$$line" in \
				''|\#*) ;; \
				\#\ CONFIG_*\ is\ not\ set) \
					key=$$(echo "$$line" | sed 's/^# \(CONFIG_[A-Za-z0-9_]*\) is not set/\1/'); \
					$(KCONFIG) --disable $$key ;; \
				CONFIG_*=y) \
					key=$$(echo "$$line" | cut -d= -f1); \
					$(KCONFIG) --enable $$key ;; \
				CONFIG_*=*) \
					key=$$(echo "$$line" | cut -d= -f1); \
					val=$$(echo "$$line" | cut -d= -f2- | tr -d '"'); \
					$(KCONFIG) --set-val $$key $$val ;; \
			esac; \
		done < $(1); \
	fi
endef

# Shorthand paths to generated config fragments
KERNEL_CFG          := $(PWD_DIR)/.config.kernel
KERNEL_CFG_MINIMAL  := $(PWD_DIR)/.config.kernel.minimal
KERNEL_CFG_BUILDROOT := $(PWD_DIR)/.config.kernel.buildroot

# Unified build: always builds minimal; also builds buildroot when .config.buildroot exists
build: linux opensbi
	# --- Minimal variant ---
	$(MAKE) build_linux
	$(MAKE) make_initramfs_simple
	$(MAKE) install_initramfs
	$(MAKE) build_opensbi_with_kernel
	# --- Buildroot variant (if .config.buildroot exists) ---
	@if [ -f $(PWD_DIR)/.config.buildroot ]; then \
		echo "--- Building buildroot variant ---"; \
		$(MAKE) make_initramfs_buildroot; \
	else \
		echo "--- Skipping buildroot (no .config.buildroot) ---"; \
	fi
	@echo ""
	@echo "Build complete.  Run: make test"

# Unified test: boot minimal variant in emulator per config
test:
ifeq ($(SYSTEM_LOADER),spike)
	$(MAKE) test_spike
else
	$(MAKE) test_qemu_kernel
endif

clean_config:
	rm -f $(PWD_DIR)/.config.mk $(PWD_DIR)/.config.kernel \
	     $(PWD_DIR)/.config.kernel.minimal $(PWD_DIR)/.config.kernel.buildroot \
	     $(PWD_DIR)/.config.buildroot
	@echo "Declarative config removed."

# ---------------------------------------------------------------------------
# Source acquisition
# ---------------------------------------------------------------------------

linux:
	@if [ -d $(LINUX_DIR) ]; then echo "$(LINUX_DIR) already exists, skipping download"; else \
		mkdir -p $(PWD_DIR)/linux && \
		wget https://cdn.kernel.org/pub/linux/kernel/$(KERNEL_MAJOR)/linux-$(KERNEL_VERSION).tar.xz && \
		tar -xf linux-$(KERNEL_VERSION).tar.xz -C $(PWD_DIR)/linux && \
		rm linux-$(KERNEL_VERSION).tar.xz; \
	fi

opensbi:
	@if [ -d opensbi ]; then echo "opensbi/ already exists, skipping clone"; else \
		git clone https://github.com/riscv-software-src/opensbi; \
	fi

spike_src:
	@if [ -d spike ]; then echo "spike/ already exists, skipping clone"; else \
		git clone https://github.com/riscv-software-src/riscv-isa-sim spike; \
	fi

build_spike: spike_src
	mkdir -p $(SPIKE_BUILD)
	cd $(SPIKE_BUILD) && $(SPIKE_DIR)/configure --prefix=$(SPIKE_BUILD)
	$(MAKE) -C $(SPIKE_BUILD) -j$(NPROC)
	$(MAKE) -C $(SPIKE_BUILD) install
	@echo "Spike built: $(SPIKE_BUILD)/bin/spike"

# ---------------------------------------------------------------------------
# Kernel build
# ---------------------------------------------------------------------------

build_linux: linux
	mkdir -p $(OBJDIR)
	$(KERNEL_MAKE) defconfig
	# Apply shared + minimal kernel config from generated fragments
	$(call apply_kconfig_fragment,$(KERNEL_CFG))
	$(call apply_kconfig_fragment,$(KERNEL_CFG_MINIMAL))
	$(KERNEL_MAKE) olddefconfig
	$(KERNEL_MAKE)

# ---------------------------------------------------------------------------
# Simple initramfs (init_loop only)
# ---------------------------------------------------------------------------

# Build just the init_loop ELF binary into payload/
build_init:
	make -C payload BITS=$(BITS) CROSS_COMPILE=$(CROSS_COMPILE) init_loop

# ---------------------
# Simple initramfs (init_loop)
# Calls build_init then assembles a minimal root FS and packs it.
# ---------------------
make_initramfs_simple:
	$(MAKE) build_init
	mkdir -p $(INITRAMFS_DIR)/{bin,dev,etc,lib,lib64,mnt/root,proc,root,sbin,sys,run}
	cp payload/init $(INITRAMFS_DIR)/init
	# Create device nodes (idempotent, requires sudo)
	sudo mknod -m 600 $(INITRAMFS_DIR)/dev/console c 5 1 2>/dev/null || true
	sudo mknod -m 666 $(INITRAMFS_DIR)/dev/null   c 1 3 2>/dev/null || true
	sudo mknod -m 660 $(INITRAMFS_DIR)/dev/sda    b 8 0 2>/dev/null || true
	# Pack into cpio.gz
	(cd $(INITRAMFS_DIR) && find . | cpio -o --format=newc | gzip > $(INITRAMFS_CPIO))
	@echo "Simple initramfs: $(INITRAMFS_CPIO)"

# ---------------------------------------------------------------------------
# Embed initramfs into kernel Image (CONFIG_INITRAMFS_SOURCE)
# ---------------------------------------------------------------------------

install_initramfs:
	$(call require,$(INITRAMFS_CPIO),Run make_initramfs_simple first.)
	$(KCONFIG) --set-str CONFIG_INITRAMFS_SOURCE $(INITRAMFS_CPIO)
	$(KERNEL_MAKE) olddefconfig
	$(KERNEL_MAKE)
	@echo "Kernel with embedded initramfs: $(KERNEL_IMAGE)"

# ---------------------------------------------------------------------------
# OpenSBI firmware
# ---------------------------------------------------------------------------

build_opensbi: opensbi
	$(OPENSBI_MAKE)

build_opensbi_with_kernel: opensbi
	$(OPENSBI_MAKE) FW_PAYLOAD_PATH=$(KERNEL_IMAGE)

# ---------------------------------------------------------------------------
# QEMU tests
# ---------------------------------------------------------------------------
#
# test_qemu:        boot the self-contained fw_payload (OpenSBI + kernel embedded)
# test_qemu_kernel: boot OpenSBI fw_dynamic + separate kernel Image + initramfs
#                   (useful to iterate without rebuilding firmware)

QEMU_BASE    := qemu-system-riscv$(BITS) -M virt -m $(QEMU_MEM)M -nographic

test_qemu:
	$(call require,$(FW_PAYLOAD_BIN),Run build_opensbi_with_kernel first.)
	$(IF_TIMEOUT) $(QEMU_BASE) -bios $(FW_PAYLOAD_BIN)

test_qemu_kernel:
	$(call require,$(KERNEL_IMAGE),Run build_linux first.)
	$(call require,$(INITRAMFS_CPIO),Run make_initramfs_simple or make_initramfs_buildroot first.)
	$(IF_TIMEOUT) $(QEMU_BASE) $(QEMU_KERNEL_ARGS)

# ---------------------------------------------------------------------------
# Spike tests
#
# Uses the locally-built Spike when spike-build/bin/spike exists (via build_spike),
# otherwise falls back to the system 'spike' in PATH.
# The generic OpenSBI fw_payload.elf works with Spike's built-in HTIF/SBI.
# ---------------------------------------------------------------------------

test_spike:
	@test -x $(SPIKE) 2>/dev/null || command -v $(SPIKE) >/dev/null 2>&1 || \
		(echo "ERROR: spike not found. Run 'make build_spike' or install from https://github.com/riscv-software-src/riscv-isa-sim" && false)
	$(call require,$(FW_PAYLOAD_ELF),Run build_opensbi_with_kernel first.)
	$(SPIKE) --isa=$(RISCV_ISA) -m$(SPIKE_MEM) $(FW_PAYLOAD_ELF)

# ---------------------------------------------------------------------------
# Batch and housekeeping
# ---------------------------------------------------------------------------

build_all: linux opensbi
	$(MAKE) BITS=32 build_linux make_initramfs_simple install_initramfs build_opensbi_with_kernel
	$(MAKE) BITS=64 build_linux make_initramfs_simple install_initramfs build_opensbi_with_kernel

# ---------------------------------------------------------------------------
# Package: bundle build artifacts into a distributable tarball
#
# Usage:
#   make BITS=32 package   → linux-riscv-rv32-v<ver>.tar.gz
#   make BITS=64 package   → linux-riscv-rv64-v<ver>.tar.gz
#   make package_all       → both tarballs
# ---------------------------------------------------------------------------

package: linux opensbi
	@echo "--- Packaging simple initramfs artifacts for rv$(BITS) ---"
	$(call require,$(KERNEL_IMAGE),Run build_linux first.)
	# Build simple initramfs if not already present
	@test -f $(INITRAMFS_CPIO) || $(MAKE) make_initramfs_simple
	# Apply minimal kernel config, re-embed initramfs, rebuild
	$(call apply_kconfig_fragment,$(KERNEL_CFG_MINIMAL))
	$(KCONFIG) --set-str CONFIG_INITRAMFS_SOURCE $(INITRAMFS_CPIO)
	$(KERNEL_MAKE) olddefconfig
	$(KERNEL_MAKE)
	$(MAKE) build_opensbi_with_kernel
	@echo "--- Assembling $(RELEASE_NAME) ---"
	rm -rf $(RELEASE_STAGING)
	mkdir -p $(RELEASE_STAGING)
	cp $(FW_PAYLOAD_BIN) $(FW_PAYLOAD_ELF) $(FW_DYNAMIC_BIN) $(RELEASE_STAGING)/
	cp $(KERNEL_IMAGE) $(RELEASE_STAGING)/
	cp $(INITRAMFS_CPIO) $(RELEASE_STAGING)/initramfs.cpio.gz
	cp $(OBJDIR)/vmlinux $(RELEASE_STAGING)/
	bash scripts/gen-package-readme.sh $(BITS) $(KERNEL_VERSION) $(RISCV_ISA) $(RISCV_ABI) simple $(SYSTEM_PRESET) \
		> $(RELEASE_STAGING)/README.md
	tar -czf $(RELEASE_TARBALL) -C $(PWD_DIR)/dist $(RELEASE_NAME)
	@echo "Package ready: $(RELEASE_TARBALL)"

package_all:
	$(MAKE) package
	-$(MAKE) package_buildroot
	@echo ""
	@echo "Packages created under dist/:"
	@ls -1 $(PWD_DIR)/dist/*.tar.gz 2>/dev/null | sed 's/^/  /'

# ---------------------------------------------------------------------------
# GitHub Release  (requires the 'gh' CLI: https://cli.github.com)
#
# Usage:
#   make github_release                    # tag = <preset>-v<KERNEL_VERSION>
#   make github_release TAG=v6.18.15-rc1  # custom tag
#
# All tarballs must exist (run 'make package_all' first).
# ---------------------------------------------------------------------------

TAG ?= rv-v$(KERNEL_VERSION)

github_release:
	$(call require_cmd,gh,Install from https://cli.github.com)
	@echo "--- Creating GitHub Release $(TAG) ---"
	$(eval RELEASE_FILES := $(wildcard $(PWD_DIR)/dist/*.tar.gz))
	@test -n "$(RELEASE_FILES)" || (echo "ERROR: No tarballs found in dist/. Run 'make package_all' first." && false)
	gh release create $(TAG) \
		$(RELEASE_FILES) \
		--title "Linux $(KERNEL_VERSION) for RISC-V" \
		--notes $$'Pre-built Linux $(KERNEL_VERSION) kernels for RISC-V.\n\nMinimal variants: rv32imac / rv64imac (FPU disabled).\nBuildroot variants: rv32imafd / rv64imafd (FPU enabled for hard-float userspace).\n\nSee README.md inside each tarball for boot instructions (QEMU / Spike).'
	@echo "Release $(TAG) published."

clean_packages:
	rm -rf $(PWD_DIR)/dist
	@echo "dist/ removed."

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

clean:
	rm -rf linux/ build32 build64 \
		initramfs32 initramfs64 initramfs32.cpio.gz initramfs64.cpio.gz \
		initramfs32-buildroot.cpio.gz initramfs64-buildroot.cpio.gz \
		initramfs32-buildroot.stamp initramfs64-buildroot.stamp \
		opensbi opensbi-build32 opensbi-build64 \
		payload/build \
		.config.mk .config.kernel .config.kernel.minimal .config.kernel.buildroot .config.buildroot

clean_spike:
	rm -rf spike spike-build

.PHONY: help all \
        configure build test clean_config \
        linux opensbi spike_src \
        build_linux \
        build_init make_initramfs_simple \
        install_initramfs \
        build_opensbi build_opensbi_with_kernel build_spike \
        test_qemu test_qemu_kernel test_spike \
        build_all clean clean_spike \
        package package_all github_release clean_packages

