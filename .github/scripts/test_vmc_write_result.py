"""BDM and MMCE VMC page writes, reads and erases report device failures to MCMAN.

Compiles the production chain on the host, as two objects linked like the two IOP modules:
mcemu (Sio2McEmu -> MceWrite/MceRead/MceEraseBlock -> DeviceWritePage/DeviceReadPage from
modules/mcemu/device-bdm.c or device-mmce.c) and cdvdman (bdm_writeSector/bdm_readSector or
mmce_write_offset/mmce_read_offset) over a simulated block device or mmcedrv. Transfers are
built the way ps2sdk's MCMAN reimplementation (mcsio2.c) builds them: a page write is
0x22 + data + ECC, a page read is 0x23 + data + ECC + 0x81 and an erase is 0x21 + 0x82 in ONE SIO2
transfer, so a trailing status command must not turn a failed access into a success. The
simulated block device fails the way the shipped drivers do: -EIO (usbmass_bd, IEEE1394_bd, ATA)
or a short sector count (mx4sio_bd). Also pins the oplutils export/import
signatures (the two modules are linked by ordinal, so nothing else checks that they agree).
Linux CI enables ASan/UBSan; this is a host regression, not console acceptance.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FAILURES = []


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def check(cond, what):
    if not cond:
        FAILURES.append(what)


def definition(source, name):
    """The body of the function named name (a definition, never a prototype)."""
    for match in re.finditer(r'^[A-Za-z_][\w \t\*]*\b' + re.escape(name) + r'\s*\(', source, re.M):
        brace, semi = source.find('{', match.end()), source.find(';', match.end())
        if brace != -1 and (semi == -1 or brace < semi):
            end, depth = brace, 1
            while depth:
                end += 1
                depth += (source[end] == '{') - (source[end] == '}')
            return source[match.start():end + 1]
    raise AssertionError('no definition of ' + name)


def header(source, name):
    """The definition's signature with whitespace normalized."""
    text = definition(source, name)
    return ' '.join(text[:text.index('{')].split())


def prototype(source, name):
    match = re.search(r'^([A-Za-z_][\w \t\*]*\b' + re.escape(name) + r'\s*\([^;{]*\))\s*;', source, re.M)
    assert match, 'no prototype of ' + name
    return ' '.join(match.group(1).split())


def block(source, start, end):
    i = source.index(start)
    return source[i:source.index(end, i) + len(end)]


def export_ordinals(table, define):
    """Ordinal of every DECLARE_EXPORT in table, as compiled with define set."""
    names, stack = [], []
    for line in table.split('\n'):
        s = line.strip()
        if s.startswith('#ifdef'):
            stack.append(s.split()[1] == define)
        elif s.startswith('#endif'):
            stack.pop()
        elif s.startswith('DECLARE_EXPORT(') and all(stack):
            names.append(s[len('DECLARE_EXPORT('):s.index(')')])
    return {name: i for i, name in enumerate(names)}


cdvdman_bdm = read('modules/iopcore/cdvdman/device-bdm.c')
cdvdman_mmce = read('modules/iopcore/cdvdman/device-mmce.c')
exports = read('modules/iopcore/cdvdman/exports.tab')
utils = read('modules/mcemu/mcemu_utils.h')
imports = read('modules/mcemu/imports.lst')
mcemu_h = read('modules/mcemu/mcemu.h')
mcemu = read('modules/mcemu/mcemu.c')
mcemu_sys = read('modules/mcemu/mcemu_sys.c')
mcemu_var = read('modules/mcemu/mcemu_var.c')
mcemu_io = read('modules/mcemu/mcemu_io.c')

