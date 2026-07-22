#include "syscall.h"
#include "transfer.h"
#include "util.h"

#define SIGCHLD 17

static int http_status_ok(const char *header)
{
    const char *cursor = header;

    if (cursor[0] != 'H' || cursor[1] != 'T' || cursor[2] != 'T' ||
        cursor[3] != 'P' || cursor[4] != '/') {
        return 0;
    }
    while (*cursor != '\0' && *cursor != ' ') {
        cursor++;
    }
    return cursor[0] == ' ' && cursor[1] == '2' && cursor[2] == '0' &&
           cursor[3] == '0' && cursor[4] == ' ';
}

static char ascii_lower(char value)
{
    return value >= 'A' && value <= 'Z' ? (char)(value + ('a' - 'A')) : value;
}

static int header_name_matches(const char *line, const char *name)
{
    while (*name != '\0') {
        if (ascii_lower(*line++) != *name++) {
            return 0;
        }
    }
    return 1;
}

static int content_length(const char *header, unsigned long *length)
{
    const char *line = header;

    while (*line != '\0') {
        if (header_name_matches(line, "content-length:")) {
            unsigned long value = 0;
            const char *cursor = line + 15;
            int has_digit = 0;

            while (*cursor == ' ' || *cursor == '\t') {
                cursor++;
            }
            while (*cursor >= '0' && *cursor <= '9') {
                unsigned long next = value * 10 + (unsigned long)(*cursor - '0');
                if (next < value) {
                    return -1;
                }
                value = next;
                has_digit = 1;
                cursor++;
            }
            if (!has_digit || (*cursor != '\r' && *cursor != '\n')) {
                return -1;
            }
            *length = value;
            return 1;
        }
        while (*line != '\0' && *line != '\n') {
            line++;
        }
        if (*line == '\n') {
            line++;
        }
    }
    return 0;
}

static long connect_tcp(const char *host, unsigned long port)
{
    struct sockaddr_in address;
    long socket_fd;

    memory_clear(&address, sizeof(address));
    if (parse_ipv4(host, &address.address) < 0) {
        put_line("fetch: numeric IPv4 required");
        return -1;
    }
    address.family = AF_INET;
    address.port = host_to_network16((u16)port);

    socket_fd = sys_socket(AF_INET, SOCK_STREAM, 0);
    if (socket_fd < 0 ||
        sys_connect((int)socket_fd, (const struct sockaddr *)&address,
                    sizeof(address)) < 0) {
        if (socket_fd >= 0) {
            (void)sys_close((int)socket_fd);
        }
        print_error("fetch", "connect");
        return -1;
    }
    return socket_fd;
}

static int send_request(int socket_fd, const char *host, const char *path)
{
    return write_all(socket_fd, "GET ", 4) < 0 ||
           write_all(socket_fd, path, cstr_len(path)) < 0 ||
           write_all(socket_fd, " HTTP/1.0\r\nHost: ", 17) < 0 ||
           write_all(socket_fd, host, cstr_len(host)) < 0 ||
           write_all(socket_fd, "\r\nConnection: close\r\n\r\n", 23) < 0
               ? -1 : 0;
}

static int read_response_header(int socket_fd, char *header, size_t capacity)
{
    size_t length = 0;

    while (length + 1 < capacity) {
        long count = sys_read(socket_fd, &header[length], 1);
        if (count <= 0) {
            return -1;
        }
        length++;
        if (length >= 4 && header[length - 4] == '\r' &&
            header[length - 3] == '\n' && header[length - 2] == '\r' &&
            header[length - 1] == '\n') {
            header[length] = '\0';
            return http_status_ok(header) ? 0 : -1;
        }
    }
    return -1;
}

void cmd_fetch(int argc, char **argv)
{
    char header[1024];
    u8 buffer[1024];
    unsigned long port;
    unsigned long expected_length = 0;
    u64 total = 0;
    long socket_fd;
    long output_fd;
    int has_content_length;
    int failed = 0;

    if (argc != 5 || parse_unsigned(argv[2], &port) < 0 || port == 0 ||
        port > 65535 || argv[3][0] != '/') {
        put_line("usage: fetch IPv4 PORT /REMOTE_PATH LOCAL_PATH");
        return;
    }
    socket_fd = connect_tcp(argv[1], port);
    if (socket_fd < 0) {
        return;
    }
    if (send_request((int)socket_fd, argv[1], argv[3]) < 0 ||
        read_response_header((int)socket_fd, header, sizeof(header)) < 0) {
        put_line("fetch: HTTP request failed or non-200 response");
        (void)sys_close((int)socket_fd);
        return;
    }
    has_content_length = content_length(header, &expected_length);
    if (has_content_length < 0) {
        put_line("fetch: invalid Content-Length");
        (void)sys_close((int)socket_fd);
        return;
    }

    output_fd = sys_openat(AT_FDCWD, argv[4], O_WRONLY | O_CREAT | O_TRUNC,
                           0755);
    if (output_fd < 0 || sys_fchmod((int)output_fd, 0755) < 0) {
        print_error("fetch", argv[4]);
        if (output_fd >= 0) {
            (void)sys_close((int)output_fd);
            (void)sys_unlinkat(AT_FDCWD, argv[4], 0);
        }
        (void)sys_close((int)socket_fd);
        return;
    }
    for (;;) {
        long count = sys_read((int)socket_fd, buffer, sizeof(buffer));
        if (count == 0) {
            break;
        }
        if (count < 0 || write_all((int)output_fd, buffer, (size_t)count) < 0) {
            failed = 1;
            break;
        }
        total += (u64)count;
    }
    if (has_content_length > 0 && total != (u64)expected_length) {
        failed = 1;
    }
    (void)sys_close((int)output_fd);
    (void)sys_close((int)socket_fd);
    if (failed) {
        (void)sys_unlinkat(AT_FDCWD, argv[4], 0);
        print_error("fetch", argv[4]);
        return;
    }
    puts_raw("saved ");
    print_u64(total);
    puts_raw(" bytes to ");
    put_line(argv[4]);
}

void run_program(char **argv)
{
    char *empty_environment[] = {NULL};
    long process_id;
    int wait_status = 0;

    process_id = sys_clone(SIGCHLD, 0, NULL, NULL, 0);
    if (process_id < 0) {
        print_error("run", "clone");
        return;
    }
    if (process_id == 0) {
        (void)sys_execve(argv[0], argv, empty_environment);
        print_error("run", argv[0]);
        sys_exit(127);
    }
    if (sys_wait4((int)process_id, &wait_status, 0) < 0) {
        print_error("run", "wait4");
        return;
    }
    if ((wait_status & 0x7f) == 0) {
        puts_raw("exit ");
        print_unsigned((unsigned long)((wait_status >> 8) & 0xff));
        puts_raw("\n");
    } else {
        puts_raw("signal ");
        print_unsigned((unsigned long)(wait_status & 0x7f));
        puts_raw("\n");
    }
}

void cmd_run(int argc, char **argv)
{
    if (argc < 2) {
        put_line("usage: run PATH [ARG...]");
        return;
    }
    run_program(&argv[1]);
}