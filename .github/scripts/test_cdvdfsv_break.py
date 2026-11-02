#!/usr/bin/env python3
"""Regression tests for EE reads that sceCdBreak stops (Tales of the Abyss: RiptOPL #185, Open-PS2-Loader #924).

cdvdfsv serves the EE's sceCdRead (cdvd_readee) and sceCdReadChain (cdvd_readchain) in chunks. A break that lands
during a chunk leaves sectors in cdvdfsv's buffer that the read never produced, so none of that chunk may reach EE
memory, and the EE must be told only the bytes it got. Both functions are compiled on the host from ncmd.c, with
AddressSanitizer when it is available, and run against a simulated cdvdman and EE memory: including the case where
something resets the shared error code before cdvdfsv looks (sceCdDiskReady on another cdvdfsv thread resets it to
SCECdErNO in OPL, and so does a stream fill), which used to let a cut-short chunk through as data.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NCMD = ROOT / 'modules/iopcore/cdvdfsv/ncmd.c'
FSV = ROOT / 'modules/iopcore/cdvdfsv/cdvdfsv.c'
OPL_H = ROOT / 'modules/iopcore/common/cdvdman_opl.h'
CDVDMAN = ROOT / 'modules/iopcore/cdvdman/cdvdman.c'
CDVDMAN_SCMD = ROOT / 'modules/iopcore/cdvdman/scmd.c'
CDVDMAN_DIR = ROOT / 'modules/iopcore/cdvdman'
CC = shutil.which('cc') or shutil.which('gcc')
SECTOR = 2048


def function(text, name):
    match = re.search(r'\n[^\n;{}]*\b' + re.escape(name) + r'\([^;{]*\)[^;{\n]*\n\{', text)
    assert match, name
    depth, i = 0, match.end() - 1
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[match.start():i]


def typedef(text, name):
    match = re.search(r'typedef struct\s*\{[^}]*\}\s*' + re.escape(name) + ';', text)
    assert match, name
    return match.group(0)


def define(text, name):
    match = re.search(r'#define ' + re.escape(name) + r'\s+(\w+)', text)
    assert match, name
    return match.group(1)


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef struct { u8 trycount; u8 spindlctrl; u8 datapattern; u8 pad; } sceCdRMode;
enum { SCECdSecS2048 = 0, SCECdSecS2328, SCECdSecS2340 };
enum { SCECdErNO = 0x00, SCECdErABRT = 0x01, SCECdErREADCF = 0xFD, SCECdErREADCFR = 0xFE };
#define CDVDMAN_FS_SECTORS %(fs_sectors)s
#define CDSC_SET_ERROR %(set_error)s

#define EE_BASE 0x00100000u
#define EE_SIZE 0x00100000u
#define IOP_BASE 0x00300000u
#define IOP_SIZE 0x00040000u
#define UNTOUCHED 0xA5 /* EE and IOP memory before the read */
#define STALE 0xEE     /* what cdvdfsv's buffer holds where a break stopped the read */

static u8 disc[256 * 2048];
static u8 ee[EE_SIZE];
static u8 iop[IOP_SIZE];
static u8 fs_buf[CDVDMAN_FS_SECTORS * 2048 + 64];
u8 *cdvdfsv_buf = fs_buf;
static volatile unsigned char break_flag; /* cdvdman's cdvdfsv_break */
volatile unsigned char *cdvdfsv_break = &break_flag;

static int err;              /* cdvdman_stat.err */
static int reads, sends;     /* sceCdRead and sysmemSendEE calls so far */
static int break_read;       /* the sceCdRead call that a break cuts short (from 1), or 0 */
static int break_sectors;    /* sectors that call reads before the break stops it */
static int break_after_send; /* a break with no read in flight, right after this sysmemSendEE call (from 1), or 0 */
static int reset_error;      /* the error code is reset before cdvdfsv looks: sceCdDiskReady on another thread, a fill */

static void accept_break(void) /* cdvdman_BreakRead, or sceCdBreak's path with no read in flight */
{
    err = SCECdErABRT;
    break_flag = 1;
    if (reset_error)
        err = SCECdErNO;
}

static u8 *iop_or_host(void *p, u32 size)
{
    uintptr_t a = (uintptr_t)p;
    if (a >= IOP_BASE && a < IOP_BASE + IOP_SIZE) {
        if (a + size > IOP_BASE + IOP_SIZE) {
            fprintf(stderr, "read past IOP memory\n");
            exit(3);
        }
        return iop + (a - IOP_BASE);
    }
    return (u8 *)p;
}

int sceCdRead(u32 lsn, u32 sectors, void *buf, sceCdRMode *mode)
{
    u8 *dst = iop_or_host(buf, sectors * 2048);
    u32 done = sectors;

    reads++;
    err = SCECdErNO; /* cdvdman_read_sectors starts every read with the error reset */
    if (reads == break_read) {
        done = break_sectors;
        memset(dst + done * 2048, STALE, (sectors - done) * 2048);
        accept_break();
    }
    memcpy(dst, disc + lsn * 2048, done * 2048);
    return 1;
}

int sceCdSync(int mode) { return 0; }
int sceCdGetError(void) { return err; }
int sceCdDiskReady(int mode) { err = SCECdErNO; return 2; } /* OPL's resets the error code; Sony's does not */

int sceCdSC(int code, int *param)
{
    if ((u32)code == (u32)CDSC_SET_ERROR)
        return err = *param;
    return 1;
}

void sysmemSendEE(void *buf, void *EE_addr, int size)
{
    u32 a = (u32)(uintptr_t)EE_addr;

    if (a < EE_BASE || a + size > EE_BASE + EE_SIZE) {
        fprintf(stderr, "sysmemSendEE outside EE memory: %%x %%d\n", a, size);
        exit(3);
    }
    memcpy(ee + (a - EE_BASE), buf, size);
    if (++sends == break_after_send)
        accept_break();
}

%(types)s
%(code)s

/* The first byte of [addr, addr + len) that differs from the disc after its first valid bytes, or that the read wrote
   past them: -1 if none. */
static long bad_byte(u32 addr, u32 len, u32 lsn, u32 valid, const u8 *mem, u32 base)
{
    u32 i;
    for (i = 0; i < len; i++) {
        u8 want = i < valid ? disc[lsn * 2048 + i] : UNTOUCHED;
        if (mem[addr - base + i] != want)
            return i;
    }
    return -1;
}

int main(int argc, char **argv)
{
    u32 i;
    const char *what = argv[1];

    break_read = atoi(argv[2]);
    break_sectors = atoi(argv[3]);
    break_after_send = atoi(argv[4]);
    reset_error = atoi(argv[5]);
    for (i = 0; i < sizeof(disc); i++)
        disc[i] = (u8)(i * 7 + i / 2048 * 13 + 1);
    memset(ee, UNTOUCHED, sizeof(ee));
    memset(iop, UNTOUCHED, sizeof(iop));
    memset(fs_buf, STALE, sizeof(fs_buf));

    if (strcmp(what, "readee") == 0) {
        u32 offset = atoi(argv[6]), lsn = 10, sectors = atoi(argv[7]);
        u32 dst = EE_BASE + 0x1000 + offset, rec = EE_BASE + 0x80000, pos = EE_BASE + 0x90000;
        union { RpcCdvd_t r; int result; } rpc;
        cdvdfsv_readee_t record;
        u32 progress;

        memset(&rpc, 0, sizeof(rpc));
        rpc.r.lsn = lsn;
        rpc.r.sectors = sectors;
        rpc.r.buf = (void *)(uintptr_t)dst;
        rpc.r.eeaddr1 = (void *)(uintptr_t)rec;
        rpc.r.eeaddr2 = (void *)(uintptr_t)pos;
        cdvd_readee(&rpc);

        /* The EE's completion callback: copy the alignment record's head and tail bytes into place. */
        memcpy(&record, ee + (rec - EE_BASE), sizeof(record));
        memcpy(&progress, ee + (pos - EE_BASE), sizeof(progress));
        if (record.b1len)
            memcpy(ee + ((u32)(uintptr_t)record.pdst1 - EE_BASE), record.buf1, record.b1len);
        if (record.b2len)
            memcpy(ee + ((u32)(uintptr_t)record.pdst2 - EE_BASE), record.buf2, record.b2len);
        printf("result=%%d progress=%%u err=%%d reads=%%d b1len=%%u b2len=%%u bad=%%ld\n", rpc.result, progress, err,
               reads, record.b1len, record.b2len,
               bad_byte(dst, sectors * 2048, lsn, rpc.result < 0 ? 0 : (u32)rpc.result, ee, EE_BASE));
    } else {
        /* Two entries of 20 sectors: to EE memory ("ee"), or the first to IOP memory ("iop"). */
        RpcCdvdchain_t chain[66];
        u32 a = EE_BASE + 0x1000, b = EE_BASE + 0x20000, iop_dst = IOP_BASE + 0x100, pos = EE_BASE + 0x90000;
        u32 readpos = 0xFFFFFFFF;
        int iop_first = strcmp(what, "chain-iop") == 0;

        memset(chain, 0, sizeof(chain));
        chain[0].lsn = 10;
        chain[0].sectors = 20;
        chain[0].buf = (void *)(uintptr_t)(iop_first ? (iop_dst | 1) : a);
        chain[1].lsn = 40;
        chain[1].sectors = 20;
        chain[1].buf = (void *)(uintptr_t)b;
        chain[2].lsn = 0xFFFFFFFF;
        chain[2].sectors = 0xFFFFFFFF;
        chain[2].buf = (void *)(uintptr_t)0xFFFFFFFF;
        chain[65].sectors = pos;
        memcpy(ee + (pos - EE_BASE), &readpos, sizeof(readpos));
        cdvd_readchain(chain);
        memcpy(&readpos, ee + (pos - EE_BASE), sizeof(readpos));
        printf("readpos=%%u err=%%d reads=%%d first=%%ld second=%%ld\n", readpos, err, reads,
               iop_first ? -2 : bad_byte(a, 20 * 2048, 10, 20 * 2048, ee, EE_BASE),
               bad_byte(b, 20 * 2048, 40, atoi(argv[6]) * 2048, ee, EE_BASE));
    }
    return 0;
}
'''


def harness():
    text = NCMD.read_text()
    opl = OPL_H.read_text()
    types = '\n'.join(typedef(text, name) for name in ('RpcCdvd_t', 'RpcCdvdchain_t', 'cdvdfsv_readee_t'))
    names = ['cdvd_readee', 'cdvd_readchain']
    if re.search(r'\bcdvdfsv_report_break\(void\)\n\{', text):  # the read functions' helper, where there is one
        names.insert(0, 'cdvdfsv_report_break')
    code = '\n'.join(function(text, name) for name in names)
    return HARNESS % {'fs_sectors': define(opl, 'CDVDMAN_FS_SECTORS'), 'set_error': define(opl, 'CDSC_SET_ERROR'),
                      'types': types, 'code': code}


@unittest.skipUnless(CC, 'no host C compiler')
class EeReadBreakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = Path(cls.tmp.name) / 'ncmd_host.c'
        src.write_text(harness())
        cls.exe = Path(cls.tmp.name) / 'ncmd_host'
        for flags in (['-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []):
            built = subprocess.run([CC, '-std=gnu99', '-g', '-O1', '-w', *flags, '-o', str(cls.exe), str(src)],
                                   capture_output=True, text=True)
            if built.returncode == 0:
                break
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_case(self, *args):
        run = subprocess.run([str(self.exe), *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        return {k: int(v) for k, v in (item.split('=') for item in run.stdout.split())}

    def readee(self, offset, sectors=20, break_read=0, break_sectors=0, break_after_send=0, reset_error=0):
        return self.run_case('readee', break_read, break_sectors, break_after_send, reset_error, offset, sectors)

    def chain(self, kind, second_valid, break_read=0, break_sectors=0, break_after_send=0, reset_error=0):
        return self.run_case('chain-' + kind, break_read, break_sectors, break_after_send, reset_error, second_valid)

    def test_whole_reads(self):
        for offset in (0, 16, 63):
            with self.subTest(offset=offset):
                got = self.readee(offset)
                self.assertEqual(got['result'], 20 * SECTOR)
                self.assertEqual(got['progress'], 20 * SECTOR)
                self.assertEqual(got['bad'], -1)
                self.assertEqual(got['err'], 0)

    def test_break_during_a_chunk(self):
        # Offset 16: 48 head bytes travel in the alignment record, and every chunk reads 7 sectors of body plus one.
        for offset, sent in ((0, 8 * SECTOR), (16, 48 + 7 * SECTOR)):
            for reset_error in (0, 1):
                with self.subTest(offset=offset, reset_error=reset_error):
                    got = self.readee(offset, break_read=2, break_sectors=3, reset_error=reset_error)
                    self.assertEqual(got['reads'], 2, 'the read goes on after the break')
                    self.assertEqual(got['result'], sent, 'bytes reported: the head and the chunks before the break')
                    self.assertEqual(got['progress'], sent)
                    self.assertEqual(got['bad'], -1, 'EE memory holds other than the disc data up to the reported '
                                                     'count, or the read wrote past it (byte index)')
                    self.assertEqual(got['b2len'], 0, 'the tail was never read')
                    self.assertEqual(got['err'], 1, 'the EE does not see SCECdErABRT for its broken read')

    def test_break_during_the_first_chunk(self):
        for reset_error in (0, 1):
            with self.subTest(reset_error=reset_error):
                got = self.readee(16, break_read=1, break_sectors=2, reset_error=reset_error)
                self.assertEqual((got['result'], got['progress'], got['b1len'], got['b2len']), (0, 0, 0, 0))
                self.assertEqual(got['bad'], -1)
                self.assertEqual(got['reads'], 1)
                self.assertEqual(got['err'], 1)

    def test_break_between_chunks(self):
        # The break comes while the first chunk goes to the EE, with no read in flight: no chunk is cut short, and
        # the read ends before it starts the next one.
        for reset_error in (0, 1):
            with self.subTest(reset_error=reset_error):
                got = self.readee(16, break_after_send=1, reset_error=reset_error)
                self.assertEqual(got['reads'], 1)
                self.assertEqual(got['result'], 48 + 7 * SECTOR)
                self.assertEqual(got['bad'], -1)
                self.assertEqual(got['err'], 1)

    def test_chain_to_ee(self):
        got = self.chain('ee', 20)
        self.assertEqual((got['readpos'], got['err'], got['reads'], got['first'], got['second']),
                         (40 * SECTOR, 0, 6, -1, -1))
        # Chunks of 8 sectors: the break cuts the second chunk of the second entry short.
        for reset_error in (0, 1):
            with self.subTest(reset_error=reset_error):
                got = self.chain('ee', 8, break_read=5, break_sectors=3, reset_error=reset_error)
                self.assertEqual(got['reads'], 5)
                self.assertEqual(got['first'], -1)
                self.assertEqual(got['second'], -1, 'a chunk the break cut short reached EE memory (byte index)')
                self.assertEqual(got['readpos'], 20 * SECTOR, 'the position is published per finished entry')
                self.assertEqual(got['err'], 1)

    def test_chain_break_between_entries(self):
        # Sends for the first entry: three chunks, then its position. The break comes with no read in flight.
        for reset_error in (0, 1):
            with self.subTest(reset_error=reset_error):
                got = self.chain('ee', 0, break_after_send=4, reset_error=reset_error)
                self.assertEqual((got['reads'], got['first'], got['second']), (3, -1, -1))
                self.assertEqual(got['readpos'], 20 * SECTOR)
                self.assertEqual(got['err'], 1)

    def test_chain_to_iop(self):
        for reset_error in (0, 1):
            with self.subTest(reset_error=reset_error):
                got = self.chain('iop', 0, break_read=1, break_sectors=5, reset_error=reset_error)
                self.assertEqual(got['reads'], 1, 'the chain goes on after the break')
                self.assertEqual(got['readpos'], 0xFFFFFFFF, 'a broken entry published a position')
                self.assertEqual(got['second'], -1)
                self.assertEqual(got['err'], 1)


class SourceTests(unittest.TestCase):
    def test_only_sce_cd_break_sets_the_flag(self):
        sets = {}
        for path in sorted(CDVDMAN_DIR.glob('*.c')):
            text = path.read_text()
            sets[path.name] = len(re.findall(r'\bcdvdfsv_break = 1;', text))
            self.assertEqual(re.findall(r'\bcdvdfsv_break = 0;', text), [],
                             f'{path.name} clears the break flag: only cdvdfsv does')
        self.assertEqual({k: v for k, v in sets.items() if v}, {'cdvdman.c': 1, 'scmd.c': 1})
        self.assertIn('cdvdfsv_break = 1;', function(CDVDMAN.read_text(), 'cdvdman_BreakRead'))
        self.assertIn('cdvdfsv_break = 1;', function(CDVDMAN_SCMD.read_text(), 'sceCdBreak'))
        self.assertRegex(function(CDVDMAN.read_text(), 'sceCdSC'),
                         r'case CDSC_GET_BREAK_FLAG:\n\s*\*param = \(int\)&cdvdfsv_break;')

    def test_cdvdfsv_goes_by_the_flag(self):
        text = NCMD.read_text()
        self.assertEqual(re.findall(r'sceCdGetError\(\)\s*==\s*SCECdErABRT', text), [],
                         'ncmd.c tests the shared error code for a break: another thread can reset it first')
        for name in ('cdvd_readee', 'cdvd_readchain'):
            self.assertEqual(function(text, name).count('*cdvdfsv_break = 0;'), 1, name)
        init = function(FSV.read_text(), 'init_thread')
        self.assertRegex(init, r'sceCdSC\(CDSC_GET_BREAK_FLAG, &(\w+)\);')
        # A CDVDMAN that leaves the answer at 0 must not turn the flag into a pointer to IOP address 0.
        self.assertRegex(init, r'if \(break_flag != 0\)\s*cdvdfsv_break = ')
        self.assertRegex(FSV.read_text(), r'volatile unsigned char \*cdvdfsv_break = &\w+;')
        codes = re.findall(r'#define (CDSC_\w+)\s+(0x[0-9A-Fa-f]+)', OPL_H.read_text())
        self.assertIn(('CDSC_GET_BREAK_FLAG', '0xFFFFFFED'), codes)


if __name__ == '__main__':
    unittest.main()
