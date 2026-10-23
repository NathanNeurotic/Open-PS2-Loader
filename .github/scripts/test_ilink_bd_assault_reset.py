"""POPSTARTER's i.LINK driver must reconnect after an IOP reset (#1018).

modules/bdmassault/ilink_bd_assault is the source of POPS/usbhdfsd.irx.ilink: an older ps2sdk
IEEE1394_bd linked with iLinkman (israpps/BDMAssault, branch ilink). POPSTARTER resets the IOP and
loads it from the memory card. The SDK driver never logs out of the drive, and an IOP reset ends it
without warning, so this driver finds the drive still holding the old exclusive login for its SBP-2
reconnect hold: at least 1 s. The SDK gave up after 5 LOGIN tries 200 ms apart (about 0.8 s) and
nothing retried until the next bus reset, which POPSTARTER never causes. It also spun on TEST UNIT
READY with no limit and published a device whose inquiry, readiness or capacity had failed.

This compiles the real code against simulated drives and a simulated clock:
  * initConfigureSBP2Device (and sbp2ElapsedUs, when present) from sbp2_driver.c, extracted,
  * all of scsi.c, built like the shipped module (printf enabled).
Every login case and every warm-up failure case below fails on the sources before the fix.

Usage: test_ilink_bd_assault_reset.py [DRIVER_SRC_DIR]   (default: the vendored sources)
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
driver = root / 'modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src'
if len(sys.argv) > 1:
    driver = Path(sys.argv[1]).resolve()
failures = []


def read(path):
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


def extract_function(source, signature):
    """Full text of the C function whose definition starts with `signature` (string/char aware)."""
    start = source.find(signature)
    if start < 0:
        return None
    i = source.index('{', start)
    depth = 0
    while i < len(source):
        c = source[i]
        if source.startswith('//', i):
            i = source.index('\n', i)
            continue
        if source.startswith('/*', i):
            i = source.index('*/', i) + 2
            continue
        if c in '"\'':
            i += 1
            while source[i] != c:
                i += 2 if source[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    return None


def define(source, name):
    for line in source.splitlines():
        if line.startswith('#define %s ' % name):
            return line
    return None


sbp2 = read(driver / 'sbp2_driver.c')
login = extract_function(sbp2, 'static int initConfigureSBP2Device(')
if login is None:
    failures.append('sbp2_driver.c: initConfigureSBP2Device not found')
# The budget and the clock helper only exist once the fix is in; the old function compiles without
# them, so the behaviour checks below run (and fail) on the old sources too.
login_parts = [part for part in (define(sbp2, 'SBP2_LOGIN_RETRY_US'), define(sbp2, 'SBP2_LOGIN_BUDGET_US'),
                                 extract_function(sbp2, 'static u32 sbp2ElapsedUs('), login) if part]

STUBS = {
    'tamtypes.h': '#include <stdint.h>\ntypedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;\n',
    'sysclib.h': '#include <string.h>\n',
    'thsemap.h': '',
    'thbase.h': '#include <stdint.h>\ntypedef struct { uint32_t lo, hi; } iop_sys_clock_t;\nint DelayThread(int);\nvoid GetSystemTime(iop_sys_clock_t *);\nvoid SysClock2USec(iop_sys_clock_t *, uint32_t *, uint32_t *);\n',
    # Same layout as modules/bdmassault/ilink_bd_assault/include/bdm.h (the header this module builds with).
    'bdm.h': r'''
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
struct block_device {
    void *priv; char *name; unsigned int devNr; unsigned int parNr; unsigned char parId;
    unsigned int sectorSize; u64 sectorOffset; u64 sectorCount;
    int (*read)(struct block_device *bd, u64 sector, void *buffer, u16 count);
    int (*write)(struct block_device *bd, u64 sector, const void *buffer, u16 count);
    void (*flush)(struct block_device *bd);
    int (*stop)(struct block_device *bd);
};
void bdm_connect_bd(struct block_device *bd);
void bdm_disconnect_bd(struct block_device *bd);
''',
}

SCSI_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "bdm.h"
#include "thbase.h"
#include "include/scsi.h"

/* This scsi.c predates the SDK's opcode enum; it sends the raw opcodes. */
enum { OP_TEST_UNIT_READY = 0x00, OP_REQUEST_SENSE = 0x03, OP_INQUIRY = 0x12, OP_READ_CAPACITY_10 = 0x25 };

static long long simUs;
static int notReady, turCalls, inquiryFails, capacityFails, blockLength, connects, commandCost;
static struct block_device *lastBd;
int DelayThread(int usec) { simUs += usec; return 0; }
void GetSystemTime(iop_sys_clock_t *c) { c->lo=simUs; c->hi=(uint64_t)simUs>>32; }
void SysClock2USec(iop_sys_clock_t *c,uint32_t *s,uint32_t *u) {
    uint64_t us=((uint64_t)c->hi<<32)|c->lo;*s=us/1000000;*u=us%1000000;
}

void bdm_connect_bd(struct block_device *bd) { connects++; lastBd = bd; }
void bdm_disconnect_bd(struct block_device *bd) { (void)bd; }

static void be32(unsigned char *p, unsigned int v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }
static int fakeLun(struct scsi_interface *s) { (void)s; return 0; }
static int fakeCmd(struct scsi_interface *s, const unsigned char *cmd, unsigned int cmd_len, unsigned char *data,
                   unsigned int data_len, unsigned int data_wr)
{
    (void)cmd_len; (void)data_wr;
    if (commandCost) {
        unsigned int cost=commandCost;
        if (s->timeout_us && cost>=s->timeout_us) {
            simUs+=s->timeout_us;
            return -1;
        }
        simUs+=cost;
    }
    switch (cmd[0]) {
        case OP_INQUIRY:
            return inquiryFails ? -1 : 0;
        case OP_TEST_UNIT_READY:
            if (++turCalls > 100000)
                return 0; /* the old driver never gives up: end the run so the check below can report it */
            return turCalls <= notReady ? 1 : 0;
        case OP_REQUEST_SENSE:
            memset(data, 0, data_len);
            data[0] = 0x70; data[2] = 0x02; data[12] = 0x04; data[13] = 0x01; /* NOT READY, becoming ready */
            return 0;
        case OP_READ_CAPACITY_10:
            if (capacityFails)
                return -1;
            be32(data, 1000000); be32(data + 4, blockLength);
            return 0;
        default:
            return 0;
    }
}

static struct scsi_interface iface = {NULL, "sd", 32, fakeLun, fakeCmd};
static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL %s\n", m); fails++; } } while (0)
static void reset(int nr, int inq, int cap, int len)
{
    simUs = 0; notReady = nr; turCalls = 0; inquiryFails = inq; capacityFails = cap; blockLength = len;
    connects = 0; lastBd = NULL; commandCost = 0;
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0); /* keep the FAIL lines if a later case crashes */
    scsi_init();

    reset(0, 0, 0, 512);
    scsi_connect(&iface);
    CHECK(connects == 1 && lastBd && lastBd->sectorSize == 512, "a ready drive is offered to BDM");
    scsi_disconnect(&iface);

    reset(50, 0, 0, 512);
    scsi_connect(&iface);
    CHECK(connects == 1, "a drive that becomes ready after 50 polls is offered");
    CHECK(simUs >= 50 * 100000LL, "TEST UNIT READY polls are spaced, not a busy loop");
    scsi_disconnect(&iface);

    reset(1 << 30, 0, 0, 512);
    commandCost=10000000;
    CHECK(scsi_connect(&iface)<0, "slow commands propagate failed connection");
    CHECK(connects==0 && simUs>=30000000 && simUs<=30100000,
          "warm-up budget includes time inside SCSI commands");
    scsi_disconnect(&iface);

    /* Each failure case starts from a free slot (scsi_disconnect is what a bus reset does). */
    reset(1 << 30, 0, 0, 512);
    scsi_connect(&iface);
    CHECK(turCalls <= 300, "TEST UNIT READY is bounded (SCSI_READY_TRIES)");
    CHECK(connects == 0, "a drive that never becomes ready is not offered");
    scsi_disconnect(&iface);

    reset(0, 1, 0, 512);
    scsi_connect(&iface);
    CHECK(connects == 0, "a failed INQUIRY is not offered");
    scsi_disconnect(&iface);

    reset(0, 0, 1, 512);
    scsi_connect(&iface);
    CHECK(connects == 0, "a failed READ CAPACITY is not offered");
    scsi_disconnect(&iface);

    /* A failed attempt frees its own slot. Three back to back (more than the 2 slots), with no
       disconnect between them, must still leave room for the drive once it answers. */
    reset(0, 1, 0, 512);
    scsi_connect(&iface);
    scsi_connect(&iface);
    scsi_connect(&iface);
    reset(0, 0, 0, 512);
    scsi_connect(&iface);
    CHECK(connects == 1, "failed attempts do not use up the device slots");
    scsi_disconnect(&iface);

    /* Last: the old driver divides by the block length in its capacity printf (a crash on the host). */
    reset(0, 0, 0, 0);
    scsi_connect(&iface);
    CHECK(connects == 0, "a block length of 0 is not offered");
    scsi_disconnect(&iface);
    return fails ? 1 : 0;
}
'''

LOGIN_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
typedef uint32_t u32; typedef uint64_t u64;
typedef struct { u32 lo, hi; } iop_sys_clock_t;
#define M_DEBUG(...) ((void)0)
#define SBP2_LOGIN_REQUEST 0
struct scsi_interface { int unused; };
struct SBP2Device { struct scsi_interface scsi; };

/* One clock tick = 1 us, so SysClock2USec is a plain split. */
static u64 simUs;
static u64 holdUntilUs, attemptCostUs;
static int attempts, connects, connect_error;
static void GetSystemTime(iop_sys_clock_t *c) { c->lo = (u32)simUs; c->hi = (u32)(simUs >> 32); }
static void SysClock2USec(iop_sys_clock_t *c, u32 *sec, u32 *usec)
{
    u64 t = ((u64)c->hi << 32) | c->lo;
    *sec = (u32)(t / 1000000);
    *usec = (u32)(t % 1000000);
}
static int DelayThread(int usec) { simUs += usec; return 0; }
/* The drive refuses every LOGIN until it lets go of the login held across the reset. */
static int ieee1394_SendManagementORB(int mode, struct SBP2Device *dev)
{
    (void)mode; (void)dev;
    attempts++;
    simUs += attemptCostUs;
    return simUs >= holdUntilUs ? 0 : -1;
}
static int ieee1394_InitializeFetchAgent(struct SBP2Device *dev) { (void)dev; return 0; }
static int scsi_connect(struct scsi_interface *s) { (void)s; connects++; return connect_error ? -1 : 0; }

@LOGIN@

static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL %s\n", m); fails++; } } while (0)
static int run(u64 hold, u64 cost)
{
    struct SBP2Device dev;
    simUs = 1000000; /* not zero, so elapsed time is measured from the start, not from 0 */
    holdUntilUs = simUs + hold; attemptCostUs = cost; attempts = 0; connects = 0;
    return initConfigureSBP2Device(&dev);
}

int main(void)
{
    (void)GetSystemTime; (void)SysClock2USec; /* unused by the old driver */
    CHECK(run(1000000, 0) >= 0 && connects == 1, "logs in once the drive's 1 s reconnect hold ends");
    CHECK(run(1600000, 0) >= 0 && connects == 1, "logs in on a bridge that holds 1.6 s");
    CHECK(run(4500000, 0) >= 0 && connects == 1, "logs in on a bridge that holds 4.5 s");
    CHECK(run(0, 0) >= 0 && attempts == 1, "a free drive logs in on the first try");
    connect_error=1;
    CHECK(run(0,0)<0, "failed SCSI warm-up propagates to device initialization");
    connect_error=0;

    u64 start = 1000000;
    CHECK(run(~0ULL / 2, 0) < 0 && connects == 0, "a drive that never lets go fails");
    CHECK(simUs - start >= 5000000 && simUs - start < 5200000 + 200000, "...after the 5 s budget, not sooner or much later");
    CHECK(run(~0ULL / 2, 2000000) < 0 && simUs - start < 5000000 + 2000000 + 200000 + 2000000,
          "slow refusals cannot stretch the budget: it is elapsed time, not a try count");
    return fails ? 1 : 0;
}
'''


def compile_and_run(name, sources, include_dirs, extra_flags):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        exe = tmp / (name + ('.exe' if sys.platform == 'win32' else ''))
        paths = []
        for fname, text in sources.items():
            p = tmp / fname
            p.write_text(text, encoding='utf-8')
            if fname.endswith('.c'):
                paths.append(str(p))
        incs = ['-I' + str(tmp)] + ['-I' + str(d) for d in include_dirs]
        cmd = ['gcc', '-std=gnu2x', '-Wall', '-Werror', '-Wno-unused-function'] + extra_flags + incs + paths + ['-o', str(exe)]
        try:
            build = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        except subprocess.TimeoutExpired:
            return ['%s: gcc did not finish within 120 s' % name]
        if build.returncode != 0:
            return ['%s did not compile:\n%s' % (name, build.stderr)]
        try:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=20)
        except subprocess.TimeoutExpired:
            return ['%s: did not finish within 20 s (unbounded loop?)' % name]
        if run.returncode != 0:
            # The shipped module prints ("SBP2: ..."); report only the harness's verdicts.
            lines = [line for line in run.stdout.splitlines() if line.startswith('FAIL ')]
            if run.returncode < 0 or run.returncode > 1:
                lines.append('exited %d (crashed?)' % run.returncode)
            return ['%s: %s' % (name, line) for line in lines or ['exited %d' % run.returncode]]
    return []


scsi_sources = dict(STUBS)
scsi_sources['scsi.c'] = read(driver / 'scsi.c')
scsi_sources['harness.c'] = SCSI_HARNESS
# -Wno-format: the module prints its u64 sector count with %u (harmless on the IOP, an error here).
failures += compile_and_run('scsi', scsi_sources, [driver], ['-Wno-format'])

if login is not None:
    login_sources = {'login.c': LOGIN_HARNESS.replace('@LOGIN@', '\n\n'.join(login_parts))}
    failures += compile_and_run('login', login_sources, [], [])

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('POPSTARTER i.LINK driver: post-reset login, bounded readiness and connect gate OK')
