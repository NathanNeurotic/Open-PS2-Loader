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
| `RIPTOPL-<rel>-<sha>.zip` | **The installable package.** Contains three loader folders that differ ONLY by the SDK toolchain they were built with (the RiptOPL code in each is identical): `APP_RIPTOPL-WOPLSDK/RIPTOPL.ELF` and `APP_RIPTOPL-OLDSDK/RIPTOPL.ELF` — both built on **pinned, known-stable** SDK snapshots (**recommended**) — plus `APP_RIPTOPL/RIPTOPL.ELF`, built on the moving `ps2dev:latest` tag (bleeding-edge; may not boot on all consoles). Also the `POPSTARTER/` + `POPS/` folders for PS1 support and the bundled Neutrino core as a ready-to-use `neutrino/` folder (drag-and-drop to `mc?:/`). Extract it and use a **WOPLSDK or OLDSDK** ELF — see [Which build should I use?](#which-build-should-i-use) below. |
| `RIPTOPL-<version>-woplsdk.ELF` | Bare loader, wOPL's digest-pinned `ghcr.io/ps2homebrew` container (**recommended**; in-app version ends `-woplsdk`). |
| `RIPTOPL-<version>-oldsdk.ELF` | Bare loader, `ps2max/dev` (pinned) toolchain (**recommended fallback**; in-app version ends `-oldsdk`). |
| `RIPTOPL-<version>.ELF` | Bare loader, `ps2dev/ps2dev:latest` toolchain (bleeding-edge; in-app version ends `-latest`; may not boot on all consoles). |
| `RIPTOPL-<version>-src.zip` | Source snapshot to rebuild this exact commit. |
| `SHA256SUMS.txt` | SHA256 of every published binary + the source snapshot. |
| `IRX-MANIFEST*.txt` | SHA256 of every SDK-prebuilt IOP module each toolchain consumed (provenance for silent SDK-side driver swaps). |
| `RIPTOPL-LANGS-*.zip` | Extra UI language files (`.lng` + non-Latin fonts) — copy into your OPL folder. |
| `RIPTOPL-VARIANTS-*.zip` / `RIPTOPL-DEBUG-*.zip` | Alternate build configs and debug builds, both toolchains — for testing/diagnostics. |

`<version>` is the `ps2dev:latest` build's `git describe` (e.g. `v1.2.0-Beta-2559-bb25a00`); the
pinned flavours carry the same version with a `-woplsdk` / `-oldsdk` suffix.

## Which build should I use?

The three loaders are **the same RiptOPL code** — they differ only by the SDK toolchain that built them:

- **Recommended: `-woplsdk` or `-oldsdk`.** Both are built on **pinned, immutable** SDK snapshots, so
  they build the same way every time and boot reliably across consoles. `-woplsdk` uses wOPL's exact
  digest-pinned SDK (stock MMCE drivers); `-oldsdk` uses a pinned 2025 SDK (the most conservative choice).
- **`APP_RIPTOPL/RIPTOPL.ELF` (`-latest`) is the bleeding edge.** It is built against the `ps2dev:latest`
  Docker tag, which **moves constantly** (often several times a day). That makes it the best early-warning
  signal for upstream SDK regressions, but it also means it can *intermittently fail to boot* on some
  consoles when the SDK underneath it changes — that is expected volatility of a moving tag, **not** a
  RiptOPL bug. If the `-latest` ELF black-screens at startup, switch to a `-woplsdk` or `-oldsdk` build.

When something misbehaves on hardware, please say **which flavour you ran** — the in-app version string's
`-latest` / `-woplsdk` / `-oldsdk` suffix tells you. A latest-only failure points at an SDK regression; an
all-three failure points at RiptOPL code. Those bits triple the value of a report.

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

- Triggers on every push to `master` (updates `rolling`), on every `v*` **tag** push (cuts a
  curated per-version release with identical packaging), and on manual **Run workflow** (workflow_dispatch).
- Builds with three toolchains — `ps2dev/ps2dev:latest` (the moving target/canary), wOPL's
  digest-pinned `ghcr.io/ps2homebrew` container, and the pinned `ps2max/dev` (2025) — the same
  images as the main CI build.
- The `ps2dev/ps2dev:latest` build is **required to compile**: if it fails to build, the publish
  fails loudly. Note this guards against *build* breakage only — because `ps2dev:latest` tracks a
  moving SDK tag, a green build can still produce a binary that does not boot on hardware (see
  [Which build should I use?](#which-build-should-i-use)), which is why the pinned `-woplsdk` /
  `-oldsdk` flavours are the recommended download. The two pinned builds are best-effort
  (`continue-on-error`); when one fails, the package ships without that folder and the notes say so.
- Publishes/updates the single `rolling` pre-release from the host runner.
- `concurrency` cancels superseded in-flight runs, so the release reflects the newest push.

## One pipeline, two channels

This workflow is the **single** place release packaging lives. The pushed ref picks the target:

- **`master` push** → updates the `rolling` pre-release (the development channel).
- **`v*` tag push** → cuts the **curated per-version release** for that tag (a full release; an
  `-rc*` tag stays a pre-release). It publishes the **identical** asset set as rolling — same `.zip`
  installable bundle, both toolchains, `src.zip`, `SHA256SUMS` — so the two channels can't drift.

`compilation.yml` no longer cuts releases (its release step is retired); on `master` it only runs
CI + uploads run artifacts. Per-ref `concurrency` keeps a `master` push and a tag release from
cancelling each other.

## Not a stable release

`rolling` is a development build and may be unstable. Use the tagged releases for
known-good versions.
