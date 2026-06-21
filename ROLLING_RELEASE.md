# Rolling Release

This fork publishes a continuously-updated **`rolling`** pre-release so the current
`master` build can be pulled straight from GitHub as development progresses, without
touching the curated `v*` tagged releases. `rolling` is the **only** channel updated on
each `master` push.

## What the rolling release contains

Every push to `master` rebuilds and republishes the `rolling` pre-release. The headline
asset is a **full installable package** (built with both toolchains); the bare loader
ELFs and supporting files are published alongside it:

| Asset | What it is |
|---|---|
| `RIPTOPL-<sdk>-<rel>-<sha>.zip` | **The installable package.** Contains `APP_RIPTOPL/RIPTOPL.ELF` (built with `ps2dev:latest`), `APP_RIPTOPL-OLDSDK/RIPTOPL.ELF` (the pinned/stable toolchain), the `POPSTARTER/` + `POPS/` folders for PS1 support, and the bundled Neutrino core (`neutrino_*.7z`). Extract it and use `APP_RIPTOPL/RIPTOPL.ELF`. |
| `RIPTOPL-<version>.ELF` | Bare loader, `ps2max/dev` (pinned) toolchain. |
| `RIPTOPL-<version>-ps2dev-latest.ELF` | Bare loader, `ps2dev/ps2dev:latest` (bleeding-edge) toolchain. |
| `RIPTOPL-<version>-src.zip` | Source snapshot to rebuild this exact commit. |
| `SHA256SUMS.txt` | SHA256 of every published binary + the source snapshot. |
| `RIPTOPL-LANGS-*.zip` | Extra UI language files (`.lng` + non-Latin fonts) — copy into your OPL folder. |
| `RIPTOPL-VARIANTS-*.zip` / `RIPTOPL-DEBUG-*.zip` | Alternate build configs and debug builds, both toolchains — for testing/diagnostics. |

`<version>` is the pinned build's `git describe` (e.g. `v1.2.0-Beta-2559-bb25a00`).

## Pull the latest build

Because the filenames change each build, pull by the `rolling` tag rather than a fixed
filename — the `gh` CLI grabs whatever is currently published:

```sh
# Everything in the current rolling release
gh release download rolling --repo NathanNeurotic/Open-PS2-Loader --clobber

# Just the installable package zip
gh release download rolling --repo NathanNeurotic/Open-PS2-Loader \
  --pattern 'RIPTOPL-*-*-*.zip' --clobber
```

Or download from the release page:
<https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling>

Every prior run's assets are wiped before the new ones are uploaded, so nothing stale
accumulates (GitHub's auto "Source code" archives are added separately). The release
notes show the source commit, version, build time, the CI run that produced it, and
whether the bleeding-edge build succeeded.

## How it updates

[`.github/workflows/rolling-release.yml`](.github/workflows/rolling-release.yml):

- Triggers on every push to `master`, and on manual **Run workflow** (workflow_dispatch).
- Builds with both toolchains — `ps2max/dev` (pinned) and `ps2dev/ps2dev:latest`
  (bleeding-edge) — the same images as the main CI build.
- The `ps2dev/ps2dev:latest` build is best-effort (`continue-on-error`): if it breaks,
  the rolling release still updates with the pinned build, and the notes flag that the
  bleeding-edge build failed.
- Publishes/updates the single `rolling` pre-release from the host runner.
- `concurrency` cancels superseded in-flight runs, so the release reflects the newest push.

## Isolation

The rolling channel is deliberately additive:

- Publishes **only** to the `rolling` tag / pre-release.
- Never modifies the curated `v*` tagged releases (cut by `compilation.yml` only on a
  `v*` tag) or any branch — it only uploads release assets.

`compilation.yml` no longer publishes anything on a `master` push; its `release` job only
cuts a per-version release on a `v*` tag. So `rolling` is the single channel that tracks
`master`.

## Not a stable release

`rolling` is a development build and may be unstable. Use the tagged releases for
known-good versions.
