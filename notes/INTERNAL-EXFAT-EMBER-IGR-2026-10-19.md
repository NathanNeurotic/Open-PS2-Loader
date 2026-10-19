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

## PS2 IGR: a known repaired mechanism, report still unconfirmed

Internal exFAT is not intentionally excluded from OPL-core IGR. The sampler
and worker in `ee_core/src/padhook.c` are shared across OPL game transports.
Neutrino does not implement this IGR path; compatibility Mode 6 disables it.

[Issue #984](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/984)
records an internal-exFAT IGR failure on standard OFFICIALROLLING builds,
including Beta-4032 at `c4b707a`. A later fix,
[PR #990](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/990), merged
on October 18 as `895d4b765521c519e03af8a2ed37a58a94d4e0aa`. It replaces a
lost running-thread wake with a semaphore that retains the request.

The existing production-function regression was rerun during this audit:

```sh
python3 .github/scripts/test_igr_wait_race.py c4b707a
# Fails: request latched, alarm stopped, running-thread wake lost, worker asleep.
python3 .github/scripts/test_igr_wait_race.py
# Passes: retained request, already-latched request and spurious wake cases.
python3 .github/scripts/test_igr_polling.py
# Passes standard alarm and RA handler/lifecycle cases.
```

This establishes a real mechanism already repaired in current main. It does
not establish which build the screenshot reporter uses, or that every console
report is resolved. No additional IGR runtime change was justified by this
investigation.

Grimdoomer's public default branch was compared at
`24340b5ec9303d209a73efcdd68e741f48641aec`. It uses the older VBLANK sampler,
while standard RiptOPL uses the EE alarm to avoid the documented VBLANK game
compatibility failure. Its successful hardware result is useful comparative
evidence, but does not justify replacing the current sampler globally.

Distinguish a combination that does nothing from a reset that cannot load its
destination. In both inspected implementations, `t_loadElf()` restores memory
card access and optionally USB drivers from `mc?:SYS-CONF`; it does not restore
an internal exFAT filesystem for an `ata:` destination. An internal exFAT game
source and the IGR return-ELF location are separate concerns. Test with an
empty IGR Path (PS2 browser) or a known-good memory-card ELF first.

To attribute a remaining hardware failure, record the exact version/flavour
and SHA (including whether #990 is present), OPL versus Neutrino, game/ID,
Mode 6, controller/PADEMU, IGR Path, and whether the combo does nothing,
freezes after detection, or returns to the browser. Physical power-button
behavior is an additional cross-check. Keep #984's report-wide status open
until the hardware evidence supports resolution.
