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
//   9  purple       argv composed (the 256-byte pool check is NEXT, not done -- it can still refuse)
//   10 light yellow ELF probe open OK (elfldr next)
//   11 salmon       ExecPS2 into elfldr child imminent
//   12 pink         elfldr child entered (SifLoadElf running)
//   13 spring green target ELF loaded, ExecPS2 into it imminent
//   15 silver       HELD ~2 s: the probe's open() failed but fileXio opened the same file -- continuing
//   16 light blue   HELD ~2 s: the probe's open() failed, then a retry within ~3 s worked -- continuing
//
// REFUSALS no longer share one colour (the old stage 14). A refused handoff is past the teardown,
// so nothing else can run: the screen PARKS on dark gray, flashes WHITE N times, pauses, and
// repeats forever. Count the flashes:
//   1  null argument / unsupported device at sysLaunchNeutrino entry
//   2  core argv (loadpath + argv[0] + -bsd/-bsdfs/-dvd) over the 256-byte kernel pool
//   3  target ELF will not open, but its device root DOES open (path/file problem on a live device)
//   4  target ELF will not open, and its device root does NOT open either (device gone after teardown)
//   5  child-loader argv over the kernel budget (15 strings / 256 bytes)
//   6  embedded child-loader ELF has a bad magic
//
// Set LAUNCH_DIAG to 0 to strip every marker from the build.
#define LAUNCH_DIAG 1

enum LaunchDiagRefusal {
    LAUNCHDIAG_REFUSE_ARGS = 1,
    LAUNCHDIAG_REFUSE_CORE_ARGV = 2,
    LAUNCHDIAG_REFUSE_OPEN_ROOT_OK = 3,
    LAUNCHDIAG_REFUSE_OPEN_ROOT_GONE = 4,
    LAUNCHDIAG_REFUSE_CHILD_BUDGET = 5,
    LAUNCHDIAG_REFUSE_CHILD_MAGIC = 6,
};

#if LAUNCH_DIAG

// Armed by stage 1; every later call site checks this so usb/mx4sio/etc. launches stay unpainted.
extern int gLaunchDiag;

void launchDiagMark(int stage);

// Paint a stage colour and keep it on screen for ms milliseconds (the continuing stages 15/16).
void launchDiagHold(int stage, int ms);

// Post-teardown refusal. With gLaunchDiag armed this NEVER returns: it parks on the blink code
// above. Unarmed it only LOGs and returns, so the caller's normal refusal path runs unchanged.
void launchDiagRefuse(int code);

// A udp launch that aborts back to a live menu clears the armed state, so a later launch from
// another device never inherits its markers (or its non-returning refusal).
void launchDiagDisarm(void);

#else

#define gLaunchDiag 0
static inline void launchDiagMark(int stage)
{
    (void)stage;
}
static inline void launchDiagHold(int stage, int ms)
{
    (void)stage;
    (void)ms;
}
static inline void launchDiagRefuse(int code)
{
    (void)code;
}
static inline void launchDiagDisarm(void)
{
}

#endif

#endif
