"""IGR and power-off let an in-flight VMC save finish before CDVDMAN locks the device.

oplShutdown (IGR, IGR power-off, and the power button with IGR off) takes the device lock and never
releases it. The EE is stopped, but MCEMU's IOP threads keep running, so a save MCEMU was in the middle
of (one MCMAN call writes many VMC pages) used to be cut at its next page.

This compiles the real VMC drain from modules/iopcore/cdvdman/cdvdman.c -- the begin/end hooks the
oplutils exports call and cdvdman_vmc_drain() -- against a simulated IOP clock and a scripted MCEMU
writer, and checks:
  (a) a write sequence in flight, read phase included, completes before the lock;
  (b) a writer that never stops (or a device call that never returns) cannot hold shutdown past the cap;
  (c) no wait without a VMC, long after a save, or while the burst has only read;
and the source shape: oplShutdown drains before DeviceLock in every CDVDMAN build variant, every VMC
export MCEMU calls reports to the drain, and the oplutils slots MCEMU imports still line up.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def check(cond, what):
    if not cond:
        failures.append(what)


def function(src, signature, name):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', src, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (name, signature))
        return ''
    return src[match.start():src.index('\n}', match.start()) + 2] + '\n'


def if_depth(src, pos):
    """Preprocessor #if nesting at a position in a source file."""
    depth = 0
    for line in src[:pos].split('\n'):
        s = line.strip()
        if s.startswith('#if'):
            depth += 1
        elif s.startswith('#endif'):
            depth -= 1
    return depth


cdvdman = read('modules/iopcore/cdvdman/cdvdman.c')

# ---------------------------------------------------------------------------
# 1. Behaviour of the real drain code.

start = cdvdman.find('#define VMC_TICKS_PER_MS')
drain_fn = function(cdvdman, 'static void cdvdman_vmc_drain(', 'cdvdman.c')
if start < 0:
    failures.append('cdvdman.c: the VMC drain (VMC_TICKS_PER_MS ... cdvdman_vmc_drain) is missing')
    block = ''
else:
    end = cdvdman.find(drain_fn) + len(drain_fn) if drain_fn else -1
    block = cdvdman[start:end] if end > start else ''
    check(block != '', 'cdvdman.c: cdvdman_vmc_drain must follow the VMC_* constants')

consts = {k: int(v) for k, v in re.findall(r'#define (VMC_\w+)\s+(\d+)', block)}
for name in ('VMC_TICKS_PER_MS', 'VMC_DRAIN_QUIET_MS', 'VMC_DRAIN_CAP_MS', 'VMC_DRAIN_POLL_US'):
    check(name in consts, 'cdvdman.c: %s not defined' % name)

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned int u32;
typedef unsigned long long u64;
typedef struct { u32 lo, hi; } iop_sys_clock_t;

static u64 sim;           /* IOP system clock, ticks */
static int intr_off;      /* CpuSuspendIntr nesting */
static int delays, misuse;

int GetSystemTime(iop_sys_clock_t *c)
{
    if (intr_off)
        misuse++; /* the drain must not depend on GetSystemTime with interrupts off */
    c->lo = (u32)sim;
    c->hi = (u32)(sim >> 32);
    return 0;
}
int CpuSuspendIntr(int *state) { *state = intr_off; intr_off = 1; return 0; }
int CpuResumeIntr(int state) { intr_off = state; return 0; }
int DelayThread(int usec);

%(block)s

/* ---- scripted MCEMU: page operations one after another, each begin..end, gaps between ---- */
#define US(t) ((u64)(t) * %(ticks_per_ms)dULL / 1000ULL)
#define MS(t) US((u64)(t) * 1000ULL)
#define MAXOPS 4096
typedef struct { u64 begin, end; int write, begun, ended; } op_t;
static op_t ops[MAXOPS];
static int nops;
static u64 cursor;

