"""Compile the production SMAP notice tap on the host.

While a game streams from SMB or HTTP, smap-ingame owns SMAP RX; it sets one
RA datagram for port 18195 aside (ra_tap_notice) for raudp to collect once
(SMAPReadNotice). The VBLANK side is in test_caduceus_overlay.py.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
xfer = (root / 'modules/network/smap-ingame/xfer.c').read_text(encoding='utf-8')

tap = xfer[xfer.index('/* Copy only achievement'):xfer.index('#endif', xfer.index('static void ra_tap_notice('))]

program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
typedef uint64_t u64;
#include "modules/network/common/ra_snap.h"
static int intr_depth;
static void CpuSuspendIntr(int *state) { *state = intr_depth++; }
static void CpuResumeIntr(int state) { intr_depth = state; }
''' + tap + r'''
/* An Ethernet/IPv4/UDP frame to port 18195 carrying text. */
static unsigned frame(unsigned char *p, const char *text, unsigned port) {
    unsigned n = strlen(text), udp = 8 + n;
    memset(p, 0, 256);
    p[12] = 8; p[14] = 0x45; p[23] = 17;
    p[36] = port >> 8; p[37] = port & 255;
    p[38] = udp >> 8; p[39] = udp & 255;
    memcpy(p + 42, text, n);
    return 42 + n < 60 ? 60 : 42 + n;
}

int main(void) {
    unsigned char p[256];
    char out[133];
    unsigned n;

    n = frame(p, "RAU1 42 10 Title", 18195);
    p[26] = 192; p[27] = 168; p[28] = 1; p[29] = 9;          /* the sender comes first */
    ra_tap_notice(p, n);
    assert(SMAPReadNotice(out, 8) == 0);                      /* too small: kept, not truncated */
    assert(SMAPReadNotice(out, 132) == 20 && !memcmp(out, "\300\250\001\011RAU1 42 10 Title", 20));
    assert(SMAPReadNotice(out, 132) == 0 && intr_depth == 0); /* handed out once */
    n = frame(p, "RAU1 42", 18196); ra_tap_notice(p, n); assert(SMAPReadNotice(out, 128) == 0);
    n = frame(p, "XXU1 42", 18195); ra_tap_notice(p, n); assert(SMAPReadNotice(out, 128) == 0);
    n = frame(p, "RAR1 ", 18195); ra_tap_notice(p, 46); assert(SMAPReadNotice(out, 128) == 0); /* truncated */
    n = frame(p, "RAU1 42 10 Title", 18195); ra_tap_notice(p, 42 + 15); assert(SMAPReadNotice(out, 128) == 0);
    n = frame(p, "RAR1 ", 18195); p[23] = 6; ra_tap_notice(p, n); assert(SMAPReadNotice(out, 128) == 0); /* TCP */
    n = frame(p, "RAR1 ", 18195); ra_tap_notice(p, n);
    n = frame(p, "RAU1 7", 18195); ra_tap_notice(p, n);       /* a second waits for the first to be read */
    assert(SMAPReadNotice(out, 132) == 9 && !memcmp(out + 4, "RAR1 ", 5));
    {
        char longest[130];
        memset(longest, 'A', sizeof longest); longest[0] = 'R'; longest[128] = 0;
        n = frame(p, longest, 18195); ra_tap_notice(p, n); assert(SMAPReadNotice(out, 132) == 132);
        longest[128] = 'A'; longest[129] = 0;                  /* 129 bytes: more than the notice holds */
        n = frame(p, longest, 18195); ra_tap_notice(p, n); assert(SMAPReadNotice(out, 132) == 0);
    }
    puts("PASS: SMAP sets aside one whole RA datagram for port 18195, hands it out once with its sender, refuses the rest");

    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='ra-ingame-events-') as temp:
    src, exe = Path(temp) / 'events.c', Path(temp) / 'events'
    src.write_text(program, encoding='utf-8')
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-Wno-unused-value',
                    '-fsanitize=address,undefined', '-I', str(root), str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
