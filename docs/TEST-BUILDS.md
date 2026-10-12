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

Extract the ZIP and read BUILD-MANIFEST.txt for commit, flavour and build configuration. Launch the ELF requested in the test instructions. The rolling suffix identifies a moving toolchain; it does not prove the source commit has been published. Artifacts contain loader builds and a manifest, so retain the complete companion installation for Neutrino, Ember, POPSTARTER and artwork.

Replacing only RIPTOPL.ELF does not update companion cores or modules. Use the full release package when its notes announce such updates; back up configuration and save cards first.

A useful result names PS2 model, exact OPL version/commit and flavour, loader/device, filesystem, selected core, changed settings, VMC state, PADEMU state, exact error/stage and reproduction steps. Compare the same setup against a known-good build. Compilation and host tests are not a console pass.

See [the release guide](https://nathanneurotic.github.io/Open-PS2-Loader/releases.html) and [troubleshooting](https://nathanneurotic.github.io/Open-PS2-Loader/troubleshooting.html).

## RetroAchievements theme release previews

The **RetroAchievements Release** workflow produces `RetroAchievements-both-themes`, containing
inceBtion and Korium full kits, separately named ELF and PSU updates, a source snapshot and a release
manifest. Its six compile jobs cover both themes across official moving, ps2dev moving and ps2dev
pinned toolchains. PR previews use the current PR source with shared files from a successful standard
release; they are explicitly marked as previews and cannot publish. Production requires same-revision
shared files and builds. This supplements the ordinary flavour CI; neither is physical-console acceptance.
