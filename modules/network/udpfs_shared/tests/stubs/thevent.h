/* Host stub for the IOP event flag API (see test_udprdma_session.c). */
#ifndef THEVENT_H
#define THEVENT_H

#include <stdint.h>

typedef struct
{
    uint32_t attr;
    uint32_t option;
    uint32_t bits;
} iop_event_t;

#define WEF_AND   0
#define WEF_OR    1
#define WEF_CLEAR 0x10

int CreateEventFlag(iop_event_t *event);
int DeleteEventFlag(int ef);
int SetEventFlag(int ef, uint32_t bits);
int iSetEventFlag(int ef, uint32_t bits);
int ClearEventFlag(int ef, uint32_t bits);
int WaitEventFlag(int ef, uint32_t bits, int mode, uint32_t *resbits);

#endif
