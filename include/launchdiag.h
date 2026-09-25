#ifndef LAUNCH_DIAG_H
#define LAUNCH_DIAG_H

// Launch-stage diagnostic markers -- UDPBD launch-hang triage build.
//
// Every marker writes one distinct GS background colour (0xBBGGRR; the exact same mechanism
// ee_core's debug colors use, ee_core/include/ee_core.h) and a LOG line. Nothing repaints the
// display between the launch teardown and the handoff target's first draw, so the LAST colour
// left on screen pins the boundary where execution stopped. Markers are silent on non-udpbd
// launches: bdmTryNeutrinoLaunch arms gLaunchDiag only when the game device is a udp block
// transport, and every later call site gates on it.
//
// Stage map (what each colour means):
//   1  red          udpbd neutrino leg entered (frag pre-count next)
//   2  green        frag pre-count passed (preflight next)
//   3  blue         bsd toml preflight passed (mmceSendGameID next)
//   4  yellow       gameID sent (deinitEx next)
//   5  magenta      deinitEx: Please Wait painted (io drain next)
//   6  cyan         io/art drain done (module teardown next)
//   7  orange       module cleanup done (audioEnd/ioEnd next)
//   8  azure        deinitEx finished (sysLaunchNeutrino next)
//   9  purple       argv composed + pool fits (sysLoadELFKeepIOP next)
//   10 light yellow ELF probe open OK (elfldr next)
//   11 rose         ExecPS2 into elfldr child imminent
//   12 pink         elfldr child entered (SifLoadElf running)
//   13 spring green target ELF loaded, ExecPS2 into it imminent
//   14 dark gray    handoff REFUSED (argv budget / open failed / unsupported)
//
// Set LAUNCH_DIAG to 0 to strip every marker from the build.
#define LAUNCH_DIAG 1

#if LAUNCH_DIAG

// Armed by stage 1; every later call site checks this so usb/mx4sio/etc. launches stay unpainted.
extern int gLaunchDiag;

void launchDiagMark(int stage);

#else

#define gLaunchDiag 0
static inline void launchDiagMark(int stage)
{
    (void)stage;
}

#endif

#endif