static void at(u64 t) { cursor = t; }
static void gap_us(u64 us) { cursor += US(us); }
static void op_us(int write, u64 us)
{
    if (nops == MAXOPS) { printf("too many ops\n"); exit(2); }
    ops[nops].begin = cursor;
    ops[nops].end = cursor + US(us);
    ops[nops].write = write;
    cursor = ops[nops].end;
    nops++;
}
static void run_until(u64 t)
{
    int i;
    for (i = 0; i < nops; i++) {
        if (!ops[i].begun) {
            if (ops[i].begin > t)
                return;
            sim = ops[i].begin;
            cdvdman_vmc_io_begin(ops[i].write);
            ops[i].begun = 1;
        }
        if (!ops[i].ended) {
            if (ops[i].end > t)
                return;
            sim = ops[i].end;
            cdvdman_vmc_io_end();
            ops[i].ended = 1;
        }
    }
}
int DelayThread(int usec)
{
    u64 target = sim + US(usec);
    delays++;
    if (intr_off)
        misuse++;
    run_until(target); /* the writer runs while the shutdown thread sleeps */
    sim = target;
    return 0;
}
static int count(int begun, int ended)
{
    int i, n = 0;
    for (i = 0; i < nops; i++)
        n += ops[i].begun == begun && ops[i].ended == ended;
    return n;
}
static long long us_between(u64 from, u64 to)
{
    return ((long long)to - (long long)from) * 1000LL / %(ticks_per_ms)dLL;
}

/* Starts just below a 2^32-tick boundary so the low clock word wraps inside the scenarios. */
#define BASE ((1ULL << 32) - MS(150))

/* One block flush as MCEMU sees it: erase (16 page writes), 34 page writes, 14 page reads for
   the next block, its erase and 34 writes. */
static void save_sequence(void)
{
    int i;
    for (i = 0; i < 50; i++) { op_us(1, 2000); gap_us(500); }
    for (i = 0; i < 14; i++) { op_us(0, 3000); gap_us(500); }
    for (i = 0; i < 50; i++) { op_us(1, 2000); gap_us(500); }
}
static void endless(int write)
{
    while (nops < MAXOPS) { op_us(write, 3000); gap_us(2000); }
}

