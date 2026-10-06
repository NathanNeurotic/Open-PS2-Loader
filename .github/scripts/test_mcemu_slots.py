"""mcemu VMC slots survive a launch that returned to the menu.

Every native launch writes each VMC slot's settings over that slot's marker (0xC0DEFAC0 + slot) in the
embedded mcemu image, and nothing writes the marker back. The BDM, SMB, HDD and MMCE legs used to search
for the marker on every launch, so after any launch that came back to the menu -- a declined prompt, a
failed preflight, Back on a preview -- the next one found no slot, left mcemu out, and that game ran
without its VMC, silently. (The BDM/SMB/HDD searches also counted u32 words up to the image's BYTE
size, reading up to four times past it once the marker was gone.)

Compiles the real sbMcemuSlotWord against a fake image and checks: each slot is found once while the
image is pristine; the position survives the marker being written over; the search stays inside the
image; an unknown slot is refused. Then checks that all four legs use it with their own image, size and
cache, that none still searches for the marker itself, and that the HDD leg writes a slot with no card
as inactive (so an aborted launch's card cannot linger there).
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        sys.exit('missing ' + signature)
    return source[match.start():source.index('\n}', match.start()) + 2]


support = text('src/supportbase.c')
helper = function(support, 'int sbMcemuSlotWord(')

HARNESS = r'''
#include <stdio.h>
#include <string.h>
typedef unsigned int u32;

@HELPER@

int main(void)
{
    /* A 16-word image with the slot markers at words 5 and 9, plus room past its end. */
    u32 image[24];
    int cache[2] = {-2, -2}, a, b, c, d;
    memset(image, 0, sizeof(image));
    image[5] = 0xC0DEFAC0;
    image[9] = 0xC0DEFAC1;
    a = sbMcemuSlotWord(image, 16 * 4, 0, cache);
    b = sbMcemuSlotWord(image, 16 * 4, 1, cache);
    printf("first %d %d\n", a, b);

    /* A launch writes its VMC settings over both markers, then returns to the menu. */
    image[5] = 0x12345678;
    image[9] = 0;
    a = sbMcemuSlotWord(image, 16 * 4, 0, cache);
    b = sbMcemuSlotWord(image, 16 * 4, 1, cache);
    printf("after %d %d\n", a, b);

    /* A marker just past the image's end is not the image's: the search stops at size / 4 words. */
    int bounded[2] = {-2, -2};
    memset(image, 0, sizeof(image));
    image[16] = 0xC0DEFAC0;
    image[17] = 0xC0DEFAC1;
    c = sbMcemuSlotWord(image, 16 * 4, 0, bounded);
    d = sbMcemuSlotWord(image, 16 * 4, 1, bounded);
    printf("bounded %d %d\n", c, d);

    /* Only slots 0 and 1 exist. */
    int other[2] = {-2, -2};
    printf("slot2 %d slot-1 %d\n", sbMcemuSlotWord(image, 16 * 4, 2, other), sbMcemuSlotWord(image, 16 * 4, -1, other));
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src, exe = Path(tmp) / 'slots.c', Path(tmp) / 'slots'
    src.write_text(HARNESS.replace('@HELPER@', helper), encoding='utf-8')
    build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                           capture_output=True, text=True, check=False)
    if build.returncode != 0:
        sys.exit('harness did not compile:\n' + build.stderr)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=False).stdout.splitlines()

want = ['first 5 9', 'after 5 9', 'bounded -1 -1', 'slot2 -1 slot-1 -1']
if out != want:
    failures.append('sbMcemuSlotWord:\n  got  %r\n  want %r' % (out, want))

for leg, image, cache, fn in (('src/bdmsupport.c', 'bdm_mcemu_irx', 'bdmMcemuSlots', 'void bdmLaunchGame('),
                              ('src/ethsupport.c', 'smb_mcemu_irx', 'ethMcemuSlots', 'static void ethLaunchGame('),
                              ('src/hddsupport.c', 'hdd_mcemu_irx', 'hddMcemuSlots', 'void hddLaunchGame('),
                              ('src/mmcesupport.c', 'mmce_mcemu_irx', 'mmceMcemuSlots', 'void mmceLaunchGame(')):
    body = text(leg)
    launch = function(body, fn)
    call = 'sbMcemuSlotWord(&%s, size_%s, vmc_id, %s)' % (image, image, cache)
    if launch.count(call) != 1:
        failures.append('%s: the VMC slot must be found through %s' % (leg, call))
    if 'static int %s[2] = {-2, -2};' % cache not in body:
        failures.append('%s: %s must start unsearched (-2, -2)' % (leg, cache))
    if '0xC0DEFAC0 + vmc_id' in launch:
        failures.append('%s: the launch must not search for the marker itself -- it is gone after the first launch' % leg)
    if not re.search(r'if \(slotWord >= 0\) \{\s*if \(\w+_vmc_infos\.active\)\s*size_mcemu_irx = size_%s;\s*'
                     r'memcpy\(&\(\(u32 \*\)&%s\)\[slotWord\]' % (image, image), launch):
        failures.append('%s: write the slot only where it was found, loading mcemu only for an active card' % leg)

hdd = function(text('src/hddsupport.c'), 'void hddLaunchGame(')
loop = hdd[hdd.index('for (vmc_id = 0; vmc_id < 2; vmc_id++) {'):]
if not (0 <= loop.find('} else\n                hdd_vmc_infos.active = 0;') < loop.find('int slotWord = sbMcemuSlotWord(&hdd_mcemu_irx')):
    failures.append('hddsupport.c: a slot with no VMC must be written inactive, after the per-card block')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('mcemu VMC slots: found once, kept after the marker is overwritten, bounded; all four legs use them')
