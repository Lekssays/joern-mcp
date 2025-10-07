#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>

#define TICK_NSEC 1000000
#define NSEC_PER_SEC 1000000000

struct buffer {
    char *data;
    size_t size;
    size_t capacity;
};

int initialize_buffer(struct buffer *buf, size_t initial_capacity) {
    buf->data = (char *)malloc(initial_capacity);
    if (!buf->data) return -1;
    buf->size = 0;
    buf->capacity = initial_capacity;
    return 0;
}

void cleanup_buffer(struct buffer *buf) {
    if (buf->data) {
        free(buf->data);
        buf->data = NULL;
    }
    buf->size = 0;
    buf->capacity = 0;
}

int resize_buffer(struct buffer *buf, size_t new_capacity) {
    char *new_data = (char *)realloc(buf->data, new_capacity);
    if (!new_data) return -1;
    buf->data = new_data;
    buf->capacity = new_capacity;
    return 0;
}

int append_to_buffer(struct buffer *buf, const char *data, size_t len) {
    if (buf->size + len > buf->capacity) {
        size_t new_capacity = (buf->capacity == 0) ? 1024 : buf->capacity * 2;
        while (new_capacity < buf->size + len) {
            new_capacity *= 2;
        }
        if (resize_buffer(buf, new_capacity) != 0) {
            return -1;
        }
    }
    memcpy(buf->data + buf->size, data, len);
    buf->size += len;
    return 0;
}

int safe_div_u64_rem(uint64_t dividend, uint64_t divisor, uint32_t *remainder) {
    if (divisor == 0) {
        return -1;
    }
    *remainder = (uint32_t)(dividend % divisor);
    return 0;
}

void jiffies_to_timespec(const unsigned long jiffies, struct timespec *value) {
    uint32_t rem;
    uint64_t result = (uint64_t)jiffies * TICK_NSEC;
    if (safe_div_u64_rem(result, NSEC_PER_SEC, &rem) != 0) {
        value->tv_sec = 0;
        value->tv_nsec = 0;
        return;
    }
    value->tv_sec = (int64_t)(result / NSEC_PER_SEC);
    value->tv_nsec = (int64_t)rem;
}

int process_jiffies(unsigned long jiffies, struct timespec *output) {
    if (!output) return -1;
    jiffies_to_timespec(jiffies, output);
    return 0;
}

int validate_and_convert(struct buffer *input_buf, struct timespec *output) {
    if (!input_buf || !output) return -1;
    unsigned long jiffies = 0;
    if (input_buf->size > 0) {
        char *tmp = (char *)malloc(input_buf->size + 1);
        if (!tmp) return -1;
        memcpy(tmp, input_buf->data, input_buf->size);
        tmp[input_buf->size] = '\0';
        char *endptr;
        jiffies = strtoul(tmp, &endptr, 10);
        if (*endptr != '\0') {
            free(tmp);
            return -1;
        }
        free(tmp);
    }
    return process_jiffies(jiffies, output);
}

int main() {
    struct buffer input_buf;
    struct timespec ts;
    if (initialize_buffer(&input_buf, 1024) != 0) {
        return 1;
    }
    const char *test_input = "1000";
    if (append_to_buffer(&input_buf, test_input, strlen(test_input)) != 0) {
        cleanup_buffer(&input_buf);
        return 1;
    }
    if (validate_and_convert(&input_buf, &ts) != 0) {
        cleanup_buffer(&input_buf);
        return 1;
    }
    printf("Seconds: %ld\n", ts.tv_sec);
    printf("Nanoseconds: %ld\n", ts.tv_nsec);
    cleanup_buffer(&input_buf);
    return 0;
}