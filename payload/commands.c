#include "commands.h"
#include "net.h"
#include "syscall.h"
#include "transfer.h"
#include "util.h"

struct command {
    const char *name;
    void (*handler)(int argc, char **argv);
};

void mount_defaults(void)
{
    (void)sys_mkdirat(AT_FDCWD, "/proc", 0755);
    (void)sys_mkdirat(AT_FDCWD, "/sys", 0755);
    (void)sys_mkdirat(AT_FDCWD, "/dev", 0755);
    (void)sys_mount("proc", "/proc", "proc", 0, "");
    (void)sys_mount("sysfs", "/sys", "sysfs", 0, "");
    (void)sys_mount("devtmpfs", "/dev", "devtmpfs", 0, "");
}

static void cmd_help(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    put_line("filesystem: pwd cd ls cat cp touch mkdir rm rmdir mount sync");
    put_line("system:     uname uptime free sleep run clear reboot poweroff exit");
    put_line("network:    ifconfig ping nc fetch");
}

static void cmd_echo(int argc, char **argv)
{
    int arg_index;
    for (arg_index = 1; arg_index < argc; arg_index++) {
        if (arg_index > 1) {
            puts_raw(" ");
        }
        puts_raw(argv[arg_index]);
    }
    puts_raw("\n");
}

static void cmd_pwd(int argc, char **argv)
{
    char path[256];
    (void)argc;
    (void)argv;
    if (sys_getcwd(path, sizeof(path)) < 0) {
        print_error("pwd", NULL);
        return;
    }
    put_line(path);
}

static void cmd_cd(int argc, char **argv)
{
    const char *path = argc >= 2 ? argv[1] : "/";
    if (sys_chdir(path) < 0) {
        print_error("cd", path);
    }
}

