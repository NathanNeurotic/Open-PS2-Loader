// Launch-stage diagnostic markers -- see include/launchdiag.h for the stage map and rationale.

#include "include/launchdiag.h"

#if LAUNCH_DIAG

#include <kernel.h>        // DelayThread
#include "include/ioman.h" // LOG

// Same register ee_core's debug colors write (ee_core/include/ee_core.h GS_BGCOLOUR).
#define LAUNCHDIAG_GS_BGCOLOUR (*(volatile unsigned long int *)0x120000E0)

#define LAUNCHDIAG_PARK_GRAY  0x404040
#define LAUNCHDIAG_PARK_FLASH 0xFFFFFF

int gLaunchDiag = 0;

// 0xBBGGRR, indexed by stage. Chosen for distinctness on composite; stages 12/13 live in
// elfldr/loader.c (separate binary, own copy of the table tail). 11 used to be 0xFF80FF -- the
// very value the child paints for 12 -- so a stop at 11 read as a stop at 12.
static const unsigned long int stageColors[] = {
    0x000000, // 0  (unused)
    0x0000FF, // 1  red
    0x00FF00, // 2  green
    0xFF0000, // 3  blue
    0x00FFFF, // 4  yellow
    0xFF00FF, // 5  magenta
    0xFFFF00, // 6  cyan
    0x0080FF, // 7  orange
    0x80FF00, // 8  azure
    0xFF0080, // 9  purple
    0x80FFFF, // 10 light yellow
    0x8080FF, // 11 salmon
    0x000000, // 12 (child: pink)
    0x000000, // 13 (child: spring green)
    0x000000, // 14 (retired: refusals blink, see launchDiagRefuse)
    0xC0C0C0, // 15 silver
    0xFFC080, // 16 light blue
};

void launchDiagMark(int stage)
{
    if (stage == 1)
        gLaunchDiag = 1;

    if (stage > 0 && stage < (int)(sizeof(stageColors) / sizeof(stageColors[0])) && stageColors[stage] != 0)
        LAUNCHDIAG_GS_BGCOLOUR = stageColors[stage];

    LOG("[LAUNCHDIAG] stage %d\n", stage);
}

void launchDiagHold(int stage, int ms)
{
    launchDiagMark(stage);
    if (gLaunchDiag && ms > 0)
        DelayThread(ms * 1000);
}

void launchDiagRefuse(int code)
{
    LOG("[LAUNCHDIAG] refusal code %d\n", code);
    if (!gLaunchDiag)
        return;

    // Past the teardown there is no menu to go back to, so park and repeat the code for the camera:
    // dark gray, then `code` white flashes, then a long gray gap.
    for (;;) {
        int i;
        LAUNCHDIAG_GS_BGCOLOUR = LAUNCHDIAG_PARK_GRAY;
        DelayThread(1500 * 1000);
        for (i = 0; i < code; i++) {
            LAUNCHDIAG_GS_BGCOLOUR = LAUNCHDIAG_PARK_FLASH;
            DelayThread(350 * 1000);
            LAUNCHDIAG_GS_BGCOLOUR = LAUNCHDIAG_PARK_GRAY;
            DelayThread(350 * 1000);
        }
    }
}

#endif
