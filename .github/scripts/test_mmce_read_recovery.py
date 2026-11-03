"""MMCE in-game reads wait out a card swap, bounded, and a shutdown cuts that wait short.

Compiles DeviceLock and DeviceReadSectors from modules/iopcore/cdvdman/device-mmce.c on the host, over a
simulated mmcedrv, IOP clock and IOP semaphore, and checks:

- a read that fails while the card is swapping (an MMCE switching folders, for example its own Game ID
  detection reacting to the OSD history write) waits for the card to answer for our handle, then reads again;
- a card that never answers costs the recovery budget once; later reads fail fast until a probe at the top
  of a read answers again, and then reads work again;
- the budget is time on the IOP clock, not a probe count: probes that each take a second (mmcedrv's size
  query allows its reply up to 1 s) do not stretch it, and the clock's low word wrapping mid-wait is harmless;
- DeviceLock (oplShutdown: IGR, IGR power-off, the power button) arriving while a read retries or waits for
  the card ends that read at its next attempt or probe, without the retry, and the lock passes to the
  shutdown at once. No card access happens once the shutdown holds the lock (the barrier holds).

VMC page I/O (mmce_read_offset/mmce_write_offset) still waits for the lock while a read waits for the card,
by design: the VMC is on the same card, and a page write sent while the card swaps would fail (a torn save).

The simulated semaphore hands itself to its waiter on release, as the IOP's does. Host only; console unverified.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DRIVER = 'modules/iopcore/cdvdman/device-mmce.c'


def definition(source, name):
    """The full definition of the function named name (never a prototype)."""
    for match in re.finditer(r'^[A-Za-z_][\w \t\*]*\b' + re.escape(name) + r'\s*\(', source, re.M):
        brace, semi = source.find('{', match.end()), source.find(';', match.end())
        if brace != -1 and (semi == -1 or brace < semi):
            end, depth = brace, 1
            while depth:
                end += 1
                depth += (source[end] == '{') - (source[end] == '}')
            return source[match.start():end + 1]
    raise AssertionError('no definition of ' + name + ' in ' + DRIVER)


def declaration(source, pattern, what):
    match = re.search(pattern, source, re.M)
    assert match, 'no ' + what + ' in ' + DRIVER
    return match.group(0)


source = (ROOT / DRIVER).read_text(encoding='utf-8').replace('\r\n', '\n')
macros = re.findall(r'^#define MMCE_\w+[^\n]*$', source, re.M)
for name in ('MMCE_SWAP_RECOVERY_MS', 'MMCE_SWAP_PROBE_US', 'MMCE_TICKS_PER_MS'):
    assert any(m.split()[1] == name for m in macros), 'no ' + name + ' in ' + DRIVER
DECLS = '\n'.join(macros + [
    declaration(source, r'^int64_t \(\*fp_mmcedrv_get_size\)\(int fd\);$', 'get_size pointer'),
    declaration(source, r'^int \(\*fp_mmcedrv_read_sector\)\([^;\n]*\);$', 'read_sector pointer'),
    declaration(source, r'^static int mmce_io_sema;$', 'I/O semaphore'),
    declaration(source, r'^static int mmce_dev_ready;$', 'ready flag'),
    declaration(source, r'^static int mmce_dev_lost;$', 'lost flag'),
    declaration(source, r'^static volatile int mmce_stopping;$', 'shutdown flag'),
])
DRIVER_CODE = definition(source, 'DeviceLock') + '\n\n' + definition(source, 'DeviceReadSectors')

PROGRAM = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef unsigned int u32;
typedef unsigned long long u64;
typedef struct {
    u32 lo, hi;
} iop_sys_clock_t;
#define SCECdErNO   0x00
#define SCECdErREAD 0x30
#define DPRINTF(...) ((void)(0 && printf(__VA_ARGS__))) /* arguments stay type-checked */
#define ISO_FD 7

static struct {
    int iso_fd;
} cdvdman_settings = {ISO_FD};

@DECLS@

void DeviceLock(void);

/* Time and the card. The card answers for our handle once now_us >= silent_until; until then it answers
   nothing (a swap: card exit, flush, close, 500 ms, open, then the new card loading), and each size query
   to it costs probe_cost_us (0: the SIO2 gives up at once; 1 s: mmcedrv's own timeout). */
static long long now_us, silent_until, probe_cost_us;
static u64 clock_base; /* IOP clock ticks at now_us == 0 */
static int read_calls, probe_calls, delays;

static void GetSystemTime(iop_sys_clock_t *clock)
{
    u64 ticks = clock_base + (u64)now_us * 36864u / 1000u; /* the 36.864 MHz IOP clock */
    clock->lo = (u32)ticks;
    clock->hi = (u32)(ticks >> 32);
}

/* The IOP semaphore (initial 1, max 1). holder: 0 free, 1 the reading thread, 2 the shutdown. The shutdown's
   WaitSema while the reader holds it blocks (shutdown_waiting); the reader's SignalSema then hands the lock
   straight to the shutdown, as the IOP wakes its waiter. */
static int holder, shutdown_waiting, in_shutdown, shutdown_at_delay, shutdown_at_read;
static long long shutdown_started_us, shutdown_locked_us;

static void WaitSema(int sema)
{
    (void)sema;
    if (in_shutdown) {
        if (holder == 0) {
            holder = 2;
            shutdown_locked_us = now_us;
        } else
            shutdown_waiting = 1;
        return;
    }
    assert(holder == 0); /* no read starts after the shutdown took the lock in these runs */
    holder = 1;
}

static void SignalSema(int sema)
{
    (void)sema;
    assert(holder == 1);
    holder = 0;
    if (shutdown_waiting) {
        shutdown_waiting = 0;
        holder = 2;
        shutdown_locked_us = now_us;
    }
}

/* oplShutdown, on its own thread: DeviceLock sets the flag, then waits for the lock. */
static void start_shutdown(void)
{
    shutdown_started_us = now_us;
    in_shutdown = 1;
    DeviceLock();
    in_shutdown = 0;
}

static void DelayThread(int us)
{
    assert(holder == 1); /* the recovery wait sleeps holding the lock (VMC I/O waits for the card, by design) */
    now_us += us;
    if (++delays == shutdown_at_delay)
        start_shutdown(); /* the shutdown thread runs while this one sleeps */
}

/* Card access: only by the reader, under the lock; never once the shutdown holds it (the barrier). */
static int64_t sim_get_size(int fd)
{
    assert(holder == 1 && fd == ISO_FD);
    probe_calls++;
    if (now_us >= silent_until)
        return 4LL * 1024 * 1024 * 1024;
    now_us += probe_cost_us;
    return -1;
}

static int sim_read_sector(int fd, unsigned int start, unsigned int count, void *buffer)
{
    (void)start;
    (void)buffer;
    assert(holder == 1 && fd == ISO_FD);
    if (++read_calls == shutdown_at_read)
        start_shutdown(); /* the shutdown begins while this transfer is on the wire */
    return now_us >= silent_until ? (int)count : 0;
}

@DRIVER@

static void reset(long long silent_for_us)
{
    now_us = 0;
    silent_until = silent_for_us;
    probe_cost_us = 0;
    clock_base = 0xFFFFFFFFull - 36864ull * 250; /* the clock's low word wraps 250 ms into every run */
    read_calls = probe_calls = delays = 0;
    holder = shutdown_waiting = in_shutdown = 0;
    shutdown_at_delay = shutdown_at_read = -1;
    shutdown_started_us = shutdown_locked_us = -1;
    mmce_stopping = 0;
    mmce_dev_ready = 1; /* DeviceFSInit saw the card */
    mmce_dev_lost = 0;
    fp_mmcedrv_get_size = sim_get_size;
    fp_mmcedrv_read_sector = sim_read_sector;
}

int main(void)
{
    static unsigned char buf[2048 * 4];
    const long long probe_us = MMCE_SWAP_PROBE_US;
    const long long budget_us = MMCE_SWAP_RECOVERY_MS * 1000LL;
    const long long forever = 1LL << 60;

    reset(0);
    assert(DeviceReadSectors(16, buf, 4) == SCECdErNO);
    assert(read_calls == 1 && probe_calls == 0 && now_us == 0 && holder == 0);
    printf("ok   a healthy read is one transfer and no wait\n");

    reset(12 * probe_us); /* the card swaps for 1.2 s */
    assert(DeviceReadSectors(16, buf, 4) == SCECdErNO);
    assert(read_calls == 4 && probe_calls == 12 && now_us == 12 * probe_us && holder == 0);
    assert(mmce_dev_ready && !mmce_dev_lost);
    printf("ok   a read that fails while the card swaps waits for the card, then reads again\n");

    reset(forever);
    assert(DeviceReadSectors(16, buf, 4) == SCECdErREAD);
    assert(read_calls == 3 && probe_calls == budget_us / probe_us && now_us == budget_us);
    assert(holder == 0 && !mmce_dev_ready && mmce_dev_lost);
    read_calls = probe_calls = 0;
    assert(DeviceReadSectors(17, buf, 1) == SCECdErREAD); /* fails fast: one probe, no transfer, no wait */
    assert(read_calls == 0 && probe_calls == 1 && now_us == budget_us && holder == 0);
    silent_until = now_us; /* the card answers again */
    read_calls = probe_calls = 0;
    assert(DeviceReadSectors(17, buf, 1) == SCECdErNO);
    assert(read_calls == 1 && probe_calls == 1 && mmce_dev_ready && !mmce_dev_lost);
    printf("ok   a card that never answers costs the budget once, then reads fail fast until it answers again\n");

    reset(forever);
    probe_cost_us = 1000 * 1000; /* every size query runs into mmcedrv's 1 s timeout */
    assert(DeviceReadSectors(16, buf, 4) == SCECdErREAD);
    assert(now_us >= budget_us && now_us < budget_us + probe_us + probe_cost_us); /* not 150 x 1.1 s */
    assert(probe_calls == (int)((budget_us + probe_us + probe_cost_us - 1) / (probe_us + probe_cost_us)));
    assert(holder == 0 && mmce_dev_lost);
    printf("ok   the budget is time on the IOP clock: slow probes do not stretch it\n");

    reset(forever);
    shutdown_at_delay = 5; /* IGR while the read waits for the card */
    assert(DeviceReadSectors(16, buf, 4) == SCECdErREAD);
    assert(mmce_stopping && holder == 2);
    assert(read_calls == 3 && delays == 5 && probe_calls == 5); /* the probe under way, then out; no retry */
    assert(shutdown_started_us == 5 * probe_us && shutdown_locked_us == shutdown_started_us);
    assert(!mmce_dev_lost); /* not judged lost on the way out */
    printf("ok   a shutdown during the wait for the card takes the lock at once; the read fails, no retry\n");

    reset(forever);
    shutdown_at_read = 1; /* IGR during the first transfer */
    assert(DeviceReadSectors(16, buf, 4) == SCECdErREAD);
    assert(read_calls == 1 && probe_calls == 0 && delays == 0 && now_us == 0);
    assert(holder == 2 && shutdown_locked_us == 0);
    reset(0);
    shutdown_at_read = 1; /* IGR during a transfer that succeeds: the read keeps its data */
    assert(DeviceReadSectors(16, buf, 4) == SCECdErNO);
    assert(read_calls == 1 && holder == 2);
    printf("ok   a shutdown during a transfer stops the fast retries and the wait\n");

    reset(0);
    start_shutdown(); /* an idle device */
    assert(mmce_stopping && holder == 2 && shutdown_locked_us == 0);
    printf("ok   DeviceLock on an idle device sets the flag and takes the lock\n");
    return 0;
}
'''

program = PROGRAM.replace('@DECLS@', DECLS).replace('@DRIVER@', DRIVER_CODE)
with tempfile.TemporaryDirectory(prefix='mmce-read-') as directory:
    directory = Path(directory)
    src, binary = directory / 'mmce_read.c', directory / 'mmce_read.exe'
    src.write_text(program, encoding='utf-8')
    flags = ['-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare']
    if os.name != 'nt':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer']
    built = subprocess.run([os.environ.get('CC', 'gcc'), *flags, str(src), '-o', str(binary)],
                           capture_output=True, text=True, timeout=120)
    if built.returncode != 0:
        print('FAIL: the driver did not compile on the host:\n' + built.stderr[-3000:])
        sys.exit(1)
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    print(ran.stdout.strip())
    if ran.returncode != 0:
        print('FAIL: ' + ran.stderr.strip()[-1500:])
        sys.exit(1)
print('test_mmce_read_recovery: all checks passed (host only; console unverified)')
