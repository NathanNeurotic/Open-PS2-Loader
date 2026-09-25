"""A held button must keep repeating across a wrap of the EE tick counter (#729).

readPads() feeds the key-repeat counters the milliseconds since the previous poll. That value used to
be computed by dividing each cpu_ticks() reading by the tick rate and subtracting the quotients. The
32-bit counter wraps about every 29.1 s; at the wrap the reading fell from ~29127 ms to ~0, the u32
difference came out near 2^32, and `delaycnt[i] -= time_since_last` pushed every held key's repeat
counter UP by ~29 s. The next wrap arrived just before that countdown ran out and pushed it up again,
so a held direction or L1/R1 stopped at a random row and stayed stopped until it was released.

This compiles padPollElapsedMs, padAdvanceRepeatTimers, getKeyDelay, getKey, getKeyOn and
getKeyPressed from src/pad.c on the host, with cpu_ticks() replaced by a simulated counter, and holds
R1 at 60 Hz for 70 s from several points before a wrap:

- every repeat after the initial delay must follow the previous one within one repeat period plus
  one frame, across every wrap;
- the elapsed-time sum must track real time to the millisecond over ten simulated minutes;
- a long stall between polls must produce one repeat, not a freeze.

The same run is repeated with the old divide-then-subtract clock (kept here only as the reference),
and must show the freeze -- proof that the harness can see the defect it guards against.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
pad = (root / 'src/pad.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/pad.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def define(name):
    match = re.search(r'^#define ' + name + r'\s+(\d+)', pad, re.M)
    if match is None:
        failures.append('src/pad.c: #define %s not found' % name)
        return '0'
    return match.group(1)


key_table = re.search(r'^static const int keyToPad\[17\] = \{.*?\};', pad, re.M | re.S)
if key_table is None:
    failures.append('src/pad.c: keyToPad table not found')

functions = ''.join(function_text(pad, sig) for sig in (
    'static int getKeyDelay(',
    'static u32 padPollElapsedMs(',
    'static void padAdvanceRepeatTimers(',
    'int getKey(',
    'int getKeyOn(',
    'int getKeyPressed(',
))

# readPads must take its elapsed time from the wrap-safe clock and hand it to the repeat counters.
reads = function_text(pad, 'int readPads(')
if 'time_since_last = padPollElapsedMs();' not in reads or 'padAdvanceRepeatTimers(time_since_last);' not in reads:
    failures.append('readPads: must use padPollElapsedMs() and padAdvanceRepeatTimers(time_since_last)')
if re.search(r'cpu_ticks\(\)\s*/\s*CLOCKS_PER_MILISEC', pad):
    failures.append('src/pad.c: a cpu_ticks() reading is divided before it is subtracted (wraps every ~29 s)')

HARNESS = r'''
#include <stdio.h>
#include <stdint.h>

typedef uint32_t u32;
typedef uint64_t u64;

#define CLOCKS_PER_MILISEC @CLOCKS@
#define DEFAULT_PAD_DELAY @DELAY@

#define PAD_LEFT 0x0080
#define PAD_DOWN 0x0040
#define PAD_RIGHT 0x0020
#define PAD_UP 0x0010
#define PAD_START 0x0008
#define PAD_R3 0x0004
#define PAD_L3 0x0002
#define PAD_SELECT 0x0001
#define PAD_SQUARE 0x8000
#define PAD_CROSS 0x4000
#define PAD_CIRCLE 0x2000
#define PAD_TRIANGLE 0x1000
#define PAD_R1 0x0800
#define PAD_L1 0x0400
#define PAD_R2 0x0200
#define PAD_L2 0x0100
#define KEY_R1 13

static u32 fakeTicks;
static u32 cpu_ticks(void) { return fakeTicks; }

static u32 paddata, oldpaddata;
static int delaycnt[16], paddelay[16];
static int KeyPressedOnce, DisableCron;

@TABLE@

int getKey(int id);
int getKeyOn(int id);
int getKeyPressed(int id);

@FUNCTIONS@

/* The removed clock, kept only to prove the harness sees the defect. */
static u32 oldCurtime;
static u32 oldPollElapsedMs(void)
{
    u32 newtime = cpu_ticks() / CLOCKS_PER_MILISEC;
    u32 elapsed = newtime - oldCurtime;
    oldCurtime = newtime;
    return elapsed;
}

#define FRAME_MS (1000.0 / 59.94)

static int failures;

/* One poll: what readPads() does with the clock and the repeat counters, then the menu's getKey. */
static int poll(double nowMs, u64 startTicks, int held, int useOld)
{
    fakeTicks = (u32)(startTicks + (u64)(nowMs * CLOCKS_PER_MILISEC));
    oldpaddata = paddata;
    paddata = held ? PAD_R1 : 0;
    u32 elapsed = useOld ? oldPollElapsedMs() : padPollElapsedMs();
    padAdvanceRepeatTimers(elapsed);
    return getKey(KEY_R1);
}

/* Hold R1 for holdMs starting secondsBeforeWrap before the counter wraps. Returns the longest gap
   between repeats after the initial delay, in ms. */
static double holdR1(double secondsBeforeWrap, double holdMs, int useOld, int *events)
{
    u64 wrap = (u64)1 << 32;
    u64 startTicks = wrap - (u64)(secondsBeforeWrap * 1000.0 * CLOCKS_PER_MILISEC);
    double t = 0, last = -1, worst = 0;
    int n = 0;

    /* Released for a second first, so the counters start from a clean rearm. */
    for (; t < 1000; t += FRAME_MS)
        poll(t, startTicks, 0, useOld);

    double pressAt = t;
    for (; t < pressAt + holdMs; t += FRAME_MS) {
        if (poll(t, startTicks, 1, useOld)) {
            if (n >= 2 && t - last > worst)
                worst = t - last;
            if (n == 1 && !useOld && (t - last < 3 * DEFAULT_PAD_DELAY - FRAME_MS || t - last > 3 * DEFAULT_PAD_DELAY + FRAME_MS)) {
                printf("initial delay %.1f ms, expected %d ms\n", t - last, 3 * DEFAULT_PAD_DELAY);
                failures++;
            }
            last = t;
            n++;
        }
    }
    /* A freeze may never end while the key is held, so the tail counts as a gap too. */
    if (n >= 2 && t - last > worst)
        worst = t - last;
    poll(t, startTicks, 0, useOld);
    *events = n;
    return worst;
}

int main(void)
{
    static const double before[] = {0.2, 1.0, 5.0, 12.5, 20.0, 28.9};
    const double holdMs = 70000.0;
    const double allowed = DEFAULT_PAD_DELAY + FRAME_MS + 0.5;
    int i, n;

    for (i = 0; i < 16; i++)
        delaycnt[i] = paddelay[i] = DEFAULT_PAD_DELAY;

    for (i = 0; i < (int)(sizeof(before) / sizeof(before[0])); i++) {
        double worst = holdR1(before[i], holdMs, 0, &n);
        double minEvents = 1 + (holdMs - 3 * DEFAULT_PAD_DELAY) / allowed;
        printf("hold R1 70 s from %4.1f s before a wrap: %d repeats, longest gap %.1f ms\n", before[i], n, worst);
        if (worst > allowed || n < minEvents) {
            printf("  FAIL: a held key must repeat at least every %.1f ms across the wrap\n", allowed);
            failures++;
        }
    }

    /* The reference: with the old clock every wrap re-adds almost a whole wrap period to the
       countdown just before it expires, so the held key stops at the first wrap and stays stopped. */
    double oldWorst = holdR1(5.0, holdMs, 1, &n);
    printf("old clock, same hold: %d repeats, longest gap %.1f ms\n", n, oldWorst);
    if (oldWorst < 20000.0) {
        printf("  FAIL: the harness no longer reproduces the old freeze\n");
        failures++;
    }

    /* Ten minutes of polls: the millisecond sum must follow real time (the carry keeps it exact). */
    {
        u64 startTicks = ((u64)1 << 32) - (u64)(3.0 * 1000.0 * CLOCKS_PER_MILISEC);
        double t = 0;
        u64 sum = 0;
        fakeTicks = (u32)startTicks;
        padPollElapsedMs();
        for (t = FRAME_MS; t < 600000.0; t += FRAME_MS) {
            fakeTicks = (u32)(startTicks + (u64)(t * CLOCKS_PER_MILISEC));
            sum += padPollElapsedMs();
        }
        double real = t - FRAME_MS;
        printf("10 min of polls: %llu ms counted, %.1f ms real\n", (unsigned long long)sum, real);
        if (sum + 2 < real || sum > real + 1) {
            printf("  FAIL: the elapsed-time sum drifted from real time\n");
            failures++;
        }
    }

    /* A 5 s stall between polls while held: the next poll repeats once, then the normal cadence. */
    {
        u64 startTicks = 1000000;
        double t = 0;
        int hits = 0;
        for (; t < 1000; t += FRAME_MS)
            poll(t, startTicks, 0, 0);
        poll(t, startTicks, 1, 0); /* press */
        t += 5000.0;
        hits += poll(t, startTicks, 1, 0);
        t += FRAME_MS;
        hits += poll(t, startTicks, 1, 0);
        poll(t + FRAME_MS, startTicks, 0, 0);
        printf("5 s stall while held: %d repeat(s) on the next two polls\n", hits);
        if (hits != 1) {
            printf("  FAIL: a stall must yield exactly one repeat, not a burst or a freeze\n");
            failures++;
        }
    }

    return failures ? 1 : 0;
}
'''

if not failures:
    source = (HARNESS.replace('@CLOCKS@', define('CLOCKS_PER_MILISEC'))
                     .replace('@DELAY@', define('DEFAULT_PAD_DELAY'))
                     .replace('@TABLE@', key_table.group(0))
                     .replace('@FUNCTIONS@', functions))

if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'pad_clock.c'
        exe = Path(tmp) / ('pad_clock.exe' if sys.platform == 'win32' else 'pad_clock')
        c_file.write_text(source, encoding='utf-8')
        build = subprocess.run(['cc', '-std=gnu99', '-O1', '-Wall', '-Wextra', '-Werror',
                                '-Wno-unused-function', str(c_file), '-o', str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('harness reported failures (see above)')

if failures:
    for failure in failures:
        print('FAIL:', failure)
    sys.exit(1)
print('pad repeat clock: OK')
