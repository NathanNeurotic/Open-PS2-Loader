"""The flicker-filtered 480i/576i HIRES rows blend each line with the one below it in the GS merge circuit.

gsKit's hires renderer displays one front buffer through read circuit 2 only. The lineBlend rows switch read
circuit 1 on, point it at the same buffer one line down, and mix the two at a fixed ~50%, so a one-line detail
shows in both fields at half strength instead of strobing at 25/30Hz (RiptOPL issue #132).

This compiles the real rm_mode_table, rmSetDisplayOffset and rmApplyLineBlend
(src/renderman.c) on the host against recorded GS privileged registers and checks:

- only interlaced FIELD multi-pass rows carry lineBlend, and each one is an exact twin of an earlier row apart
  from that flag (same raster, safe area and PAR), appended after every pre-existing row;
- on a lineBlend row, after every display offset change: PMODE has both circuits on, the fixed-ALP blend of
  circuit 1 with circuit 2 at 0x80; DISPFB1 is DISPFB2's buffer, width and format one line down; DISPLAY1 has
  DISPLAY2's position and magnification and is exactly two raster lines shorter, so circuit 1 never reads past
  the end of the framebuffer;
- on every other row, setDisplayOffset leaves PMODE and DISPFB1 alone (gsKit's single-circuit setup stays).
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'src/renderman.c').read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise SystemExit(f'unterminated {signature}')


struct = src[src.index('struct rm_mode\n{'):]
struct = struct[:struct.index('};') + 2]
table = src[src.index('static struct rm_mode rm_mode_table'):]
table = table[:table.index('};') + 2]
num_modes = src[src.index('#define NUM_RM_VMODES'):]
num_modes = num_modes[:num_modes.index('\n')]
set_offset = function_text(src, 'void rmSetDisplayOffset(int x, int y)')
blend = function_text(src, 'static void rmApplyLineBlend(void)')

program = r'''
#include <stdio.h>
#include <string.h>
typedef unsigned long long u64;
enum { GS_MODE_PAL = 3, GS_MODE_NTSC = 2, GS_MODE_DTV_480P = 0x50, GS_MODE_DTV_576P = 0x53, GS_MODE_VGA_640_60 = 0x1a,
       GS_MODE_DTV_720P = 0x52, GS_MODE_DTV_1080I = 0x51 };
enum { GS_INTERLACED = 1, GS_NONINTERLACED = 0, GS_FIELD = 0, GS_FRAME = 1 };
enum { GS_PSM_CT24 = 1 };
enum rm_aratio { RM_ARATIO_4_3 = 0, RM_ARATIO_16_9 = 1 };
struct GSGLOBAL { int Width, Height, PSM, StartX, StartY, StartXOffset, StartYOffset, MagH, MagV, DW, DH;
                  unsigned ScreenBuffer[2]; };
static GSGLOBAL globalStore, *gsGlobal = &globalStore;

// Recorded GS privileged registers, as fields so the checks read plainly.
struct PMODE { int written, en1, en2, mmod, amod, slbg, alp; } pmode;
struct DISPFB { int written, fbp, fbw, psm, dbx, dby; } dispfb1, dispfb2;
struct DISPLAY { int written, dx, dy, magh, magv, dw, dh; } display1, display2;
static int intrDepth, intrUnbalanced;
static void DIntr() { intrDepth++; }
static void EIntr() { if (--intrDepth < 0) intrUnbalanced = 1; }
#define GS_SET_PMODE(a, b, c, d, e, f) (pmode = PMODE{1, (a), (b), (c), (d), (e), (f)})
#define GS_SET_DISPFB1(a, b, c, d, e) (dispfb1 = DISPFB{1, (int)(a), (b), (c), (d), (e)})
#define GS_SET_DISPLAY1(a, b, c, d, e, f) (display1 = DISPLAY{1, (a), (b), (c), (d), (e), (f)})

// gsKit_set_display_offset as shipped: both DISPLAY registers at full height, the interlace parity kept.
static void gsKit_set_display_offset(GSGLOBAL *g, int x, int y)
{
    g->StartXOffset = x;
    g->StartYOffset = y & ~1;
    display1 = DISPLAY{1, g->StartX + g->StartXOffset, g->StartY + g->StartYOffset, g->MagH, g->MagV, g->DW - 1, g->DH - 1};
    display2 = display1;
}

@NUM_MODES@
@STRUCT@
@TABLE@
static short int vmode = -1;
@BLEND@
@SET_OFFSET@

static int failures, m;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL mode %d: ", m); printf(__VA_ARGS__); printf("\n"); failures++; } } while (0)

int main()
{
    int blendRows = 0, firstBlend = -1;
    for (m = 0; m < NUM_RM_VMODES; m++) {
        const rm_mode &row = rm_mode_table[m];
        if (!row.lineBlend) {
            CHECK(firstBlend < 0, "a plain row after the flicker-filtered ones (they must be appended last)");
            continue;
        }
        if (firstBlend < 0)
            firstBlend = m;
        blendRows++;
        CHECK(row.interlace == GS_INTERLACED && row.field == GS_FIELD && row.passes > 1,
              "lineBlend on a row that is not an interlaced FIELD HIRES row");
        int twin = -1;
        for (int t = 0; t < m; t++) {
            rm_mode a = rm_mode_table[t];
            a.lineBlend = 1;
            if (!rm_mode_table[t].lineBlend && memcmp(&a, &row, sizeof(a)) == 0)
                twin = t;
        }
        CHECK(twin >= 0, "no earlier row identical apart from lineBlend");
    }
    CHECK(blendRows == 3, "want 3 flicker-filtered rows (PAL 576, NTSC 480, NTSC 448), have %d", blendRows);

    for (m = 1; m < NUM_RM_VMODES; m++) {
        const rm_mode &row = rm_mode_table[m];
        memset(&pmode, 0, sizeof(pmode));
        memset(&dispfb1, 0, sizeof(dispfb1));
        memset(&display1, 0, sizeof(display1));
        globalStore = GSGLOBAL{row.width, row.height, GS_PSM_CT24, 652, 40, 0, 0, 3, 0, 2816, row.height, {0, 0}};
        dispfb2 = DISPFB{1, 0, row.width / 64, GS_PSM_CT24, 0, 0}; // what gsKit_init_screen left there
        vmode = m;
        for (int y = -8; y <= 8; y += 4) {
            int x = y / 2;
            rmSetDisplayOffset(x, y);
            CHECK(intrDepth == 0 && !intrUnbalanced, "interrupts left disabled or unbalanced");
            if (!row.lineBlend) {
                CHECK(!pmode.written && !dispfb1.written, "a plain row touched PMODE or DISPFB1");
                continue;
            }
            CHECK(pmode.written && pmode.en1 == 1 && pmode.en2 == 1 && pmode.mmod == 1 && pmode.slbg == 0 && pmode.alp == 0x80,
                  "PMODE en1=%d en2=%d mmod=%d slbg=%d alp=0x%x", pmode.en1, pmode.en2, pmode.mmod, pmode.slbg, pmode.alp);
            CHECK(dispfb1.written && dispfb1.fbp == dispfb2.fbp && dispfb1.fbw == dispfb2.fbw && dispfb1.psm == dispfb2.psm &&
                  dispfb1.dbx == 0 && dispfb1.dby == 1, "DISPFB1 is not DISPFB2's buffer one line down");
            CHECK(display1.dx == display2.dx && display1.dy == display2.dy && display1.magh == display2.magh &&
                  display1.magv == display2.magv && display1.dw == display2.dw,
                  "DISPLAY1 position/size differs from DISPLAY2 at offset %d,%d", x, y);
            CHECK(display1.dh == display2.dh - 2, "DISPLAY1 DH %d, want DISPLAY2's %d minus 2", display1.dh, display2.dh);
            // Circuit 1's last line per field must stay inside the framebuffer: lines read are DBY + (DH+1) - 1.
            CHECK(dispfb1.dby + display1.dh + 1 <= row.height, "circuit 1 reads past framebuffer line %d", row.height - 1);
        }
    }
    if (failures)
        return 1;
    printf("hires line blend: ok\n");
    return 0;
}
'''
program = (program.replace('@NUM_MODES@', num_modes).replace('@STRUCT@', struct).replace('@TABLE@', table)
           .replace('@SET_OFFSET@', set_offset).replace('@BLEND@', blend))

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'hires_line_blend.cpp'
    exe = Path(tmp) / 'hires_line_blend'
    c.write_text(program, encoding='utf-8')
    built = subprocess.run(['g++', '-std=gnu++17', '-Wall', '-Wno-unused-function', '-Wno-narrowing', str(c), '-o', str(exe)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr)
        sys.exit('FAIL: could not build the line-blend harness')
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    print(ran.stdout, end='')
    if ran.returncode != 0:
        print(ran.stderr)
        sys.exit('FAIL: a flicker-filtered HIRES row sets up the merge circuit wrongly')
