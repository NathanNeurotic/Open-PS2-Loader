# Community reports handoff — October 2, 2026

This handoff collects the RiptOPL reports from TwistedZeon, FifthFox,
eliminator1403, Aislinn, and zackcage6. It is a triage and implementation
guide, not a claim that the reported behavior has been reproduced or fixed.
The [artwork comparison screenshot](./community-report-evidence/2026-10-02/art-last-good-3248.png)
adds one concrete artwork comparison:
**3248 loaded artwork normally; Beta 3420 Korium loads it slowly**, according
to eliminator1403. Beta 3420 Korium now has release and tag provenance below.
Build 3248 still lacks the tester's exact ELF or archive, so its matching
commit-count candidate is not a proven asset mapping.

## Preserved report evidence

These are the original user-provided captures, kept with this handoff so their
temporary local paths are not required:

- [Art version comparison and attached ELF message](./community-report-evidence/2026-10-02/art-last-good-3248.png)
- [Neutrino picker and 480i request](./community-report-evidence/2026-10-02/neutrino-480i-picker.png)
- [Neutrino picker clip](./community-report-evidence/2026-10-02/neutrino-picker-clip.mp4)
- [CRT font report](./community-report-evidence/2026-10-02/crt-font-report.png)
- [Default video and field-flip compatibility follow-up](./community-report-evidence/2026-10-02/neutrino-default-field-flip.png)
- [October 3 iLink/Neutrino follow-up](./community-report-evidence/2026-10-03/ilink-neutrino-followup.png)

The clip records the menu interaction, not the game's rolling/flipping output.

## Implementation checkpoint

