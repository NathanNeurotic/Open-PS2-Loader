""".pad USB pad profiles (RIPPS2 builds 126-129, akilluminati47): the format 1 reader, packer and decoder on the host.

src/padfile.c is RIPPS2's reference code, with two casts and three pairs of parentheses so it also builds as C++ and
passes clang-format. These checks are RIPPS2's own host tests (test_ripps2_pad.py and the decode-only and game-map parts
of test_ripps2_pad129.py), run against this tree:

1. A profile for a copy DualShock 3 (2563:0575, buttons from byte 0) reads with CRLF line ends, a comment after a value,
   an active-low button, a hat, an inverted axis, a deadzone and a section this reader does not know.
2. The game map (PADS/GAMES/<ID>.pad) reads: a swap and a button sent to nothing.
3. Both pack into the 180-byte block, little endian, and read back the same; a block of a later format is refused.
4. A report through the profile gives the DualShock 2 button word (active low) and the four axes.
5. Files that are wrong are refused, each with its line and reason: a byte past 31, format 2, a line that is not
   key=value, a bad reference, a hat together with d-pad buttons, a profile with no buttons, an unknown rumble.
6. padfile.c builds with PADFILE_DECODE_ONLY (no text, no libc beyond memcpy and memset), as PADEMU and the menu's USB
   driver build it.
7. padApplyMap and padMapIsSame: CROSS sent as CIRCLE, SELECT sent nowhere, the rest unchanged.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
fail = []
src = root / 'src/padfile.c'
if not src.exists():
    print('src/padfile.c missing')
    sys.exit(1)
if 'padfile.o' not in (root / 'Makefile').read_text(encoding='utf-8', errors='replace'):
    fail.append('Makefile: padfile.o in the ELF')

cc = shutil.which('gcc') or shutil.which('cc')
if cc is None:
    print('\n'.join(fail) or 'pad profiles: no host C compiler, programs skipped')
    sys.exit(1 if fail else 0)

PROG = r'''
#include <stdio.h>
#include <string.h>
#include "include/padfile.h"
static const char *fake =
    "# USB Gamepad (made by RIPPS2)\r\n[Device]\r\nformat=1\r\nname=USB Gamepad\r\ndecoder=generic\r\noffset=0\r\n"
    "[Buttons]\r\nsquare=b0.0\r\ncross=b0.1\r\ncircle=b0.2\r\ntriangle=b0.3\r\nl1=b0.4\r\nr1=b0.5\r\nl2=b0.6\r\n"
    "r2=b0.7\r\nselect=b1.0\r\nstart=b1.1\r\nl3=b1.2\r\nr3=!b1.3\r\n[Axes]\r\ndpad=hat2   # 0-7 from up\r\n"
    "lx=a3\r\nly=a4\r\nrx=a5\r\nry=a6-\r\ndeadzone=12\r\n[Rumble]\r\nrumble=off\r\nled=off\r\ninit=off\r\n"
    "[Future]\r\nsomething_new=7\r\n";
static const char *game = "format=1\ncross=circle\ncircle=cross\nselect=none\n";
static int bad(const char *t, const char *want)
{
    pad_def_t d;
    char err[96];
    if (padDefParse(t, strlen(t), 1, 2, &d, err, sizeof(err)) == 0 || strstr(err, want) == NULL) {
        printf("refuse '%s': got '%s'\n", want, err);
        return 1;
    }
    return 0;
}
int main(void)
{
    pad_def_t d, back[PAD_DEFS_MAX];
    unsigned char block[PAD_BLOCK_SIZE], map[PAD_B_COUNT], map2[PAD_B_COUNT], axes[4];
    unsigned short buttons;
    unsigned vid, pid;
    char err[96];
    int n;
    if (sizeof(pad_def_t) < PAD_DEF_SIZE) return 1;
    if (padFileId("2563_0575.pad", &vid, &pid) || vid != 0x2563 || pid != 0x0575) return 2;
    if (padFileId("2563-0575.pad", &vid, &pid) == 0 || padFileId("2563_0575.cfg", &vid, &pid) == 0) return 3;
    if (padDefParse(fake, strlen(fake), vid, pid, &d, err, sizeof(err))) { printf("%s\n", err); return 4; }
    if (d.button[PAD_B_CROSS] != (0 | 1 << 5) || !(d.activeLow & 1u << PAD_B_R3) || d.hat != 2 || d.axis[PAD_AX_RY] != (6 | 0x80) ||
        d.deadzone != 12 || d.flags != 0 || d.present != 0xFF0F)
        return 5;
    if (padMapParse(game, strlen(game), map, err, sizeof(err))) { printf("%s\n", err); return 6; }
    if (map[PAD_B_CROSS] != PAD_B_CIRCLE || map[PAD_B_CIRCLE] != PAD_B_CROSS || map[PAD_B_SELECT] != 0xFE || map[PAD_B_START] != 0xFF)
        return 7;
    if (padBlockPack(&d, 1, map, block) != 180 || block[0] != 'P' || block[1] != 'D' || block[2] != 1 || block[3] != 1) return 8;
    if (block[4] != 0x63 || block[5] != 0x25 || block[6] != 0x75 || block[7] != 0x05) return 9; /* little endian */
    if (padBlockUnpack(block, sizeof(block), back, &n, map2) || n != 1 || memcmp(map, map2, sizeof(map))) return 10;
    if (memcmp(&back[0], &d, 14) || memcmp(back[0].button, d.button, 16) || back[0].present != d.present ||
        back[0].activeLow != d.activeLow || back[0].fromAxis != d.fromAxis)
        return 11;
    block[2] = 2;
    if (padBlockUnpack(block, sizeof(block), back, &n, map2) == 0) return 12; /* a newer block is not read as this one */
    {   /* CROSS (b0.1) and START (b1.1) down, R3 (active low) up, the hat at 2 (right), RY at 0 inverted, LX in the deadzone */
        unsigned char rep[7] = {0x02, 0x02 | 0x08, 2, 133, 0, 128, 0};
        unsigned short want = (unsigned short)~(1u << PAD_B_CROSS | 1u << PAD_B_START | 1u << PAD_B_RIGHT);
        padTranslate(&d, rep, sizeof(rep), &buttons, axes);
        if (buttons != want) { printf("buttons %04x want %04x\n", buttons, want); return 13; }
        if (axes[0] != 128 || axes[1] != 0 || axes[2] != 128 || axes[3] != 255) { printf("axes %d %d %d %d\n", axes[0], axes[1], axes[2], axes[3]); return 14; }
        rep[1] = 0; /* R3 at 0: pressed */
        padTranslate(&d, rep, sizeof(rep), &buttons, axes);
        if (buttons & 1u << PAD_B_R3) return 15;
    }
    if (bad("cross=b40.1\n", "line 1: cross's byte must be 0-31") || bad("format=2\n", "made for .pad format 2") ||
        bad("cross=b0.1\nnot a line\n", "line 2: not key=value") || bad("cross=c0.1\n", "cross wants") ||
        bad("dpad=hat2\nup=b0.1\n", "one or the other") || bad("name=x\n", "no buttons") || bad("rumble=ds5\ncross=b0.0\n", "rumble is"))
        return 16;
    /* the game map on a button word: CROSS to CIRCLE, SELECT to nothing, the rest as they were */
    memset(map, PAD_REMAP_SAME, sizeof(map));
    if (!padMapIsSame(map)) return 17;
    map[PAD_B_CROSS] = PAD_B_CIRCLE;
    map[PAD_B_SELECT] = 0xFE;
    if (padMapIsSame(map)) return 18;
    buttons = padApplyMap((unsigned short)~(1u << PAD_B_CROSS | 1u << PAD_B_SELECT | 1u << PAD_B_START), map);
    if (buttons != (unsigned short)~(1u << PAD_B_CIRCLE | 1u << PAD_B_START)) { printf("map %04x\n", buttons); return 19; }
    printf("pad ok\n");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / 't.c').write_text(PROG, encoding='utf-8')
    exe = td / 't.exe'
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I', str(root), str(td / 't.c'), str(src), '-o', str(exe)],
                       capture_output=True, text=True)
    if r.returncode:
        fail.append('padfile.c must build on the PC: ' + r.stderr[-600:])
    else:
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        if r.returncode:
            fail.append('padfile.c check %d failed: %s' % (r.returncode, r.stdout.strip()))

    (td / 'only.c').write_text('#include <string.h>\n#define PADFILE_DECODE_ONLY\n#include "src/padfile.c"\nint main(void) { return 0; }\n',
                               encoding='utf-8')
    r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I', str(root), str(td / 'only.c'), '-o', str(td / 'only.exe')],
                       capture_output=True, text=True)
    if r.returncode:
        fail.append('padfile.c must build decode-only (as PADEMU and the menu driver build it): ' + r.stderr[-600:])

print('\n'.join(fail) or 'pad profiles: .pad files read, refused with their line and reason, packed into the 180-byte block and '
      'read back, a report decoded, the game map applied, and the decode-only build OK')
sys.exit(1 if fail else 0)