# 1. Export signature: the import mcemu declares is the function cdvdman exports, at the same ordinal.
oplutils = block(exports, 'DECLARE_EXPORT_TABLE(oplutils, 1, 2)', 'END_EXPORT_TABLE')
check('#define oplutils_IMPORTS_start DECLARE_IMPORT_TABLE(oplutils, 1, 2)' in utils, 'oplutils import table version 1.2')
SIGNATURES = {
    'bdm_readSector': ('BDM_DRIVER', cdvdman_bdm, 6, 'int bdm_readSector(u64 lba, unsigned short int nsectors, unsigned char *buffer)'),
    'bdm_writeSector': ('BDM_DRIVER', cdvdman_bdm, 7, 'int bdm_writeSector(u64 lba, unsigned short int nsectors, const unsigned char *buffer)'),
    'mmce_read_offset': ('MMCE_DRIVER', cdvdman_mmce, 6, 'int mmce_read_offset(int fd, unsigned int offset, unsigned int size, unsigned char *buffer)'),
    'mmce_write_offset': ('MMCE_DRIVER', cdvdman_mmce, 7, 'int mmce_write_offset(int fd, unsigned int offset, unsigned int size, const unsigned char *buffer)'),
}
for name, (define, source, ordinal, expected) in SIGNATURES.items():
    check(header(source, name) == expected, f'cdvdman defines {expected} (got {header(source, name)})')
    check(prototype(utils, name) == expected, f'mcemu imports {expected} (got {prototype(utils, name)})')
    check(export_ordinals(oplutils, define).get(name) == ordinal, f'{name} is oplutils export {ordinal} under {define}')
    check(f'#define I_{name} DECLARE_IMPORT({ordinal}, {name})' in utils, f'{name} is imported as ordinal {ordinal}')
    guarded = block(imports, f'#ifdef {define}', '#endif')
    check(f'I_{name}' in guarded, f'imports.lst imports {name} under {define}')

# 2. The device layer returns the transfer's outcome instead of a constant 1.
for rel in ('modules/mcemu/device-bdm.c', 'modules/mcemu/device-mmce.c'):
    source = read(rel)
    for name in ('DeviceWritePage', 'DeviceReadPage'):
        check('return 1;' not in definition(source, name), f'{rel} {name} does not report success unconditionally')

# 3. Compile and run the production chain.
TYPES = (block(mcemu_h, 'typedef struct _Sio2Packet', '} Sio2Packet;') + '\n'
         + block(mcemu_h, '/* Memory Card Spec (do not change this structure) */', '} MemoryCard;'))
MCEMU_PROTOTYPES = block(mcemu_h, 'void SioResponse(MemoryCard *mcd, void *buf, int length);',
                         'int MceWrite(MemoryCard *mcd, void *buf, u32 size);')
MCEMU_CODE = '\n'.join(definition(mcemu, name) for name in (
    'sio2McUnlock', 'sio2McLock', 'Sio2McEmu', 'SioResponse', 'MceEraseBlock', 'do_read',
    'MceStartRead', 'MceRead', 'MceStartWrite', 'MceWrite'))
HELPERS = '\n'.join(definition(mcemu_sys, name) for name in ('GetInt', 'CalculateEDC', 'CalculateECC'))
XORTABLE = block(mcemu_var, 'const u8 xortable[256] = {', '};')

COMMON = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define DPRINTF(...) do { } while (0)
'''

MCEMU_SIDE = COMMON + r'''
#define MCEMU_PORTS 2
#define PAGE 512
@TYPES@
@IMPORTS@
#include "sim.h"
static void mips_memcpy(void *d, const void *s, unsigned n) { memcpy(d, s, n); }
static void mips_memset(void *d, int c, unsigned n) { memset(d, c, n); }
@XORTABLE@
McImageSpec vmcSpec[MCEMU_PORTS];
MemoryCard memcards[MCEMU_PORTS];
u8 mceccbuf[MCEMU_PORTS][0x20];
u8 mcdatabuf[0x200];
typedef void (*Sio2McProc2)(void);
static int locks, unlocks;
static void lock_stub(void) { locks++; }
static void unlock_stub(void) { unlocks++; }
static Sio2McProc2 psio2_mc_transfer_init[2] = {lock_stub, lock_stub}, psio2_transfer_reset[2] = {unlock_stub, unlock_stub};
static int sio2TransferVersion;
int DeviceWritePage(int mc_num, void *buf, u32 page_num);
int DeviceReadPage(int mc_num, void *buf, u32 page_num);
#ifdef BDM_DRIVER
int DeviceWritePages(int mc_num, void *buf, u32 page_num, u32 count);
#endif
@MCEMU_PROTOTYPES@
@HELPERS@
@MC_CONFIGURE@
@MCEMU_CODE@
@DEVICE@

