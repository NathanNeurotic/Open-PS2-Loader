# Internal exFAT: Ember listing and PS2 IGR investigation

Investigated against `rebuild/main` at `7988eff5a83339cfff78b2b6da65141199163a30`.
The supplied community screenshot reports missing Ember titles and PS2 IGR
working in Grimdoomer's build but failing in RiptOPL. The maintainer clarified
that the IGR report concerns **PS2 games**, not Ember. The reporter's exact
RiptOPL build, loader core, IGR destination and directory contents are unknown.

## Ember: a reproduced listing defect

The expected layout is already supported on internal exFAT through BDM:

```text
EMBER/
  ember.elf
  bios.bin
  games/
    Spyro/
      Spyro.cue
      Spyro.bin
```

`bdmUpdateGameList()` passes the selected device's `massN:/` root to
`ps1FillGameList()`, which includes the Ember scanner. ATA is not excluded.
`ata:/` is a typed SDK alias; the menu uses the volume's actual `massN:` mount,
whose number depends on attachment order. The PS2 BDM Prefix does not relocate
the PS1 library. Changing it is not a fix for this layout.

**Reproduction:** scan that layout successfully, then add a regular file such
as `EMBER/games/readme.txt` or `EMBER/games/.DS_Store`. The old scanner returns
`-1` instead of listing Spyro. An initially empty PS1 list stays empty; a
previously populated list can retain its earlier contents or publish only the
POPSTARTER half.

`cueEntryIsGame()` opens each entry as a directory to avoid relying on
inconsistent `d_type` values. The pinned BDM FatFs `fs_dopen()` returns negative
FatFs result codes directly. Opening a regular file as a directory produces
`FR_NO_PATH` (5), which newlib exposes as `EIO` (also 5). The scanner interprets
this as a device read failure and discards the entire Ember scan.

The fix performs `stat()` only after an otherwise fatal directory-open error.
A successfully identified **regular file** is skipped. A directory or failed
stat retains the original error and existing last-good-list/retry behavior.
The change does not treat all `EIO` errors as absent files.

Evidence:

- `.github/scripts/test_ember_fatfs_images.py` compiles the production scanner,
  the pinned SDK `fs_dopen()` and the pinned FatFs implementation. It creates
  disposable FAT32 and exFAT images with the Spyro layout and loose files.
- Both clean layouts pass before the fix; adding loose files fails on both
  filesystems at the baseline commit. Both pass with the fix, including typed
  and legacy path adapters, empty groups and an injected directory-open error.
- The focused scanner harness also checks that failed stat cannot hide the
  open error. Existing missing-core, settings, ATA-discovery and view-switch
  regressions remain applicable.
- These host tests model filesystem behavior, not ATA hardware or an actual
  Ember launch. The screenshot does not establish whether this reporter has
  a loose file; this is a confirmed defect that can explain the symptom, not
  a confirmed attribution of their individual report.

Reproduce the old failure with:

```sh
python3 .github/scripts/test_ember_fatfs_images.py --ref 7988eff5a83339cfff78b2b6da65141199163a30
```

Omit `--ref` to test the working tree. Inputs are hash-verified against
`.github/patches/bdmfs-vmc-sources.json`; `--source` accepts a cache preserving
those source paths.

## PS2 IGR: restore the interrupt-side handoff

