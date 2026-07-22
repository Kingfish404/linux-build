#include "net.h"
#include "syscall.h"
#include "util.h"

struct icmp_echo {
    u8 type;
    u8 code;
    u16 checksum;
    u16 identifier;
    u16 sequence;
    u8 payload[16];
};

void cmd_ifconfig(int argc, char **argv)
{
    const char *interface = argc >= 2 ? argv[1] : "eth0";
    struct ifreq request;
    long fd = sys_socket(AF_INET, SOCK_DGRAM, 0);

    if (fd < 0) {
        print_error("ifconfig", "socket");
        return;
    }

    memory_clear(&request, sizeof(request));
    cstr_copy(request.name, interface, sizeof(request.name));
    puts_raw(interface);
    if (sys_ioctl((int)fd, SIOCGIFFLAGS, &request) < 0) {
        puts_raw(": not found\n");
        (void)sys_close((int)fd);
        return;
    }
    puts_raw(":");
    if (request.value.flags & IFF_UP) {
        puts_raw(" UP");
    }
    if (request.value.flags & IFF_RUNNING) {
        puts_raw(" RUNNING");
    }
    puts_raw("\n");

    memory_clear(&request.value, sizeof(request.value));
    if (sys_ioctl((int)fd, SIOCGIFADDR, &request) == 0) {
        struct sockaddr_in *address = (struct sockaddr_in *)&request.value.address;
        puts_raw("  inet ");
        print_ipv4(address->address);
        puts_raw("\n");
    }
    memory_clear(&request.value, sizeof(request.value));
    if (sys_ioctl((int)fd, SIOCGIFNETMASK, &request) == 0) {
        struct sockaddr_in *netmask = (struct sockaddr_in *)&request.value.address;
        puts_raw("  netmask ");
        print_ipv4(netmask->address);
        puts_raw("\n");
    }
    (void)sys_close((int)fd);
}

void cmd_ping(int argc, char **argv)
{
    struct sockaddr_in destination;
    struct icmp_echo request;
    u8 response[128];
    long fd;
    int sequence;
    int received = 0;

    memory_clear(&destination, sizeof(destination));
    if (argc != 2 || parse_ipv4(argv[1], &destination.address) < 0) {
        put_line("usage: ping IPv4");
        return;
    }

    fd = sys_socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
    if (fd < 0) {
        print_error("ping", "raw socket");
        return;
    }

    destination.family = AF_INET;
    puts_raw("PING ");
    put_line(argv[1]);

    for (sequence = 1; sequence <= 3; sequence++) {
        struct pollfd poll_fd;
        struct kernel_timespec timeout;
        long bytes;

        memory_clear(&request, sizeof(request));
        request.type = 8;
        request.identifier = host_to_network16(1);
        request.sequence = host_to_network16((u16)sequence);
        request.payload[0] = 't';
        request.payload[1] = 'i';
        request.payload[2] = 'n';
        request.payload[3] = 'y';
        request.checksum = internet_checksum(&request, sizeof(request));

        if (sys_sendto((int)fd, &request, sizeof(request),
                       (const struct sockaddr *)&destination,
                       sizeof(destination)) < 0) {
            put_line("send failed");
            continue;
        }

        poll_fd.fd = (int)fd;
        poll_fd.events = POLLIN;
        poll_fd.revents = 0;
        timeout.seconds = 1;
        timeout.nanoseconds = 0;
        if (sys_ppoll(&poll_fd, 1, &timeout) <= 0) {
            puts_raw("timeout seq=");
            print_unsigned((unsigned long)sequence);
            puts_raw("\n");
            continue;
        }

        bytes = sys_recvfrom((int)fd, response, sizeof(response));
        if (bytes > 0) {
            size_t offset = (response[0] >> 4) == 4 ? (size_t)(response[0] & 0x0f) * 4 : 0;
            if ((size_t)bytes >= offset + 8 && response[offset] == 0) {
                puts_raw("reply from ");
                print_ipv4(destination.address);
                puts_raw(" seq=");
                print_unsigned((unsigned long)sequence);
                puts_raw("\n");
                received++;
                continue;
            }
        }
        put_line("invalid reply");
    }

    print_unsigned((unsigned long)received);
    put_line("/3 replies");
    (void)sys_close((int)fd);
}

