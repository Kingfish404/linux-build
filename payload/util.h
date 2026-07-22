#ifndef TINY_UTIL_H
#define TINY_UTIL_H

#include "tiny.h"

size_t cstr_len(const char *text);
int cstr_eq(const char *left, const char *right);
void cstr_copy(char *destination, const char *source, size_t capacity);
void memory_clear(void *memory, size_t length);
int is_space(char value);
int parse_unsigned(const char *text, unsigned long *value);
int parse_ipv4(const char *text, u32 *address);
u16 host_to_network16(u16 value);
u16 internet_checksum(const void *buffer, size_t length);
void puts_raw(const char *text);
void put_line(const char *text);
void print_unsigned(unsigned long value);
void print_u64(u64 value);
void print_ipv4(u32 address);
void print_error(const char *command, const char *target);
long write_all(int fd, const void *buffer, size_t length);
int read_line(char *line, size_t capacity);
int split_args(char *line, char **argv, int argv_capacity);

#endif
