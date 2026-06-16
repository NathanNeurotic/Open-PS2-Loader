# Rolling Release

This fork publishes a continuously-updated **`rolling`** pre-release so the current
`master` build can be pulled straight from GitHub as development progresses —
without touching the curated tagged releases or the `latest` pre-release.

## Pull the latest build

Stable URL — always the newest `master` build:

```
https://github.com/NathanNeurotic/Open-PS2-Loader/releases/download/rolling/OPNPS2LD.ELF
```

Examples:

```sh
# curl
curl -L -o OPNPS2LD.ELF \
  https://github.com/NathanNeurotic/Open-PS2-Loader/releases/download/rolling/OPNPS2LD.ELF

# PowerShell
Invoke-WebRequest -Uri "https://github.com/NathanNeurotic/Open-PS2-Loader/releases/download/rolling/OPNPS2LD.ELF" -OutFile OPNPS2LD.ELF

# gh CLI (grabs every asset on the rolling release)
gh release download rolling --repo NathanNeurotic/Open-PS2-Loader --clobber
```

The `rolling` release also carries the versioned `OPNPS2LD-<version>.ELF` and the
`DETAILED_CHANGELOG`. The release notes show the source commit, version, build
time, and the CI run that produced it.

## How it updates

[`.github/workflows/rolling-release.yml`](.github/workflows/rolling-release.yml):

- Triggers on every push to `master`, and on manual **Run workflow** (workflow_dispatch).
- Builds the release ELF in the `ps2max/dev` container (same image as the main CI build).
- Publishes/updates the single `rolling` pre-release from the host runner.
- `concurrency` cancels superseded in-flight runs, so the release reflects the newest push.

## Isolation

The rolling channel is deliberately additive:

- Publishes **only** to the `rolling` tag / pre-release.
- Never modifies the curated tagged releases, the `latest` pre-release (managed by
  `compilation.yml`), or any branch — it only uploads release assets.

> Note: `compilation.yml` independently publishes a rolling pre-release to the
> **`latest`** tag on each `master` push. Both channels coexist. To keep only
> `rolling`, remove the "Create or update prerelease" step in `compilation.yml`'s
> `release` job — this workflow does not depend on it.

## Not a stable release

`rolling` is a development build and may be unstable. Use the tagged releases for
known-good versions.
