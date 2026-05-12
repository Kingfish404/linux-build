typedef unsigned long size_t;
typedef unsigned long long u64;
typedef long long s64;

#define NULL ((void *)0)

#define AT_FDCWD (-100)
#define O_RDONLY 0
#define O_DIRECTORY 00200000

#define SYS_GETCWD 17
#define SYS_MKDIRAT 34
#define SYS_MOUNT 40
#define SYS_CHDIR 49
#define SYS_OPENAT 56
#define SYS_CLOSE 57
#define SYS_GETDENTS64 61
#define SYS_READ 63
#define SYS_WRITE 64
#define SYS_EXIT 93
#define SYS_REBOOT 142

#define LINUX_REBOOT_MAGIC1 0xfee1deadUL
#define LINUX_REBOOT_MAGIC2 672274793UL
#define LINUX_REBOOT_CMD_RESTART 0x01234567UL
#define LINUX_REBOOT_CMD_POWER_OFF 0x4321fedcUL

struct linux_dirent64 {
    u64 d_ino;
    s64 d_off;
    unsigned short d_reclen;
    unsigned char d_type;
    char d_name[];
};

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

static long sys_read(int fd, void *buf, size_t count)
{
    return syscall6(SYS_READ, fd, (long)buf, count, 0, 0, 0);
}

static long sys_write(int fd, const void *buf, size_t count)
{
    return syscall6(SYS_WRITE, fd, (long)buf, count, 0, 0, 0);
}

static long sys_openat(int dirfd, const char *path, long flags, long mode)
{
    return syscall6(SYS_OPENAT, dirfd, (long)path, flags, mode, 0, 0);
}

static long sys_close(int fd)
{
    return syscall6(SYS_CLOSE, fd, 0, 0, 0, 0, 0);
}

static long sys_getdents64(int fd, void *buf, size_t count)
{
    return syscall6(SYS_GETDENTS64, fd, (long)buf, count, 0, 0, 0);
}

static long sys_mkdirat(int dirfd, const char *path, long mode)
{
    return syscall6(SYS_MKDIRAT, dirfd, (long)path, mode, 0, 0, 0);
}

static long sys_chdir(const char *path)
{
    return syscall6(SYS_CHDIR, (long)path, 0, 0, 0, 0, 0);
}

static long sys_getcwd(char *buf, size_t size)
{
    return syscall6(SYS_GETCWD, (long)buf, size, 0, 0, 0, 0);
}

static long sys_mount(const char *source, const char *target,
                      const char *type, unsigned long flags, const void *data)
{
    return syscall6(SYS_MOUNT, (long)source, (long)target, (long)type,
                    flags, (long)data, 0);
}

static long sys_reboot(unsigned long command)
{
    return syscall6(SYS_REBOOT, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
                    command, 0, 0, 0);
}

static void sys_exit(int code)
{
    syscall6(SYS_EXIT, code, 0, 0, 0, 0, 0);
    for (;;) {
        __asm__ volatile ("j .");
    }
}

static size_t cstr_len(const char *text)
{
    size_t length = 0;
    while (text[length] != '\0') {
        length++;
    }
    return length;
}

static int cstr_eq(const char *left, const char *right)
{
    size_t offset = 0;
    while (left[offset] != '\0' && right[offset] != '\0') {
        if (left[offset] != right[offset]) {
            return 0;
        }
        offset++;
    }
    return left[offset] == right[offset];
}

static void puts_raw(const char *text)
{
    (void)sys_write(1, text, cstr_len(text));
}

static void put_line(const char *text)
{
    puts_raw(text);
    puts_raw("\n");
}

static void print_error(const char *command, const char *target)
{
    puts_raw(command);
    puts_raw(": failed");
    if (target != NULL) {
        puts_raw(": ");
        puts_raw(target);
    }
    puts_raw("\n");
}

static int is_space(char value)
{
    return value == ' ' || value == '\t' || value == '\r' || value == '\n';
}

static int read_line(char *line, size_t capacity)
{
    size_t length = 0;

    while (length + 1 < capacity) {
        char value;
        long count = sys_read(0, &value, 1);
        if (count <= 0) {
            return -1;
        }
        if (value == '\r') {
            continue;
        }
        if (value == '\n') {
            break;
        }
        line[length++] = value;
    }

    line[length] = '\0';
    return (int)length;
}

static int split_args(char *line, char **argv, int argv_capacity)
{
    int argc = 0;
    char *cursor = line;

    while (*cursor != '\0' && argc < argv_capacity - 1) {
        while (is_space(*cursor)) {
            *cursor = '\0';
            cursor++;
        }
        if (*cursor == '\0') {
            break;
        }
        argv[argc++] = cursor;
        while (*cursor != '\0' && !is_space(*cursor)) {
            cursor++;
        }
    }

    if (*cursor != '\0') {
        *cursor = '\0';
    }
    argv[argc] = NULL;
    return argc;
}

static void mount_defaults(void)
{
    (void)sys_mkdirat(AT_FDCWD, "/proc", 0755);
    (void)sys_mkdirat(AT_FDCWD, "/sys", 0755);
    (void)sys_mkdirat(AT_FDCWD, "/dev", 0755);
    (void)sys_mount("proc", "/proc", "proc", 0, "");
    (void)sys_mount("sysfs", "/sys", "sysfs", 0, "");
    (void)sys_mount("devtmpfs", "/dev", "devtmpfs", 0, "");
}

