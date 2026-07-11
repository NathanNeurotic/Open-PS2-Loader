#ifndef __OPL_DIAG_H
#define __OPL_DIAG_H

// Always-on, ship-in-release diagnostic counters for the MMCE #120 cascade investigation.
//
// Every serial/__DEBUG log path is compiled out on a stock retail PS2, and a log file on the MMCE card
// would itself write to the (possibly wedged) mmceman SIO2 bus we are trying to observe. So the ONLY
// diagnostic channel that reaches a hardware tester is the screen: these counters are bumped at existing
// choke points on whatever thread reaches them, and rendered as ONE line by the GUI (gui.c) every frame
// on the EE main thread -- proven alive during the cascade (the busy spinner keeps animating and the
// USB/Apps tabs stay live while MMCE art is wedged). The overlay only READS these ints; it issues no
// fileXio / SIO2 / card IO, so it adds ZERO traffic to the bus under investigation.
//
// Thread model: no field has more than one MEANINGFUL writer, and the GUI only reads. artOpens is bumped
// from BOTH the art worker AND the EE main thread (texDiscoverLoad also loads theme PNGs during thmLoad),
// so its non-atomic ++ can lose a rare update -- harmless for a delta-read diagnostic. memoHit/memoMiss are
// art-worker-only; artTerminate from the launch/theme path; vcdRescanPreserved/isoScanPreserved/lastSaveErrno
// from the deferred-IO (or config-write) path. Aligned 32-bit loads/stores are atomic on the EE, so a read
// is at most one frame stale (torn reads impossible) -- acceptable for diagnostics; no locks are taken.
//
// Reading the line (shown only when the user enables debug info, so it costs nothing in normal use). Read
// the counters as a DELTA while performing the repro (they are cumulative and some are not MMCE-exclusive):
//   AO artOpens          - EVERY texDiscoverLoad() entry: ISO + VCD art opens AND theme-element PNGs (theme
//                          loads spike it on a theme switch, NOT the MMCE bus). So don't read the absolute
//                          value -- watch whether AO keeps CLIMBING while parked on ONE PS1 info screen /
//                          scrolling a cover-less PS1 list: if it does, the miss-memo is NOT suppressing
//                          re-probes (epoch/key bug) and the storm is still live.
//   MH memoHit           - vcdLoadArt short-circuits with ZERO opens (memo working). This is the precise
//                          VCD-storm signal: AO plateauing while MH climbs == the storm is bounded.
//   MM memoMiss          - full VCD art misses recorded into the memo (first probe of each cover).
//   TK artTerminate      - **THE smoking gun.** The art watchdog TerminateThread'd the worker, which
//                          corrupts the shared mmceman RPC channel for the rest of the session. TK > 0
//                          means every reduce-the-opens fix is MOOT and we need a no-terminate / channel-
//                          reset fix instead. We have never been able to SEE this before.
//   Vp vcdRescanPreserved- a VCD (PS1) list rebuild kept its last-good list on a failed device read.
//                          NOTE: bumped for ANY VCD backend (mmce/bdm/eth/udpfs/hdd), so on a multi-device
//                          rig it is not MMCE-exclusive -- reliable as an MMCE signal only if MMCE is the
//                          rig's only VCD source (Andrew's case).
//   Ip isoScanPreserved  - an ISO (PS2) list rebuild kept its last-good list on a failed read (same all-
//                          backend caveat as Vp). Ip ticking up when the tester presses "show PS2 games"
//                          confirms the toggle is failing on the contended bus, not a handler that never fired.
//   SE lastSaveErrno     - errno of the last failed settings write (0 = none), latched at the actual write-
//                          failure site inside configWrite() (config.c). EIO/ENODEV here confirms the config
//                          save failed because the card itself is wedged, not a path problem.

typedef struct
{
    volatile unsigned int artOpens;
    volatile unsigned int memoHit;
    volatile unsigned int memoMiss;
    volatile unsigned int artTerminate;
    volatile unsigned int vcdRescanPreserved;
    volatile unsigned int isoScanPreserved;
    volatile int lastSaveErrno;
} opl_diag_t;

extern opl_diag_t gDiag;

#endif
