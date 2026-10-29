"""Leaving a multi-pass (hires) video mode gives the thread that entered it its priority back.

gsKit_hires_init_screen ends with a HACK: ChangeThreadPriority(GetThreadId(), 2), so its caller sits right under the
priority-1 DMA thread it starts. gsKit_hires_deinit_global never undoes that. rmSetMode is the caller, and the
GUI thread runs at 31 (opl.c main), so one visit to a 704-wide, 720p or 1080i mode used to leave the GUI thread at 2
until reboot, above the background-music threads (30/31) it normally yields to, in every mode chosen after it.

This compiles the real rmSetMode and rmEnd (src/renderman.c) on the host against a scripted
gsKit/kernel that bumps the caller exactly as gsHires.c does, and checks:

- a hires -> single-pass switch puts the GUI thread back at 31;
- hires -> hires -> single-pass and repeated back-and-forth trips always end at 31;
- the restore targets the thread that ENTERED the mode, even if another thread leaves it (setMode can run on the IO
  worker through applyConfig);
- a failed ReferThreadStatus leaves the priority alone rather than writing a garbage one;
- single-pass modes never touch thread priorities.
"""
from pathlib import Path
import re
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


table = src[src.index('static struct rm_mode rm_mode_table'):]
table = table[:table.index('};') + 2]
set_mode = function_text(src, 'int rmSetMode(int force)')
end = function_text(src, 'void rmEnd(void)')

program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned long long u64;
enum { GS_MODE_PAL = 3, GS_MODE_NTSC = 2, GS_MODE_DTV_480P = 0x50, GS_MODE_DTV_576P = 0x53, GS_MODE_VGA_640_60 = 0x1a,
       GS_MODE_DTV_720P = 0x52, GS_MODE_DTV_1080I = 0x51 };
enum { GS_INTERLACED = 1, GS_NONINTERLACED = 0, GS_FIELD = 0, GS_FRAME = 1 };
enum { GS_PSM_CT24 = 1, GS_PSM_CT16S = 10, GS_PSMZ_16S = 0x3a, GS_SETTING_OFF = 0, GS_SETTING_ON = 1, GS_ONESHOT = 1,
       GS_ZTEST_OFF = 1 };
enum rm_aratio { RM_ARATIO_4_3 = 0, RM_ARATIO_16_9 = 1 };
#define LOG(...) ((void)0)
struct test_t { int ATST, AREF, AFAIL; };
struct GSGLOBAL { int Mode, Width, Height, Interlace, Field, PSM, PSMZ, ZBuffering, PrimAlphaEnable, DoubleBuffering,
                  Dithering, OffsetX, OffsetY, ActiveBuffer; test_t *Test; test_t testStore; };
static GSGLOBAL globalStore, *gsGlobal;
static u64 gColBlack, gDefaultAlpha;
static int gVMode, gXOff, gYOff, gOverscan, gWideScreen;
constexpr int NUM_RM_VMODES = 16;
constexpr int RM_VMODE_AUTO = 0;
struct rm_mode { char mode; char hsync; short int width, height, passes, VCK, interlace, field, aratio, PAR1, PAR2; };
@TABLE@

// The scripted kernel: thread 1 is the GUI thread (31, as main sets it), thread 2 the IO worker (40).
static int priority[8] = {0, 31, 40};
static int current = 1, referFails = 0, priorityWrites = 0;
struct ee_thread_status_t { int current_priority; };
static int GetThreadId() { return current; }
static int ReferThreadStatus(int id, ee_thread_status_t *s) { if (referFails) return -1; s->current_priority = priority[id]; return id; } // the EE returns the thread id, not 0
static void ChangeThreadPriority(int id, int p) { priority[id] = p; priorityWrites++; }