int main(int argc, char **argv)
{
    const char *s = argv[1];
    u64 press = 0, seq_end = 0;
    int i;

    at(BASE);
    if (!strcmp(s, "inflight")) {
        save_sequence();
        seq_end = ops[nops - 1].end;
        press = BASE + MS(40);
    } else if (!strcmp(s, "slow_write")) {
        op_us(1, 300000); /* one page write slower than the quiet period */
        seq_end = ops[nops - 1].end;
        press = BASE + MS(10);
    } else if (!strcmp(s, "endless")) {
        endless(1);
        press = BASE + MS(1000);
    } else if (!strcmp(s, "hung_write")) {
        op_us(1, 2000);
        gap_us(500);
        op_us(1, 100000000ULL); /* a device call that does not return for 100 s */
        press = BASE + MS(20);
    } else if (!strcmp(s, "none")) {
        press = BASE + MS(1000);
    } else if (!strcmp(s, "old_save")) {
        save_sequence();
        press = cursor + MS(10000);
    } else if (!strcmp(s, "wrapped_save")) {
        save_sequence(); /* low clock words equal 2^32 ticks (about 116 s) later */
        press = ops[nops - 1].end + (1ULL << 32) + MS(1);
    } else if (!strcmp(s, "reads_only")) {
        endless(0);
        press = BASE + MS(1000);
    } else if (!strcmp(s, "reads_after_save")) {
        for (i = 0; i < 20; i++) { op_us(1, 2000); gap_us(500); }
        gap_us(1000000);
        endless(0);
        press = BASE + MS(2000);
    } else if (!strcmp(s, "just_saved")) {
        for (i = 0; i < 20; i++) { op_us(1, 2000); gap_us(500); }
        seq_end = ops[nops - 1].end;
        press = seq_end + MS(30);
    } else {
        printf("unknown scenario\n");
        return 2;
    }

    run_until(press);
    sim = press;
    delays = 0;
    cdvdman_vmc_drain();
    /* DeviceLock comes now: it waits for a call in flight, and every later VMC call is cut. */
    printf("%%s elapsed_us=%%lld delays=%%d done=%%d in_flight=%%d cut=%%d total=%%d seq_end_us=%%lld misuse=%%d intr=%%d\n",
           s, us_between(press, sim), delays, count(1, 1), count(1, 0), count(0, 0), nops,
           seq_end ? us_between(press, seq_end) : -1LL, misuse, intr_off);
    return 0;
}
'''

SCENARIOS = ['inflight', 'slow_write', 'endless', 'hung_write', 'none', 'old_save', 'wrapped_save',
             'reads_only', 'reads_after_save', 'just_saved']

results = {}
if block and not failures:
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / 'drain.c'
        exe = Path(tmp) / 'drain'
        c.write_text(HARNESS % {'block': block, 'ticks_per_ms': consts['VMC_TICKS_PER_MS']}, encoding='utf-8')
        built = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(c)],
                               capture_output=True, text=True)
        if built.returncode != 0:
            failures.append('drain harness failed to build:\n' + built.stderr)
        else:
            for name in SCENARIOS:
                out = subprocess.run([str(exe), name], capture_output=True, text=True)
                if out.returncode != 0:
                    failures.append('%s: harness exited %d: %s' % (name, out.returncode, out.stdout))
                    continue
                fields = dict(kv.split('=') for kv in out.stdout.split()[1:])
                results[name] = {k: int(v) for k, v in fields.items()}
                print(out.stdout.strip())

if results:
    quiet_us = consts['VMC_DRAIN_QUIET_MS'] * 1000
    cap_us = consts['VMC_DRAIN_CAP_MS'] * 1000
    poll_us = consts['VMC_DRAIN_POLL_US']

    for name, r in results.items():
        check(r['misuse'] == 0 and r['intr'] == 0,
              '%s: no sleep or clock read with interrupts disabled, and interrupts restored' % name)

    # (a) A save in flight finishes before the lock.
    for name in ('inflight', 'slow_write'):
        r = results[name]
        check(r['done'] == r['total'] and r['in_flight'] == 0 and r['cut'] == 0,
              '%s: every page operation of the save completes before the lock (%d/%d done, %d cut)'
              % (name, r['done'], r['total'], r['cut']))
        check(r['seq_end_us'] + quiet_us <= r['elapsed_us'] <= r['seq_end_us'] + quiet_us + poll_us,
              '%s: the lock follows the end of the save by the quiet period (elapsed %d us, save ended at %d us)'
              % (name, r['elapsed_us'], r['seq_end_us']))
        check(r['elapsed_us'] < cap_us, '%s: finished inside the cap' % name)

    # (b) A writer that never stops, or a call that never returns, cannot hold shutdown past the cap.
    for name in ('endless', 'hung_write'):
        r = results[name]
        check(cap_us <= r['elapsed_us'] <= cap_us + poll_us,
              '%s: the drain gives up at the cap (elapsed %d us, cap %d us)' % (name, r['elapsed_us'], cap_us))
        check(r['done'] < r['total'], '%s: the scripted writer was still going' % name)

    # (c) No wait when there is nothing to finish.
    for name in ('none', 'old_save', 'wrapped_save', 'reads_only', 'reads_after_save'):
        r = results[name]
        check(r['elapsed_us'] == 0 and r['delays'] == 0,
              '%s: no wait (elapsed %d us, %d sleeps)' % (name, r['elapsed_us'], r['delays']))

    # A save that finished just before the press costs only the rest of the quiet period.
    r = results['just_saved']
    check(quiet_us - 30000 <= r['elapsed_us'] <= quiet_us - 30000 + poll_us,
          'just_saved: waits only the rest of the quiet period (elapsed %d us)' % r['elapsed_us'])

# The cap stays well inside ee_core's INGAMEDIAG shutdown deadline, which also has to cover the
# device lock, MCEMU's shutdown callback and the unmount after the drain.
budget = re.search(r'#define FREEZE_DIAG_IOP_BUDGET_MS\s+(\d+)', read('ee_core/src/freeze_diag.c'))
check(budget is not None, 'ee_core/src/freeze_diag.c: FREEZE_DIAG_IOP_BUDGET_MS not found')
if budget and consts.get('VMC_DRAIN_CAP_MS') is not None and consts.get('VMC_DRAIN_POLL_US') is not None:
    check((consts['VMC_DRAIN_CAP_MS'] + consts['VMC_DRAIN_POLL_US'] // 1000) * 2 <= int(budget.group(1)),
          'the drain cap plus one poll is at most half of the INGAMEDIAG shutdown deadline')
if consts.get('VMC_DRAIN_QUIET_MS') is not None and consts.get('VMC_DRAIN_CAP_MS') is not None:
    check(consts['VMC_DRAIN_QUIET_MS'] < consts['VMC_DRAIN_CAP_MS'], 'the quiet period is shorter than the cap')

# ---------------------------------------------------------------------------
# 2. oplShutdown drains before DeviceLock in every CDVDMAN build variant.

shutdown = function(cdvdman, 'static void oplShutdown(', 'cdvdman.c')
check(cdvdman.count('DeviceLock();') == 1 and 'DeviceLock();' in shutdown,
      'cdvdman.c: oplShutdown is the only place that takes the device lock')
check(re.search(r'static void oplShutdown\(int poff\)\n\{\n    u32 stat;\n\n    cdvdman_vmc_drain\(\);\n    DeviceLock\(\);\n',
                shutdown) is not None,
      'cdvdman.c: oplShutdown drains the VMC first, directly before DeviceLock')
for text, what in ((shutdown, 'oplShutdown'), (block, 'the VMC drain')):
    if text:
        check(if_depth(cdvdman, cdvdman.find(text)) == 0, 'cdvdman.c: %s is not inside any #if' % what)
check(re.search(r'case CDSC_OPL_SHUTDOWN:\n\s*oplShutdown\(\*param\);', cdvdman) is not None,
      'cdvdman.c: the IGR RPC (CDSC_OPL_SHUTDOWN) reaches oplShutdown')
check(re.search(r'static void cdvdman_poff_thread\(void \*arg\)\n\{\n\s*SleepThread\(\);\n\n\s*oplShutdown\(1\);', cdvdman)
      is not None, 'cdvdman.c: the power-button thread reaches oplShutdown')

module_make = read('modules/iopcore/cdvdman/Makefile')
check(re.match(r'IOP_OBJS = cdvdman\.o ', module_make) is not None, 'cdvdman.o is in every CDVDMAN variant')
top = read('Makefile')
variants = re.findall(r'\t\$\(MAKE\) \$\(CDVDMAN_PS2LOGO_FLAGS\)[^\n]*?(USE_[A-Z_]+)=1 -C \$< all', top)
check(len(variants) == 8, 'eight CDVDMAN variants in the top Makefile (got %d)' % len(variants))


def variant_defines(use, debug, diag):
    """-D flags the CDVDMAN Makefile gives one variant (ifeq/endif nesting, USE_DEV9 assignment)."""
    vars_ = {use: '1', 'IOPCORE_DEBUG': debug, 'INGAMEDIAG': diag, 'USE_DEV9': '0'}
    stack, defs = [], set()
    for line in module_make.split('\n'):
        s = line.strip()
        m = re.match(r'ifeq \(\$\((\w+)\),1\)', s)
        if m:
            stack.append(vars_.get(m.group(1)) == '1')
            continue
        if s == 'endif':
            stack.pop()
            continue
        if not all(stack):
            continue
        if re.match(r'USE_DEV9 = 1', s):
            vars_['USE_DEV9'] = '1'
        if s.startswith('IOP_CFLAGS +='):
            defs.update(re.findall(r'-D(\w+)', s))
    return sorted(defs)


region = cdvdman[start:cdvdman.find(shutdown) + len(shutdown)] if (start >= 0 and shutdown) else ''
seen = set()
for use in variants:
    for debug in ('0', '1'):
        for diag in ('0', '1'):
            defs = variant_defines(use, debug, diag)
            if region:
                pre = subprocess.run(['gcc', '-E', '-P', '-x', 'c'] + ['-D' + d for d in defs] + ['-'],
                                     input=region, capture_output=True, text=True)
                body = pre.stdout[pre.stdout.find('static void oplShutdown('):]
                ok = (pre.returncode == 0 and 'static void cdvdman_vmc_drain(void)' in pre.stdout and
                      re.search(r'u32 stat;\s*cdvdman_vmc_drain\(\);\s*DeviceLock\(\);', body) is not None)
                check(ok, '%s (debug=%s, INGAMEDIAG=%s, -D%s): oplShutdown drains before DeviceLock'
                      % (use, debug, diag, ' -D'.join(defs)))
            seen.add(tuple(defs))
check(len(seen) >= 8, 'variant flag sets were parsed from the CDVDMAN Makefile (%d distinct)' % len(seen))

# ---------------------------------------------------------------------------
# 3. Every VMC export MCEMU calls reports to the drain, around the whole device call.

EXPORTS = [
    ('modules/iopcore/cdvdman/device-bdm.c', 'bdm_readSector(', '0', 'WaitSema(bdm_io_sema);', 'SignalSema(bdm_io_sema);'),
    ('modules/iopcore/cdvdman/device-bdm.c', 'bdm_writeSector(', '1', 'WaitSema(bdm_io_sema);', 'SignalSema(bdm_io_sema);'),
    ('modules/iopcore/cdvdman/device-mmce.c', 'mmce_read_offset(', '0', 'WaitSema(mmce_io_sema);', 'SignalSema(mmce_io_sema);'),
    ('modules/iopcore/cdvdman/device-mmce.c', 'mmce_write_offset(', '1', 'WaitSema(mmce_io_sema);', 'SignalSema(mmce_io_sema);'),
    ('modules/iopcore/cdvdman/device-hdd.c', 'hdd_vmcDmaTransfer(', 'dir == ATA_DIR_WRITE', 'res = sceAtaDmaTransfer(device, buf, lba, nsectors, dir);', None),
    ('modules/iopcore/cdvdman/device-smb.c', 'smb_vmcReadFile(', '0', 'res = smb_ReadFile(FID, offsetlow, offsethigh, readbuf, nbytes);', None),
    ('modules/iopcore/cdvdman/device-smb.c', 'smb_vmcWriteFile(', '1', 'res = smb_WriteFile(FID, offsetlow, offsethigh, writebuf, nbytes);', None),
]
for rel, sig, kind, first, last in EXPORTS:
    # The return type is not what matters here (void or int), only where the hooks sit.
    src = read(rel)
    match = re.search(r'^(?:void|int) ' + re.escape(sig), src, re.M)
    body = function(src, src[match.start():match.end()], rel) if match else ''
    if not body:
        failures.append('%s: %s...) not found' % (rel, sig))
        continue
    begin = 'cdvdman_vmc_io_begin(%s);' % kind
    i_begin, i_first = body.find(begin), body.find(first)
    i_last = body.find(last) if last else i_first
    i_end = body.find('cdvdman_vmc_io_end();')
    check(body.count('cdvdman_vmc_io_begin(') == 1 and body.count('cdvdman_vmc_io_end();') == 1,
          '%s %s: one begin and one end' % (rel, sig))
    check(0 <= i_begin < i_first <= i_last < i_end, '%s %s: %s before the device call, end after it'
          % (rel, sig, begin))
    check('return' not in body[i_begin:i_end], '%s %s: no return between begin and end' % (rel, sig))

hooks = []
for path in sorted((root / 'modules/iopcore/cdvdman').glob('*.c')):
    for m in re.finditer(r'cdvdman_vmc_io_(?:begin|end)\(', path.read_text(encoding='utf-8')):
        hooks.append(path.name)
check(hooks.count('cdvdman.c') == 2 and len(hooks) == 2 + 2 * len(EXPORTS),
      'only the VMC exports (not the game-image reads) report to the drain: %s' % hooks)

# MCEMU imports these by slot number; each slot must still hold the same call (or its reporting wrapper).
utils = read('modules/mcemu/mcemu_utils.h')
tab = read('modules/iopcore/cdvdman/exports.tab')
EXPECTED = {
    'BDM_DRIVER': ['bdm_readSector', 'bdm_writeSector'],
    'MMCE_DRIVER': ['mmce_read_offset', 'mmce_write_offset'],
    'HDD_DRIVER': ['hdd_vmcDmaTransfer'],
    'SMB_DRIVER': ['smb_OpenAndX', 'smb_vmcReadFile', 'smb_vmcWriteFile', 'smb_Close'],
}
IMPORTED = {
    'BDM_DRIVER': ['bdm_readSector', 'bdm_writeSector'],
    'MMCE_DRIVER': ['mmce_read_offset', 'mmce_write_offset'],
    'HDD_DRIVER': ['sceAtaDmaTransfer'],
    'SMB_DRIVER': ['smb_OpenAndX', 'smb_ReadFile', 'smb_WriteFile', 'smb_Close'],
}
for driver, names in EXPECTED.items():
    pre = subprocess.run(['gcc', '-E', '-P', '-x', 'c', '-D' + driver, '-'], input=tab, capture_output=True, text=True)
    tables = dict(re.findall(r'DECLARE_EXPORT_TABLE\((\w+),[^)]*\)(.*?)END_EXPORT_TABLE', pre.stdout, re.S))
    slots = re.findall(r'DECLARE_EXPORT\((\w+)\)', tables.get('oplutils', ''))
    check(slots == ['_retonly'] * 4 + ['getModInfo', 'oplRegisterShutdownCallback'] + names,
          '%s: oplutils exports %s' % (driver, slots))
    for n, name in enumerate(IMPORTED[driver], 6):
        check(re.search(r'DECLARE_IMPORT\(%d, %s\)' % (n, name), utils) is not None,
              'mcemu_utils.h: MCEMU imports %s from oplutils slot %d' % (name, n))

if failures:
    for f in failures:
        print('FAIL:', f)
    sys.exit(1)
print('test_igr_vmc_drain: all checks passed')
