#include <unistd.h>
static inline int DelayThread(int us)
{
    usleep(us);
    return 0;
}
/* The keepalive's thread and alarm: on the host nothing runs them, the cases call ECHO directly. */
#ifndef HOST_THBASE_THREADS
#define HOST_THBASE_THREADS
#define TH_C 0x02000000
typedef struct
{
    unsigned int attr, option;
    void (*thread)(void *);
    unsigned int stacksize, priority;
} iop_thread_t;
typedef struct
{
    unsigned int lo, hi;
} iop_sys_clock_t;
static inline int CreateThread(iop_thread_t *t)
{
    (void)t;
    return 1;
}
static inline int StartThread(int tid, void *arg)
{
    (void)tid;
    (void)arg;
    return 0;
}
static inline void USec2SysClock(unsigned int usec, iop_sys_clock_t *c)
{
    c->lo = usec;
    c->hi = 0;
}
static inline int SetAlarm(iop_sys_clock_t *c, unsigned int (*cb)(void *), void *arg)
{
    (void)c;
    (void)cb;
    (void)arg;
    return 0;
}
static inline int iSetAlarm(iop_sys_clock_t *c, unsigned int (*cb)(void *), void *arg)
{
    (void)c;
    (void)cb;
    (void)arg;
    return 0;
}
static inline int CancelAlarm(unsigned int (*cb)(void *), void *arg)
{
    (void)cb;
    (void)arg;
    return 0;
}
#endif