Draft PR [#825](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/825)
contains four separate, pushed commits for immediate per-game Ember settings
saves and no-art PS1 identification/save-card guidance. Its focused host checks
and GitHub format/build workflows passed at commit `8126c058`; real-console
testing is still required. The original dirty `migrate/riptopl-korium`
checkout was preserved. This document remains the report and evidence ledger;
PR #825 records exactly which fixes were committed and which were withheld.

## Working rules and current checkout

- Repository: `NathanNeurotic/Open-PS2-Loader`. The separately named
  `NathanNeurotic/RiptOPL` repository is a future migration destination, not
  an interchangeable source for this work.
- Current checkout at handoff: `migrate/riptopl-korium`, HEAD `0afa4962`.
  It has pre-existing edits in Ember settings, launch support, release/docs
  files, an untracked `docs/DOCUMENTATION_AUDIT_HANDOFF.md`, and an untracked
  `worktrees-temp/` directory. Preserve them. Recheck `git status`, refs,
  remotes, and release provenance before changing anything. Use an isolated
  worktree for source work that would overlap these edits.
- The user prefers a concrete plan and approval before source implementation.
  Keep fixes causal and small. Do not add a delay, queue, retry, or new launch
  machinery solely because a tester found one working configuration.
- Host tests, builds, and CI are not physical-console passes. Do not run PCSX2
  locally as a substitute. The user tests Actions or preview `BOOT.ELF` builds
  on real hardware.
- Source paths and line numbers below identify this checkout snapshot. Recheck
  them after changing refs. A `gh release list --repo
  NathanNeurotic/Open-PS2-Loader` read returned `401 Unauthorized` during this
  triage, so no current release-to-commit mapping was established.

## Report ledger

| ID | Report and desired outcome | What is established | What remains unknown |
| --- | --- | --- | --- |
| E1 | TwistedZeon wants per-game Ember `settings.txt` written from the menu, without launching the game. | PR #825 commits the immediate-save implementation; focused host tests and CI builds passed. | Console behavior and slow/failed writes on each supported device. |
| I1 | FifthFox's iLink drive sometimes needs a recent drive reboot to launch PS2 ISOs. After reformatting a drive previously used on a Mac, exFAT was visible but still would not launch PS2 games after reboot; FAT32 worked better in that setup. A later Seagate drive and PS2 logo enabled successful Jak and Daxter launch with four compatibility modes. | These are tester observations, not isolated causes. | Exact build, drive/enclosure, partition scheme, filesystem, four modes, console, game ID, and results with one variable changed at a time. |
| I2 | FifthFox initially reported "Neutrino (MC) runs via iLink" with PS2 logo and a custom argument, but on October 3 said they **cannot repeat** that success. They suspect the logo must run after compatibility modes to slow a drive/enclosure handshake. | This is an intermittent result, not a stable working combination. The source appends auto compatibility modes before auto `-logo`, but that ordering does not prove a timing cause. | Exact build, Neutrino ELF/ISO locations and version, full stored/effective args, whether `-logo` reached Neutrino, cold-start repetitions, and measured iLink readiness. |
| I3 | FifthFox tried a custom text-only theme to keep memory available but did not gain a repeatable launch; an AI suggested disabling Coverflow, and FifthFox could not find an option. Native OPL launches with individual modes seem robust in their tests. | Launch teardown already stops art requests and releases menu resources. Coverflow is theme-defined; the built-in `<OPL>` theme is an alternate view. | Active theme, its declared elements, memory measurements before/after teardown, and controlled same-game native/Neutrino comparisons. |
| I4 | FifthFox says RiptOPL removes `-logo` from custom Neutrino arguments, sees two logo controls in launcher settings but none in the game menu, and wants the full effective Neutrino argv visible per game. | Current source has a per-game **Neutrino Launch Args → Logo** toggle and passes global/per-game active `-logo` tokens to its argv builder; iLink is not in the automatic logo-suppression list. User-supplied tail arguments may be dropped if the 256-byte launch pool is full. | Which field was edited, the saved `$NeutrinoArgs`/global `neutrino_args` values, whether the UI merely moved `-logo` from Extra to its checkbox, and the final argv on the tester's build. |
| V1 | TwistedZeon reports that a PAL game is "flipping" on an NTSC interlaced CRT under Neutrino and explicitly asks for 480i. | The clip shows the video picker, not game output. A later screenshot confirms the field-flip picker is disabled while Video is Default. Upstream parses `-gsm=:1` but does not enable GSM without a forced video mode; it exposes no forced NTSC 480i. | Exact game, cable/CRT, what "flipping" looks like during gameplay (roll, field shake, or periodic loss), and whether native OPL-core GSM works for that title. |
| T1 | zackcage6 says the font in the pictured RiptOPL settings view looks "sluggish" and is hard to read on the CRT; they suggest changing the font or rendering it for interlace. | The main RiptOPL interface already offers NTSC/PAL interlaced `FLICKER-FREE` modes, and themes can load alternate fonts. Neither has been tested for this report. | Exact build, theme/font, interface video mode, CRT/cable, whether "sluggish" means visual flicker/blur or slow UI response, and whether the alternate mode improves legibility. |
| A1 | eliminator1403 reports slow art in Beta 3420 Korium and names 3248 as the last good build. | The current Beta 3420 Korium release names source `1a663941`; `f83e6f9f` is a version-3248 commit-count candidate with different art scheduling, but its tester ELF is unverified. | Exact 3248 asset/hash, same-device A/B timings, source type, theme, art settings, and whether the slowdown affects PS1, PS2, or both. |
| P1 | Aislinn wants a useful error when PS1 prerequisites are missing. | Launch paths already show several missing POPSTARTER/Ember/BIOS messages; missing Ember core can remove Ember rows at scan time. | Which missing item and path produced the reported lack of guidance, and whether the title was a VCD or Ember folder. |
| P2 | Aislinn mistook PS1 007 entries for PS2 titles without cover art, then could not open the expected PS2 game/VMC menu. | PS1 rows intentionally open a different Triangle menu. PR #825 adds a PS1 row label and save-card guidance there. | Console legibility in each theme/view and what save-card workflow the tester expected. |

## E1 — Save Ember per-game settings before launch

At this document's original checkout snapshot, the implementation was
uncommitted; its focused source changes are now committed in PR #825.
`src/gui.c:3489` confirms the Ember per-game editor; `src/menusys.c:608`
routes its save through the selected support's `itemSaveCueSettings` callback;
`src/cuesupport.c:507` updates only managed per-game keys in
`EMBER/games/<Name>/settings.txt`. The callbacks cover BDM, SMB, APA/PFS HDD,
MMCE, UDPFS, and Favorites delegation; review each before a completeness
claim. Confirming an unchanged dialog also requests the file save, while no
managed keys should leave the file untouched. Launch still reapplies managed
settings. The global `EMBER/settings.txt` is a separate changed-only path.

The October 2 run of `python .github/scripts/test_ember_settings.py` passed its
host checks, including explicit per-game save, path selection, preservation of
unmanaged lines, and a simulated failed write. `git diff --check` also passed
on the dirty checkout. Neither exercises actual device latency or a console.

Review risks before shipping:

1. A successful CFG save followed by a failed Ember file write leaves the
   menu's CFG value ahead of the file until the next launch. The UI must report
   this accurately, and the next attempt must recover.
2. `menuSaveEmberGameSettings()` currently calls device I/O after drawing a
   saving screen. Confirm it cannot stall input for an unacceptable time on
   SMB, UDPFS, MMCE, or a waking disk. Reuse existing deferred I/O if evidence
   requires it; avoid inventing a new worker.
3. Check writable game-folder and APA mount behavior, Default-key removal,
   no-op save, short write/restore, and hand-written unknown lines on hardware.

The requested user outcome is a saved per-game file after confirming the
existing menu. A separate **Save** row is unnecessary unless testers find
confirming the dialog unclear.

## I1/I2 — iLink native and Neutrino launch reliability

FifthFox reported an initial need to reboot the drive before native PS2 games
would launch, and suggested an internal-HDD-like delay as a possible remedy.
The drive had been reformatted from Mac use for PC use; exFAT exposed its
contents to RiptOPL, yet even rebooting did not make PS2 games launch in that
configuration. FAT32 worked better in the reported setup. FifthFox suspected
exFAT driver memory use, but supplied no memory measurement; the earlier drive
also made unusual mechanical noises, and the later Seagate swap changes the
hardware under test. They also observed
Ember titles appearing promptly while PS2 titles populated later; that
ordering alone does not establish a memory shortage or a failed PS2 scan.
Turning off all artwork and using RiptOPL modes 1, 3, and 6 allowed
Madagascar to launch without repowering in one test. That suggests the native
OPL core, because mode 6 is disabled under Neutrino (`src/guigame.c:1164`),
but confirm the core
with the tester. In this source those modes mean Accurate Reads, Unhook
Syscalls, and Disable IGR respectively
(`include/iosupport.h:94`); none by itself demonstrates a drive spin-up fix.
Later, Jak and Daxter:
The Precursor Legacy launched without a drive reboot with **four unspecified
modes plus PS2 logo** after a Seagate drive swap. A separate report says
"Neutrino (MC) runs via iLink" with PS2 logo; do not assume which file was on
the memory card until the tester confirms it. The screenshot renders its custom
argument as `-=gc136`; get the exact bytes rather than silently correcting or
copying that string. Neutrino's documented grammar is `-gc=<digits>` and its
documented compatibility modes are 0, 1, 2, 3, 5, and 7; its mode 1 is labeled
"dummy" and it does not document mode 6. RiptOPL's native OPL mode numbers
do not have identical meanings. Source: `src/system.c:1234` and the official
Neutrino README at <https://github.com/ps2max32/neutrino>.

**October 3 correction:** FifthFox [could not repeat the Neutrino/iLink
success](./community-report-evidence/2026-10-03/ilink-neutrino-followup.png).
They now suspect the PS2 logo must be triggered after compatibility modes to
give their enclosure time to handshake. They say RiptOPL removes `-logo` from
custom arguments, that two launcher-menu locations expose logo controls but
their custom game menu does not, and that seeing the full effective Neutrino
arguments in the game menu would help. Their text-only theme experiment did not
make the launch repeatable. They also report native OPL launches with individual
modes as relatively robust. None of this isolates a memory or timing cause.

At the current PR #825 source, the per-game Compatibility dialog has a
**Neutrino Launch Args** button (`src/guigame.c:1256`) whose structured
sub-screen has a **Logo** checkbox (`src/dialogs.c:1856`); the global launcher
menu has its own PS2 Logo setting and Neutrino args editor. The parser moves a
typed `-logo` into that checkbox and reassembles the stored args with `-logo`
(`src/supportbase.c:2202-2261`). Thus a token disappearing from the **Extra**
field alone would not show that it was removed from the saved or launched args.
The iLink backend passes the global logo preference to Neutrino and is not in
`sysLaunchNeutrino()`'s automatic logo-suppression list. Auto-generated `-gc`
precedes auto-generated `-logo`, and global then per-game user tokens come
after those (`src/system.c:1660-1747`). Command-line order does not by itself
establish the order or duration of Neutrino's later boot operations. The
256-byte argv pool check may drop
tail user tokens, including a typed per-game `-logo`, without on-screen notice
(`src/system.c:1753-1772`). These are source possibilities, not a diagnosis of
FifthFox's build. Obtain their saved config and final argv before changing
argument order or promising that the logo delay fixes the drive handshake.

Do not infer that FAT32 is universally required for iLink or that exFAT fails
because of memory. Neutrino documents FAT32 and exFAT for block devices;
FifthFox's result could depend on the bridge, enclosure, spin-up state, driver
handoff, fragmentation, or mode combination. Likewise, PS2 logo may add
helpful time, but the report does not prove a fixed delay would reproduce it.

The native BDM and Neutrino paths differ. `src/bdmsupport.c:2054` passes
`gPS2Logo` to Neutrino's `-logo`; the native path does its own logo check and
loader handoff around `src/bdmsupport.c:2320`. `src/opl.c:4460` and
`src/texcache.c:644` already shut down art work during teardown. `deinitEx()`
also has a bounded I/O/art drain and then calls `guiEnd`, `thmEnd`, and `rmEnd`
(`src/opl.c:4460`). Its source comments report a previously measured
multi-second handoff pause. Measure the actual iLink readiness and memory
state before adding another wait or extra cleanup. A simple/low-art theme is
a diagnostic configuration, not an established memory fix.

Minimum tester matrix, on one known-good drive/enclosure and one ISO:

1. Record console model, iLink bridge and drive model, partition scheme
   (MBR/GPT), filesystem, build/ELF hash, game ID, loader core, Neutrino
   version/location, and exact arguments. Separate "device and games list are
   readable" from "ISO launches" in each result.
2. Try cold-drive and recently-rebooted-drive launches with the same settings.
3. Change only PS2 logo; then change one compatibility mode at a time. Repeat
   successful combinations after a full console and drive cold start.
4. Only then compare the original drive or exFAT. A second game distinguishes
   a title-specific mode requirement from transport readiness.
5. If a console diagnostic build is needed, log the iLink device and partition
   state at handoff; prefer that evidence over a blind sleep.

Treat the native launches as individual tester observations; the earlier
Neutrino success is now explicitly **unrepeatable**. Do not generalize any of
them to all iLink drives, POPSTARTER, or exFAT.

## V1 — PAL game on an NTSC interlaced CRT with Neutrino

`src/gui.c:2067` and `src/gui.c:2969` list RiptOPL's Neutrino video choices.
`src/system.c:1684` emits `-gsm=fp1`, `fp2`, or `1080ix1..3`; the optional
`:1..3` half is field-flip compatibility, not a PAL-to-NTSC standard switch.
The official Neutrino README describes unforced output as 480i/576i and its
forced low-resolution modes as automatically PAL/NTSC. Do not add a menu label
for NTSC 480i without upstream support for such an argument.

In the [picker screenshot](./community-report-evidence/2026-10-02/neutrino-480i-picker.png), TwistedZeon explicitly says **"No 480i"** and
clarifies: **"I'm trying to play a pal game on ntsc but the video is
flipping."** The preserved [5.27-second video](./community-report-evidence/2026-10-02/neutrino-picker-clip.mp4) shows the RiptOPL
Neutrino Video picker being cycled on a CRT. It does **not** show the game's
output, so it cannot establish the visual failure mode or prove that a field
flip setting would fix it. `1080i` is interlaced, but it is HDTV timing rather
than the standard-definition 480i/576i signal their CRT needs. The available
`240p` and `480p` choices do not supply a forced NTSC 480i mode.

The October 2 [follow-up screenshot](./community-report-evidence/2026-10-02/neutrino-default-field-flip.png)
adds a concrete UI reproduction. TwistedZeon
said that leaving **Neutrino Video** on **Default** disables **Neutrino GSM
Compatibility**, so they cannot select a field-flipping type without changing
video mode; they checked again and confirmed this. darkladark said Luna selects
`fp2` (480p/576p) when compatibility is enabled from Default. This is a report
about Luna's behavior, not a tested fix for TwistedZeon's interlaced CRT.

The dependency is deeper than RiptOPL's greyed picker. Neutrino's loader parser
accepts an empty video component with a compatibility value, such as
`-gsm=:1`, but its EE core calls `EnableGSM()` only when `GsmVideoMode` is not
`NONE`. As a result, enabling RiptOPL's picker and emitting `-gsm=:1` would
store a setting that parses yet does not activate the field-flipping hook in
the inspected upstream commit. RiptOPL currently emits the compatibility
component only with a forced video mode. Source references:
[parser](https://github.com/ps2max32/neutrino/blob/7be8de2798c99af433c91993e021746a54d6800d/ee/loader/src/main.c#L215-L274),
[GSM enable gate](https://github.com/ps2max32/neutrino/blob/7be8de2798c99af433c91993e021746a54d6800d/ee/ee_core/src/main.c#L82-L90),
and [field-flipping hook](https://github.com/ps2max32/neutrino/blob/7be8de2798c99af433c91993e021746a54d6800d/ee/ee_core/src/gsm_api.c#L647-L690).
Confirm the exact Neutrino ELF version in the tester's setup before extending
this conclusion to that build. Forcing `fp2` selects progressive 480p/576p,
which may be unusable on the reported CRT. Do not silently select it from
Default. The issue remains open pending a game-output clip or another upstream
method for interlaced field-flip compatibility without forced progressive mode.

First determine whether "flipping" means vertical roll due to 50 Hz/PAL on
an NTSC-only CRT, or field shake with an otherwise visible signal. The former
needs an NTSC-rate interlaced output; the latter may be the documented
compatibility field. If the game works under RiptOPL's native OPL core, its
GSM picker includes interlaced **NTSC** (`src/guigame.c:455`,
`src/gsm.c:108`); have the tester try that as a targeted workaround. A CRT
that cannot sync to 480p should not be asked to test 480p/1080i as a fix.

## T1 — CRT font legibility and perceived sluggishness

In the [font report screenshot](./community-report-evidence/2026-10-02/crt-font-report.png), zackcage6 describes the **font** in the pictured
settings view as "sluggish + not easily view-able" and asks whether the font
should change or be rendered for interlace. The screenshot shows text on a CRT,
but does not identify the build, theme, selected RiptOPL interface video mode,
connection, or whether "sluggish" refers to motion/response time versus
flicker, ghosting, or soft glyph edges. Keep this report separate from
TwistedZeon's PAL-game output problem; a menu font change cannot establish a
Neutrino PAL-to-NTSC fix.

The **Interface → Video Mode** picker already exposes NTSC/PAL 640-wide
interlaced `FLICKER-FREE` entries (`src/gui.c:2839`), distinct from the
per-game **Neutrino Video** picker. In this checkout they use `GS_FRAME` with
the same interlaced CRT timing as the corresponding `GS_FIELD` modes
(`src/renderman.c:65-82`). The source notes reduced line flicker on thin text
at the cost of half the framebuffer's vertical detail; it may improve or
worsen perceived sharpness on this CRT. The built-in Korium theme uses the
embedded default font, while folder themes can select a font file and size
(`misc/conf_theme_OPL.cfg:17`, `src/themes.c:3359-3382`).

For a controlled console comparison, record the current interface mode,
theme/font, cable, display model, and build. Photograph or film the same
settings page with standard NTSC 640x448i and `FLICKER-FREE` NTSC 640x448i,
holding camera exposure/shutter and theme constant. Compare static legibility
and actual navigation response separately; only then try an alternate font or
size if the video mode does not solve the reported issue. Do not assume
Neutrino's per-game `-gsm` setting changes RiptOPL menu text rendering.

## A1 — Slow cover art in 3420 versus 3248

The [artwork screenshot](./community-report-evidence/2026-10-02/art-last-good-3248.png)
supplies the comparison: eliminator1403 called **3248**
the last good version and **Beta 3420 Korium** slow. It does not supply the
device, theme, art files, whether backgrounds are enabled, or timings.

The Makefile computes a normal revision as `git rev-list --count HEAD + 2`.
The Korium release workflow instead pins that number to its last common
`rebuild/main` commit. As checked on October 2, the
[rolling-korium release](https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling-korium)
lists `RIPTOPL-DEBUG-v1.2.0-Beta-3420-Korium.zip` and names source
[`1a663941`](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/1a6639410beaf8dd9c5505be0f470fd5f5a60259).
The moving `rolling-korium` tag points to that commit; its merge base with
`rebuild/main` is `65d4b89a` (commit count 3418, hence revision 3420).
This establishes the **current published** Beta 3420 source, but the tester's
downloaded ELF has not been hashed against the release asset.

[`f83e6f9f`](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/f83e6f9f6166015dbdecb8b6f024c988daf58b1b)
has commit count 3246 and thus could display revision **3248** on its branch.
It is the PR #770 tip, not a proven match for the tester's 3248 ELF. That code
has a separate priority tier for the selected cover, icon and background, and
pre-requests small images before the large background. The successful
[PR #770 build-flavours run](https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/36293060322)
for head `f83e6f9f` still has six unexpired artifacts as of October 2. The
`OPL-OFFICIALROLLING` artifact is ID `10923036654` (ZIP SHA-256
`9632905c6ee207f49f71a05a922594575ec8c15c08921266b8e6694a22d58872`),
with an October 11 expiry reported by GitHub. The workflow's default PR
checkout uses GitHub's merge ref, so this artifact may have a different
revision number and source tree from a direct `f83e6f9f` build. It is useful
for investigating that art implementation, not a confirmed 3248 binary or
proof that it matches eliminator1403's last-good ELF.
The later
[`68405e23`](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/68405e2392d3bb6606f46863365cb0f1f844784b)
rollback removed that tier and restored front-of-queue promotion/background
admission after **other** testers reported late or out-of-order art. Beta 3420
contains the rollback and subsequent background-cancellation fix. A slower
cover relative to this candidate is plausible, but the rollback was itself a
response to a regression. Do not reapply PR #770 wholesale without the exact
3248 asset and same-device timing evidence.
The later screenshot also shows eliminator1403 uploading a 1.41 MB
`RIPTOPL.ELF` at 11:00 AM, but its bytes and build identity were not supplied.
Do not assume that attachment is build 3248, Beta 3420, or a confirmed fix.

Relevant source history in this branch:

- September 16: `6057c6c2` added per-game `BG` art to the built-in main list,
  gated by **Background Art**. That setting defaults off (`src/opl.c:4797`),
  but a user's saved value may turn it on. Large background PNGs can occupy
  the single art worker ahead of a cover. See `misc/conf_theme_OPL.cfg:27`.
- September 26: `7273b222` introduced a new priority tier for COV/ICO/BG.
  The source-backed late/out-of-order mechanism was older requests retaining
  priority ahead of a new selection, plus a removed Coverflow BG admission
  gate. September 27 commit `68405e23` rolled that feature back. Do not blame
  the reverted algorithm without verifying that a specific shipped build
  predates the rollback.
- September 27: `96fc1d6d` broadened stale-background cancellation across
  BG cache slots. It intends to reduce waiting behind obsolete backgrounds.
- Later commits in this checkout changed theme layout/discovery, but a review
  of `src/texcache.c`, `src/textures.c`, and `src/artindex.c` history found no
  newer cover read/decode rewrite that itself proves this report's cause.

Use the same storage, game, art files, theme, view, and build flavor for the
3248/3420 A/B. First compare Background Art off/on; then Disc Art and ART.TAR
if enabled. **Interface → Artwork Settings** exposes these controls and Art
Delay (`src/gui.c:2186`); default Art Delay is zero, so a saved nonzero value
should be recorded. The existing **Settings → Advanced → Debug** HUD at
`src/gui.c:4292` reports `Q/A/D/X`, last load `ms`, last successful `ok ms`
and decoded dimensions, staged-open times `O:`, error counts, and art-index
hits. A slow `O:` miss points to directory lookup; small opens but large
`ok ms` point to read/decode cost; growing queues with low completions point
to scheduling or contention. Do not call any of these the cause until the
same-device A/B shows it.

## P1/P2 — PS1 prerequisites, row identity, and memory-card guidance

Aislinn mistook PS1 007 entries for PS2 games when covers were absent, tried
to assign every game a VMC, and found that the expected PS2 Game Settings menu
would not open. In their list, the PS1 007 titles appeared before the PS2
titles; they only recognized the boundary after the failed boot/menu attempt.
That ordering is an observation about their setup, not a guaranteed sort rule
for every view. The observed menu behavior is consistent with current routing:
`src/opl.c:668` sends a PS1 row's Triangle action to
`menuInitVcdMenu()`, while PS2 rows open `menuInitGameMenu()`.
`src/menusys.c:729` currently offers global PS emulation settings, Ember
per-game settings only for Ember rows, and Rename. It deliberately omits
PS2-only VMC, GSM, and compatibility controls. This is an understandable UI
misread, not proof that the PS2 Game Settings handler failed.

The three save-card paths must stay distinct:

- PS2 games: RiptOPL's Game Settings can assign a PS2 VMC.
- Ember PS1 folders: Ember creates/uses `MC1.vmc` and `MC2.vmc` inside the
  game's folder on writable media, generally on first launch. These are not
  the PS2 VMC picker (`README.md:361` and
  `docs/EMBER-INTEGRATION-PLAN.md:726`).
- POPSTARTER VCD rows: do not promise the PS2 VMC picker or invent an Ember
  `MC1.vmc` rule. Check POPSTARTER's actual memory-card behavior and the
  installed build before writing user-facing guidance.

The maintainer's reply was that this sounded like a need for better on-screen
guidance and possibly settings fixes. Treat "settings fixes" as a follow-up
question, not a diagnosed defect: determine whether Aislinn wants a clear
explanation of automatic PS1 save cards, a way to prepare them before first
launch, or a different PS1 menu action. Do not route PS1 titles through the
PS2 VMC editor merely to make a familiar menu appear.

Missing-prerequisite messages already exist *at launch* in several backends:
`_STR_POPSTARTER_NOT_FOUND`, `_STR_EMBER_NOT_FOUND`,
`_STR_EMBER_BIOS_MISSING`, and `_STR_EMBER_NO_DISC` are used in
`src/bdmsupport.c`, `src/ethsupport.c`, `src/hddsupport.c`, and
`src/mmcesupport.c`; UDPFS is Ember-only. At scan time,
`src/cuesupport.c:182` skips Ember rows when `ember.elf` is unreadable,
so a missing core may appear as an empty/partial PS1 library instead of a
launch error. Preserve the valid POPSTARTER half of the library when Ember
is absent. Identify which prerequisite Aislinn lacked before changing the
notification path.

Presentation work to plan after reproducing the no-art case:

1. Show a persistent **PS1** identity on a selected PS1 row or its list,
   including Mixed and Favorites views, without needing cover art or a new
   device lookup. The existing PS1 jewel-case/disc defaults in
   `misc/conf_theme_OPL.cfg:118` help visually, but Aislinn's report shows
   they were insufficient in the tested context. Base the label on row kind,
   not only the page, because mixed views contain both PS1 and PS2 rows.
2. On the PS1 Triangle menu, explain why PS2 VMC settings are absent and
   where this core stores saves. Keep the actionable Ember settings item.
   Avoid a dead PS2 VMC menu on a PS1 row.
3. For missing components, prefer one precise message at the attempted
   operation, naming the missing core/BIOS/path and the supported setup.
   Avoid repeated boot or scan popups for a deliberately unused PS1 core.

Test no-cover PS1 and PS2 rows in Both, Mixed, PS1-only, and Favorites views;
test VCD and Ember rows separately; test missing POPSTARTER, missing
`ember.elf`, missing `bios.bin`, and an unreadable device separately. Check
localization and that normal PS2 Game Settings/VMC behavior is unchanged.

The first two presentation actions above are implemented in PR #825. They
remain unverified on a console; the missing-component case lacks the reported
file/path and was deliberately left without a speculative code change.

## Suggested implementation sequence and completion gates

1. **Resolve remaining evidence.** Obtain the tester's exact 3248 ELF/archive
   hash to confirm its source, then collect the same-device art A/B and iLink
   matrix. Beta 3420's current published source and a PR #770 merge-build
   artifact are recorded above; neither identifies the tester's 3248 binary.
   Capture Aislinn's source/view/theme and the missing PS1 prerequisite.
2. **Console-check E1 and P2.** PR #825 commits the narrow Ember save and PS1
   row/menu guidance changes, with host checks and CI builds passed. Validate
   pre-launch writes, Default behavior and failures on writable Ember devices;
   inspect no-cover PS1 and PS2 rows in each view and theme on a real console.
   Preserve the original dirty checkout and keep POPSTARTER and Ember tests
   distinct.
3. **Reproduce P1 before changing its error path.** Identify which PS1 core,
   file, and path were missing and whether the user saw a VCD or Ember folder.
   Add only the guidance that the reproduced flow lacks.
4. **Fix A1 only after timing isolates a cause.** Compare the confirmed
   3248/3420 source delta and make the smallest scheduling, lookup, or theme
   change supported by the HUD and console A/B. Do not reinstall a broad
   priority system just because covers feel slow.
5. **Investigate I1/I2 and V1 separately.** Preserve the successful iLink
   combinations as test cases; add a readiness delay only if controlled tests
   isolate timing and a measurable condition or bounded wait. Treat Neutrino
   CRT output as an upstream-capability question; validate the native OPL GSM
   workaround where compatible.
6. **Check T1 on the reported CRT.** Compare the existing main-interface
   interlaced modes and measure UI response before changing glyph assets or
   rendering. Keep Neutrino game-video settings out of this menu-font test.

For every code change: inspect the exact diff and `git diff --check`, use a
focused behavior test when the behavior can be host-tested, build the relevant
PS2 flavor(s), and hand a specific Actions/preview ELF to console testers.
Record real-console results by build hash, device, game, mode, and result.
Do not close a hardware report from source or CI evidence alone.
