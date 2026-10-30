// Minimal test macros: CHECK keeps going and reports every failure, main returns the failure count.
#pragma once
#include <stdio.h>
static int g_failures = 0;
#define CHECK(cond)                                                           \
    do {                                                                      \
        if (!(cond)) {                                                        \
            fprintf(stderr, "  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            g_failures++;                                                     \
        }                                                                     \
    } while (0)
#define CHECK_STR(a, b)                                                             \
    do {                                                                            \
        const char *_a = (a), *_b = (b);                                            \
        if (!_a || !_b || strcmp(_a, _b) != 0) {                                    \
            fprintf(stderr, "  FAIL %s:%d: \"%s\" != \"%s\"\n", __FILE__, __LINE__, \
                    _a ? _a : "(null)", _b ? _b : "(null)");                        \
            g_failures++;                                                           \
        }                                                                           \
    } while (0)
#define TEST_DONE(name)                                         \
    do {                                                        \
        printf("%s: %s\n", g_failures ? "FAIL" : "PASS", name); \
        return g_failures ? 1 : 0;                              \
    } while (0)
