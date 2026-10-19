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
report is resolved. In particular, retaining a notification cannot repair a
sampler that never detects the combination.

### Follow-up: compare the released exFAT build, not the default branch

The first comparison inspected Grimdoomer's default branch at
`24340b5ec9303d209a73efcdd68e741f48641aec`. That was an incomplete reference:
the exFAT releases were built from `hdd_large_capacity_support`. The follow-up
uses released tag
[`v1.2.0.6-1996-Beta`](https://github.com/grimdoomer/Open-PS2-Loader/releases/tag/v1.2.0.6-1996-Beta),
commit `b6717a842e02a8010abaf23a9116081ec43d8512`, and checks the archived
branch tip `d1f51be4452074c2352931e0b9c474da9242e481` (only a missing assembly
file was added after that release).

| Stage | Released Grimdoomer | Current standard RiptOPL | Finding |
| --- | --- | --- | --- |
| Pad recognition | Seven PadOpen patterns and the same libpad/libpad2 byte offsets | Same pattern header, byte for byte | No missing pattern port found |
| Sampling | VBLANK_END interrupt reads the pad; priority-127 worker sleeps until shutdown | EE alarm reads the pad; a semaphore signals the shutdown worker | Different sampling resource, not just a changed worker wake |
| Alarm allocation failure | No SetAlarm dependency for sampling | Failed initial registration or rearm leaves no sampler; only a later pad-open retries | A remaining loss of availability that the old handler avoids |
| Shutdown RPC | 64-byte-aligned client and parameter | Entire `cd_igr_rpc.c` is identical | The archive's explicit RPC fix is already present |
| ATA runtime | BDM ATA includes DEV9/ATAD; prevents games replacing owned ATA interrupts; fakes DEV9/ATAD modules | Equivalent protections present | No missing exFAT-specific IGR enable found |
| Reset destination | Memory-card modules and optional USB SYS-CONF drivers | Same destination restriction | Neither inspected path restores an internal exFAT return ELF |

The release history identifies the concrete IGR fix in
[`02ff1224`](https://github.com/grimdoomer/Open-PS2-Loader/commit/02ff1224d056d6965fca57eb7f7500070139962a):
align the shutdown RPC client to 64 bytes and turn debug printing off by
default. RiptOPL already has that alignment and defaults EESIO debugging off.
Blindly cherry-picking it would add no missing fix.

### Reproduced architectural difference

`.github/scripts/test_igr_grimdoomer_compare.py` hash-checks the released
archive's `padhook.c` and compiles its actual handler/installer and current
production functions against the same existing host kernel/hardware fixture.
The probe does not reproduce game execution, a full EE kernel, or ATA hardware.
It injects the documented error return at the allocation API boundary:

| Injected scenario | Archived handler detects combo | Current standard sampler detects combo |
| --- | --- | --- |
| Normal sampling | Yes | Yes |
| Initial SetAlarm fails | Yes | No |
| iSetAlarm rearm fails | Yes | No |

Run the comparison (downloads only the hash-pinned archived source):

```sh
python3 .github/scripts/test_igr_grimdoomer_compare.py
python3 .github/scripts/test_igr_grimdoomer_compare.py --require-parity
```

The second command intentionally exits 1 while these sampling gaps remain.
`--archived-source /path/to/padhook.c` uses a local copy of the same pinned
file. The current ordinary IGR regression also verifies that a later pad-open
can repair a failed registration; it does not guarantee one will occur.

Grimdoomer gets interrupt-driven detection without depending on a shared
alarm slot. RiptOPL's earlier priority-127 sampling added worker starvation;
#973 moved sampling into the alarm callback and #990 retained its notification.
Those fixes do not remove the alarm dependency. The SDK alarm API has a finite
table and can return failure, but these injections **do not establish** that
this reporter exhausted it or suffered a rearm failure. They also do not show
that rearm exhaustion is reachable in an otherwise healthy alarm dispatcher;
the current callback normally inherits a slot freed by its own expiry.

No production sampler change is included in this audit. Restoring VBLANK_END
globally would reintroduce the documented Fatal Fury: Battle Archives Volume 2
registration conflict. A diagnostic/per-game comparison of the old and new
samplers can distinguish that tradeoff; a claimed fix needs evidence of which
event source disappears on the affected console, and should preserve Mode 6,
the RA handler, the retained-request fix and the pad-buffer lifetime safeguards.

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
