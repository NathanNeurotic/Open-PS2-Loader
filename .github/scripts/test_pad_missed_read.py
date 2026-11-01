"""A missed pad read is unknown, not a release; rumble alignment never lands in the middle of input.

zackcage6's RIPTOPL-NAVTRACE capture (2026-10-29, SCPH-30001R, DualShock 2, rumble and cursor
sounds on) recorded every native pad read. Two shapes made one press move the cursor twice:

1. The first rumble pulse ran padSetActAlign from inside readPads(). That pulse is armed by the
   press's own cursor sound, so the alignment command went out while the direction was still held.
   freepad then answered no reads for about 80 ms (EXECCMD), readPads() zeroed the held bits, and
   when samples came back with the direction still down getKeyOn() saw a second press. It happened
   on the first press after boot and on the first press after each reconnect re-init.
2. Pressing ANALOG while holding a direction: freepad re-reads the pad for 240-260 ms (EXECCMD,
   no samples), and the same release + press followed.

This compiles the whole of src/pad.c on the host against a simulated libpad whose padSetActAlign
puts the pad into EXECCMD for four polls, as the trace shows, and checks:

- the first press with rumble on moves once, and no padSetActAlign is sent while a button is held;
  alignment happens in the next quiet second instead, and rumble works after it;
- a hold across an ANALOG press (13 polls of EXECCMD with no reads, mode 0x41 -> 0x73) is one press,
  with no repeat fired from the unknown polls;
- a blank reply taken while freepad is mid-command is not a release;
- unplugging (FINDPAD) releases at once, and a pad that stays silent past 300 ms is released;
- a release that arrives with the first sample after a miss is seen at once.

Pass --ref <git revision> to run the same scenarios against an older src/pad.c; the parent of this
change fails them, which shows the harness sees the defect.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []

ref = None
if len(sys.argv) == 3 and sys.argv[1] == '--ref':
    ref = sys.argv[2]


def read_source(path):
    if ref is None:
        return (root / path).read_text(encoding='utf-8').replace('\r\n', '\n')
    return subprocess.run(['git', '-C', str(root), 'show', '%s:%s' % (ref, path)], check=True,
                          capture_output=True, text=True).stdout.replace('\r\n', '\n')


pad = read_source('src/pad.c')
pad_h = read_source('include/pad.h')
# The real includes are replaced by the stubs below.
pad = re.sub(r'^#include [^\n]*$', '', pad, flags=re.M)

STUBS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uint64_t u64;
#include "pad.h"

#define LOG(...) ((void)0)
static void diagLog(const char *fmt, ...) { (void)fmt; }
static int gEnableRumble = 1, gXSensitivity = 1, gYSensitivity = 1;
static int KeyPressedOnce, DisableCron;
static void DelayThread(int us) { (void)us; }

static u32 fakeTicks;
static u32 cpu_ticks(void) { return fakeTicks; }

struct padButtonStatus {
    uint8_t ok, mode;
    uint16_t btns;
    uint8_t rjoy_h, rjoy_v, ljoy_h, ljoy_v;
    uint8_t reserved[24];
};
#define PAD_STATE_DISCONN 0
#define PAD_STATE_FINDPAD 1
#define PAD_STATE_FINDCTP1 2
#define PAD_STATE_EXECCMD 5
#define PAD_STATE_STABLE 6
#define PAD_STATE_ERROR 7
#define PAD_RSTAT_COMPLETE 0
#define PAD_RSTAT_FAILED 1
#define PAD_RSTAT_BUSY 2
#define PAD_MODECURID 1
#define PAD_MODECUREXID 2
#define PAD_MODETABLE 4
#define PAD_TYPE_DUALSHOCK 7
#define PAD_MMODE_DIGITAL 0
#define PAD_MMODE_DUALSHOCK 1
#define PAD_MMODE_UNLOCK 2
#define PAD_MMODE_LOCK 3
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

/* Simulated freepad: one DualShock on port 0, nothing on port 1. */
static int simState = PAD_STATE_STABLE, simLen = 32, simExec = 0, simBlankExec = 0;
static u16 simButtons = 0; /* active-high, what the user is physically pressing */
static u8 simMode = 0x41;
static int alignCalls, alignWhileHeld, directCalls;

static int padGetState(int port, int slot)
{
    (void)slot;
    if (port != 0)
        return PAD_STATE_DISCONN;
    return simExec > 0 ? PAD_STATE_EXECCMD : simState;
}
static int padGetReqState(int port, int slot) { (void)port; (void)slot; return simExec > 0 ? PAD_RSTAT_BUSY : PAD_RSTAT_COMPLETE; }
static int padRead(int port, int slot, struct padButtonStatus *d)
{
    (void)slot;
    if (port != 0)
        return 0;
    if (simExec > 0) {
        if (!simBlankExec)
            return 0;
        d->btns = 0xffff; /* a reply taken mid-command: everything released */
        d->mode = simMode;
        return 32;
    }
    if (simState != PAD_STATE_STABLE || !simLen)
        return 0;
    d->btns = (u16)(0xffff ^ simButtons);
    d->mode = simMode;
    d->ljoy_h = d->ljoy_v = d->rjoy_h = d->rjoy_v = 127;
    return simLen;
}
static int padInfoMode(int port, int slot, int infoMode, int index) { (void)port; (void)slot; (void)infoMode; (void)index; return PAD_TYPE_DUALSHOCK; }
static int padInfoAct(int port, int slot, int actuator, int cmd) { (void)port; (void)slot; (void)actuator; (void)cmd; return 2; }
static int padInfoPressMode(int port, int slot) { (void)port; (void)slot; return 1; }
static int padEnterPressMode(int port, int slot) { (void)port; (void)slot; return 1; }
static int padExitPressMode(int port, int slot) { (void)port; (void)slot; return 1; }
static int padSetMainMode(int port, int slot, int mode, int lock) { (void)port; (void)slot; (void)mode; (void)lock; return 1; }
static int padSetActAlign(int port, int slot, const char *a)
{
    (void)port; (void)slot; (void)a;
    alignCalls++;
    if (simButtons)
        alignWhileHeld++;
    simExec = 4; /* trace: ~80 ms of EXECCMD with no samples */
    return 1;
}
static int padSetActDirect(int port, int slot, const char *a)
{
    (void)port; (void)slot; (void)a;
    directCalls++;
    return 1;
}
static int padPortOpen(int port, int slot, void *buf) { (void)port; (void)slot; (void)buf; return 1; }
static int padPortClose(int port, int slot) { (void)port; (void)slot; return 1; }
static int padEnd(void) { return 1; }
static int padGetPortMax(void) { return 2; }
static int padGetSlotMax(int port) { (void)port; return 1; }
'''

MAIN = r'''
static const u32 TICKS_PER_MS = 294912;
static int failures;
static int moves, edges;

static void reset(int aligned)
{
    int i;
    memset(pad_data, 0, sizeof(pad_data));
    pad_count = 2;
    pad_data[0].port = 0;
    pad_data[0].state = PAD_STATE_STABLE;
    pad_data[0].actuators = 2;
    pad_data[0].actAligned = aligned;
    pad_data[0].locked = 1; /* the ANALOG lock is test_pad_mode_lock.py's subject, not this one's */
    pad_data[1].port = 1;
    pad_data[1].state = PAD_STATE_DISCONN;
    for (i = 0; i < 16; i++)
        delaycnt[i] = paddelay[i] = DEFAULT_PAD_DELAY;
    paddata = oldpaddata = 0;
    padIdleMs = 0;
    rumbleActive = rumbleOnRepeats = rumbleOffRepeats = 0;
    simState = PAD_STATE_STABLE;
    simLen = 32;
    simExec = simBlankExec = 0;
    simButtons = 0;
    simMode = 0x41;
    alignCalls = alignWhileHeld = directCalls = 0;
    moves = edges = 0;
}

/* One 20 ms frame: what the GUI does -- read the pads, then the menu asks getKey() and plays the
   cursor sound, which arms a rumble pulse, on a move. */
static void frame(int keyId)
{
    fakeTicks += 20 * TICKS_PER_MS;
    readPads();
    if (simExec > 0)
        simExec--;
    if (getKeyOn(keyId))
        edges++;
    if (getKey(keyId)) {
        moves++;
        padRumble(100, 128);
    }
}

static void frames(int n, int keyId)
{
    while (n-- > 0)
        frame(keyId);
}

static void expect(const char *what, int got, int want)
{
    printf("%-70s %d (want %d)\n", what, got, want);
    if (got != want)
        failures++;
}

int main(void)
{
    int i, before, repeatsDuringMiss;

    /* 1. First press after boot, rumble on, alignment not yet confirmed. 200 ms press. */
    reset(0);
    frames(10, KEY_RIGHT);
    simButtons = PAD_RIGHT;
    frames(10, KEY_RIGHT);
    simButtons = 0;
    frames(3, KEY_RIGHT);
    expect("first press, rumble on: moves", moves, 1);
    expect("first press, rumble on: padSetActAlign sent while a button was held", alignWhileHeld, 0);
    frames(50, KEY_RIGHT); /* a quiet second */
    expect("quiet second after it: padSetActAlign sent", alignCalls, 1);
    expect("quiet second after it: alignment confirmed", pad_data[0].actAligned, 1);
    directCalls = 0;
    simButtons = PAD_RIGHT;
    frames(10, KEY_RIGHT);
    simButtons = 0;
    frames(10, KEY_RIGHT);
    expect("next press: moves", moves, 2);
    expect("next press: rumble commands reached the pad", directCalls > 0, 1);

    /* 2. Hold LEFT and press ANALOG 300 ms in: 13 polls of EXECCMD with no reads, then analog mode. */
    reset(1);
    frames(5, KEY_LEFT);
    simButtons = PAD_LEFT;
    frames(15, KEY_LEFT);
    before = moves;
    simExec = 13;
    repeatsDuringMiss = 0;
    for (i = 0; i < 13; i++) {
        int m = moves;
        frame(KEY_LEFT);
        repeatsDuringMiss += moves - m;
    }
    simMode = 0x73;
    frames(20, KEY_LEFT);
    simButtons = 0;
    frames(3, KEY_LEFT);
    expect("hold across an ANALOG press: key-on edges", edges, 1);
    expect("hold across an ANALOG press: moves while no sample arrived", repeatsDuringMiss, 0);
    expect("hold across an ANALOG press: still repeating after it", moves > before, 1);

    /* 3. A blank reply while freepad is mid-command, during a hold. */
    reset(1);
    simButtons = PAD_RIGHT;
    frames(5, KEY_RIGHT);
    simExec = 1;
    simBlankExec = 1;
    frames(1, KEY_RIGHT);
    simBlankExec = 0;
    frames(5, KEY_RIGHT);
    simButtons = 0;
    frames(2, KEY_RIGHT);
    expect("blank reply mid-command during a hold: key-on edges", edges, 1);

    /* 4. Unplug mid-hold: FINDPAD releases at once. */
    reset(1);
    simButtons = PAD_RIGHT;
    frames(5, KEY_RIGHT);
    simState = PAD_STATE_FINDPAD;
    frames(1, KEY_RIGHT);
    expect("unplugged (FINDPAD): direction still pressed", getKeyPressed(KEY_RIGHT) != 0, 0);
    simState = PAD_STATE_STABLE;
    simButtons = 0;
    frames(2, KEY_RIGHT);

    /* 5. A pad that stays silent past 300 ms is released. */
    reset(1);
    simButtons = PAD_RIGHT;
    frames(5, KEY_RIGHT);
    simLen = 0;
    frames(10, KEY_RIGHT); /* 200 ms */
    expect("silent 200 ms: direction still pressed", getKeyPressed(KEY_RIGHT) != 0, 1);
    frames(10, KEY_RIGHT); /* 400 ms */
    expect("silent 400 ms: direction still pressed", getKeyPressed(KEY_RIGHT) != 0, 0);
    simLen = 32;
    simButtons = 0;
    frames(2, KEY_RIGHT);

    /* 6. Released during the miss: the first sample after it releases at once. */
    reset(1);
    simButtons = PAD_RIGHT;
    frames(5, KEY_RIGHT);
    simLen = 0;
    frames(3, KEY_RIGHT);
    simButtons = 0;
    simLen = 32;
    frames(1, KEY_RIGHT);
    expect("released during a miss: pressed on the first sample after it", getKeyPressed(KEY_RIGHT) != 0, 0);
    expect("released during a miss: moves", moves, 1);

    /* 7. Rumble off: no alignment traffic at all. */
    reset(0);
    gEnableRumble = 0;
    frames(100, KEY_RIGHT);
    expect("rumble off: padSetActAlign sent", alignCalls, 0);
    gEnableRumble = 1;

    return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'pad.h').write_text(pad_h, encoding='utf-8')
    (tmp / 'pad_missed_read.c').write_text(STUBS + pad + MAIN, encoding='utf-8')
    exe = tmp / 'pad_missed_read'
    build = subprocess.run(['gcc', '-std=gnu99', '-w', '-I', str(tmp), str(tmp / 'pad_missed_read.c'), '-o', str(exe)],
                           capture_output=True, text=True)
    if build.returncode != 0:
        failures.append('harness did not compile:\n' + build.stderr)
    else:
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        print(run.stdout, end='')
        if run.returncode != 0:
            failures.append('scenarios failed (see above)')

if failures:
    for failure in failures:
        print('FAIL: ' + failure)
    sys.exit(1)
print('pad missed reads: OK')
