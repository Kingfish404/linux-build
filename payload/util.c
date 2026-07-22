#include "syscall.h"
#include "util.h"

size_t cstr_len(const char *text)
{
    size_t length = 0;
    while (text[length] != '\0') {
        length++;
    }
    return length;
}

int cstr_eq(const char *left, const char *right)
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

void cstr_copy(char *destination, const char *source, size_t capacity)
{
    size_t offset = 0;
    while (offset + 1 < capacity && source[offset] != '\0') {
        destination[offset] = source[offset];
        offset++;
    }
    destination[offset] = '\0';
}

void memory_clear(void *memory, size_t length)
{
    u8 *bytes = memory;
    size_t offset = 0;
    while (offset < length) {
        bytes[offset++] = 0;
    }
}

int is_space(char value)
{
    return value == ' ' || value == '\t' || value == '\r' || value == '\n';
}

int parse_unsigned(const char *text, unsigned long *value)
{
    unsigned long parsed = 0;

    if (*text == '\0') {
        return -1;
    }
    while (*text != '\0') {
        unsigned long next;
        if (*text < '0' || *text > '9') {
            return -1;
        }
        next = parsed * 10 + (unsigned long)(*text - '0');
        if (next < parsed) {
            return -1;
        }
        parsed = next;
        text++;
    }
    *value = parsed;
    return 0;
}

int parse_ipv4(const char *text, u32 *address)
{
    unsigned int octets[4];
    int octet = 0;
    unsigned int value = 0;
    int has_digit = 0;

    while (*text != '\0') {
        if (*text >= '0' && *text <= '9') {
            value = value * 10 + (unsigned int)(*text - '0');
            if (value > 255) {
                return -1;
            }
            has_digit = 1;
        } else if (*text == '.' && has_digit && octet < 3) {
            octets[octet++] = value;
            value = 0;
            has_digit = 0;
        } else {
            return -1;
        }
        text++;
    }

    if (!has_digit || octet != 3) {
        return -1;
    }
    octets[3] = value;
    *address = octets[0] | (octets[1] << 8) |
               (octets[2] << 16) | (octets[3] << 24);
    return 0;
}

u16 host_to_network16(u16 value)
{
    return (u16)((value << 8) | (value >> 8));
}

u16 internet_checksum(const void *buffer, size_t length)
{
    const u16 *words = buffer;
    u32 sum = 0;

    while (length > 1) {
        sum += *words++;
        length -= 2;
    }
    if (length != 0) {
        sum += *(const u8 *)words;
    }
    while (sum >> 16) {
        sum = (sum & 0xffff) + (sum >> 16);
    }
    return (u16)~sum;
}

void puts_raw(const char *text)
{
    (void)write_all(1, text, cstr_len(text));
}

void put_line(const char *text)
{
    puts_raw(text);
    puts_raw("\n");
}

void print_unsigned(unsigned long value)
{
    char digits[3 * sizeof(unsigned long) + 1];
    int count = 0;

    do {
        digits[count++] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0);

    while (count > 0) {
        count--;
        (void)sys_write(1, &digits[count], 1);
    }
}

void print_u64(u64 value)
{
    u8 digits[20];
    int bit;
    int index;
    int started = 0;

    memory_clear(digits, sizeof(digits));
    for (bit = 63; bit >= 0; bit--) {
        unsigned int carry = (unsigned int)((value >> bit) & 1);
        for (index = 19; index >= 0; index--) {
            unsigned int digit = digits[index] * 2U + carry;
            if (digit >= 10) {
                digit -= 10;
                carry = 1;
            } else {
                carry = 0;
            }
            digits[index] = (u8)digit;
        }
    }

    for (index = 0; index < 20; index++) {
        char digit;
        if (!started && digits[index] == 0 && index != 19) {
            continue;
        }
        started = 1;
        digit = (char)('0' + digits[index]);
        (void)sys_write(1, &digit, 1);
    }
}

void print_ipv4(u32 address)
{
    print_unsigned(address & 0xff);
    puts_raw(".");
    print_unsigned((address >> 8) & 0xff);
    puts_raw(".");
    print_unsigned((address >> 16) & 0xff);
    puts_raw(".");
    print_unsigned((address >> 24) & 0xff);
}

void print_error(const char *command, const char *target)
{
    puts_raw(command);
    puts_raw(": failed");
    if (target != NULL) {
        puts_raw(": ");
        puts_raw(target);
    }
    puts_raw("\n");
}

long write_all(int fd, const void *buffer, size_t length)
{
    const u8 *bytes = buffer;
    size_t written = 0;

    while (written < length) {
        long count = sys_write(fd, bytes + written, length - written);
        if (count <= 0) {
            return count;
        }
        written += (size_t)count;
    }
    return (long)written;
}

int read_line(char *line, size_t capacity)
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

int split_args(char *line, char **argv, int argv_capacity)
{
    int argc = 0;
    char *cursor = line;

    while (*cursor != '\0' && argc < argv_capacity - 1) {
        while (is_space(*cursor)) {
            *cursor++ = '\0';
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
