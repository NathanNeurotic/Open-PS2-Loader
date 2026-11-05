"""The CD stream emulation must not hang the IOP (#185, Tales of the Abyss field freeze).

Compiles the real modules/iopcore/cdvdman/streaming.c on the host against fake IOP kernel calls and drives two
cases that used to hang:

1. A stream read into EE memory while SIFMAN's DMA tag queue is full. sceSifSetDma keeps returning 0 until the
   SIF0 completion interrupt drains the queue, so the retry has to run with interrupts on. The fake queue only
   drains while interrupts are on, and the test fails if the code keeps retrying with them off.
2. A blocking stream read (mode 1) that empties a full buffer without getting all it asked for. The fill chain
   stops while the buffer is full, so the read must restart it before it waits. The fake event flag fails the
   test if the read waits while no fill is queued and no retry alarm is set.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
streaming = root / 'modules/iopcore/cdvdman/streaming.c'

FAKE_INTERNAL = r'''
#pragma once
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uintptr_t u32; /* wide enough for the host's pointers: streaming.c casts buffers through u32 */
typedef uint16_t u16;
typedef uint8_t u8;

typedef struct { u32 hi, lo; } iop_sys_clock_t;
typedef struct { void *src, *dest; int size, attr; } SifDmaTransfer_t;
typedef struct { u8 trycount, spindlctrl, datapattern, pad; } sceCdRMode;
typedef void (*StmCallback_t)(void);

struct SteamingData
{
    unsigned short int StBufmax;
    unsigned short int StBankmax;
    unsigned short int StBanksize;
    unsigned short int StWritePtr;
    unsigned short int StReadPtr;
    unsigned short int StStreamed;
    unsigned short int StStat;
    unsigned short int StIsReading;
    void *StIOP_bufaddr;
    u32 Stlsn;
};

typedef struct
{
    int err;
    u8 status;
    struct SteamingData StreamingData;
    int intr_ef;
} cdvdman_status_t;

#define SCECdErNO 0
#define SCECdStatPause 0x0A
#define WEF_AND 0
#define DPRINTF(...)
#define iDPRINTF(...)

extern cdvdman_status_t cdvdman_stat;
int CpuSuspendIntr(int *state);
int CpuResumeIntr(int state);
int sceSifSetDma(SifDmaTransfer_t *dmat, int count);
int sceSifDmaStat(int id);
int DelayThread(int usec);
int SetAlarm(iop_sys_clock_t *clock, unsigned int (*cb)(void *), void *arg);
int CancelAlarm(unsigned int (*cb)(void *), void *arg);
int SetEventFlag(int ef, u32 bits);
int ClearEventFlag(int ef, u32 bits);
int WaitEventFlag(int ef, u32 bits, int mode, u32 *res);
int sceCdSync(int mode);
int sceCdGetError(void);
void SetStm0Callback(StmCallback_t callback);
int cdvdman_StreamRead(u32 lsn, u32 sectors, u16 sector_size, void *buf);
int sceCdStInit(u32 bufmax, u32 bankmax, void *iop_bufaddr);
int sceCdStStart(u32 lsn, sceCdRMode *mode);
int sceCdStRead(u32 sectors, u32 *buffer, u32 mode, u32 *error);
int sceCdStStop(void);
'''

HARNESS = r'''
#include "internal.h"
#include <sys/mman.h>

cdvdman_status_t cdvdman_stat;

static int intr_off, sif_queue_full, retries_with_intr_off, alarm_set;
static u32 ef_bits;
static StmCallback_t stm0;
static int fill_pending;
static u32 fill_lsn, fill_sectors;
static u8 *fill_buf;

static void fail(const char *why)
{
    printf("FAIL: %s\n", why);
    exit(1);
}

int CpuSuspendIntr(int *state) { *state = intr_off; intr_off = 1; return 0; }
int CpuResumeIntr(int state) { intr_off = state; return 0; }

int sceSifSetDma(SifDmaTransfer_t *dmat, int count)
{
    (void)dmat; (void)count;
    if (sif_queue_full) {
        /* The queue drains only from the SIF0 completion interrupt, which cannot run while interrupts are off. */
        if (intr_off && ++retries_with_intr_off > 1000)
            fail("EE stream read retried a full SIF DMA queue with interrupts off (IOP hang)");
        return 0;
    }
    return 1;
}

int sceSifDmaStat(int id) { (void)id; return -1; }

int DelayThread(int usec)
{
    (void)usec;
    if (intr_off)
        fail("DelayThread with interrupts off");
    sif_queue_full = 0; /* time passes with interrupts on: the completion interrupt drains the queue */
    return 0;
}

int SetAlarm(iop_sys_clock_t *clock, unsigned int (*cb)(void *), void *arg) { (void)clock; (void)cb; (void)arg; alarm_set = 1; return 0; }
int CancelAlarm(unsigned int (*cb)(void *), void *arg) { (void)cb; (void)arg; alarm_set = 0; return 0; }
int SetEventFlag(int ef, u32 bits) { (void)ef; ef_bits |= bits; return 0; }
int ClearEventFlag(int ef, u32 bits) { (void)ef; ef_bits &= bits; return 0; }
int sceCdSync(int mode) { (void)mode; return 0; }
int sceCdGetError(void) { return 0; }
void SetStm0Callback(StmCallback_t callback) { stm0 = callback; }

int cdvdman_StreamRead(u32 lsn, u32 sectors, u16 sector_size, void *buf)
{
    (void)sector_size;
    if (fill_pending)
        fail("a second stream fill was queued while one was in flight");
    fill_pending = 1;
    fill_lsn = lsn;
    fill_sectors = sectors;
    fill_buf = buf;
    return 1;
}

/* What cdvdman_cdread_Thread does when the queued fill is read: data in, read-end flags, stream callback. */
static void complete_fill(void)
{
    u32 i;
    fill_pending = 0;
    for (i = 0; i < fill_sectors; i++)
        memset(fill_buf + i * 2048, (int)((fill_lsn + i) & 0xFF), 2048);
    ef_bits |= 9;
    if (stm0 != NULL)
        stm0();
}

int WaitEventFlag(int ef, u32 bits, int mode, u32 *res)
{
    (void)ef; (void)mode; (void)res;
    if ((ef_bits & bits) == bits)
        return 0;
    if (!fill_pending && !alarm_set)
        fail("blocking stream read waits with no fill queued and no retry alarm (IOP thread hangs)");
    if (fill_pending)
        complete_fill();
    return 0;
}

/* streaming.c strips bit 31 off an IOP address with a 32-bit mask, so the host buffers must live below 2 GB. */
static u8 *iop_stream_buf, *iop_dest;

static u8 *low_alloc(size_t size)
{
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    if (p == MAP_FAILED)
        fail("mmap MAP_32BIT");
    return p;
}

static void fill_until_full(void)
{
    int guard = 0;
    while (fill_pending) {
        complete_fill();
        if (++guard > 100)
            fail("stream never filled up");
    }
}

int main(void)
{
    u32 err = 0;
    int got, i;

    iop_stream_buf = low_alloc(32 * 2048);
    iop_dest = low_alloc(64 * 2048);

    /* Case 1: EE stream read with SIFMAN's queue full. */
    sceCdStInit(32, 4, iop_stream_buf);
    sceCdStStart(1000, NULL);
    fill_until_full();
    if (cdvdman_stat.StreamingData.StStreamed != 32)
        fail("setup: stream buffer not full");
    sif_queue_full = 1;
    got = sceCdStRead(8, (u32 *)(uintptr_t)(0x80000000u | 0x00100000u), 0, &err);
    if (got != 8)
        fail("EE stream read returned the wrong sector count");
    if (intr_off)
        fail("EE stream read returned with interrupts off");
    sceCdStStop();
    fill_pending = 0;

    /* Case 2: blocking IOP stream read larger than what a full buffer holds. */
    sceCdStInit(32, 4, iop_stream_buf);
    sceCdStStart(2000, NULL);
    fill_until_full();
    if (fill_pending || alarm_set)
        fail("setup: fill chain should be stopped on a full buffer");
    got = sceCdStRead(40, (u32 *)iop_dest, 1, &err);
    if (got != 40)
        fail("blocking stream read returned the wrong sector count");
    for (i = 0; i < 40; i++)
        if (iop_dest[i * 2048] != (u8)((2000 + i) & 0xFF))
            fail("blocking stream read returned sectors out of order");

    printf("OK\n");
    return 0;
}
'''


def main():
    cc = shutil.which('cc') or shutil.which('gcc')
    if cc is None:
        sys.exit('no host C compiler')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'internal.h').write_text(FAKE_INTERNAL, encoding='utf-8')
        shutil.copy(streaming, tmp / 'streaming.c')
        (tmp / 'harness.c').write_text(HARNESS, encoding='utf-8')
        exe = tmp / 'harness'
        build = subprocess.run([cc, '-std=gnu99', '-w', '-I', str(tmp), str(tmp / 'streaming.c'), str(tmp / 'harness.c'), '-o', str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stderr)
            sys.exit('streaming.c did not build against the host fakes')
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(run.stdout.strip())
        if run.returncode != 0:
            sys.exit(1)


if __name__ == '__main__':
    main()