static void cmd_ls(int argc, char **argv)
{
    const char *path = argc >= 2 ? argv[1] : ".";
    char buffer[1024];
    long fd = sys_openat(AT_FDCWD, path, O_RDONLY | O_DIRECTORY, 0);

    if (fd < 0) {
        print_error("ls", path);
        return;
    }
    for (;;) {
        long bytes = sys_getdents64((int)fd, buffer, sizeof(buffer));
        long offset = 0;
        if (bytes <= 0) {
            if (bytes < 0) {
                print_error("ls", path);
            }
            break;
        }
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
    int arg_index;

    if (argc < 2) {
        put_line("usage: cat PATH...");
        return;
    }
    for (arg_index = 1; arg_index < argc; arg_index++) {
        long fd = sys_openat(AT_FDCWD, argv[arg_index], O_RDONLY, 0);
        if (fd < 0) {
            print_error("cat", argv[arg_index]);
            continue;
        }
        for (;;) {
            long bytes = sys_read((int)fd, buffer, sizeof(buffer));
            if (bytes <= 0) {
                if (bytes < 0) {
                    print_error("cat", argv[arg_index]);
                }
                break;
            }
            if (write_all(1, buffer, (size_t)bytes) < 0) {
                break;
            }
        }
        (void)sys_close((int)fd);
    }
}

static void cmd_cp(int argc, char **argv)
{
    char buffer[512];
    long source;
    long destination;

    if (argc != 3) {
        put_line("usage: cp SOURCE DEST");
        return;
    }
    source = sys_openat(AT_FDCWD, argv[1], O_RDONLY, 0);
    if (source < 0) {
        print_error("cp", argv[1]);
        return;
    }
    destination = sys_openat(AT_FDCWD, argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (destination < 0) {
        print_error("cp", argv[2]);
        (void)sys_close((int)source);
        return;
    }
    for (;;) {
        long count = sys_read((int)source, buffer, sizeof(buffer));
        if (count <= 0) {
            if (count < 0) {
                print_error("cp", argv[1]);
            }
            break;
        }
        if (write_all((int)destination, buffer, (size_t)count) < 0) {
            print_error("cp", argv[2]);
            break;
        }
    }
    (void)sys_close((int)destination);
    (void)sys_close((int)source);
}

static void cmd_touch(int argc, char **argv)
{
    int index;
    if (argc < 2) {
        put_line("usage: touch PATH...");
        return;
    }
    for (index = 1; index < argc; index++) {
        long fd = sys_openat(AT_FDCWD, argv[index], O_WRONLY | O_CREAT, 0644);
        if (fd < 0) {
            print_error("touch", argv[index]);
        } else {
            (void)sys_close((int)fd);
        }
    }
}

static void cmd_mkdir(int argc, char **argv)
{
    if (argc != 2 || sys_mkdirat(AT_FDCWD, argv[1], 0755) < 0) {
        print_error("mkdir", argc >= 2 ? argv[1] : NULL);
    }
}

static void cmd_remove(int argc, char **argv)
{
    int flags = cstr_eq(argv[0], "rmdir") ? AT_REMOVEDIR : 0;
    if (argc != 2 || sys_unlinkat(AT_FDCWD, argv[1], flags) < 0) {
        print_error(argv[0], argc >= 2 ? argv[1] : NULL);
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

static void cmd_sync(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    sys_sync();
}

static void cmd_uname(int argc, char **argv)
{
    struct new_utsname name;
    if (sys_uname(&name) < 0) {
        print_error("uname", NULL);
        return;
    }
    if (argc == 1) {
        put_line(name.sysname);
    } else if (argc == 2 && cstr_eq(argv[1], "-a")) {
        puts_raw(name.sysname);
        puts_raw(" ");
        puts_raw(name.nodename);
        puts_raw(" ");
        puts_raw(name.release);
        puts_raw(" ");
        puts_raw(name.version);
        puts_raw(" ");
        put_line(name.machine);
    } else {
        put_line("usage: uname [-a]");
    }
}

static int get_sysinfo(struct sysinfo *info)
{
    if (sys_sysinfo(info) < 0) {
        print_error("sysinfo", NULL);
        return -1;
    }
    return 0;
}

static void cmd_uptime(int argc, char **argv)
{
    struct sysinfo info;
    unsigned long uptime;
    (void)argc;
    (void)argv;
    if (get_sysinfo(&info) < 0) {
        return;
    }
    uptime = (unsigned long)info.uptime;
    puts_raw("up ");
    print_unsigned(uptime / 86400);
    puts_raw("d ");
    print_unsigned((uptime % 86400) / 3600);
    puts_raw("h ");
    print_unsigned((uptime % 3600) / 60);
    puts_raw("m ");
    print_unsigned(uptime % 60);
    put_line("s");
}

static void print_memory_line(const char *label, unsigned long value,
                              unsigned long unit)
{
    puts_raw(label);
    print_u64(((u64)value * unit) / 1024);
    put_line(" KiB");
}

static void cmd_free(int argc, char **argv)
{
    struct sysinfo info;
    (void)argc;
    (void)argv;
    if (get_sysinfo(&info) < 0) {
        return;
    }
    print_memory_line("total:  ", info.totalram, info.mem_unit);
    print_memory_line("free:   ", info.freeram, info.mem_unit);
    print_memory_line("shared: ", info.sharedram, info.mem_unit);
    print_memory_line("buffers:", info.bufferram, info.mem_unit);
}

static void cmd_sleep(int argc, char **argv)
{
    unsigned long seconds;
    struct kernel_timespec duration;
    if (argc != 2 || parse_unsigned(argv[1], &seconds) < 0) {
        put_line("usage: sleep SECONDS");
        return;
    }
    duration.seconds = (long)seconds;
    duration.nanoseconds = 0;
    if (sys_nanosleep(&duration) < 0) {
        print_error("sleep", NULL);
    }
}

static void cmd_clear(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    puts_raw("\033[2J\033[H");
}

static void cmd_reboot(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    (void)sys_reboot(LINUX_REBOOT_CMD_RESTART);
    print_error("reboot", NULL);
}

static void cmd_poweroff(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    (void)sys_reboot(LINUX_REBOOT_CMD_POWER_OFF);
    print_error("poweroff", NULL);
}

static void cmd_exit(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    put_line("PID 1 cannot exit cleanly; use poweroff or reboot");
}

static const struct command commands[] = {
    {"help", cmd_help}, {"echo", cmd_echo}, {"pwd", cmd_pwd},
    {"cd", cmd_cd}, {"ls", cmd_ls}, {"cat", cmd_cat}, {"cp", cmd_cp},
    {"touch", cmd_touch}, {"mkdir", cmd_mkdir}, {"rm", cmd_remove},
    {"rmdir", cmd_remove}, {"mount", cmd_mount}, {"sync", cmd_sync},
    {"uname", cmd_uname}, {"uptime", cmd_uptime}, {"free", cmd_free},
    {"sleep", cmd_sleep}, {"ifconfig", cmd_ifconfig}, {"ping", cmd_ping},
    {"nc", cmd_nc}, {"fetch", cmd_fetch}, {"run", cmd_run},
    {"clear", cmd_clear}, {"reboot", cmd_reboot},
    {"poweroff", cmd_poweroff}, {"exit", cmd_exit},
};

void run_command(int argc, char **argv)
{
    size_t index;
    const char *cursor;
    if (argc == 0) {
        return;
    }
    for (index = 0; index < sizeof(commands) / sizeof(commands[0]); index++) {
        if (cstr_eq(argv[0], commands[index].name)) {
            commands[index].handler(argc, argv);
            return;
        }
    }
    cursor = argv[0];
    while (*cursor != '\0') {
        if (*cursor++ == '/') {
            run_program(argv);
            return;
        }
    }
    puts_raw(argv[0]);
    put_line(": unknown command");
}