static int nc_relay(int socket_fd)
{
    struct pollfd fds[2];
    u8 buffer[512];

    fds[0].fd = 0;
    fds[0].events = POLLIN;
    fds[1].fd = socket_fd;
    fds[1].events = POLLIN;

    for (;;) {
        long ready;
        fds[0].revents = 0;
        fds[1].revents = 0;
        ready = sys_ppoll(fds, 2, NULL);
        if (ready < 0) {
            return -1;
        }
        if (fds[1].revents & (POLLIN | POLLHUP | POLLERR)) {
            long count = sys_read(socket_fd, buffer, sizeof(buffer));
            if (count <= 0) {
                return 0;
            }
            if (write_all(1, buffer, (size_t)count) < 0) {
                return -1;
            }
        }
        if (fds[0].revents & POLLIN) {
            long count = sys_read(0, buffer, sizeof(buffer));
            if (count <= 0) {
                return 0;
            }
            if (write_all(socket_fd, buffer, (size_t)count) < 0) {
                return -1;
            }
        }
    }
}

static void nc_client(const char *host, unsigned long port)
{
    struct sockaddr_in address;
    long fd;

    memory_clear(&address, sizeof(address));
    if (parse_ipv4(host, &address.address) < 0) {
        put_line("nc: numeric IPv4 required");
        return;
    }
    address.family = AF_INET;
    address.port = host_to_network16((u16)port);

    fd = sys_socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        print_error("nc", "socket");
        return;
    }
    if (sys_connect((int)fd, (const struct sockaddr *)&address,
                    sizeof(address)) < 0) {
        print_error("nc", "connect");
        (void)sys_close((int)fd);
        return;
    }
    puts_raw("connected to ");
    print_ipv4(address.address);
    puts_raw(":");
    print_unsigned(port);
    puts_raw("\n");
    if (nc_relay((int)fd) < 0) {
        print_error("nc", "relay");
    }
    (void)sys_close((int)fd);
}

static void nc_listen(unsigned long port)
{
    struct sockaddr_in address;
    int reuse = 1;
    long listener;
    long connection;

    memory_clear(&address, sizeof(address));
    address.family = AF_INET;
    address.port = host_to_network16((u16)port);

    listener = sys_socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0) {
        print_error("nc", "socket");
        return;
    }
    (void)sys_setsockopt((int)listener, SOL_SOCKET, SO_REUSEADDR,
                         &reuse, sizeof(reuse));
    if (sys_bind((int)listener, (const struct sockaddr *)&address,
                 sizeof(address)) < 0 || sys_listen((int)listener, 1) < 0) {
        print_error("nc", "listen");
        (void)sys_close((int)listener);
        return;
    }
    puts_raw("listening on 0.0.0.0:");
    print_unsigned(port);
    puts_raw("\n");

    connection = sys_accept((int)listener, NULL, NULL);
    if (connection < 0) {
        print_error("nc", "accept");
    } else {
        put_line("connection accepted");
        if (nc_relay((int)connection) < 0) {
            print_error("nc", "relay");
        }
        (void)sys_close((int)connection);
    }
    (void)sys_close((int)listener);
}

void cmd_nc(int argc, char **argv)
{
    unsigned long port;

    if (argc == 3 && cstr_eq(argv[1], "-l")) {
        if (parse_unsigned(argv[2], &port) < 0 || port == 0 || port > 65535) {
            put_line("usage: nc -l PORT");
            return;
        }
        nc_listen(port);
        return;
    }
    if (argc == 3 && parse_unsigned(argv[2], &port) == 0 &&
        port > 0 && port <= 65535) {
        nc_client(argv[1], port);
        return;
    }
    put_line("usage: nc IPv4 PORT | nc -l PORT");
}
