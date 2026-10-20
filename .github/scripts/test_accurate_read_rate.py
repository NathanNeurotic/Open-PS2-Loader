"""Accurate Reads (Mode 1) keeps its rates, and Slow Reads (Mode 8) gives a DVD title the CD rate (#924).

Tales of the Abyss loses its music and SFX when the in-game reader runs at >=1200KB/s and plays clean at
<=1000KB/s. Mode 1 throttles DVD media to 33512 IOP ticks per sector (~2200KB/s), so the title needs a
slower rate, but every other Mode 1 game must keep the speed it has today.

Compiles the real cdvdman_accu_read_ticks() from modules/iopcore/cdvdman/cdvdman.c against fake settings
and pins the ticks per sector for CD and DVD media, with and without Slow Reads. Then checks the read loop
uses it, sbPrepare maps Mode 8 onto the in-game flags, and the per-game screen saves and shows Mode 8.
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


cdvdman = read('modules/iopcore/cdvdman/cdvdman.c')
config = read('modules/iopcore/common/cdvd_config.h')
ticks = function(cdvdman, r'^static u32 cdvdman_accu_read_ticks\(void\)\s*\{', 'cdvdman.c')

flags = {name: int(value, 16) for name, value in re.findall(r'#define (IOPCORE_\w+)\s+(0x[0-9A-Fa-f]+)', config)}
if 'IOPCORE_COMPAT_SLOW_READS' not in flags:
    sys.exit('cdvd_config.h: IOPCORE_COMPAT_SLOW_READS not defined')
for name, value in flags.items():
    if name != 'IOPCORE_COMPAT_SLOW_READS' and value & flags['IOPCORE_COMPAT_SLOW_READS']:
        failures.append('cdvd_config.h: IOPCORE_COMPAT_SLOW_READS shares a bit with %s' % name)

HARNESS = r'''
#include <stdio.h>
typedef unsigned int u32;
#define IOPCORE_COMPAT_ACCU_READS %(accu)s
#define IOPCORE_COMPAT_SLOW_READS %(slow)s
static struct { struct { unsigned char media; unsigned short flags; } common; } cdvdman_settings;
%(ticks)s
int main(void)
{
    static const unsigned char media[2] = {0x12, 0x14}; /* SCECdPS2CD, SCECdPS2DVD */
    int m, s;
    for (m = 0; m < 2; m++)
        for (s = 0; s < 2; s++) {
            cdvdman_settings.common.media = media[m];
            cdvdman_settings.common.flags = IOPCORE_COMPAT_ACCU_READS | (s ? IOPCORE_COMPAT_SLOW_READS : 0);
            printf("%%s %%d %%u\n", m ? "dvd" : "cd", s, cdvdman_accu_read_ticks());
        }
    return 0;
}
'''

# Mode 1 alone is unchanged for both media; Slow Reads only moves DVD, onto the CD rate.
EXPECTED = {('cd', 0): 81920, ('dvd', 0): 33512, ('cd', 1): 81920, ('dvd', 1): 81920}
CLOCK = 36864000  # IOP sysclock, Hz

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'ticks.c'
    exe = Path(tmp) / 'ticks'
    c.write_text(HARNESS % {'accu': hex(flags['IOPCORE_COMPAT_ACCU_READS']),
                            'slow': hex(flags['IOPCORE_COMPAT_SLOW_READS']), 'ticks': ticks}, encoding='utf-8')
    built = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(c)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit('harness failed to build:\n' + built.stderr)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split('\n')

got = {}
for line in filter(None, out):
    medium, slow, value = line.split()
    got[(medium, int(slow))] = int(value)
for case, want in EXPECTED.items():
    if got.get(case) != want:
        failures.append('%s media, Slow Reads %s: %s ticks/sector, want %d' % (case[0], 'on' if case[1] else 'off',
                                                                            got.get(case), want))
if ('dvd', 1) in got and CLOCK * 2048 // got[('dvd', 1)] > 1000 * 1024:
    failures.append('Slow Reads on DVD reads faster than the 1000KB/s Tales of the Abyss plays clean at')

loop = function(cdvdman, r'^static int cdvdman_read_sectors\(u32 lsn, unsigned int sectors, void \*buf\)\s*\{',
                'cdvdman.c')
if 'TargetTime.lo = cdvdman_accu_read_ticks() * SectorsToRead;' not in loop:
    failures.append('cdvdman_read_sectors: the Accurate Reads alarm must take its rate from cdvdman_accu_read_ticks()')
if re.search(r'\b(81920|33512)\b', loop):
    failures.append('cdvdman_read_sectors: a hard-coded rate bypasses cdvdman_accu_read_ticks()')

# sbPrepare: Mode 1 sets Accurate Reads alone; Mode 8 sets Accurate Reads plus the slow rate by itself.
prepare = function(read('src/supportbase.c'), r'^int sbPrepare\(', 'supportbase.c')
if not re.search(r'if \(compatmask & COMPAT_MODE_1\) \{\n\s+settings->flags \|= IOPCORE_COMPAT_ACCU_READS;\n\s+\}', prepare):
    failures.append('sbPrepare: Mode 1 must set only IOPCORE_COMPAT_ACCU_READS')
if not re.search(r'if \(compatmask & COMPAT_MODE_8\) \{\n\s+settings->flags \|= IOPCORE_COMPAT_ACCU_READS \| '
                 r'IOPCORE_COMPAT_SLOW_READS;\n\s+\}', prepare):
    failures.append('sbPrepare: Mode 8 must set IOPCORE_COMPAT_ACCU_READS | IOPCORE_COMPAT_SLOW_READS')
if prepare.count('IOPCORE_COMPAT_SLOW_READS') != 1:
    failures.append('sbPrepare: only Mode 8 may set IOPCORE_COMPAT_SLOW_READS')

# The per-game screen reads and saves bits 0..COMPAT_MODE_COUNT-1, so Mode 8 (bit 7) needs a count of 8.
iosupport = read('include/iosupport.h')
if not re.search(r'#define COMPAT_MODE_8 0x80\b', iosupport) or not re.search(r'#define COMPAT_MODE_COUNT 8\b', iosupport):
    failures.append('iosupport.h: COMPAT_MODE_8 must be 0x80 and COMPAT_MODE_COUNT 8, or the screen drops Mode 8')
if '{UI_BOOL, COMPAT_MODE_BASE + 7, 1, 1, _STR_HINT_MODE8,' not in read('src/dialogs.c'):
    failures.append('dialogs.c: the Compatibility screen has no Mode 8 checkbox')
if 'diaSetEnabled(diaCompatConfig, COMPAT_MODE_BASE + 7, !neutrino);' not in read('src/guigame.c'):
    failures.append('guigame.c: Mode 8 must grey out under Neutrino (the OPL core reader is the only one it slows)')
if 'COMPAT_MODE_8' in function(read('src/system.c'), r'^static int convertCompatmaskToModes\(', 'system.c'):
    failures.append('system.c: Mode 8 is OPL-core only and must not reach Neutrino -gc')

# External .lng files are positional: the new labels must be the last two.
labels = re.findall(r'^- label: (\S+)', read('lng_tmpl/_base.yml'), re.M)
if labels[-2:] != ['MODE8', 'HINT_MODE8']:
    failures.append('lng_tmpl/_base.yml: MODE8 and HINT_MODE8 must be appended at the very end')

if failures:
    print('\n'.join('FAIL: ' + f for f in failures))
    sys.exit(1)
print('accurate read rate: CD 81920, DVD 33512, DVD with Slow Reads 81920 ticks/sector (~%d KB/s)'
      % (CLOCK * 2048 // got[('dvd', 1)] // 1024))
