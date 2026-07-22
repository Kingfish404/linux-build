#ifndef TINY_SYSCALL_H
#define TINY_SYSCALL_H

#include "tiny.h"

#define AT_FDCWD (-100)
#define AT_REMOVEDIR 0x200
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 00000100
#define O_TRUNC 00001000
#define O_DIRECTORY 00200000

#define AF_INET 2
#define SOCK_STREAM 1
#define SOCK_DGRAM 2
#define SOCK_RAW 3
#define IPPROTO_ICMP 1
#define SOL_SOCKET 1
#define SO_REUSEADDR 2
#define POLLIN 0x0001
#define POLLERR 0x0008
#define POLLHUP 0x0010

#define IFF_UP 0x1
#define IFF_RUNNING 0x40
#define SIOCGIFFLAGS 0x8913
#define SIOCGIFADDR 0x8915
#define SIOCGIFNETMASK 0x891b

#define LINUX_REBOOT_MAGIC1 0xfee1deadUL
#define LINUX_REBOOT_MAGIC2 672274793UL
#define LINUX_REBOOT_CMD_RESTART 0x01234567UL
#define LINUX_REBOOT_CMD_POWER_OFF 0x4321fedcUL

struct linux_dirent64 {
    u64 d_ino;
    s64 d_off;
    u16 d_reclen;
    u8 d_type;
    char d_name[];
};

struct sockaddr {
    u16 family;
    char data[14];
};

struct sockaddr_in {
    u16 family;
    u16 port;
    u32 address;
    u8 zero[8];
};

struct ifreq {
    char name[16];
    union {
        struct sockaddr address;
        short flags;
        char padding[24];
    } value;
};

struct pollfd {
    int fd;
    short events;
    short revents;
};

struct kernel_timespec {
    long seconds;
    long nanoseconds;
};

struct new_utsname {
    char sysname[65];
    char nodename[65];
    char release[65];
    char version[65];
    char machine[65];
    char domainname[65];
};

struct sysinfo {
    long uptime;
    unsigned long loads[3];
    unsigned long totalram;
    unsigned long freeram;
    unsigned long sharedram;
    unsigned long bufferram;
    unsigned long totalswap;
    unsigned long freeswap;
    u16 procs;
    u16 pad;
    unsigned long totalhigh;
    unsigned long freehigh;
    u32 mem_unit;
    char padding[20 - 2 * sizeof(unsigned long) - sizeof(u32)];
};

long sys_read(int fd, void *buffer, size_t count);
long sys_write(int fd, const void *buffer, size_t count);
long sys_openat(int dirfd, const char *path, long flags, long mode);
long sys_close(int fd);
long sys_fchmod(int fd, long mode);
long sys_unlinkat(int dirfd, const char *path, int flags);
long sys_ioctl(int fd, unsigned long request, void *argument);
long sys_getdents64(int fd, void *buffer, size_t count);
long sys_mkdirat(int dirfd, const char *path, long mode);
long sys_chdir(const char *path);
long sys_getcwd(char *buffer, size_t size);
long sys_mount(const char *source, const char *target, const char *type,
               unsigned long flags, const void *data);
long sys_nanosleep(const struct kernel_timespec *duration);
long sys_uname(struct new_utsname *name);
long sys_sysinfo(struct sysinfo *info);
long sys_reboot(unsigned long command);
long sys_socket(int domain, int type, int protocol);
long sys_bind(int fd, const struct sockaddr *address, unsigned int length);
long sys_listen(int fd, int backlog);
long sys_accept(int fd, struct sockaddr *address, unsigned int *length);
long sys_connect(int fd, const struct sockaddr *address, unsigned int length);
long sys_sendto(int fd, const void *buffer, size_t length,
                const struct sockaddr *address, unsigned int address_length);
long sys_recvfrom(int fd, void *buffer, size_t length);
long sys_setsockopt(int fd, int level, int option, const void *value,
                    unsigned int length);
long sys_ppoll(struct pollfd *fds, unsigned long count,
               const struct kernel_timespec *timeout);
long sys_clone(unsigned long flags, void *stack, int *parent_tid,
               int *child_tid, unsigned long tls);
long sys_execve(const char *path, char *const argv[], char *const envp[]);
long sys_wait4(int process_id, int *status, int options);
void sys_sync(void);
void sys_exit(int code) __attribute__((noreturn));

#endif
