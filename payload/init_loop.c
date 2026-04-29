/*
 * Minimal PID-1 init: print a boot marker, then spin forever.
 *
 * Built with -nostdlib, so we use raw Linux syscalls and define _start
 * directly as the ELF entry point.
 */
static long sys_write(int fd, const void *buf, unsigned long len)
{
    register long a0 __asm__("a0") = fd;
    register const void *a1 __asm__("a1") = buf;
    register unsigned long a2 __asm__("a2") = len;
    register long a7 __asm__("a7") = 64; /* __NR_write on riscv */

    __asm__ volatile ("ecall"
                      : "+r"(a0)
                      : "r"(a1), "r"(a2), "r"(a7)
                      : "memory");
    return a0;
}

void __attribute__((noreturn)) _start(void)
{
    static const char msg[] = "init_loop: entered /init, spinning...\n";
    (void)sys_write(1, msg, sizeof(msg) - 1);

    for (;;) {
        __asm__ volatile("j .");
    }
}