static void cmd_help(void)
{
    put_line("commands: help echo pwd cd ls cat mkdir mount clear reboot poweroff exit");
}

static void cmd_echo(int argc, char **argv)
{
    int arg_index = 1;
    while (arg_index < argc) {
        if (arg_index > 1) {
            puts_raw(" ");
        }
        puts_raw(argv[arg_index]);
        arg_index++;
    }
    puts_raw("\n");
}

static void cmd_pwd(void)
{
    char path[256];
    if (sys_getcwd(path, sizeof(path)) < 0) {
        print_error("pwd", NULL);
        return;
    }
    put_line(path);
}

static void cmd_ls(const char *path)
{
    char buffer[1024];
    long fd = sys_openat(AT_FDCWD, path, O_RDONLY | O_DIRECTORY, 0);
    if (fd < 0) {
        print_error("ls", path);
        return;
    }

    for (;;) {
        long bytes = sys_getdents64((int)fd, buffer, sizeof(buffer));
        if (bytes < 0) {
            print_error("ls", path);
            break;
        }
        if (bytes == 0) {
            break;
        }

        long offset = 0;
        while (offset < bytes) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buffer + offset);
            puts_raw(entry->d_name);
            if (entry->d_type == 4) {
                puts_raw("/");
            }
            puts_raw("  ");
            offset += entry->d_reclen;
        }
    }

    puts_raw("\n");
    (void)sys_close((int)fd);
}

static void cmd_cat(int argc, char **argv)
{
    char buffer[512];
    int arg_index = 1;

    if (argc < 2) {
        put_line("usage: cat PATH...");
        return;
    }

    while (arg_index < argc) {
        long fd = sys_openat(AT_FDCWD, argv[arg_index], O_RDONLY, 0);
        if (fd < 0) {
            print_error("cat", argv[arg_index]);
            arg_index++;
            continue;
        }

        for (;;) {
            long bytes = sys_read((int)fd, buffer, sizeof(buffer));
            if (bytes < 0) {
                print_error("cat", argv[arg_index]);
                break;
            }
            if (bytes == 0) {
                break;
            }
            (void)sys_write(1, buffer, (size_t)bytes);
        }

        (void)sys_close((int)fd);
        arg_index++;
    }
}

static void cmd_mount(int argc, char **argv)
{
    const char *source;

    if (argc == 1) {
        mount_defaults();
        put_line("mounted proc, sysfs and devtmpfs if available");
        return;
    }
    if (argc < 3) {
        put_line("usage: mount TYPE TARGET [SOURCE]");
        return;
    }

    source = argc >= 4 ? argv[3] : argv[1];
    if (sys_mount(source, argv[2], argv[1], 0, "") < 0) {
        print_error("mount", argv[2]);
    }
}

static void run_command(int argc, char **argv)
{
    if (argc == 0) {
        return;
    }
    if (cstr_eq(argv[0], "help")) {
        cmd_help();
    } else if (cstr_eq(argv[0], "echo")) {
        cmd_echo(argc, argv);
    } else if (cstr_eq(argv[0], "pwd")) {
        cmd_pwd();
    } else if (cstr_eq(argv[0], "cd")) {
        const char *path = argc >= 2 ? argv[1] : "/";
        if (sys_chdir(path) < 0) {
            print_error("cd", path);
        }
    } else if (cstr_eq(argv[0], "ls")) {
        cmd_ls(argc >= 2 ? argv[1] : ".");
    } else if (cstr_eq(argv[0], "cat")) {
        cmd_cat(argc, argv);
    } else if (cstr_eq(argv[0], "mkdir")) {
        if (argc < 2 || sys_mkdirat(AT_FDCWD, argv[1], 0755) < 0) {
            print_error("mkdir", argc >= 2 ? argv[1] : NULL);
        }
    } else if (cstr_eq(argv[0], "mount")) {
        cmd_mount(argc, argv);
    } else if (cstr_eq(argv[0], "clear")) {
        puts_raw("\033[2J\033[H");
    } else if (cstr_eq(argv[0], "reboot")) {
        (void)sys_reboot(LINUX_REBOOT_CMD_RESTART);
        print_error("reboot", NULL);
    } else if (cstr_eq(argv[0], "poweroff")) {
        (void)sys_reboot(LINUX_REBOOT_CMD_POWER_OFF);
        print_error("poweroff", NULL);
    } else if (cstr_eq(argv[0], "exit")) {
        put_line("PID 1 cannot exit cleanly; use poweroff or reboot");
    } else {
        puts_raw(argv[0]);
        put_line(": unknown command");
    }
}

void __attribute__((noreturn)) _start(void)
{
    char line[256];
    char *argv[16];

    mount_defaults();
    put_line("tinysh: initramfs shell ready. Type 'help'.");

    for (;;) {
        int argc;
        puts_raw("tinysh# ");
        if (read_line(line, sizeof(line)) < 0) {
            puts_raw("\n");
            continue;
        }
        argc = split_args(line, argv, 16);
        run_command(argc, argv);
    }

    sys_exit(0);
}
