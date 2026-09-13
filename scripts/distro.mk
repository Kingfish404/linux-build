# RV64 upstream distribution userspace, stored on a persistent raw ext4 disk.
SKOPEO ?= skopeo## Download upstream OCI images without executing them on the host
DISTRO_BUILD_OPTIONS ?=## Extra rootfs builder flags
DISTRO_PRESET ?= $(PWD_DIR)/configs/$(SYSTEM_PRESET).toml
DISTRO_IMAGE := $(BUILD_ROOT)/$(SYSTEM_PRESET)/rootfs.ext4

check_distro:
	@test "$(BITS)" = 64 -a -n "$(filter alpine debian,$(SYSTEM_ROOTFS))" || { echo 'Select an RV64 Alpine/Debian preset first.'; exit 1; }

build_distro_kernel: check_distro
	$(MAKE) KERNEL_VARIANT=distro build_linux
	$(MAKE) KERNEL_VARIANT=distro build_opensbi

build_distro_rootfs: build_distro_kernel ## Provision upstream packages inside RV64 QEMU (preserve existing disks)
	python3 scripts/build-distro.py --preset "$(DISTRO_PRESET)" --output "$(DISTRO_IMAGE)" \
		--kernel "$(KERNEL_IMAGE)" --firmware "$(FW_DYNAMIC_BIN)" --skopeo "$(SKOPEO)" $(DISTRO_BUILD_OPTIONS)

build_distro: build_distro_rootfs ## Build distribution disk, independent kernel and OpenSBI

test_qemu_distro: check_distro ## Boot the selected persistent distribution disk (console root shell)
	$(call require,$(DISTRO_IMAGE),Run make build_distro first.)
	$(call require,$(KERNEL_IMAGE),Run make build_distro first.)
	$(call require,$(FW_DYNAMIC_BIN),Run make build_distro first.)
	$(IF_TIMEOUT) qemu-system-riscv64 -M virt -m $(QEMU_MEM)M -nographic \
		-bios $(FW_DYNAMIC_BIN) -kernel $(KERNEL_IMAGE) \
		-drive file=$(DISTRO_IMAGE),format=raw,if=none,id=rootfs \
		-device virtio-blk-device,drive=rootfs $(QEMU_NET) $(QEMU_SHARE) \
		-append "root=/dev/vda rootfstype=ext4 rw rootwait init=/sbin/raptor-init console=ttyS0 earlycon=sbi"

.PHONY: check_distro build_distro_kernel build_distro_rootfs build_distro test_qemu_distro

# Release disks are separate from the writable development guest. Packaging
# verifies that this disk still matches its original build hash.
DISTRO_RELEASE_IMAGE := $(BUILD_ROOT)/release-rootfs/$(SYSTEM_PRESET)/rootfs.ext4
package_distro: build_distro_kernel
	python3 scripts/build-distro.py --preset "$(DISTRO_PRESET)" --output "$(DISTRO_RELEASE_IMAGE)" \
		--kernel "$(KERNEL_IMAGE)" --firmware "$(FW_DYNAMIC_BIN)" --skopeo "$(SKOPEO)" --pristine $(DISTRO_BUILD_OPTIONS)
	python3 scripts/package-distro.py --preset "$(DISTRO_PRESET)" --disk "$(DISTRO_RELEASE_IMAGE)" \
		--kernel-dir "$(OBJDIR)" --firmware-dir "$(OPENSBI_OBJDIR)/platform/generic/firmware" --dist "$(DIST_DIR)"

.PHONY: package_distro