The follow-up compared the actual released exFAT tag
[`v1.2.0.6-1996-Beta`](https://github.com/grimdoomer/Open-PS2-Loader/releases/tag/v1.2.0.6-1996-Beta),
commit `b6717a842e02a8010abaf23a9116081ec43d8512`, from
`hdd_large_capacity_support`. The first audit's default-branch reference was
incomplete. The branch tip `d1f51be4452074c2352931e0b9c474da9242e481`
adds only a missing assembly file after the release.

### Root cause and minimal fix

Grimdoomer's interrupt handler suspends the other game threads **before**
waking the IGR worker. RiptOPL moved that suspension into the worker and relied
on promoting the worker to priority 0 after detecting a combination.

EE scheduling is cooperative between equal-priority threads. A running game
thread at priority 0 does not yield merely because another thread becomes
ready at priority 0. Another already-ready priority-0 game thread can also
remain ahead of the worker. The combination is detected and its semaphore
notification retained, yet the worker can still never run to suspend those
threads. The game's priority-0 path is explicitly supported by RiptOPL's own
`Hook_CreateThread` in `ee_core/src/asm.S`.

The fix restores the archived interrupt-side suspension before signalling the
worker's semaphore. The existing suspension loop is moved, not duplicated.
DMA/GS stop and ResetEE remain in the ordinary worker. No new worker, timer,
VBLANK handler, configuration option or recurring polling work is introduced.
The standard alarm sampler retains the compatibility benefit of upstream
[#1762](https://github.com/ps2homebrew/Open-PS2-Loader/pull/1762), including
avoiding Fatal Fury: Battle Archives Volume 2's VBLANK registration conflict.
The RA handler and Mode 6 behavior are unchanged.

The semaphore fix from [#990](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/990)
still matters: it preserves a request arriving before the worker first waits.
It cannot by itself force equal-priority game threads to yield. Likewise,
[#973](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/973) prevented
starvation of input sampling, but did not guarantee the shutdown worker runs.

In the FREEZEDIAG build, thread status now includes the sampler's suspension
when `FreezeDiag_Begin` records it. The report still runs before worker DMA/GS
shutdown; comments and the ordering regression reflect that distinction.

### Reproduction and validation

`.github/scripts/test_igr_priority_handoff.py` compiles the actual production
alarm callback and worker against a cooperative scheduler. Its worker keeps a
real host stack across semaphore blocking and resumption. Hardware input and
reset operations are stubbed; this is not PS2 console acceptance.

```sh
python3 .github/scripts/test_igr_priority_handoff.py 387081db
# Fails the two priority-0 handoffs on the previous source.
python3 .github/scripts/test_igr_priority_handoff.py
# Passes: READY-before-first-wait, blocked/resumed worker, current and queued
# priority-0 competitors, and the interrupt-before-wait notification boundary.
python3 .github/scripts/test_igr_polling.py
python3 .github/scripts/test_igr_wait_race.py
python3 .github/scripts/test_ingame_freeze_diag.py
```

The existing polling fixture verifies no suspension on ordinary input samples,
once-only suspension on handoff, worker reset ordering, libpad/libpad2 and
power inputs, alarm retry, stale callbacks across ExecPS2, and RA/Mode 6 paths.

### Other comparison findings and limits

- The archive's explicit IGR fix in
  [`02ff1224`](https://github.com/grimdoomer/Open-PS2-Loader/commit/02ff1224d056d6965fca57eb7f7500070139962a)
  aligns the RPC client to 64 bytes and turns debug printing off by default.
  RiptOPL already has both changes. The released `cd_igr_rpc.c` and PadOpen
  pattern header are byte-identical to ours.
- BDM ATA already includes DEV9/ATAD, protects owned ATA interrupts, and fakes
  the game modules. No missing exFAT-specific IGR enable was found.
- Earlier injected alarm errors demonstrated a separate availability limit:
  failed registration/rearm leaves no standard sampler until a later pad-open.
  Those injections did not establish the cause of this console report. Normal
  SDK alarm dispatch frees the expired slot before the callback, so artificial
  rearm exhaustion is not evidence it occurs in ordinary dispatch. The
  exploratory comparison probe is superseded by the scheduler regression.
- Neither inspected reset loader restores internal exFAT for an `ata:` return
  ELF. Test with a blank IGR Path (PS2 browser) or a known-good memory-card ELF
  to isolate destination loading from combination detection and handoff.

This fixes a reproduced production scheduling defect and restores the archived
handoff without restoring its VBLANK sampler. The reporter's exact build and
real-console result remain unknown. Keep
[#984](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/984) open for
report-wide resolution; passing host tests and builds is not hardware proof.
