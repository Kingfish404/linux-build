#include "commands.h"
#include "syscall.h"
#include "util.h"

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
}
