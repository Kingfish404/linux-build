#include "syscall.h"

#define SYS_GETCWD 17
#define SYS_IOCTL 29
#define SYS_UNLINKAT 35
#define SYS_MKDIRAT 34
#define SYS_MOUNT 40
#define SYS_CHDIR 49
#define SYS_FCHMOD 52
#define SYS_OPENAT 56
#define SYS_CLOSE 57
#define SYS_GETDENTS64 61
#define SYS_READ 63
#define SYS_WRITE 64
#define SYS_PPOLL 73
#define SYS_SYNC 81
#define SYS_EXIT 93
#define SYS_NANOSLEEP 101
#define SYS_REBOOT 142
#define SYS_UNAME 160
#define SYS_SYSINFO 179
#define SYS_SOCKET 198
#define SYS_BIND 200
#define SYS_LISTEN 201
#define SYS_ACCEPT 202
#define SYS_CONNECT 203
#define SYS_SENDTO 206
#define SYS_RECVFROM 207
#define SYS_SETSOCKOPT 208
#define SYS_CLONE 220
#define SYS_EXECVE 221
#define SYS_WAIT4 260

static long syscall6(long number, long arg0, long arg1, long arg2,
                     long arg3, long arg4, long arg5)
{
    register long syscall_arg0 __asm__("a0") = arg0;
    register long syscall_arg1 __asm__("a1") = arg1;
    register long syscall_arg2 __asm__("a2") = arg2;
    register long syscall_arg3 __asm__("a3") = arg3;
    register long syscall_arg4 __asm__("a4") = arg4;
    register long syscall_arg5 __asm__("a5") = arg5;
    register long syscall_number __asm__("a7") = number;

    __asm__ volatile ("ecall"
                      : "+r"(syscall_arg0)
                      : "r"(syscall_arg1), "r"(syscall_arg2),
                        "r"(syscall_arg3), "r"(syscall_arg4),
                        "r"(syscall_arg5), "r"(syscall_number)
                      : "memory");
    return syscall_arg0;
}

long sys_read(int fd, void *buffer, size_t count)
{
    return syscall6(SYS_READ, fd, (long)buffer, count, 0, 0, 0);
}

long sys_write(int fd, const void *buffer, size_t count)
{
    return syscall6(SYS_WRITE, fd, (long)buffer, count, 0, 0, 0);
}

long sys_openat(int dirfd, const char *path, long flags, long mode)
{
    return syscall6(SYS_OPENAT, dirfd, (long)path, flags, mode, 0, 0);
}

long sys_close(int fd)
{
    return syscall6(SYS_CLOSE, fd, 0, 0, 0, 0, 0);
}

long sys_fchmod(int fd, long mode)
{
    return syscall6(SYS_FCHMOD, fd, mode, 0, 0, 0, 0);
}

long sys_unlinkat(int dirfd, const char *path, int flags)
{
    return syscall6(SYS_UNLINKAT, dirfd, (long)path, flags, 0, 0, 0);
}

long sys_ioctl(int fd, unsigned long request, void *argument)
{
    return syscall6(SYS_IOCTL, fd, request, (long)argument, 0, 0, 0);
}

long sys_getdents64(int fd, void *buffer, size_t count)
{
    return syscall6(SYS_GETDENTS64, fd, (long)buffer, count, 0, 0, 0);
}

long sys_mkdirat(int dirfd, const char *path, long mode)
{
    return syscall6(SYS_MKDIRAT, dirfd, (long)path, mode, 0, 0, 0);
}

long sys_chdir(const char *path)
{
    return syscall6(SYS_CHDIR, (long)path, 0, 0, 0, 0, 0);
}

long sys_getcwd(char *buffer, size_t size)
{
    return syscall6(SYS_GETCWD, (long)buffer, size, 0, 0, 0, 0);
}

long sys_mount(const char *source, const char *target, const char *type,
               unsigned long flags, const void *data)
{
    return syscall6(SYS_MOUNT, (long)source, (long)target, (long)type,
                    flags, (long)data, 0);
}

long sys_nanosleep(const struct kernel_timespec *duration)
{
    return syscall6(SYS_NANOSLEEP, (long)duration, 0, 0, 0, 0, 0);
}

long sys_uname(struct new_utsname *name)
{
    return syscall6(SYS_UNAME, (long)name, 0, 0, 0, 0, 0);
}

long sys_sysinfo(struct sysinfo *info)
{
    return syscall6(SYS_SYSINFO, (long)info, 0, 0, 0, 0, 0);
}

long sys_reboot(unsigned long command)
{
    return syscall6(SYS_REBOOT, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
                    command, 0, 0, 0);
}

long sys_socket(int domain, int type, int protocol)
{
    return syscall6(SYS_SOCKET, domain, type, protocol, 0, 0, 0);
}

long sys_bind(int fd, const struct sockaddr *address, unsigned int length)
{
    return syscall6(SYS_BIND, fd, (long)address, length, 0, 0, 0);
}

long sys_listen(int fd, int backlog)
{
    return syscall6(SYS_LISTEN, fd, backlog, 0, 0, 0, 0);
}

long sys_accept(int fd, struct sockaddr *address, unsigned int *length)
{
    return syscall6(SYS_ACCEPT, fd, (long)address, (long)length, 0, 0, 0);
}

long sys_connect(int fd, const struct sockaddr *address, unsigned int length)
{
    return syscall6(SYS_CONNECT, fd, (long)address, length, 0, 0, 0);
}

long sys_sendto(int fd, const void *buffer, size_t length,
                const struct sockaddr *address, unsigned int address_length)
{
    return syscall6(SYS_SENDTO, fd, (long)buffer, length, 0,
                    (long)address, address_length);
}

long sys_recvfrom(int fd, void *buffer, size_t length)
{
    return syscall6(SYS_RECVFROM, fd, (long)buffer, length, 0, 0, 0);
}

long sys_setsockopt(int fd, int level, int option, const void *value,
                    unsigned int length)
{
    return syscall6(SYS_SETSOCKOPT, fd, level, option, (long)value, length, 0);
}

long sys_ppoll(struct pollfd *fds, unsigned long count,
               const struct kernel_timespec *timeout)
{
    return syscall6(SYS_PPOLL, (long)fds, count, (long)timeout, 0, 0, 0);
}

long sys_clone(unsigned long flags, void *stack, int *parent_tid,
               int *child_tid, unsigned long tls)
{
    return syscall6(SYS_CLONE, flags, (long)stack, (long)parent_tid,
                    tls, (long)child_tid, 0);
}

long sys_execve(const char *path, char *const argv[], char *const envp[])
{
    return syscall6(SYS_EXECVE, (long)path, (long)argv, (long)envp, 0, 0, 0);
}

long sys_wait4(int process_id, int *status, int options)
{
    return syscall6(SYS_WAIT4, process_id, (long)status, options, 0, 0, 0);
}

void sys_sync(void)
{
    (void)syscall6(SYS_SYNC, 0, 0, 0, 0, 0, 0);
}

void sys_exit(int code)
{
    (void)syscall6(SYS_EXIT, code, 0, 0, 0, 0, 0);
    for (;;) {
        __asm__ volatile ("j .");
    }
}
