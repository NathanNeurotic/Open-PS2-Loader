// Launch-stage diagnostic markers -- see include/launchdiag.h for the stage map and rationale.

#include "include/launchdiag.h"

#if LAUNCH_DIAG

#include "include/ioman.h" // LOG

// Same register ee_core's debug colors write (ee_core/include/ee_core.h GS_BGCOLOUR).
#define LAUNCHDIAG_GS_BGCOLOUR (*(volatile unsigned long int *)0x120000E0)

int gLaunchDiag = 0;

// 0xBBGGRR, indexed by stage. Chosen for distinctness on composite; stages 12/13 live in
// elfldr/loader.c (separate binary, own copy of the table tail).
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
    0xFF80FF, // 11 rose
};

void launchDiagMark(int stage)
{
    if (stage == 1)
        gLaunchDiag = 1;

    if (stage > 0 && stage < (int)(sizeof(stageColors) / sizeof(stageColors[0])))
        LAUNCHDIAG_GS_BGCOLOUR = stageColors[stage];
    else if (stage == 14)
        LAUNCHDIAG_GS_BGCOLOUR = 0x404040; // refusal: dark gray, deliberately not a real stage color

    LOG("[LAUNCHDIAG] stage %d\n", stage);
}

#endif
