"""A settings home on a mass slot that never mounted ("could not write settings ... (error 12)").

A launcher hands over "mass0:/APPS" (its own numbering), but after the IOP reset the stick it
booted from registers as another slot. Keeping the empty slot read defaults and failed every save:
bdmfs_fatfs's open returns the negated FatFs result, and FR_NOT_ENABLED is 12 -- shown as an errno,
"out of memory". The fix takes the one other slot that holds the booted ELF, and only when the
named slot never mounted; and a failed mass create now reports an errno.

Production functions are compiled as they are: bdmPickBootElfSlot and bdmFatfsOpenErrno.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (ROOT / path).read_text()
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


boot = (ROOT / 'src/bdmsupport.c').read_text()
# The fallback must stay behind both guards: the literal slot did not mount, and an ELF name is known.
assert '!bdmReadLiteralMassIdentity(unit, &unused)' in boot
assert "elfName != NULL && elfName[0] != '\\0'" in boot
assert 'bdmPickBootElfSlot(unit, MAX_BDM_DEVICES, bdmBootElfProbeAt, &probe)' in boot
util = (ROOT / 'src/util.c').read_text()
assert 'int savedErrno = bdmFatfsOpenErrno(fpath, errno != 0 ? errno : EIO);' in util

production = function('src/bdmsupport.c', 'int bdmPickBootElfSlot(')
production += function('src/util.c', 'int bdmFatfsOpenErrno(')
program = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
@PRODUCTION@
static int has(int slot, void *ctx) { return (*(unsigned *)ctx >> slot) & 1; }
int main(void) {
    unsigned elf;
    elf = 1u << 0; assert(bdmPickBootElfSlot(1, 10, has, &elf) == 0); /* launcher said mass1, stick is mass0 */
    elf = 1u << 3; assert(bdmPickBootElfSlot(0, 10, has, &elf) == 3);
    elf = 0;       assert(bdmPickBootElfSlot(0, 10, has, &elf) == -1); /* nothing proves a home */
    elf = (1u << 0) | (1u << 2);
    assert(bdmPickBootElfSlot(1, 10, has, &elf) == -1);               /* two copies: no guess */
    elf = 1u << 1; assert(bdmPickBootElfSlot(1, 10, has, &elf) == -1); /* the literal slot is never a candidate */
    elf = 1u << 9; assert(bdmPickBootElfSlot(0, 9, has, &elf) == -1);  /* bounded by the slot count */

    assert(bdmFatfsOpenErrno("mass0:/APPS/conf_opl.cfg", 12) == ENXIO); /* the reported "(error 12)" */
    assert(bdmFatfsOpenErrno("mass1:/x", 11) == ENXIO);
    assert(bdmFatfsOpenErrno("mass1:/x", 13) == ENXIO);
    assert(bdmFatfsOpenErrno("mass0:/x", 4) == ENOENT);
    assert(bdmFatfsOpenErrno("mass0:/x", 5) == ENOENT);
    assert(bdmFatfsOpenErrno("mass0:/x", 7) == EACCES);
    assert(bdmFatfsOpenErrno("mass0:/x", 10) == EROFS);
    assert(bdmFatfsOpenErrno("mass0:/x", 24) == 24);  /* a real -EMFILE from the driver */
    assert(bdmFatfsOpenErrno("mc0:/OPL/x", 12) == 12); /* other devices keep their own codes */
    assert(bdmFatfsOpenErrno("pfs0:/x", 5) == 5);
    assert(bdmFatfsOpenErrno(NULL, 12) == 12);
    puts("PASS: empty literal mass slot falls back to the booted ELF's slot; leaked FatFs codes named");
    return 0;
}
'''.replace('@PRODUCTION@', production)
with tempfile.TemporaryDirectory() as directory:
    source, binary = Path(directory) / 'slot.c', Path(directory) / 'slot'
    source.write_text(program)
    subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=5)