/* One SIO2 transfer, laid out the way MCMAN lays it out (0x90-byte slots, DMA mode). */
typedef struct { u8 cmd; u32 page; const u8 *data; int len; } Cmd;
static u8 wbuf[16][0x90], rbuf[16][0x90];
static u32 transfer(const Cmd *cmds, int n)
{
    Sio2Packet p;
    memset(&p, 0, sizeof(p));
    memset(wbuf, 0, sizeof(wbuf));
    memset(rbuf, 0xEE, sizeof(rbuf));
    for (int i = 0; i < n; i++) {
        u8 *w = wbuf[i];
        int length = 4;
        w[0] = 0x81;
        w[1] = cmds[i].cmd;
        if (cmds[i].cmd == 0x21 || cmds[i].cmd == 0x22 || cmds[i].cmd == 0x23) {
            for (int b = 0; b < 4; b++)
                w[2 + b] = (u8)(cmds[i].page >> (8 * b));
            length = 9;
        } else if (cmds[i].cmd == 0x42 || cmds[i].cmd == 0x43) {
            w[2] = (u8)cmds[i].len;
            if (cmds[i].data)
                memcpy(&w[3], cmds[i].data, cmds[i].len);
            length = cmds[i].len + 6;
        }
        p.ctrl[i] = 0x70 | ((u32)length << 18); /* port 0 */
    }
    p.wrmaddr = wbuf; p.wrwords = 0x90 / 4; p.wrcount = n;
    p.rdmaddr = rbuf; p.rdwords = 0x90 / 4; p.rdcount = n;
    Sio2McEmu(&p, 0);
    assert(locks == unlocks); /* SIO2 is handed back locked, as the caller expects */
    return p.iostatus;
}
#define OK(status) (((status) & 0xF000) == 0x1000)

static u8 ecc[16];
static u32 write_page(u32 page, const u8 *data)
{
    Cmd c[6] = {{0x22, page, NULL, 0}};
    for (int k = 0; k < 4; k++)
        c[1 + k] = (Cmd){0x42, 0, data + 128 * k, 128};
    c[5] = (Cmd){0x42, 0, ecc, 16};
    return transfer(c, 6);
}
static u32 read_page(u32 page, u8 *out)
{
    Cmd c[7] = {{0x23, page, NULL, 0}};
    for (int k = 0; k < 4; k++)
        c[1 + k] = (Cmd){0x43, 0, NULL, 128};
    c[5] = (Cmd){0x43, 0, NULL, 16};
    c[6] = (Cmd){0x81, 0, NULL, 0}; /* "read/write end" rides in the same transfer */
    u32 status = transfer(c, 7);
    for (int k = 0; k < 4; k++) {
        memcpy(out + 128 * k, &rbuf[1 + k][4], 128);
        assert(rbuf[1 + k][132] == CalculateEDC(&rbuf[1 + k][4], 128)); /* EDC always matches the bytes */
    }
    return status;
}
static u32 erase_block(u32 page)
{
    Cmd c[2] = {{0x21, page, NULL, 0}, {0x82, 0, NULL, 0}}; /* erase + its status, one transfer */
    return transfer(c, 2);
}
static u32 probe(void)
{
    Cmd c[1] = {{0x11, 0, NULL, 0}};
    return transfer(c, 1);
}