static int hiresActive = 0;
static GSGLOBAL *gsKit_init_global() { memset(&globalStore, 0, sizeof(globalStore)); globalStore.Test = &globalStore.testStore; return &globalStore; }
static GSGLOBAL *gsKit_hires_init_global() { return gsKit_init_global(); }
static void gsKit_deinit_global(GSGLOBAL *) {}
static void gsKit_hires_deinit_global(GSGLOBAL *) { assert(hiresActive); hiresActive = 0; } // never restores (gsHires.c)
static void gsKit_hires_init_screen(GSGLOBAL *, int) { hiresActive = 1; ChangeThreadPriority(GetThreadId(), 2); } // the HACK
static void gsKit_init_screen(GSGLOBAL *) {}
static void gsKit_mode_switch(GSGLOBAL *, int) {}
static void gsKit_set_test(GSGLOBAL *, int) {}
static void gsKit_set_primalpha(GSGLOBAL *, u64, int) {}
static void gsKit_hires_sync(GSGLOBAL *) {}
static void gsKit_hires_flip(GSGLOBAL *) {}
static void gsKit_clear(GSGLOBAL *, u64) {}
static void gsKit_setactive(GSGLOBAL *) {}
static void gsKit_sync_flip(GSGLOBAL *) {}
static int gsKit_add_vsync_handler(int (*)(int)) { return 7; }
static void gsKit_remove_vsync_handler(int) {}
static int rmOnVSync(int) { return 0; }

static short int vmode = -1;
static unsigned char hires = 0;
static int vsync_id = -1;
static int hiresThread = -1;
static int hiresPriority = -1;
void rmEnd(void);
static void rmSetDisplayOffset(int, int) {}
static void rmSetOverscan(int) {}
static void rmSetAspectRatio(enum rm_aratio) {}
static int rmIsWideDisplay(void) { return 0; }
@SETMODE@
@END@

int rmSetMode(int force);
static void to(int mode) { gVMode = mode; rmSetMode(0); }

int main()
{
    // Rows 6..11 are the multi-pass ones (704x576i, 704x480i, 704x480p, 704x576p, 720p, 1080i).
    for (int hires = 6; hires <= 11; hires++) {
        to(2);
        to(hires);
        assert(priority[1] == 2);  // the bump gsKit relies on while the mode is up
        to(2);
        assert(priority[1] == 31); // and gone once it is left
    }

    // hires -> hires -> single-pass, and a dozen trips, still end at 31
    to(10); to(11); assert(priority[1] == 2); to(3); assert(priority[1] == 31);
    for (int i = 0; i < 12; i++) { to(6 + i % 6); to(i % 2 ? 14 : 15); }
    assert(priority[1] == 31);

    // Entered on the IO worker, left on the GUI thread: the WORKER gets its 40 back and the GUI thread is untouched.
    current = 2; to(11); assert(priority[2] == 2);
    current = 1; to(2); assert(priority[2] == 40 && priority[1] == 31);

    // ReferThreadStatus failing: no garbage priority written on the way out.
    referFails = 1; to(11); int writes = priorityWrites; to(2); assert(priorityWrites == writes); referFails = 0;
    priority[1] = 31;

    // single-pass modes never touch priorities
    writes = priorityWrites;
    for (int m = 0; m < NUM_RM_VMODES; m++) if (rm_mode_table[m].passes == 1) to(m);
    assert(priorityWrites == writes);

    puts("hires thread priority: ok");
    return 0;
}
'''
program = program.replace('@TABLE@', table).replace('@SETMODE@', set_mode).replace('@END@', end)

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'hires_priority.cpp'
    exe = Path(tmp) / 'hires_priority'
    c.write_text(program, encoding='utf-8')
    built = subprocess.run(['g++', '-std=gnu++17', '-Wall', '-Wno-unused-function', '-Wno-narrowing', str(c), '-o', str(exe)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr)
        sys.exit('FAIL: could not build the setMode/end harness')
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    print(ran.stdout, end='')
    if ran.returncode != 0:
        print(ran.stderr)
        sys.exit('FAIL: a video mode switch left a thread at the wrong priority')
