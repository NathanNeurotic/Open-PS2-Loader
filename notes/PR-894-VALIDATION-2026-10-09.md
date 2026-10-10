# PR 894 validation checkpoint, 2026-10-09

Reviewed source checkpoint: `12beffd5355d12fd6de043841b6e0f087490b512`.
Base: `rebuild/main`, observed at `8fae5f19807466ce31fa7424969d00be42e66aa3`.
This is an initial targeted review, not approval of the complete PR or console validation.

## Korium background report

The supplied photograph shows a textured background, but does not establish the running
version, video mode, background-art setting, external theme selection, or whether the
pattern is visible directly as well as through the camera. The user subsequently confirmed
the latest rolling release. GitHub's live `rolling-korium` tag resolves to
`d41785a6e455637188234d9e3ad9b3a3590a24a2`, matching the release body's Beta 3608
source identifier. This confirms the release source candidate; the video mode remains unknown.

Verified against Git objects:

- `b0d350f2` (2026-09-15) supplies the 640x480 textured Korium background.
- Its decoded RGB pixels are identical at `d41785a6`. RGB SHA-256 is
  `1899da6d17d205b0124447fb24b14b2c76b2c7b0b01d912aad70d0169474e7f8`.
- `6057c6c2` (2026-09-16) changes palette alpha from 255 to 204 and introduces
  the two-layer fallback in both normal and Coverflow configurations.
- `49b1410a` (2026-09-20) optimizes PNG encoding without changing the decoded pixels.
- `src/textures.c` halves PNG alpha for the GS convention: 204 becomes 102/128.
  Two identical layers over black have approximately 95.9 percent combined opacity,
  so describing this as a substantial amplification of grain is unsupported in
  the 24-bit path. Per-pass rounding and dithering are a separate question.
- `src/renderman.c` uses CT16S with dithering for 720p and 1080i; lower-resolution
  modes use CT24. Quantization and photographic moire are hypotheses, not confirmed causes.
- The PR checkpoint does not change `src/renderman.c`, `src/textures.c`, or the
  built-in theme configurations relative to the observed base.

No background or renderer fix is claimed. The photograph's root cause remains open.
Do not replace the intentional texture or change global GS state on this evidence alone.
The reporter's actual version/mode and a controlled comparison on the same console/display
remain necessary to distinguish intentional texture, display/camera effects, and a regression.

## Confirmed review fix

`menuRenderAchievements` multiplied the parsed earned value by 568 in signed 32-bit
arithmetic. The parser permits values up to ten million; accepted input can therefore
overflow before division and produce a wrong progress-bar width. Use a 64-bit intermediate
and convert back after division. The existing parser bounds and earned <= maximum check
ensure the resulting width remains between 0 and 568.

The browser harness now compiles the production width expression and checks zero,
fractional, half-full, almost-full, and full progress at the accepted upper bound.

## Validation and remaining limits

- All 21 targeted existing host scripts passed: BDM readiness/cache/refresh/partitions,
  Caduceus browser/overlay, HDD module lifetime, IGR, language switching, RA client,
  protocol/chunk/peer/resource/PS1 tests, and theme text room.
- Twenty passed on Windows with a workspace-local temporary directory. The PS1 harness
  uses POSIX `mkdir(path, mode)` and passed in Linux instead.
- The updated browser harness and clang-format 12 check passed locally.
- Both the unmodified checkpoint and checkpoint plus the overflow fix built with
  `RETROACHIEVEMENTS=1` in `opl-build:local`.
  This is a local toolchain result, not an official pinned matrix result or console pass.
  The isolated archive had synthetic Git metadata; its package version/changelog is not
  release provenance and that package must not be distributed as a test release.
- GitHub's public API reported all 13 current-head checks successful, including six build
  variants. The substantive CodeRabbit reviews were on earlier heads, not this checkpoint.
- No merge, release publication, or physical-console graphics/launch/network test is established.

Before further feature work or merge, finish the Korium reproduction, review the remaining
PR paths and review threads against the final head, and run the same-console acceptance
sequence for BDM/HDD/Favourites and the PS1/PS2 achievement launch paths. Host tests and
compilation alone do not establish those hardware behaviors.

## Published-binary follow-up

The standard `RIPTOPL.ELF` was downloaded from the current `rolling-korium` release
and its LZMA payload inspected using the ps2-packer format. It contains the exact
release `gfx/background.png` bytes (SHA-256
`70398bd373ec92cf97e6991cc8db5f76b1ebfce66381b83f69c8bd5c8c698537`), as well as
the Beta 3608 / d41785a / OFFICIALROLLING version identifiers.

The release's `texPrepareClut` and palette row conversion were compiled with host
libpng and run on that PNG. After undoing the GS CLUT index permutation, all decoded
RGBA bytes matched an independent Pillow reference with alpha shifted into GS units.
Both decoded SHA-256 values were
`aef9b1b7b49dee4135f4215dc6b97d67a0ef2a2ba8efd3efc326863520c4eedc`.
This checks host conversion, not texture transfer or GS execution.

A numerical 16-bit blend/dither model shows a different output distribution for
the two translucent passes versus one opaque pass. It is a candidate mechanism,
not a console reproduction or proof of the photographed artifact.

The `Korium background diagnostic` workflow builds two explicitly labelled
variants from the exact released source, using the same pinned toolchain. Both
suppress per-game background requests so saved BG settings cannot confound the
comparison. `control` retains the two-pass release composition; `single-pass`
restores the original opaque PNG and disables only the redundant main1 in both
built-in layouts. Every RGB pixel is preserved. Element numbering is preserved
with `enabled=0`, including inherited Apps/PS1/Favourites families.

These are comparison artifacts, not a production fix or release. They deliberately
do not include PR 894's feature changes. A production repair must also preserve the
optional per-game artwork/tint behavior, which these BG-suppressed probes do not test.
The acceptance requirement applies to every supported video mode; no particular
mode is a prerequisite for taking the report seriously.