int main(void)
{
    u8 data[PAGE], got[PAGE], ff[PAGE];
    memset(ff, 0xFF, sizeof(ff));
    sim_reset();
    vmcSpec[0].active = 1;
    vmcSpec[0].cspec.PageSize = PAGE;
    vmcSpec[0].cspec.BlockSize = 16;
    vmcSpec[0].cspec.CardSize = SIM_PAGES;
    @SETUP@
    assert(mc_configure(memcards) == 1 && memcards[0].mcnum == 0 && memcards[1].mcnum == -1);

    for (int mode = 0; mode < SIM_MODES; mode++) {
        sim_reset();
        for (int i = 0; i < PAGE; i++)
            data[i] = (u8)(i * 7 + mode);

        /* Success path: unchanged. */
        assert(OK(write_page(3, data)) && memcmp(sim_page(3), data, PAGE) == 0);
        assert(DeviceWritePage(0, data, 4) == 1 && memcmp(sim_page(4), data, PAGE) == 0);
        memset(got, 0, sizeof(got));
        assert(OK(read_page(3, got)) && memcmp(got, data, PAGE) == 0);
        assert(DeviceReadPage(0, got, 4) == 1 && memcmp(got, data, PAGE) == 0);
        int before = sim_writes();
        assert(OK(erase_block(16)));
        for (int p = 16; p < 32; p++)
            assert(memcmp(sim_page(p), ff, PAGE) == 0);
        assert(memcmp(sim_page(15), ff, PAGE) != 0 && memcmp(sim_page(32), ff, PAGE) != 0); /* only the block */
#ifdef BDM_DRIVER
        assert(sim_writes() - before == 4); /* 16 pages, 4 sectors per device write */
        /* MX4SIO ("sdc") gets one sector per device write (its multi-sector retry restarts at the
           first sector, ps2sdk#936), and the whole block is still erased. */
        sim_driver("sdc");
        before = sim_writes();
        assert(OK(erase_block(16)));
        for (int p = 16; p < 32; p++)
            assert(memcmp(sim_page(p), ff, PAGE) == 0);
        assert(sim_writes() - before == 16);
        sim_driver("mass");
#else
        assert(sim_writes() - before == 16); /* one write per page */
#endif
        /* A 0x00-erase card (flag 0x10) erases to zeroes on the batched path too. */
        memcards[0].flags |= 0x10;
        assert(OK(erase_block(48)));
        u8 zero[PAGE];
        memset(zero, 0, sizeof(zero));
        for (int p = 48; p < 64; p++)
            assert(memcmp(sim_page(p), zero, PAGE) == 0);
        memcards[0].flags &= ~0x10;

        /* A failed device write is a failed page write, not an acknowledged save. */
        sim_fail(5, mode);
        assert(DeviceWritePage(0, data, 5) == 0);
        assert(!OK(write_page(5, data)));
        assert(OK(probe())); /* the failure is per transfer: MCMAN's card probe still answers */
        sim_fail(-1, mode);
        assert(OK(write_page(5, data)) && memcmp(sim_page(5), data, PAGE) == 0); /* MCMAN's retry lands */

        /* A failed erase fails the erase transfer even though its 0x82 status follows. */
        sim_fail(37, mode);
        assert(!OK(erase_block(32)));
        sim_fail(-1, mode);
        assert(OK(erase_block(32)));

        /* A failed read is reported (with 0xFF data), never stale data under a good status. */
        memcpy(mcdatabuf, data, PAGE); /* what the previous access left in the shared buffer */
        sim_fail(3, mode);
        assert(DeviceReadPage(0, got, 3) == 0);
        assert(!OK(read_page(3, got)) && memcmp(got, ff, PAGE) == 0);
        sim_fail(-1, mode);
        assert(OK(read_page(3, got)) && memcmp(got, data, PAGE) == 0);
        assert(sim_balanced());
    }
    @EXTRA@
    puts("PASS: @NAME@ VMC writes, reads and erases report device failures; success unchanged");
    return 0;
}
'''

BDM_SIM = COMMON + r'''
#include "sim.h"
struct block_device {
    int (*read)(struct block_device *bd, u64 sector, void *buffer, u16 count);
    int (*write)(struct block_device *bd, u64 sector, const void *buffer, u16 count);
    const char *name;
    unsigned int sectorSize;
};
static int depth, waits;
static void WaitSema(int s) { (void)s; assert(depth == 0); depth++; waits++; }
static void SignalSema(int s) { (void)s; assert(depth == 1); depth--; }
/* The IGR VMC drain's activity hooks (cdvdman.c); they do not affect the result. */
static void __attribute__((unused)) cdvdman_vmc_io_begin(int w) { (void)w; }
static void __attribute__((unused)) cdvdman_vmc_io_end(void) {}
static int bdm_io_sema;
static struct block_device *g_bd;
#define BASE 1000u /* the VMC file's first sector */
static u8 disk[SIM_PAGES][512];
static int fail_page = -1, fail_mode;
/* mode 0: usbmass_bd/IEEE1394_bd/ATA return -EIO; mode 1: mx4sio_bd returns a short count */
static int failed(u64 sector, u16 count)
{
    return fail_page >= 0 && sector <= BASE + (u64)fail_page && BASE + (u64)fail_page < sector + count;
}
static int sim_read(struct block_device *bd, u64 sector, void *buffer, u16 count)
{
    assert(bd == g_bd && depth == 1 && sector >= BASE && sector + count <= BASE + SIM_PAGES);
    if (failed(sector, count))
        return fail_mode ? count - 1 : -5;
    memcpy(buffer, disk[sector - BASE], count * 512u);
    return count;
}
static int writes;
int sim_writes(void) { return writes; }
static int sim_write(struct block_device *bd, u64 sector, const void *buffer, u16 count)
{
    assert(bd == g_bd && depth == 1 && sector >= BASE && sector + count <= BASE + SIM_PAGES);
    writes++;
    if (failed(sector, count))
        return fail_mode ? count - 1 : -5;
    memcpy(disk[sector - BASE], buffer, count * 512u);
    return count;
}
static struct block_device device = {.read = sim_read, .write = sim_write, .name = "mass", .sectorSize = 512};
@DRIVER@
void sim_reset(void) { memset(disk, 0x5A, sizeof(disk)); fail_page = -1; g_bd = &device; device.name = "mass"; }
void sim_driver(const char *name) { device.name = name; }
void sim_fail(int page, int mode) { fail_page = page; fail_mode = mode; }
const u8 *sim_page(int page) { return disk[page]; }
int sim_balanced(void) { return depth == 0 && waits > 0; }
u64 sim_base(void) { return BASE; }
@DIRECT@
'''

BDM_DIRECT = r'''
int sim_direct(void)
{
    static u8 buf[4 * 512];
    sim_reset();
    assert(bdm_writeSector(BASE + 8, 4, buf) == 1 && bdm_readSector(BASE + 8, 4, buf) == 1);
    sim_fail(10, 1); /* mx4sio_bd writes 3 of 4: a short count is a failure */
    assert(bdm_writeSector(BASE + 8, 4, buf) == 0 && bdm_readSector(BASE + 8, 4, buf) == 0);
    sim_fail(10, 0);
    assert(bdm_writeSector(BASE + 8, 4, buf) == 0 && bdm_readSector(BASE + 8, 4, buf) == 0);
    return depth == 0;
}
'''

MMCE_SIM = COMMON + r'''
#include "sim.h"
static int depth, waits;
static void WaitSema(int s) { (void)s; assert(depth == 0); depth++; waits++; }
static void SignalSema(int s) { (void)s; assert(depth == 1); depth--; }
/* The IGR VMC drain's activity hooks (cdvdman.c); they do not affect the result. */
static void __attribute__((unused)) cdvdman_vmc_io_begin(int w) { (void)w; }
static void __attribute__((unused)) cdvdman_vmc_io_end(void) {}
static int mmce_io_sema;
@FPS@
#define FD 7
static u8 file[SIM_PAGES][512];
static int pos = -1, fail_page = -1, fail_mode;
/* mode 0: the transfer fails (-1); mode 1: the card reports a short byte count; mode 2: the seek fails */
static int sim_lseek(int fd, int offset, int whence)
{
    assert(depth == 1 && whence == 0);
    if (fd != FD || (fail_mode == 2 && fail_page == offset / 512) || offset < 0 || offset >= SIM_PAGES * 512)
        return -1;
    return pos = offset;
}
static int sim_io(int fd, int size, void *ptr, int write)
{
    assert(depth == 1 && fd == FD && pos >= 0 && pos % 512 == 0 && pos + size <= SIM_PAGES * 512);
    if (fail_page == pos / 512 && fail_mode != 2)
        return fail_mode ? size - 1 : -1;
    if (write)
        memcpy(file[pos / 512], ptr, size);
    else
        memcpy(ptr, file[pos / 512], size);
    pos = -1;
    return size;
}
static int sim_read(int fd, int size, void *ptr) { return sim_io(fd, size, ptr, 0); }
static int writes;
int sim_writes(void) { return writes; }
static int sim_write(int fd, int size, void *ptr) { writes++; return sim_io(fd, size, ptr, 1); }
@DRIVER@
void sim_reset(void)
{
    memset(file, 0x5A, sizeof(file));
    fail_page = -1;
    fp_mmcedrv_lseek = sim_lseek;
    fp_mmcedrv_read = sim_read;
    fp_mmcedrv_write = sim_write;
}
void sim_fail(int page, int mode) { fail_page = page; fail_mode = mode; }
const u8 *sim_page(int page) { return file[page]; }
int sim_balanced(void) { return depth == 0 && waits > 0; }
int sim_fd(void) { return FD; }
int sim_direct(void)
{
    static u8 buf[512];
    sim_reset();
    fp_mmcedrv_write = NULL; /* mmcedrv not resident: DeviceFSInit never resolved it */
    assert(mmce_write_offset(FD, 0, 512, buf) == 0);
    fp_mmcedrv_lseek = NULL;
    assert(mmce_read_offset(FD, 0, 512, buf) == 0);
    sim_reset();
    assert(mmce_write_offset(FD + 1, 0, 512, buf) == 0); /* a stale fd fails at the seek */
    return depth == 0;
}
'''

SIM_H = r'''
#define SIM_PAGES 64
void sim_reset(void);
void sim_fail(int page, int mode);
const u8 *sim_page(int page);
int sim_balanced(void);
int sim_direct(void);
int sim_writes(void);
void sim_driver(const char *name);
'''

bdm_returns_int = header(cdvdman_bdm, 'bdm_writeSector').startswith('int ') and header(cdvdman_bdm, 'bdm_readSector').startswith('int ')
mmce_fps = '\n'.join(re.search(r'^int \(\*fp_mmcedrv_' + name + r'\)\([^;]*\);$', cdvdman_mmce, re.M).group(0)
                     for name in ('read', 'write', 'lseek'))
VARIANTS = [
    ('BDM', 'BDM_DRIVER', 'modules/mcemu/device-bdm.c', 2,
     'vmcSpec[0].stsec = sim_base();', 'u64 sim_base(void);',
     BDM_SIM.replace('@DRIVER@', definition(cdvdman_bdm, 'bdm_readSector') + '\n' + definition(cdvdman_bdm, 'bdm_writeSector'))
            .replace('@DIRECT@', BDM_DIRECT if bdm_returns_int else 'int sim_direct(void) { return 0; }')),
    ('MMCE', 'MMCE_DRIVER', 'modules/mcemu/device-mmce.c', 3,
     'vmcSpec[0].fd = sim_fd();', 'int sim_fd(void);',
     MMCE_SIM.replace('@FPS@', mmce_fps)
             .replace('@DRIVER@', definition(cdvdman_mmce, 'mmce_read_offset') + '\n' + definition(cdvdman_mmce, 'mmce_write_offset'))),
]
with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    (directory / 'sim.h').write_text(SIM_H, encoding='utf-8')
    for name, define, device, modes, setup, setup_decl, sim in VARIANTS:
        imported = '\n'.join(prototype(utils, fn) + ';' for fn, spec in SIGNATURES.items() if spec[0] == define)
        side = (MCEMU_SIDE.replace('@TYPES@', TYPES).replace('@IMPORTS@', imported)
                .replace('@XORTABLE@', XORTABLE).replace('@MCEMU_PROTOTYPES@', MCEMU_PROTOTYPES)
                .replace('@HELPERS@', HELPERS).replace('@MC_CONFIGURE@', definition(mcemu_io, 'mc_configure'))
                .replace('@MCEMU_CODE@', MCEMU_CODE)
                .replace('@DEVICE@', definition(read(device), 'DeviceWritePage') + '\n' + definition(read(device), 'DeviceReadPage')
                          + ('\n' + definition(read(device), 'DeviceWritePages') if define == 'BDM_DRIVER' else ''))
                .replace('@SETUP@', setup).replace('@NAME@', name)
                .replace('@EXTRA@', 'assert(sim_direct()); /* multi-sector and missing-driver edges */'))
        side = side.replace('#include "sim.h"', '#include "sim.h"\n' + setup_decl + '\n#define SIM_MODES ' + str(modes), 1)
        mcemu_c, cdvdman_c = directory / (name + '_mcemu.c'), directory / (name + '_cdvdman.c')
        mcemu_c.write_text(side, encoding='utf-8')
        cdvdman_c.write_text(sim, encoding='utf-8')
        binary = directory / (name + '.exe')
        flags = ['-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-Wno-unused-function',
                 '-D' + define, '-I' + str(directory)]
        if os.name != 'nt':
            flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer']
        built = subprocess.run([os.environ.get('CC', 'gcc'), *flags, str(mcemu_c), str(cdvdman_c), '-o', str(binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode != 0:
            FAILURES.append(f'{name}: production chain did not compile:\n{built.stderr[-3000:]}')
            continue
        ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        if ran.returncode != 0:
            FAILURES.append(f'{name}: {(ran.stdout + ran.stderr).strip()[-1500:]}')
        else:
            print(ran.stdout.strip())

if FAILURES:
    for failure in FAILURES:
        print('FAIL:', failure)
    sys.exit(1)
print('test_vmc_write_result: all checks passed (host only; console unverified)')
