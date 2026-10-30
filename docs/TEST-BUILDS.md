# Testing a PR or Actions build

A test artifact belongs to one GitHub Actions run and commit. It is separate from the published rolling release, which can lag while builds run. Open the supplied run, verify its source commit, sign into GitHub, then download the requested ZIP from Artifacts. Expired artifacts need a new build.

| Artifact | Toolchain or purpose |
| --- | --- |
| OPL-OFFICIALROLLING | Moving official ps2homebrew toolchain |
| OPL-PS2DEVROLLING | Moving ps2dev toolchain |
| OPL-PS2DEVROLLING-DIAG | Diagnostic build, moving ps2dev toolchain |
| OPL-OFFICIALROLLING-RA | RetroAchievements build using the moving official ps2homebrew toolchain |
| OPL-OFFICIALROLLING-FREEZEDIAG | In-game freeze report (see below), moving official ps2homebrew toolchain |

For Japanese/Unicode game-name font fallback, see [Unicode Game Titles](UNICODE-GAME-TITLES.md). The optional `font_CJK.ttf` is user-provided, not in the build artifact. Verify the artifact commit includes [PR #917](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/917).

Extract the ZIP and read BUILD-MANIFEST.txt for commit, flavour and build configuration. Launch the ELF requested in the test instructions. The rolling suffix identifies a moving toolchain; it does not prove the source commit has been published. Artifacts contain loader builds and a manifest, so retain the complete companion installation for Neutrino, Ember, POPSTARTER and artwork.

Replacing only RIPTOPL.ELF does not update companion cores or modules. Use the full release package when its notes announce such updates; back up configuration and save cards first.

A useful result names PS2 model, exact OPL version/commit and flavour, loader/device, filesystem, selected core, changed settings, VMC state, PADEMU state, exact error/stage and reproduction steps. Compare the same setup against a known-good build. Compilation and host tests are not a console pass.

The Settings index and About both show the full running build identifier. For a published
release, its notes show the build version before download; the ZIP filename omits the source
hash and SDK suffix. See [Reading the build version](../ROLLING_RELEASE.md#reading-the-build-version)
for the fields and the known Beta-3 identifier error in the standard Beta 4224 pinned build.

See [the release guide](https://nathanneurotic.github.io/Open-PS2-Loader/releases.html) and [troubleshooting](https://nathanneurotic.github.io/Open-PS2-Loader/troubleshooting.html).

## In-game freeze report (FREEZEDIAG)

Use `OPL-OFFICIALROLLING-FREEZEDIAG` when a game freezes during play. Play as usual. When it
freezes, press **L1 + L2 + R1 + R2 + Start + Select** (the normal IGR combo). The build saves
`RIPTFRZ.TXT` to the root of the memory card in slot 1 (slot 2 if slot 1 fails), then exits as
IGR always does. Copy that file off the card with wLaunchELF and send it with your report. Each
freeze overwrites the previous file.

The file records thread waits and priorities after IGR has suspended the game threads; their
status includes that suspension. It also records the last disc reads and any read that started
and never finished, memory card (VMC) activity, and whether the I/O processor still answered.
Its `hint=` line says which of those looks stuck.

Since report v2 it also lists the game's IOP memory: CDVDMAN notes every block the game's IOP
modules allocate and free, the allocations that failed, the lowest free IOP memory and the loaded
modules. ee_core reads that record straight from IOP RAM, so it is there even when the I/O
processor stopped answering. Each block line has `ff_after=`, the number of 0xFF bytes right
after the block. Some games write past their own IOP buffers and fill the overrun with 0xFF
(.hack//Infection, SLUS_202.67, per neutrino issue #92); a long run is marked `OVERRUN?` and its
length is the guard a per-game fix needs. `heap_hint=` sums it up. The hooks pass every call
through unchanged, but CDVDMAN is about 2 KB larger in this build, which shifts where the game's
blocks land, so a freeze that stops happening in this build is a result worth reporting too.

If the controller is dead (the analog light went out), press the **power button twice quickly**
instead of the combo: that is IGR's reset too, and the main CPU reads that button itself. If the
screen stays frozen after that, the IOP could not be reset either, and no file is written.

If the combo does nothing, report that and confirm Compatibility Mode 6 was off. An unresponsive
combo alone does not establish a main-CPU freeze: IGR can be disabled or fail to detect input.
Compatibility Mode 6 turns IGR off, so it also turns this report off. The configuration is
otherwise a normal Korium or IncebtIon build; it is refused for RetroAchievements, which runs
IGR from VBLANK.

If the combo does nothing, report that and confirm Compatibility Mode 6 was off. An unresponsive
combo alone does not establish a main-CPU freeze: IGR can be disabled or fail to detect input.
Compatibility Mode 6 turns IGR off, so it also turns this report off. The flavour is
otherwise a normal OFFICIALROLLING build; it is not combined with RetroAchievements.

## RetroAchievements theme release previews

The **RetroAchievements Release** workflow produces `RetroAchievements-both-themes`, containing
inceBtion and Korium full kits, separately named ELF and PSU updates, a source snapshot and a release
manifest. Its six compile jobs cover both themes across official moving, ps2dev moving and ps2dev
pinned toolchains. PR previews use the current PR source with shared files from a successful standard
release; they are explicitly marked as previews and cannot publish. Production requires same-revision
shared files and builds. This supplements the ordinary flavour CI; neither is physical-console acceptance.

## Favorites and automatic VMC failure recovery

If a Favorites edit cannot stage a complete replacement, including when the device is full,
the edit fails and the existing list is preserved. Free space before retrying.

Automatic VMC probing checks the superblock of whole-MB images before assigning them.
A full-size image left by failed formatting is not treated as a usable card solely because
its length matches. Invalid existing files are preserved and require explicit user action;
odd-size Neutrino cards retain their existing handling.
