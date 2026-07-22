# Build target bitness: 32 or 64 (default: 32, inherited from parent Makefile)
BITS ?= 32

# Cross-compiler prefix (default: riscv64-linux-gnu-, inherited from parent Makefile)
CROSS_COMPILE ?= riscv64-linux-gnu-

CC := $(CROSS_COMPILE)gcc

ifeq ($(BITS),64)
  CFLAGS := -march=rv64imac_zicsr_zifencei -mabi=lp64 -nostdlib -ffreestanding -fno-builtin
else
  CFLAGS := -march=rv32ima_zicsr_zifencei_zicntr -mabi=ilp32 -nostdlib -ffreestanding -fno-builtin
endif

LDFLAGS := -Wl,-e,_start -static
BUILD_DIR := build/$(BITS)
OBJECT_NAMES := tiny_shell.o syscall.o util.o commands.o net.o transfer.o
OBJECTS := $(addprefix $(BUILD_DIR)/,$(OBJECT_NAMES))
DEPENDENCIES := $(OBJECTS:.o=.d)

tiny_shell: init_shell

init_shell: FORCE $(OBJECTS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJECTS)

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -Wall -Wextra -Werror -MMD -MP -c -o $@ $<

$(BUILD_DIR):
	mkdir -p $@

clean:
	rm -rf init init_shell build

FORCE:

-include $(DEPENDENCIES)

.PHONY: tiny_shell clean FORCE
