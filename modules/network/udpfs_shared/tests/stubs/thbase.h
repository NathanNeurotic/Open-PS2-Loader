/* Host stub for the IOP alarm API (see test_udprdma_session.c). */
#ifndef THBASE_H
#define THBASE_H

#include <stdint.h>

typedef struct
{
    uint32_t lo;
    uint32_t hi;
} iop_sys_clock_t;

void USec2SysClock(uint32_t usec, iop_sys_clock_t *clock);
int SetAlarm(iop_sys_clock_t *clock, unsigned int (*cb)(void *), void *arg);
int CancelAlarm(unsigned int (*cb)(void *), void *arg);
int DelayThread(int usec);

#endif
