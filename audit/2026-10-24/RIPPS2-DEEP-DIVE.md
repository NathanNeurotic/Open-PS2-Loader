# RIPPS2 collaboration and source review — October 24, 2026

[RIPPS2](https://github.com/akilluminati47/RIPPS2), maintained by **[Akilluminati47](https://github.com/akilluminati47)**, is a collaborating RiptOPL-derived project. [Ripto](https://github.com/NathanNeurotic) and Akilluminati47 share GUI and backend work while developing their projects in tandem. This comparison identifies work that can flow in either direction. Shared upstream changes are credited as shared work, rather than counted again as missing [RiptOPL](https://github.com/NathanNeurotic/RiptOPL) features.

The RiptOPL comparison target is [`rebuild/main@55261de1`][ript], including the merged i.LINK, font-size, RA-badge and dedicated Language-page changes. The RIPPS2 review covers both its published line and its active development branch:

| Input | Exact revision | Meaning |
| --- | --- | --- |
| RIPPS2 `main` | `28bc44d0d3a31b084d6b7e55ff91745f9a09c026` | Build 113 plus Build 114 planning notes |
| Released `v1.1.3-beta` | `9b876e6153e3d801c4fc18ce93f38229e319fd8f` | Build 113; the release API marks this beta-named tag as a non-prerelease |
| Development `b114` | `1d8888ed63c33aa45c27355cd61c966dd1f918eb` | Implemented development work, **not** the published Build 113 package |
| Upstream incorporated by `main` | `3cd7f89c8239485e28f5343caad6beaa594d3478` | Recorded in `elf/RIPTOPL_UPSTREAM` |
| Upstream incorporated by `b114` | `57c45b4fcc922ba00fed949c634caea0a2900c63` | The branch imports 192 RiptOPL commits, before our newest five UI/release PRs and #1042 |

The snapshots were reconstructed from the pinned RiptOPL base, numbered RIPPS2 patches and the build's pinned mbedTLS source. The upstream build script was inspected, not executed. This gives the resulting C source instead of relying on patch names, changelog summaries or screenshots. Exact source pins are also recorded in [focused-refs.json](focused-refs.json).

## i.LINK: what the public evidence actually establishes

The public Build 114 plan records FifthFox's Build 112 setup: SCPH-39001, a Mobile Disk HD-338 Prolific enclosure, a Seagate IDE drive and 6-to-4-pin FireWire, alongside MMCE, MX4SIO and APA storage. Its results are separated by runtime below. These are **recorded tester observations**, not console tests performed by this audit. [Field report and upstream-import discussion][field-report]

| Runtime | RIPPS2's recorded result / source | Assessment against current RiptOPL |
| --- | --- | --- |
| Native OPL PS2 | i.LINK games reportedly launched with compatibility modes and logo | A useful configuration-specific result. It does not establish universal mode-free launch or explain the cause. |
| Ember PS1 | The report says Ember worked from the tested devices | Keep as a separate positive runtime report; it does not validate POPStarter or Neutrino. |
| Ordinary Neutrino | Build 112 report still failed on i.LINK; `b114` imports our earlier reset/login and packaged-driver work | The branch has useful shared upstream fixes, but does not yet contain #1042's transaction-ownership repair. |
| POPStarter | Build 112 report still failed on i.LINK; `b114` incorporates the earlier rebuilt pair | Its pair is older than our #1042 pair. A native OPL success cannot certify this independent stack. |
| RA ORBIT runtime | Separate runtime and packaging path | Do not infer results from ordinary Neutrino, or replace its runtime piecemeal. |

The reconstructed POPStarter driver provides a reproducible version boundary:

| Snapshot | `POPS/usbhdfsd.irx.ilink` bytes | SHA-256 |
| --- | ---: | --- |
| RIPPS2 `main` | 21,609 | `9b47d90b03804ea9ef47c3702911d83d488405cc64285b62073ce88a7b6bfc63` |
| RIPPS2 `b114` | 22,025 | `aec8f3d6b15af7024bb62120488ed1b83526c4f852add6161185a1232017edc2` |
| RiptOPL `55261de1` | 27,145 | `1a9c1baaf1dd020e35b75082b630f325b90e884819c743ddd5e1f27f106efcb6` |

These hashes identify checked-in/reconstructed driver bytes, not a benchmark or a compatibility ranking. RiptOPL's latest repair addresses SBP-2 direction, response/request ownership, late DMA, manager alarms and matching Neutrino modules. It deliberately retains target-visible storage after uncertain completion; a request that never completes can require a fresh IOP/driver start. Physical acceptance remains pending. [Current i.LINK audit][ilink-audit]

RIPPS2 also moved automatic `-logo` earlier, later reversed that experiment, and documented an A/B plan. The research note itself says Neutrino parses options before acting and recommends **not** treating argument position as the fix. Logo-on can change the boot/reset sequence, which is a different hypothesis. Preserve `--b`, duplicate-option precedence, the argv budget and MMCE/network suppression when comparing. Adding a delay before Neutrino's reset does not prove a post-reset handshake correction. [Argument-order research][logo-research] · [Build 89 reversal][logo-reversal]

**Useful next collaboration:** compare the same game, enclosure and cold/repeated-launch conditions with provenance-pinned complete runtime sets. Native OPL, standard Neutrino and POPStarter need independent results. The first code-sharing candidate is our reviewed #1042 stack for RIPPS2's newer upstream import, rather than a second logo-order workaround.

## Layout work worth adapting

### Sidebar focus and measured drawers — released Build 113

`ripps2side.c` implements three category glyphs and Storage source drawers. Focus has an explicit owner: the game list releases its selection while the sidebar handles input, and hints change with that owner. The drawer measures its translated text, caps its width and keeps its vertical extent on screen. Icons and glow cells share an atlas. Font handles are loaded lazily rather than reloaded for each label. [Sidebar source, including focus and measured drawers][sidebar]

This is a concrete addition to the existing O10 sidebar family. It is also an economical implementation model for a RiptOPL theme component. A small component and a bounded focus state are sufficient to explore it; importing RIPPS2's whole launcher/tools shell is unnecessary.

Port checks still matter: the source measures names while drawing an open drawer, so this is not a claim of zero per-frame work. Cache measurements until the theme, font, language or visible sources change. Invalidate cached font handles when RiptOPL resets font slots. Preserve Coverflow/grid Left/Right behavior, RTL handling, long translated labels, CRT margins and Back/confirm-button policy.

### Legacy-theme contract and grid navigation

Build 113's `categories=three/storage` behavior makes old OPL themes opt out of the new bar and preserves their paging behavior. This is a useful compatibility contract **if** we add category navigation; RiptOPL does not need a replacement shell merely to gain that fallback. RIPPS2's Grid element provides a second implementation for O1, including two-axis movement and a fresh-press requirement before changing sources at a grid edge. Neither is counted as another independent grid capability. [Sidebar/legacy contract][sidebar] · [Grid source][grid]

### Single-pass HD presentation

The Build 75 mode table uses 640-wide framebuffers, GS magnification and one pass for 720p/1080i, with the GUI thread priority restored around mode initialization. Its host check explicitly checks the framebuffer budget. This is a real renderer design alternative, not evidence that RiptOPL lacks HD output. It trades horizontal raster resolution for reduced band/queue replay and framebuffer pressure. Measure text quality, frame time and VRAM on the intended display before adopting it. [Mode table and renderer changes][hd]

### Font and asset footprint

`b114` selectively registers FreeType modules and strips built-in fonts. It is a promising **build-footprint investigation**, with compatibility constraints: custom TrueType/CFF fonts, CJK fallback coverage, SDK-internal module symbols and glyph/style support must remain correct. Measure allocated text/rodata/data/BSS and peak heap with the same toolchain and assets. Do not use the compressed size of two different projects' ELFs as an efficiency comparison. [Selective font initialization][font-modules] · [Font-strip tool][font-strip]

Build 113's removal of embedded Ember and POPStarter reduces its own ELF and shifts responsibility to external launcher discovery. RiptOPL already supports external copies and intentionally supplies convenient fallbacks in its packages. A lean distribution is a packaging choice, not missing launch functionality. `b114`'s remembered typed-family paths are useful, but `usb:` is not a unique physical identity when two USB devices exist. Preserve unit/volume identity where required. [Released packaging change][changelog] · [Development resolver][resolver]

## Development-branch features: implemented, not yet the released package

| IDs | Mechanism in `b114` | What RiptOPL would need before adoption |
| --- | --- | --- |
| RI21 | Master `allgames.bin`, checked schema/checksum, waiting rows before sources answer, launch-time source resolution | Owned stable row records; duplicate-title/device handling; no borrowed row indices; correct invalidation and removal; cold-boot/launch tests. RI10's per-source snapshot is a different layer. |
| RI22 | Persistent per-device hidden titles and a Settings manager | Preserve raw game identity and source policy. Hidden is distinct from parental lock, unavailable devices and deletion. |
| RI23 | Associated-file cleanup, save choices and read-only APA table preflight | Shared-save ownership, valid real APA layouts, failure injection, interrupted operations and confirmation/rollback behavior. Six synthetic disk cases are not complete disk acceptance. |
| RI24 | On-console ISO↔ZSO, sequential staging, room checks, CRC read-back and a separate source-removal confirmation | Bounds for header alignment and buffer arithmetic, exclusive/job-owned temporary files, cancellation, short writes, rename/close errors and power-loss tests. Keep the original until verified output exists. ZSO selects the OPL core, not Neutrino. |
| RI25 | One background writer, launch latch and aligned write stages | Compare existing I/O ownership first. Imported guarded exFAT allocation is already RiptOPL work; avoid another polling layer or worker unless it solves a measured conflict. |
| RI26–RI27 | Named Color Sweeps with speed/delete controls and a configurable Hold-SELECT theme chooser | Optional appearance/interaction work. Preserve the existing theme picker, classic themes and input ownership. |

These mechanisms are present in the reconstructed development C source. They are not merely the proposals still visible on `main`, and they are not attributed to released Build 113. The branch's large patch also imports extensive shared upstream work; a 9 MB patch is not 9 MB of novel RIPPS2 functionality. [Development patch][games]

The compression path has a good source-preservation shape: create a new image, close and reread it, check per-run CRCs, rename it, then ask before deleting the source. This is worth retaining. It is not an unconditional safe-storage claim. Its unpack path uses the input header's alignment in buffer sizing, and temporary `.part`/`.idx` ownership needs explicit consideration before a port. Its alignment stage and image/check buffers also have a real heap cost. [Conversion entry point][compression]

## Other released lessons

Build 111 adds a PCM WAV input path, mono/rate conversion for audsrv, metadata-keyed sound-set reuse and settings-destination bootstrap handling that survives a competing memory-card configuration. Build 112 corrects which local BIOS piece is selected and fixes chooser text bounds. These are differentiated mechanisms; RiptOPL already has BGM, sound effects and custom settings paths. The appropriate comparison is input-format coverage, reload invalidation and config precedence, not “RiptOPL has no audio/settings.” [Build 111][audio] · [Build 112][music]

RiptOPL's new Language page does not provide RIPPS2's English-hash keyed language format or Arabic/Persian/Lao shaping. RI5/RI9 remain open. Conversely, our selectable RA suffix and smaller flat cover mark close H11. Our changes to raw row identity, CFG titles and hidden PS1 IDs must survive any visual port.

## Validation and recommended order

The inspected RIPPS2 HD-mode, grid and sidebar host checks passed against the reconstructed source. The Build 114 host check also passed, including compiled extracted C against six synthetic APA tables and master-list round-trip/damaged/short-file cases. One initial sidebar check lacked an atlas in the sparse inspection checkout; adding the exact pinned asset resolved that inspection setup issue. These are structural and bounded host checks. They are not target-build, emulator-image, console, game, save-durability or throughput acceptance.

For efficient RiptOPL work, the strongest sequence is:

1. Prototype the sidebar/focus/measurement contract as an optional theme component, retaining existing navigation and font lifetime handling.
2. Measure the FreeType and single-pass renderer alternatives on a controlled build; keep them only if the measured footprint/latency benefit justifies the compatibility tradeoff.
3. Consider persistent library caches with existing I/O/snapshot ownership, one source family at a time.
4. Treat compression, full cleanup and storage recovery as separate projects with failure-injection and console/save gates.
5. Coordinate matched i.LINK runtime tests and share the newer upstream repairs; do not promote argument-order or mass-slot assumptions into protocol fixes.

No code was ported and no console program was run for this documentation audit.

[ript]: https://github.com/NathanNeurotic/Open-PS2-Loader/tree/55261de1381ae70ecfdfb2054f9cafbcfcd586cf
[field-report]: https://github.com/akilluminati47/RIPPS2/blob/28bc44d0d3a31b084d6b7e55ff91745f9a09c026/docs/plans/builds-104-on.md#field-reports-that-shape-114-1022
[ilink-audit]: https://github.com/NathanNeurotic/Open-PS2-Loader/blob/55261de1381ae70ecfdfb2054f9cafbcfcd586cf/docs/ILINK_CODE_AUDIT_2026-10-22.md
[logo-research]: https://github.com/akilluminati47/RIPPS2/blob/28bc44d0d3a31b084d6b7e55ff91745f9a09c026/docs/plans/neutrino-ilink-logo.md
[logo-reversal]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0089-ripps2-build89-system-music-ripops-peek.patch
[sidebar]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0113-ripps2-sidebar.patch#L1706
[grid]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0078-ripps2-build78-grid-element-frosted-glass-towers-key.patch
[hd]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0075-ripps2-build75-one-pass-hd-early-boot-sound-neutrino-show-args.patch#L402
[font-modules]: https://github.com/akilluminati47/RIPPS2/blob/1d8888ed63c33aa45c27355cd61c966dd1f918eb/elf/patches/0114-ripps2-games.patch#L83719
[font-strip]: https://github.com/akilluminati47/RIPPS2/blob/1d8888ed63c33aa45c27355cd61c966dd1f918eb/elf/theme/tools/strip_fonts.py
[changelog]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/CHANGELOG.md
[resolver]: https://github.com/akilluminati47/RIPPS2/blob/1d8888ed63c33aa45c27355cd61c966dd1f918eb/elf/patches/0114-ripps2-games.patch#L90662
[games]: https://github.com/akilluminati47/RIPPS2/blob/1d8888ed63c33aa45c27355cd61c966dd1f918eb/elf/patches/0114-ripps2-games.patch
[compression]: https://github.com/akilluminati47/RIPPS2/blob/1d8888ed63c33aa45c27355cd61c966dd1f918eb/elf/patches/0114-ripps2-games.patch#L90197
[audio]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0111-ripps2-soundclean.patch
[music]: https://github.com/akilluminati47/RIPPS2/blob/9b876e6153e3d801c4fc18ce93f38229e319fd8f/elf/patches/0112-ripps2-menumusic.patch
