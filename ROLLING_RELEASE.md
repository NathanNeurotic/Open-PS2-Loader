# Rolling Release

This fork publishes a continuously-updated **`rolling`** development release so the current
publishing-branch build can be pulled straight from GitHub as development progresses, without
changing a preserved snapshot such as `current-fan-favorite`. No stable `v*` release is currently published here. `rolling` is a full (non-pre-release) release and
intentionally owns GitHub's **Latest** marker. The publishing branch is `rebuild/main` during the
rebuild. `master` is the OLD LINEAGE and is no longer wired to the release workflow at all: a
push to it builds nothing and publishes nothing.

The [Korium channel](https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling-korium)
uses the standard package shape with a `-Korium` suffix. Both standard editions install
`APP_RIPTOPL`; choosing another edition replaces that app. The dedicated RA channel below
uses `APP_RIPTOPL-RA`. Preserved snapshots can retain older asset names.

## What the rolling release contains

Every push to the publishing branch rebuilds and republishes the `rolling` release. The headline
asset is a **full installable package** (built across four toolchain flavours, with best-effort
flavours called out if omitted). A post-publish normalizer consolidates the public download set into
archives by purpose (RA, DEBUG and language packs are listed when produced):

| Asset | What it is |
|---|---|
| `RIPTOPL-<version>.zip` | **Complete standard install kit.** `APPS/APP_RIPTOPL/` contains a real `RIPTOPL.ELF`, app metadata, icons and music; `ART/RIPTOPL.ELF_*.png` supplies matching artwork. `APP_RIPTOPL.psu` is the same app as a single memory-card save. The app uses `-OFFICIALROLLING` when available, with a named fallback recorded in its metadata. Four separately labelled SDK ELF folders remain for comparisons, subject to best-effort build availability. The ZIP also includes the complete `POPS/`, `EMBER/` and `neutrino/` folders and five companion-tool shortcuts, including `android-udpfs-server.url`. |
| `RIPTOPL.ELF` | **The loader on its own, for updating an install you already have.** Download it and overwrite your existing `RIPTOPL.ELF` — no archive to unpack, nothing else to copy. Its name never changes, so <https://github.com/NathanNeurotic/Open-PS2-Loader/releases/download/rolling/RIPTOPL.ELF> is a permanent link. It is the **`-OFFICIALROLLING`** flavour; there is only one of these because four would put the "which do I pick?" question back in front of the people this file exists for. It is not a first install: the bare loader does not bring `POPS/`, `EMBER/`, `neutrino/` or the language files, so PS1 and Neutrino launches need the package above. If you want a reproducible build to quote in a bug report, take a pinned folder from the package instead — see [Which build should I use?](#which-build-should-i-use). Best-effort, like the flavour it is copied from: if that build fails the release simply ships without it. |
| `APP_RIPTOPL.psu` | Standard app-only memory-card save. Copy shared folders from the full standard kit separately. |
| `RIPTOPL-src-<version>.zip` | Source snapshot to rebuild this exact commit. |
| `RIPTOPL-LANGS-*.zip` | Extra UI language files (`.lng` + non-Latin fonts) — copy into your OPL folder. |
| `RIPTOPL-VARIANTS-*.zip` | Alternate build configs across the moving and pinned ps2dev flavours; the normalizer also adds one ready-made DualSense (`DUALSENSE=1`) loader for each available official flavour. |
| `RIPTOPL-DEBUG-*.zip` | Diagnostic builds across the moving and pinned ps2dev flavours, when produced. |
| `RIPTOPL-BUGREPORT-*.zip` | The field-diagnostics build before compression, with a README on what to send, when produced. See [Launch diagnostics](docs/LAUNCH-DIAGNOSTICS.md#bug-report-build). |
| `LICENSE-LIBSMB2.txt` | The GNU LGPL-2.1 licence of [libsmb2](https://github.com/sahlberg/libsmb2), by [Ronnie Sahlberg](https://github.com/sahlberg), which every loader embeds for SMB2 browsing. The kit and the VARIANTS and DEBUG zips carry the same file; the bug-report zip carries the same text under `licenses/libsmb2/`. |

To install on a memory card, import the matching `.psu` with a PS2 save manager. For other
devices, copy the matching `APPS/APP_RIPTOPL*/` directory instead. Install `ART/`,
`POPS/`, `EMBER/`, and `neutrino/` separately where those features are used. The PSU
does not contain those shared folders. The labelled ELF folders are alternate builds, not
additional PSU saves.

The release packer writes [R3Z3N](https://github.com/saildot4k)'s SAS timestamps into the PSU save folder and
every direct file at packaging time. Its fixed schedule gives both
`APP_RIPTOPL` and `APP_RIPTOPL-RA` **2098-12-31 14:17:22 UTC**; the two names
share a one-second slot under the supplied ranking algorithm. The packer writes
those dates directly into PSU records, so it does not need a Windows file-time
step or a `psu.toml` file. Saving settings after installation may change the
memory card's file times; the release package cannot preserve them after a
runtime write.

The `.psu` format and independent package check use the CC0
[PSUManager core by techwritescode](https://git.techwritescode.dev/techwritescode/PSUManager),
preserved with its license in [third_party/PSUManager](third_party/PSUManager/README.md).
The core is release-host tooling and does not enter the installable packages.

Apart from the single stable-named `RIPTOPL.ELF` above, the final GitHub release intentionally has
no floating `.ELF`, `SHA256SUMS.txt`, detailed changelog, or SDK/IRX manifest assets. The other
standard loaders live in the unified package, DualSense loaders live in VARIANTS, and build
checksums remain in the workflow log/immutable MEGA archive rather than beside the public archives.
The permanent MEGA archive keeps the versioned `…-OFFICIALROLLING.ELF` rather than the stable copy,
since the two are byte-identical and only the versioned name identifies what it is.

The current UI presents the **PS2/PS1 Game Display** setting on Interface:
**Both (L3)** switches separate device libraries; **Mixed** combines them and L3 cycles
Mixed → PS2 → PS1; **PS2** and **PS1** lock one library and make L3 fully inert. APPS is independent:
it can remain one Mixed ELF list or split Apps / `[PS1]`-titled ELFs across L3. Favorites is also
independent and always cycles **All in One → PS2 → PS1 → ELF**. Returning from Start/Settings retains
the page the user paused on. UDPFS Files lists [POPSTARTER](https://www.psx-place.com/resources/popstarter.683/) VCDs alongside [Ember](https://github.com/Gageformer/Ember) titles and automatically
selects [Okeanos](https://github.com/Okeanos86)'s [BDM-UDPFS Assault](https://github.com/Okeanos86/BDMAssault/releases)
`.udpfs` pair when VCD BDMA Apply on Launch is enabled. The supplied `POPS/IPCONFIG.DAT`
and `POPS/UDPFSCONFIG.DAT` are editable in POPS UDPFS Network Settings; saving applies
both files to every connected USB volume. Launch requires matching valid USB configs.
Driver sources remain device-independent (`POPS/`, or APA `__common/POPS/`), while the
Alpha driver's runtime configs and other non-VCD files remain on USB. This new VCD
handoff awaits console validation. UDPBD and UDPFS IMG remain Ember-only. Confirming Network Settings now applies
the current values and reconnects immediately; Select / Refresh retries a failed network page.

## Reading the build version

You can identify a published build before downloading it: the release notes header gives the
build version and source commit. Every ZIP filename ends with the shorter version, for example
`RIPTOPL-v1.2.0-Beta-4224.zip`, `RIPTOPL-src-v1.2.0-Beta-4224.zip` or, on the Korium channel,
`RIPTOPL-Korium-v1.2.0-Beta-4224.zip`; the revision number is always the last part of the name. About and the Settings index show the full identifier, such as
`v1.2.0-Beta-4224-308bc6a-OFFICIALROLLING`:

| Part | Meaning |
|---|---|
| `v1.2.0-Beta` | Development version series |
| `4224` | Build revision, calculated from the full Git commit count plus two |
| `308bc6a` | Last source commit outside the Makefile's explicit exclusions; it can precede the release's checkout commit |
| `OFFICIALROLLING` | SDK flavour used to build this executable |

The ZIP omits the source hash and SDK suffix because it contains several SDK builds. Each of
those executables must carry the same build revision and source hash for that edition, followed
by its own flavour. Korium adds a channel label and has its own theme source hash; RA identifies
its theme and RA build. The preserved **Current Fan Favorite Build** is an older snapshot with its
own revision, rather than the newest Rolling build.

All release build jobs fetch complete Git history before calculating the version. A shallow
one-commit checkout produces the incorrect revision `Beta-3`; changing the archive name does
not correct the identifier embedded in that executable. This affected the standard
`PS2DEVPINNED` folder in the published Beta 4224 kit. Corrected workflow code takes effect only
after a new release is built and published; it does not repair an already downloaded ELF.

## Auto Loading global settings (#545; pending hardware validation)

Auto Loading now uses the GUI's existing settings-home recovery, including
same-device legacy folders and Custom Settings Path, so the launch path can read
`conf_game.cfg` when the launcher's directory is not the settings home. The change
does not scan merely because global settings are absent. For an APA/PFS ELF
launching a BDM/ATA game, explicit settings redirects take precedence, followed
by the ATA filesystem root and then the PFS home; an unrelated PFS master no
longer hides the ATA-root settings bundle. GUI/HDL settings ownership is unchanged.
Diagnostic builds show the config home,
read masks and global-config population before launch, with an eight-second hold
that is absent from normal builds. Source review supports the fix; the original
hardware report remains unconfirmed locally. See the
[validation matrix and diagnostic limits](docs/AUTOLAUNCH-GLOBAL-SETTINGS.md).

## Which build should I use?

All loaders contain **the same RiptOPL code** — they differ only by the SDK toolchain that built them.
Start with a pinned SDK for reproducible comparisons:

1. **`APP_RIPTOPL-PS2DEVPINNED/` (`-PS2DEVPINNED`) — recommended primary download.** Built on the
   `ps2dev/ps2dev` SDK pinned by image digest for reproducible toolchain selection. Pinning does not itself prove hardware compatibility.
2. **`APP_RIPTOPL-OFFICIALPINNED/` (`-OFFICIALPINNED`) — recommended official pin.** Built on the
   `ps2homebrew/ps2homebrew` official SDK, pinned by image digest.
3. **`APP_RIPTOPL-PS2DEVROLLING/` (`-PS2DEVROLLING`) — bleeding-edge canary.** Tracks `ps2dev/ps2dev:latest`.
4. **`APP_RIPTOPL-OFFICIALROLLING/` (`-OFFICIALROLLING`) — bleeding-edge official canary.** Tracks `ps2homebrew:main`.

The loose `RIPTOPL.ELF` asset is **#4**, `-OFFICIALROLLING`. It is there to make *updating* a working
install a one-file job, not to recommend that flavour: if you are chasing a bug, or want a build a
report can be reproduced against later, take #1 or #2 out of the package.

When something misbehaves on hardware, please say **which flavour you ran** — the in-app version string's
flavour suffix tells you. Those details greatly help pin down any issues between application code and toolchain updates.

## Pull the latest build

**Just updating the loader?** `RIPTOPL.ELF` is the one asset whose name is fixed, so it can be
pulled by URL and dropped straight over your existing copy:

```sh
# --fail matters: the asset is best-effort, and a plain `curl -L -o` writes the
# HTTP error page into the file and still exits 0 -- overwriting a loader that works.
curl --fail --location --show-error --output RIPTOPL.ELF.tmp \
  https://github.com/NathanNeurotic/Open-PS2-Loader/releases/download/rolling/RIPTOPL.ELF \
  && mv RIPTOPL.ELF.tmp RIPTOPL.ELF
```

Every other filename changes each build, so pull those by the `rolling` tag rather than a fixed
filename — the `gh` CLI grabs whatever is currently published:

```sh
# Everything in the current rolling release
gh release download rolling --repo NathanNeurotic/Open-PS2-Loader --clobber

# For just the normal installable package, copy its exact filename from the release page.
# Broad RIPTOPL-* globs also match RA, VARIANTS, DEBUG, LANGS and source archives.
gh release download rolling --repo NathanNeurotic/Open-PS2-Loader \
  --pattern "<exact-normal-package-filename>.zip" --clobber
```

Or download from the release page:
<https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling>

Every prior run's assets are wiped before the new ones are uploaded, so nothing stale
accumulates (GitHub's auto "Source code" archives are added separately). The release
notes show the source commit, version, build time, the CI run that produced it, and
whether the bleeding-edge build succeeded.

## How it updates

[`.github/workflows/rolling-release.yml`](.github/workflows/rolling-release.yml):

- Triggers on every push to `rebuild/main` (updates `rolling`), on every `v*` **tag** push (cuts a
  curated per-version release with identical packaging), and on manual **Run workflow** (workflow_dispatch).
  `master` is deliberately absent from both the trigger list and the publish gate.
- Builds four labelled flavours across two toolchain lineages: moving and digest-pinned
  `ps2dev/ps2dev`, plus moving and digest-pinned official `ps2homebrew/ps2homebrew`.
- The `ps2dev/ps2dev:latest` build is **required to compile**: if it fails to build, the publish
  fails loudly. Note this guards against *build* breakage only — because `ps2dev:latest` tracks a
  moving SDK tag, a green build can still produce a binary that does not boot on hardware (see
  [Which build should I use?](#which-build-should-i-use)), which is why the pinned
  `-PS2DEVPINNED` flavour is kept as the safe fallback. The other three flavours are best-effort;
  when one fails, the package ships without that folder and the notes say so.
- Publishes/updates the single `rolling` release from the host runner as GitHub Latest and explicitly
  clears the pre-release flag.
- `concurrency` cancels superseded in-flight runs, so the release reflects the newest push.
- Refreshes the rolling release's **date**. GitHub silently ignores `published_at` on the update
  API, so the only mechanism that moves it is a draft → published flip; the workflow performs that
  flip, guarded so the channel cannot be left sitting as an invisible draft, and
  `promote-rolling-latest.yml` re-asserts the published state afterwards. Curated `v*` releases are
  never re-dated — they keep the date they were actually published.

## One pipeline, two channels

This workflow is the **single** place release packaging lives. The pushed ref picks the target:

- **`rebuild/main` push** → updates the `rolling` Latest release (the development channel).
- **`v*` tag push** → cuts the **curated per-version release** for that tag (a full release; an
  `-rc*` tag stays a pre-release). Curated tags do not displace `rolling` from GitHub's Latest marker.
  It runs through the **same normalized asset pipeline** as rolling — the same installable bundle,
  source snapshot, VARIANTS archive, and DEBUG/language archives when produced, with the same
  best-effort flavour rules — so the two channels cannot drift into different package formats.

`flavours.yml` builds CI loaders and uploads run artifacts; it does not publish releases. Per-ref `concurrency` keeps a `rebuild/main` push and a tag release from
cancelling each other.

## Not a stable release

`rolling` is a development build and may be unstable. The [Current Fan Favorite Build](https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/current-fan-favorite) is a preserved development snapshot selected after positive user feedback, not a universal compatibility guarantee.

Both installable ZIPs require a usable `neutrino/` bundle; a failed download or incomplete extraction fails release packaging. MEGA uploads depend on successful publishing and configured credentials. Superseded or failed runs may have no archived package.

## Dedicated RetroAchievements release

[RetroAchievements rolling](https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling-ra)
is one experimental release containing both **inceBtion** and **Korium**. Standard Rolling and
standard Korium contain standard builds only; RA never replaces Rolling as GitHub Latest.

| Theme | Full kit | ELF update | App-only memory-card save |
| --- | --- | --- | --- |
| inceBtion | `RIPTOPL-RetroAchievements-inceBtion-<version>.zip` | `RIPTOPL-RA-inceBtion.ELF` | `APP_RIPTOPL-RA-inceBtion.psu` |
| Korium | `RIPTOPL-RetroAchievements-Korium-<version>.zip` | `RIPTOPL-RA-Korium.ELF` | `APP_RIPTOPL-RA-Korium.psu` |

Both kits use the same code revision and pinned ORBIT runtime. Their common internal app path is
`APPS/APP_RIPTOPL-RA/RIPTOPL-RA.ELF`, so switching themes replaces that app. Rename a loose
theme-labelled update to `RIPTOPL-RA.ELF` when installing it. Each kit retains the ps2dev pinned/moving
comparison apps with PADEMU on and off, beside its official moving ready app. Both themes and all
required builds must pass before publication. Failure retains the previous RA release and does not
block standard publication. Historical tagged downloads are retained. See the
[RA guide](docs/RETROACHIEVEMENTS.md) for setup and current validation limits.

`RA-RELEASE.json` and `SHA256SUMS.txt` record the exact source, theme, runtime and download digests.
The source archive contains the common source and `RA-Korium-theme.patch`. RA uses its own publication
workflow and bypasses the standard asset normalizer, which would remove theme-labelled ELFs.
