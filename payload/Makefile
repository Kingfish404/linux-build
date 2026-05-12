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

tiny_shell:
	$(CC) $(CFLAGS) $(LDFLAGS) -o init_shell tiny_shell.c

clean:
	rm -f init init_shell

.PHONY: tiny_shell clean
