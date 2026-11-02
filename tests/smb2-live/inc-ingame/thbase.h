#ifndef HOST_THBASE
#define HOST_THBASE
#include <unistd.h>
#include <time.h>
#include "tamtypes.h"
typedef struct
{
    u32 lo, hi;
} iop_sys_clock_t;
static inline int DelayThread(int us)
{
    usleep(us);
    return 0;
}
static inline void GetSystemTime(iop_sys_clock_t *c)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    c->lo = (u32)t.tv_nsec;
    c->hi = (u32)t.tv_sec;
}
#endif
