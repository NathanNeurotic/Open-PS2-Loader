# PES 2013 IGR regression — hardware triage (unverified)

Status: **Investigate; do not merge a speculative runtime change.**

Upstream source: https://github.com/ps2homebrew/Open-PS2-Loader/issues/1787
Origin of polling design: https://github.com/ps2homebrew/Open-PS2-Loader/pull/1762

## Reported reproduction

- Game: PES 2013, `SLES_556.69`, same image/revision across comparisons.
- Console reported: SCPH-90004.
- Source: SMB.
- Game compatibility: Mode 2 ON, Mode 6 OFF.
- At language selection, hold L1 + L2 + R1 + R2, then Start + Select.
- Upstream OPL 2248: reset reportedly works.
- Upstream OPL 2250: reset reportedly fails.
- Upstream OPL 2267: reset reportedly fails.
- No proof yet that RiptOPL reproduces the issue. Confirm on its exact build SHA/ELF flavour.

## Why this matters to RiptOPL

RiptOPL already adopted the alarm-driven low-priority IGR polling implementation
from #1762. Unlike the reference, it has a zero-initialized EE thread descriptor,
retry on CreateThread/StartThread failure, and latching for a held power-button signal.
These safeguards must be preserved. RetroAchievements builds use a different,
VBLANK-driven IGR path; do not conflate results.

## Reproduction matrix (all results pending)

| Loader/build | Mode 2 | Mode 6 | Transport | Expected question |
| --- | --- | --- | --- | --- |
| Upstream beta 2248 | ON | OFF | SMB | Confirm reported working baseline |
| Upstream beta 2250 | ON | OFF | SMB | Confirm first affected build |
| Upstream beta 2267 | ON | OFF | SMB | Confirm persistence |
| RiptOPL official rolling, pinned SHA | ON | OFF | SMB | Does the RiptOPL polling fork reproduce? |
| Same RiptOPL SHA | OFF | OFF | SMB | Is Mode 2 a prerequisite? |
| Same RiptOPL SHA | ON | OFF | USB or HDD | Is the problem SMB-sensitive? |
| Same RiptOPL SHA, RA build | ON | OFF | SMB | Is VBLANK-driven IGR different? |
| Same RiptOPL SHA | ON | ON | SMB | Does game remain stable with deliberate IGR disable? |

Record console model, OPL version/flavour, exact build-manifest SHA, GameID,
image hash, network/storage configuration, enabled compatibility modes,
and exit-ELF path. Distinguish combo not detected from detected-but-failed exit.

## Diagnostic plan

Build an **explicit diagnostic-only** artifact after a reproducer is available.
Use a bounded in-memory counter/event buffer instead of logging on every frame,
because console output can change scheduling and conceal the bug.

1. Count `IGR_Poll_Alarm` invocations and `iWakeupThread` results.
2. Count actual worker resumptions after `SleepThread`; check for starvation at priority 127.
3. Record `padOpen_hooked`, pad pointer presence, libpad version, stability byte,
   frame-counter advances, and combo detection (without dumping unrelated input).
4. Record the transition into `IGR_StopDmaAndGs`, `ResetEE`, suspension,
   `Reset_Iop`, and exit ELF launch to distinguish input failure from shutdown failure.
5. Validate no alarm allocation failure and no worker stuck pending a lost wakeup.
6. Compare logs and behavior of upstream known-good and known-bad builds.
7. Consider a priority/alarm change **only if observations confirm the cause**.

## Regression gate for any eventual fix

- PES 2013 on real console: repeated working IGR to configured exit ELF.
- Fatal Fury: Battle Archives Volume 2 still boots without a VBLANK_END IGR hook.
- Ratchet & Clank 3 and Ocean Commander continue to launch and return using IGR.
- Verify both libpad and libpad2, PAL/NTSC, repeated relaunch, power-button behavior,
  and common transports.
- Standard and RA host tests, every CI ELF build, no unexpected memory growth.
- No global thread-priority increase or IGR fallback without hardware evidence.

## Runtime fix policy

This document is the test plan, **not** a fix. Publishing it does not establish
a RiptOPL reproduction or resolve the reported issue. Once console evidence
isolates a cause, introduce a minimal, separately revertible runtime patch and
review its test evidence before including that runtime change in a release.
