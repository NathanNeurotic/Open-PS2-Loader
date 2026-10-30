"""The IOP pad gamefix: .hack//Infection's IOP allocations get room past its known overruns (neutrino #92).

The game writes past the end of IOP buffers it allocates and hangs loading into "The World" on USB,
HDD and UDPBD. Compiles the real Hook_AllocSysMemory() from modules/iopcore/cdvdman/ioplib_util.c
against a fake SYSMEM and checks the three overrun blocks get the overrun plus 256 bytes, every other
block 256 bytes (a flat 2 KB runs the IOP out of RAM, neutrino #148), it falls back to the size asked
for when the larger block does not fit, and never pads a zero or negative size or a fixed-address request. Then checks the flag has a bit of its own,
CDVDMAN installs the hook only when the flag is set, and sbPrepare sets it for the listed titles only.
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


def function(src, signature, name):
    match = re.search(signature, src, re.M)
    if match is None:
        sys.exit('%s: %s not found' % (name, signature))
    return src[match.start():src.index('\n}', match.start()) + 3]


util = read('modules/iopcore/cdvdman/ioplib_util.c')
config = read('modules/iopcore/common/cdvd_config.h')
cdvdman = read('modules/iopcore/cdvdman/cdvdman.c')
support = read('src/supportbase.c')

hook = function(util, r'^static void \*Hook_AllocSysMemory\(int mode, int size, void \*ptr\)\s*\{', 'ioplib_util.c')
blocks_at = util.find('static const struct\n{\n    int size;')
if blocks_at < 0:
    sys.exit('ioplib_util.c: iop_pad_blocks not found')
pad_for = util[blocks_at:util.index('static void *(*AllocSysMemory_org)', blocks_at)]
pad = re.search(r'#define IOP_PAD_SIZE\s+(\d+)', util)
if pad is None:
    sys.exit('ioplib_util.c: IOP_PAD_SIZE not defined')

HARNESS = r'''
#include <stdio.h>
#include <stddef.h>
#define IOP_PAD_SIZE %(pad)s
#define ALLOC_ADDRESS 2
static int limit, calls, sizes[4], alloc_mode;
static char heap[1];
static void *alloc_ptr, *seen_ptr;
static void *fake_alloc(int mode, int size, void *ptr)
{
    (void)mode;
    seen_ptr = ptr;
    if (calls < 4)
        sizes[calls] = size;
    calls++;
    return size <= limit ? heap : NULL;
}
static void *(*AllocSysMemory_org)(int mode, int size, void *ptr) = fake_alloc;
%(pad_for)s
%(hook)s
static void run(int lim, int size)
{
    void *r;
    limit = lim;
    calls = 0;
    sizes[0] = sizes[1] = -1;
    seen_ptr = NULL;
    r = Hook_AllocSysMemory(alloc_mode, size, alloc_ptr);
    printf("%%d %%d %%d %%d %%d\n", r != NULL, calls, sizes[0], sizes[1], seen_ptr == alloc_ptr);
}
int main(void)
{
    run(1 << 20, 25344); /* overrun block: one call, overrun + 256 */
    run(25344, 25344);   /* only the size asked for fits: padded, then the size asked for */
    run(100, 25344);     /* nothing fits: both tried, NULL as SYSMEM would */
    run(1 << 20, 0);     /* nothing to pad */
    run(1 << 20, 25200); /* rounds up to the 25344 block */
    run(1 << 20, 3328);  /* overrun block */
    run(1 << 20, 2304);  /* overrun block */
    run(1 << 20, 4096);  /* any other block: 256 */
    run(1 << 20, 25345); /* rounds past the 25344 block: 256 */
    run(1 << 20, -1);    /* negative: passed through unpadded */
    run(1 << 20, 0x7FFFFFF0); /* would overflow with the pad: passed through unpadded */
    alloc_mode = ALLOC_ADDRESS;
    alloc_ptr = (void *)0x1F0000;
    run(1 << 20, 25344); /* fixed address (pbuf_realloc in place): exact extent, unpadded */
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'pad.c'
    exe = Path(tmp) / 'pad'
    src.write_text(HARNESS % {'pad': pad.group(1), 'pad_for': pad_for, 'hook': hook}, encoding='utf-8')
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout.split('\n')

p = int(pad.group(1))
expected = [
    '1 1 %d -1 1' % (25344 + 1280 + p),
    '1 2 %d 25344 1' % (25344 + 1280 + p),
    '0 2 %d 25344 1' % (25344 + 1280 + p),
    '1 1 0 -1 1',
    '1 1 %d -1 1' % (25200 + 1280 + p),
    '1 1 %d -1 1' % (3328 + 768 + p),
    '1 1 %d -1 1' % (2304 + 1792 + p),
    '1 1 %d -1 1' % (4096 + p),
    '1 1 %d -1 1' % (25345 + p),
    '1 1 -1 -1 1',
    '0 1 %d -1 1' % 0x7FFFFFF0,
    '1 1 25344 -1 1',
]
if p != 256:
    failures.append('ioplib_util.c: IOP_PAD_SIZE is %d, not the 256 of neutrino Mode 7' % p)
for i, want in enumerate(expected):
    if out[i] != want:
        failures.append('Hook_AllocSysMemory case %d: got "%s", want "%s"' % (i, out[i], want))

flags = {name: int(value, 16) for name, value in re.findall(r'#define (IOPCORE_\w+)\s+(0x[0-9A-Fa-f]+)', config)}
if 'IOPCORE_COMPAT_IOP_PAD' not in flags:
    sys.exit('cdvd_config.h: IOPCORE_COMPAT_IOP_PAD not defined')
if flags['IOPCORE_COMPAT_IOP_PAD'] > 0xFFFF:
    failures.append('cdvd_config.h: IOPCORE_COMPAT_IOP_PAD does not fit the u16 flags field')
for name, value in flags.items():
    if name != 'IOPCORE_COMPAT_IOP_PAD' and value & flags['IOPCORE_COMPAT_IOP_PAD']:
        failures.append('cdvd_config.h: IOPCORE_COMPAT_IOP_PAD shares a bit with %s' % name)

if not re.search(r'if \(cdvdman_settings\.common\.flags & IOPCORE_COMPAT_IOP_PAD\)\s*\n\s*hookAllocSysMemory\(\);', cdvdman):
    failures.append('cdvdman.c: hookAllocSysMemory() is not installed under IOPCORE_COMPAT_IOP_PAD')
install = function(util, r'^void hookAllocSysMemory\(void\)\s*\{', 'ioplib_util.c')
if 'info.exports[4] = (void *)Hook_AllocSysMemory;' not in install or 'relinkExports(&info);' not in install:
    failures.append('ioplib_util.c: hookAllocSysMemory() must hook export 4 and relink the loaded modules')

titles = re.search(r'sbIopPadTitles\[\] = \{(.*?)\};', support, re.S)
if titles is None:
    sys.exit('supportbase.c: sbIopPadTitles not found')
listed = re.findall(r'"([A-Z]{4}_\d{3}\.\d{2})"', titles.group(1))
for want in ('SLUS_202.67', 'SLES_522.37', 'SLKA_250.80'):
    if want not in listed:
        failures.append('supportbase.c: %s missing from sbIopPadTitles' % want)
prepare = function(support, r'^int sbPrepare\(', 'supportbase.c')
if not re.search(r'if \(sbNeedsIopPad\(configSet\)\) \{\s*settings->flags \|= IOPCORE_COMPAT_IOP_PAD;', prepare):
    failures.append('supportbase.c: sbPrepare does not set IOPCORE_COMPAT_IOP_PAD from sbNeedsIopPad()')
if prepare.index('settings->flags = 0;') > prepare.index('IOPCORE_COMPAT_IOP_PAD'):
    failures.append('supportbase.c: the IOP pad flag is set before settings->flags is cleared')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('test_iop_pad: all checks passed')
