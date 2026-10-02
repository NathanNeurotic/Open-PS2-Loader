# Community reports handoff — October 2, 2026

This handoff collects the RiptOPL reports from TwistedZeon, FifthFox,
eliminator1403, and Aislinn. It is a triage and implementation guide, not a
claim that the reported behavior has been reproduced or fixed. The screenshot
supplied later in the conversation adds one concrete artwork comparison:
**3248 loaded artwork normally; Beta 3420 Korium loads it slowly**, according
to eliminator1403. The build numbers have not yet been mapped to exact commits
or release assets.

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
| E1 | TwistedZeon wants per-game Ember `settings.txt` written from the menu, without launching the game. | An uncommitted implementation makes confirming **Ember Game Settings** save it immediately. The focused host test passed on October 2. | Console behavior and slow/failed writes on each supported device. |
| I1 | FifthFox's iLink drive sometimes needs a recent drive reboot to launch PS2 ISOs. After reformatting a drive previously used on a Mac, exFAT was visible but still would not launch PS2 games after reboot; FAT32 worked better in that setup. A later Seagate drive and PS2 logo enabled successful Jak and Daxter launch with four compatibility modes. | These are tester observations, not isolated causes. | Exact build, drive/enclosure, partition scheme, filesystem, four modes, console, game ID, and results with one variable changed at a time. |
| I2 | FifthFox reports "Neutrino (MC) runs via iLink" with PS2 logo and a custom argument. | This is a valuable new console success report. | Whether "MC" means the Neutrino ELF location, exact ELF/ISO locations and argument bytes, Neutrino version, persistence across cold boots and multiple titles. |
| I3 | FifthFox asks whether freeing memory before launch or using a lighter interface would improve iLink reliability. | Launch teardown already stops art requests and releases menu resources before handoff. | Whether remaining EE/IOP memory, drive readiness, or timing causes the failures. |
| V1 | TwistedZeon reports that a PAL game is "flipping" on an NTSC interlaced CRT under Neutrino and explicitly asks for 480i. | The new 5.27-second clip shows the Neutrino Video picker on the CRT, but no game output. RiptOPL offers Off, 240p, 480p, and 1080i modes; upstream documents no forced NTSC 480i mode. | Exact game, cable/CRT, what "flipping" looks like during gameplay (roll, field shake, or periodic loss), and whether native OPL-core GSM works for that title. |
| A1 | eliminator1403 reports slow art in Beta 3420 Korium and names 3248 as the last good build. | Recent art scheduling and built-in background changes exist; the most suspicious September 26 priority feature was rolled back September 27. | Exact release commits, same-device A/B timings, source type, theme, art settings, and whether the slowdown affects PS1, PS2, or both. |
| P1 | Aislinn wants a useful error when PS1 prerequisites are missing. | Launch paths already show several missing POPSTARTER/Ember/BIOS messages; missing Ember core can remove Ember rows at scan time. | Which missing item and path produced the reported lack of guidance, and whether the title was a VCD or Ember folder. |
| P2 | Aislinn mistook PS1 007 entries for PS2 titles without cover art, then could not open the expected PS2 game/VMC menu. | PS1 rows intentionally open a different Triangle menu, without PS2 per-game VMC options. | Which list mode/theme/view made the row's PS1 identity unclear, and what save-card workflow the tester expected. |

## E1 — Save Ember per-game settings before launch

The current uncommitted work already implements the requested behavior.
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

Treat the new successes as confirmed *for the reported console/configuration*
and do not generalize them to all iLink drives, POPSTARTER, or exFAT.

## V1 — PAL game on an NTSC interlaced CRT with Neutrino

`src/gui.c:2067` and `src/gui.c:2969` list RiptOPL's Neutrino video choices.
`src/system.c:1684` emits `-gsm=fp1`, `fp2`, or `1080ix1..3`; the optional
`:1..3` half is field-flip compatibility, not a PAL-to-NTSC standard switch.
The official Neutrino README describes unforced output as 480i/576i and its
forced low-resolution modes as automatically PAL/NTSC. Do not add a menu label
for NTSC 480i without upstream support for such an argument.

In the later screenshot, TwistedZeon explicitly says **"No 480i"** and
clarifies: **"I'm trying to play a pal game on ntsc but the video is
flipping."** The attached 5.27-second video at
`C:\Users\natha\Downloads\PXL_20261002_181340020.TS.mp4` shows the RiptOPL
Neutrino Video picker being cycled on a CRT. It does **not** show the game's
output, so it cannot establish the visual failure mode or prove that a field
flip setting would fix it. `1080i` is interlaced, but it is HDTV timing rather
than the standard-definition 480i/576i signal their CRT needs. The available
`240p` and `480p` choices do not supply a forced NTSC 480i mode.

First determine whether "flipping" means vertical roll due to 50 Hz/PAL on
an NTSC-only CRT, or field shake with an otherwise visible signal. The former
needs an NTSC-rate interlaced output; the latter may be the documented
compatibility field. If the game works under RiptOPL's native OPL core, its
GSM picker includes interlaced **NTSC** (`src/guigame.c:455`,
`src/gsm.c:108`); have the tester try that as a targeted workaround. A CRT
that cannot sync to 480p should not be asked to test 480p/1080i as a fix.

## A1 — Slow cover art in 3420 versus 3248

The earlier screenshot supplies the missing comparison: eliminator1403 called **3248**
the last good version and **Beta 3420 Korium** slow. It does not supply the
device, theme, art files, whether backgrounds are enabled, or timings. Verify
release asset/Actions provenance before treating those numbers as exact source
revisions.
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

## Suggested implementation sequence and completion gates

1. **Resolve evidence first.** Map 3248 and Beta 3420 to permanent commits,
   exact Actions runs and assets; collect the art A/B and iLink matrix. Capture
   Aislinn's source/view/theme and the missing PS1 prerequisite. This step
   can proceed without editing source.
2. **Finish E1 as its own narrow change.** Review the existing dirty patch,
   correct demonstrated failure paths, run its host test and a representative
   build, then request console checks on writable Ember devices. Do not
   overwrite or commit unrelated dirty work.
3. **Address P1/P2 as a UI and guidance change.** Use row identity already in
   the menu/view model; add only the messages the reproduced flows require.
   Keep POPSTARTER and Ember contracts separate. Validate without cover art.
4. **Fix A1 only after timing isolates a cause.** Compare the confirmed
   3248/3420 source delta and make the smallest scheduling, lookup, or theme
   change supported by the HUD and console A/B. Do not reinstall a broad
   priority system just because covers feel slow.
5. **Investigate I1/I2 and V1 separately.** Preserve the successful iLink
   combinations as test cases; add a readiness delay only if controlled tests
   isolate timing and a measurable condition or bounded wait. Treat Neutrino
   CRT output as an upstream-capability question; validate the native OPL GSM
   workaround where compatible.

For every code change: inspect the exact diff and `git diff --check`, use a
focused behavior test when the behavior can be host-tested, build the relevant
PS2 flavor(s), and hand a specific Actions/preview ELF to console testers.
Record real-console results by build hash, device, game, mode, and result.
Do not close a hardware report from source or CI evidence alone.
