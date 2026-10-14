# Testing a PR or Actions build

A test artifact belongs to one GitHub Actions run and commit. It is separate from the published rolling release, which can lag while builds run. Open the supplied run, verify its source commit, sign into GitHub, then download the requested ZIP from Artifacts. Expired artifacts need a new build.

| Artifact | Toolchain or purpose |
| --- | --- |
| OPL-OFFICIALROLLING | Moving official ps2homebrew toolchain |
| OPL-OFFICIALPINNED | Digest-pinned official toolchain |
| OPL-PS2DEVROLLING | Moving ps2dev toolchain |
| OPL-PS2DEVPINNED | Digest-pinned ps2dev toolchain |
| OPL-PS2DEVPINNED-DIAG | Diagnostic build |
| OPL-OFFICIALROLLING-RA | RetroAchievements build using the moving official ps2homebrew toolchain |
| OPL-OFFICIALROLLING-FREEZEDIAG | In-game freeze report (see below), moving official ps2homebrew toolchain |

For Japanese/Unicode game-name font fallback, see [Unicode Game Titles](UNICODE-GAME-TITLES.md). The optional `font_CJK.ttf` is user-provided, not in the build artifact. Verify the artifact commit includes [PR #917](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/917).

Extract the ZIP and read BUILD-MANIFEST.txt for commit, flavour and build configuration. Launch the ELF requested in the test instructions. The rolling suffix identifies a moving toolchain; it does not prove the source commit has been published. Artifacts contain loader builds and a manifest, so retain the complete companion installation for Neutrino, Ember, POPSTARTER and artwork.

Replacing only RIPTOPL.ELF does not update companion cores or modules. Use the full release package when its notes announce such updates; back up configuration and save cards first.

A useful result names PS2 model, exact OPL version/commit and flavour, loader/device, filesystem, selected core, changed settings, VMC state, PADEMU state, exact error/stage and reproduction steps. Compare the same setup against a known-good build. Compilation and host tests are not a console pass.

See [the release guide](https://nathanneurotic.github.io/Open-PS2-Loader/releases.html) and [troubleshooting](https://nathanneurotic.github.io/Open-PS2-Loader/troubleshooting.html).

## In-game freeze report (FREEZEDIAG)

Use `OPL-OFFICIALROLLING-FREEZEDIAG` when a game freezes during play. Play as usual. When it
freezes, press **L1 + L2 + R1 + R2 + Start + Select** (the normal IGR combo). The build saves
`RIPTFRZ.TXT` to the root of the memory card in slot 1 (slot 2 if slot 1 fails), then exits as
IGR always does. Copy that file off the card with wLaunchELF and send it with your report. Each
freeze overwrites the previous file.

The file records the game's threads at the moment of the combo, the last disc reads and any read
that started and never finished, memory card (VMC) activity, and whether the I/O processor still
answered. Its `hint=` line says which of those looks stuck.

If the combo does nothing at all, report that: it means the main CPU itself is stuck, which is a
result too. Compatibility Mode 6 turns IGR off, so it also turns this report off. The flavour is
otherwise a normal OFFICIALROLLING build; it is not combined with RetroAchievements.

## RetroAchievements theme release previews

The **RetroAchievements Release** workflow produces `RetroAchievements-both-themes`, containing
inceBtion and Korium full kits, separately named ELF and PSU updates, a source snapshot and a release
manifest. Its six compile jobs cover both themes across official moving, ps2dev moving and ps2dev
pinned toolchains. PR previews use the current PR source with shared files from a successful standard
release; they are explicitly marked as previews and cannot publish. Production requires same-revision
shared files and builds. This supplements the ordinary flavour CI; neither is physical-console acceptance.
