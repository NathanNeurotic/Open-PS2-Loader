"""The 480i/576i HIRES modes draw the menu inside a 4:3 safe area instead of across the whole raster.

Those two rows render a 704-wide framebuffer that covers every active line and every one of the 704 samples of a
4:3 picture. On a CRT a good part of that sits under the bezel, so the menu was cut off at the edges (reported on
a 4:3 CRT in PAL 704x576i). They now draw the 640x480 design grid into the same footprint as the standard
640-wide rows, centred, and the user's Overscan setting shrinks that area further.

This compiles the real rm_mode_table, rmSetOverscan, rmGetPAR and rmGetInterlacedFrameMode
(src/renderman.c) on the host and checks, for every mode:

- the drawn area is centred, inside the framebuffer, and never larger than it;
- 704x480i draws into 640x480 (1:1 on both axes) and 704x576i into 640x512 (the 640x512i row's footprint);
- every other row is unchanged: Overscan 0 still means the whole framebuffer;
- PAR stays the grid's fill ratio, (drawW/640)/(drawH/480), so fonts keep the same proportions as the layout;
- Overscan still shrinks the drawn area, symmetrically, in every mode.
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
set_overscan = function_text(src, 'void rmSetOverscan(int overscan)')
get_par = function_text(src, 'float rmGetPAR()')
frame_mode = function_text(src, 'int rmGetInterlacedFrameMode()')

program = r'''
#include <math.h>
#include <stdio.h>
enum { GS_MODE_PAL = 3, GS_MODE_NTSC = 2, GS_MODE_DTV_480P = 0x50, GS_MODE_DTV_576P = 0x53, GS_MODE_VGA_640_60 = 0x1a,
       GS_MODE_DTV_720P = 0x52, GS_MODE_DTV_1080I = 0x51 };
enum { GS_INTERLACED = 1, GS_NONINTERLACED = 0, GS_FIELD = 0, GS_FRAME = 1 };
enum rm_aratio { RM_ARATIO_4_3 = 0, RM_ARATIO_16_9 = 1 };
struct GSGLOBAL { int Width, Height, Interlace, Field; };
static GSGLOBAL globalStore, *gsGlobal = &globalStore;
constexpr int NUM_RM_VMODES = 16;
@STRUCT@
@TABLE@
static short int vmode = -1;
static enum rm_aratio DAR = RM_ARATIO_4_3;
static int iDisplayXOff, iDisplayYOff, iDisplayWidth, iDisplayHeight;
static float fRenderXOff, fRenderYOff;
int rmGetInterlacedFrameMode();
@SET_OVERSCAN@
@GET_PAR@
@FRAME_MODE@

static int failures;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL mode %d: ", m); printf(__VA_ARGS__); printf("\n"); failures++; } } while (0)

int main()
{
    for (int m = 1; m < NUM_RM_VMODES; m++) {
        const rm_mode &row = rm_mode_table[m];
        vmode = m;
        gsGlobal->Width = row.width;
        gsGlobal->Height = row.height;
        gsGlobal->Interlace = row.interlace;
        gsGlobal->Field = row.field;
        if (row.interlace == GS_INTERLACED && row.field == GS_FRAME)
            gsGlobal->Height /= 2; // as setMode does

        for (int overscan = 0; overscan <= 100; overscan += 25) {
            rmSetOverscan(overscan);
            CHECK(iDisplayXOff >= 0 && iDisplayYOff >= 0, "negative offset at overscan %d", overscan);
            CHECK(iDisplayWidth + 2 * iDisplayXOff == gsGlobal->Width, "not centred horizontally at overscan %d", overscan);
            CHECK(iDisplayHeight + 2 * iDisplayYOff == gsGlobal->Height, "not centred vertically at overscan %d", overscan);
            CHECK(iDisplayWidth > 0 && iDisplayHeight > 0, "empty draw area at overscan %d", overscan);
        }

        rmSetOverscan(0);
        int fullW = gsGlobal->Width, fullH = gsGlobal->Height;
        int lines = (gsGlobal->Interlace == GS_INTERLACED && gsGlobal->Field == GS_FRAME) ? 2 : 1;
        if (row.mode == GS_MODE_NTSC && row.width == 704) {
            CHECK(iDisplayWidth == 640 && iDisplayHeight == 480, "704x480i draws %dx%d, want 640x480", iDisplayWidth, iDisplayHeight);
        } else if (row.mode == GS_MODE_PAL && row.width == 704) {
            CHECK(iDisplayWidth == 640 && iDisplayHeight == 512, "704x576i draws %dx%d, want 640x512", iDisplayWidth, iDisplayHeight);
        } else {
            CHECK(iDisplayWidth == fullW && iDisplayHeight == fullH, "unchanged row draws %dx%d, want the whole %dx%d",
                  iDisplayWidth, iDisplayHeight, fullW, fullH);
        }

        // PAR must equal the fill ratio of the 640x480 grid, or text widths stop matching the layout.
        // The AUTO row (0) is filled in at runtime and skipped by the loop.
        if (row.aratio == RM_ARATIO_4_3) {
            DAR = RM_ARATIO_4_3;
            float want = ((float)iDisplayWidth / 640.0f) / ((float)(iDisplayHeight * lines) / 480.0f);
            float got = rmGetPAR() / (float)lines;
            CHECK(fabsf(got - want) < 0.01f, "PAR %.4f, grid fill ratio %.4f", got, want);
        }

        if (row.safeW || row.safeH) {
            rmSetOverscan(100);
            CHECK(iDisplayWidth < 640 && iDisplayHeight < row.safeH, "Overscan no longer shrinks the safe area");
        }
    }
    if (failures)
        return 1;
    printf("vmode safe area: ok\n");
    return 0;
}
'''
program = (program.replace('@STRUCT@', struct).replace('@TABLE@', table).replace('@SET_OVERSCAN@', set_overscan)
           .replace('@GET_PAR@', get_par).replace('@FRAME_MODE@', frame_mode))

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'vmode_safe_area.cpp'
    exe = Path(tmp) / 'vmode_safe_area'
    c.write_text(program, encoding='utf-8')
    built = subprocess.run(['g++', '-std=gnu++17', '-Wall', '-Wno-unused-function', '-Wno-narrowing', str(c), '-o', str(exe)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr)
        sys.exit('FAIL: could not build the safe-area harness')
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    print(ran.stdout, end='')
    if ran.returncode != 0:
        print(ran.stderr)
        sys.exit('FAIL: a video mode draws outside its 4:3 safe area or with the wrong proportions')
