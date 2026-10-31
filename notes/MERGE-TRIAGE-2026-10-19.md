# Merge triage: rebuild/main first-parent merges since 2026-10-09

Read-only audit, 2026-10-19. Scope: `git log --first-parent --since=2026-10-09 origin/rebuild/main`, 74 commits,
from `e5071d13` (10-10) to `2eb0d376` (#999, 10-19). #898 and #899 merged on 10-09 but fall outside that walk; both
were folded into #894 anyway. Open PRs #1001 (autoload iLink wait), #1004 (IGR VBLANK) and #1005 (MMCE Ember
listing) are referenced but not audited here.

Method: PR bodies plus the production part of each diff. Sizes are changed lines (added + removed) from
`git diff --numstat M^1 M`. **prod** = everything outside tests, docs and CI. **test** = `tests/` and `test_*`.
**doc/ci** = `docs/`, `*.md`, `notes/`, CHANGELOG/CREDITS/README, plus `.github/` other than tests. Lines changed
under `lng*` are counted in prod.

"In-game" means the merge changes code that runs after the game starts: `ee_core`, `modules/iopcore`, `mcemu`,
`pademu`, `cdvdman`, or the in-game module list sent from `src/system.c`.

Evidence grades:
- **Reproduced**: a reported defect on hardware, or a test that fails on the old code for the reported symptom.
- **Source-proven**: a real code defect with a failing host test, but no user report it explains.
- **Speculative**: hardening against a failure nobody has reported, such as an out-of-memory path.

**HW** = console verification at merge time. Nearly everything is ZERO HW. The PR text says so in every case.

## Most damaging first

1. **IGR alarm sampler: #973 (Beta-4023), #990, and the IGR half of #999.** These moved IGR input sampling into an
   EE alarm callback. On Beta-4032 RE4 stopped answering. On Beta-4080 both the controller combo and the
   physical power button were dead in-game. That is the "IGR dead" report. The root, the Oct 5 priority-127
   polling thread (`2ef17713`), predates this window. **REVERT**, as #1004 does: VBLANK_END handler in every build,
   alarm code deleted. Keep the #999 Ember fix (item 3).

2. **#962 SIO2MAN (Beta-3981, 10-16): SDK SIO2MAN is now preloaded into every native game's IOP.**
   `sendIrxKernelRAM` packs `sio2man.irx` whenever `CORE_IRX_VMC` is set. `sysLaunchLoaderElf` sets that flag for
   every launch except disc and CF (`src/system.c:2467`). `ee_core` `ResetIopSpecial` then loads it
   unconditionally before the transport switch (`ee_core/src/iopmgr.c`, "Optional except for MX4SIO"). Before
   10-16 only MX4SIO games got it. So every USB/HDD/SMB/MMCE/iLink game now runs on the SDK SIO2 driver instead
   of the game's own. The game's later ROM SIO2MAN load finds the library already registered, so its PADMAN and
   MCMAN bind to ours.
   - The MMCE in-game driver `mmcedrv` drives SIO2 directly with no sio2man import
     (`.github/scripts/install_coherent_mmce.sh:21`). It now shares the bus with a second resident SIO2 driver
     loaded ahead of it.
   - This is the **prime suspect for the MMCE game that black-screens after the PS2 logo**. Not proven.
   - It is a port of upstream OPL #1785, merged upstream 10-05 with "I checked to make sure my submission worked"
     left unticked. No console test in either repo.
   - **REVERT the whole PR.** That restores the pre-10-16 in-game module set (SDK SIO2MAN only for MX4SIO) and the
     mcemu/pademu hook code that games had been running. A one-console A/B settles it: the same MMCE game on
     Beta-3980 against Beta-3981.
   - The sibling audit `notes/SIO2MAN-MMCE-AUDIT-2026-10-19.md` reaches the same verdict independently and gives
     the mechanism: the stock v2.1.1 `mmcedrv` hooks only the SDK's v1.2 table, and its SIO2 lock can hold forever.

3. **`0ab450a1` in #894 (Beta-3796, 10-10): `cueScanDir` treats end-of-listing as a read failure.**
   - On MMCE, `mmceman` returns -1 at the end of every listing. The Ember half of the PS1 list is then dropped,
     so no Ember games appear on MMCE.
   - It also breaks the art directory index on MMCE.
   - Fix is open as #1005 (sibling session).
   - On BDM, a regular file under `EMBER/games/` gave the same result through EIO. The second half of #999 fixes
     that (**KEEP**).

4. **#955 PC CARD CF/DVR (Beta-3988): HDD now aborts when DEV9 fails, before the HD Pro probe.**
   - `hddLoadModules` (`src/hddsupport.c:691`) now returns "HDD not connected" when `sysInitDev9()` returns 0.
     Before, it ignored the result and went on to `hddCheckHDProKit()`.
   - The comment right above it says DEV9 is "not required by the I/F (i.e. HDPro)". If `ps2dev9.irx` fails to
     stay resident on HD Pro Kit consoles, which have no SPEED chip, **HD Pro users lose the internal HDD**. That
     is plausible and unverified.
   - The rest of #955 is 1,931 production lines for a CF adapter that only fits early Japanese models. It adds a
     DEV9 bus lock to every `sysInitDev9`, a new cdvdman variant and a new game mode. It is off by default and
     inert when off.
   - **SIMPLIFY:** only return early when `sysIsPccfOwned()`, otherwise keep the old fall-through. Keep the
     feature gated off. Nobody has the hardware.

5. **#945 Favorites on a full memory card (10-15): the space-full in-place rewrite was removed.**
   #938 added a fallback: when staging `favourites.bin.new` fails with ENOSPC and the list fits in the clusters
   `favourites.bin` already holds, rewrite in place. #945 deleted it. On a full mc0, which is common, **every R3
   add or remove now fails** with "Could not … Favorites". This was speculative: no data-loss report. **SIMPLIFY:**
   restore #938's in-place fallback. Keep #945's VMC superblock check and RA chunk-header parser.

6. **#967 fade to black (10-16): adds 8 frames to every launch, exit and video-mode change.**
   That is about 133 ms NTSC or 160 ms PAL in `deinit`/`deinitEx`, on every game, ELF and exit. It is a new draw
   loop that runs right before GS teardown, and has no setting. The PR body says "CI and hardware acceptance
   pending … Leave unmerged", and it was merged. **REVERT** unless Nathan asked for it.

7. **#991 + #994 VMC (10-18/19): a custom-patched SDK `bdmfs_fatfs` is built inside CI.**
   - `install_safe_bdmfs.py` checks the stock walker's hash, patches FatFs (bounded walker, then `f_expand`) and
     rebuilds the IRX that RiptOPL embeds.
   - That makes it a build-time system: a ps2sdk image update that changes the hashed source fails the build.
   - #991's walker fix is only fault-injected. No user hit a FAT read error during a VMC check.
   - #994 does fix a real user-visible problem: newly created native cards were fragmented and then refused at
     launch.
   - New behaviour: native BDM card creation now fails outright ("VMC driver lacks safe contiguous creation") if
     the patched driver is missing. It also fails on a drive whose free space is fragmented.
   - **SIMPLIFY:** keep #994's reservation and drop #991's separate walker patch. Make the installer apply one
     patch without hash-pinning the SDK source.

8. **#977 PSBBN Flow theme (10-18): breaks the standing #733 hands-off rule.**
   It adapted #733's code and **closed #733**, a contributor's PR ([dnunezx](https://github.com/dnunezx), closed 2026-10-18 08:31Z). The
   standing rule from 10-07 says no merge, no closing, no comments on #733. The theme itself is inert unless
   selected: 171 lines in `themes.c`, one in `gui.c`. **Nathan's call:** revert and reopen #733, or keep it.

9. **#959 (10-16): Triangle (game settings) now reads the CFG synchronously on the GUI thread.**
   `gameMenuLoadConfig` → `menuLoadConfig` → `itemGetConfig`. Before, the read was deferred behind a loading
   indicator. On MMCE or SMB the menu stops responding for the length of the read. It fixed a reported
   Favorites+Triangle freeze, so **KEEP**, but watch for "menu hangs when I press Triangle" reports. The IGR asm
   and padhook half was kept on purpose per the #984 work.

10. **#980 (10-18): Left/Right page switches now take `menuSemaId` on the GUI thread.**
    `_menuLoadConfig`, the waiter variant on the I/O worker, holds that semaphore across a device read. A page
    switch during a waiter load blocks until the read ends. This is a source-only race fix with no report.
    Low impact: waiter loads are rarer since #959. **KEEP, watch.**

11. **#904 POPS UDPFS editor (10-11): a new subsystem.**
    It writes `IPCONFIG.DAT` and `UDPFSCONFIG.DAT` to every connected USB volume with staging, rollback and
    "all copies must agree" launch checks (98 to 114 host checks). The UDPFS serialization half is console-confirmed
    by the maintainer: **KEEP**. Favorites now defaults to **All**. **SIMPLIFY** the editor if it stays: one
    volume and a plain write.

12. **#947 DESR DVR (10-15).** 461 production lines plus 342 in `hddsupport.c`. No DESR owner has tested it. It
    was on by default for one day; #955 gated it off. **KEEP parked**, or remove for a leaner tree.

Everything else is a KEEP. RA work follows the standing parity rule. The rest is small, source-proven,
upstream-reported, or docs/CI.

## Autoload ~3 s slower: not in this window

The 3 s comes from `d8b50167`, "one-shot readiness probe for iLink boot discovery" (10-07, via #867). argv Auto
Loading force-enables iLink, and the I/O worker then sleeps 12 × 250 ms waiting for an absent iLink root.
`miniDeinit`'s drain waits on it. #1001 (open) skips that settle during Auto Loading. Nothing merged since 10-09
adds a comparable wait. In-window per-launch costs are smaller: #967 adds ~0.13–0.16 s, #962 adds one more IOP
module load.

## Defaults and behaviour changed without a setting

| Change | Merge |
|---|---|
| SDK SIO2MAN loaded in every native game's IOP | #962 |
| Fade to black on every launch/exit (no off switch) | #967 |
| Favorites page opens on **All** (apps + PS2 + PS1) | #904 |
| Fresh settings: 4:3 and Large artwork | #894 |
| Beat Down: Fists of Vengeance (4 IDs) → Mode 2 | #968 |
| Auto-VMC: if the format job hasn't finished, the game **stays in the menu** (was: launch without a card) | #938 |
| Resizing an existing VMC needs explicit Delete (one-click resize gone) | #909 |
| Full memory card: Favorites edits refused | #945 |
| Native BDM VMC creation requires contiguous free space; sizes 8/16/32/64 MB only | #994 |
| Neutrino budget overflow: drops one VMC slot after a prompt (was: native fallback) | #968/#970 |
| Parental lock re-arms after a settings save/remove (password users only) | #963/#966 |
| DVR discovery was on 10-15→10-16, now off by default | #947 → #955 |
| Reset-command failures are now returned to the game (was: forced success) | #911 |
| About: Financial Support section removed | #944 |
| Release titles: inceBtion / Korium / RetroAchievements; inceBtion forced Latest | #996, `78376273` |
| Bundled Neutrino = newest non-draft pre-release (today the same `latest` asset) | `7e8350bb` |
| New opt-in settings, default Off: CFG Titles (#932), PC CARD CF (#955), DESR DVR (#955), Caduceus cards (#916) | |
| New opt-in setting, default On (no change): Logo Artwork | #964 |

## Per-launch or per-boot I/O and delay added

| Cost | Merge |
|---|---|
| +1 IOP module (SDK SIO2MAN) on every game launch and every in-game IOP reset | #962 |
| +8 GS frames on every launch, exit and video-mode change | #967 |
| +1 superblock read per whole-MB VMC size probe (auto-VMC) | #945 |
| exFAT PS1 VCD launch: one `POPS/` directory listing when `MODULE_9.IRX` open returns FatFs `FR_NO_FILE` | #975 |
| Boot: up to 4 failed opens for `font_CJK`/`font_Japanese` `.ttf`/`.otf`, repeated if `_loadConfig` moves the settings home | #917 |
| Boot: one post-settle `xhdd0:` devctl when APA is off; PS1 scan retries (max 2) on the idle cadence | #894 |
| Every CFG read on each list rebuild **only when CFG Titles is on** | #932 |
| One gratuitous ARP before each UDPFS discovery broadcast | #921 |
| UDPFS VCD launch with "VCD BDMA Apply on Launch": memory-card driver equip | #904 |
| GUI thread waits on the CFG read when Triangle is pressed | #959 |
| Native VMC launch check: GET_LBA + GET_FRAGLIST replace GET_LBA + GET_CLUSTER + CHECK_CHAIN (about the same) | #989 |

## Per-merge table

Chronological. Size = prod / test / doc+ci. Beta numbers = `rev-list --count` + 2.

| # | Commit · PR · date | Claims to fix / adds | Evidence | User-visible change | Size | New system? | In-game? | HW | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `e5071d13` direct 10-10 | Ember Watch CI weekly | — | none | 0/0/5 | no | no | n/a | KEEP |
| 2 | `9e930bb6` #894 10-10 | USB PS1 RA, Caduceus, PS1 scan recovery, Favorites, IGR worker init, fresh defaults (198 commits) | Mixed. Vapor's Ember report unresolved | Many: PS1 RA, MODULE_9 prompts, fresh 4:3/Large art, power-button latch | 4989/2572/1750 | yes (POPS RA reader/sender, Caduceus) | yes: padhook, gsm (RA), POPS | none | KEEP RA; FIX `0ab450a1` scanner (#1005) |
| 3 | `b2fb7909` direct 10-10 | README sync | — | docs | 0/0/4 | no | no | n/a | KEEP |
| 4 | `a73fb2e4` #903 10-11 | Coverflow Favorites star alignment, remove toasts | Reproduced ([zackcage6](https://github.com/zackcage6)) | star position, remove toasts | 67/135/0 | no | no | none | KEEP |
| 5 | `e0add14b` #906 10-11 | RA snapshots under Mode 6 | Upstream alpha.17 proven | RA only | 48/70/19 | no | yes (RA) | none | KEEP |
| 6 | `1c328567` direct 10-11 | README sync | — | docs | 0/0/2 | no | no | n/a | KEEP |
| 7 | `906cdafe` #904 10-11 | UDPFS op serialization; Favorites default All; POPS UDPFS VCD + editor | UDPFS: maintainer console-confirmed. VCD path: none | Favorites opens on All; new POPS UDPFS settings page | 631/379/133 | yes (multi-volume transactional editor) | POPS driver pair | partial | KEEP fix; SIMPLIFY editor |
| 8 | `e26b481a` #908 10-11 | UDPFS BD stale ACK across 12-bit wrap | Source-proven | none | 21/22/8 | no | UDPFS IRX | none | KEEP |
| 9 | `c5d47515` #910 10-11 | Art cache OOM | Speculative | none | 45/85/2 | no | no | none | KEEP |
| 10 | `a695b907` #909 10-11 | Refuse implicit VMC resize; POPS UDPFS rollback | Speculative | Resize needs explicit Delete | 43/126/15 | no | no | none | KEEP |
| 11 | `679582de` #907 10-11 | Preserve unreadable VMC images; PES IGR notes | Speculative | New dialog on unreadable VMC | 33/53/79 | no | no | none | KEEP |
| 12 | `9432539d` #912 10-11 | Menu allocation guards | Speculative | none | 48/176/2 | no | no | none | KEEP |
| 13 | `aba13495` #913 10-11 | One UDPFS transport source | Refactor | none | 4407 (moved)/43/22 | no | UDPFS IRX (same code) | none | KEEP |
| 14 | `0ffa41f2` #914 10-11 | Queue snapshot under lock (function has no callers); submenu `prev` link | Source-proven | none | 18/117/2 | no | no | none | KEEP |
| 15 | `5183f85e` #915 10-11 | BDM slot on private alloc failure | Speculative | none | 42/151/2 | no | no | none | KEEP |
| 16 | `19028f35` #911 10-12 | Bound IOP reset args; DMA to 0; return failure to game | Source-proven | Failed resets now reported to the game | 87/259/4 | no | **yes** (asm.S, syshook, iopmgr) | none | KEEP, watch |
| 17 | `078f0243` #917 10-12 | CJK glyph fallback font | Feature | Optional font | 75/142/108 | no | no | none | KEEP |
| 18 | `58132c38` #920 10-12 | Wiki publish workflow | — | docs (removed by #928) | 0/0/85 | yes, then removed | no | n/a | KEEP (net zero) |
| 19 | `6d04b40e` #921 10-12 | UDPFS reconnect seq reset, stale ACK wait, ARP announce | Tests fail on old code; reported loop | UDPFS no longer loops discovery | 173/391/15 | no | UDPFS IRX | none | KEEP |
| 20 | `1d22923c` #916 10-12 | ORBIT RA Neutrino; rolling-ra channel | Feature (Nathan-reviewed) | RA release channel | 320/791/1380 | yes (release channel) | RA overlay | none | KEEP |
| 21 | `9d910fc0` #922 10-12 | RA NIC reserve, DEV9 gate for UDP, IP clash notice | Tests fail on old code | IP-clash notice | 196/253/37 | no | UDPFS IRX | none | KEEP |
| 22 | `5c06e1b7` #923 10-13 | Neutrino RA parity (chains, Caduceus) | Feature | RA only | 24/23/19 | no | no | none | KEEP |
| 23 | `90566eb8` #925 10-13 | docs-sync stages all pages | Reproduced (live site stale) | site | 0/15/7 | no | no | n/a | KEEP |
| 24 | `a0ca55c5` #926 10-13 | Xerabora achievement browser | Feature | RA only | 591/261/8 | no | no | none | KEEP |
| 25 | `d9b4df66` #927 10-13 | RA support check over UDPFS (`mstack:`) | Feature | RA only | 530/638/831 | yes (`mstack:` IOP device) | UDPFS IRX | none | KEEP |
| 26 | `0e0e9c37` #928 10-13 | Remove duplicate wiki publisher | Reproduced (flip-flop) | none | 0/0/100 | removes one | no | n/a | KEEP |
| 27 | `ebb62e1d` #929 10-13 | `mstack:` follow-ups | Review findings | RA notices | 58/58/2 | no | UDPFS IRX | none | KEEP |
| 28 | `1bfc9770` #931 10-13 | MEGA upload timeout | Reproduced (stalled release) | none | 0/20/8 | no | no | n/a | KEEP |
| 29 | `81e606f5` #930 10-13 | RA HTTPS game ID (mbedTLS); ps2ips DNS fix | Feature; DNS bug source-proven | RA only, ~93 KB zipped | 205846 (vendored)/773/78 | yes (TLS) | no | none | KEEP (standing TLS rule) |
| 30 | `dea980ef` #932 10-13 | CFG Titles in lists | Feature (#918) | Opt-in, default Off | 381/209/14 | no | no | none | KEEP |
| 31 | `6ba163f7` #938 10-13 | Auto-VMC only real cards; Favorites never truncate | Reported (#935, #936) | Game stays in menu while job runs; new notices | 234/497/4 | small (staged write) | no | none | KEEP |
| 32 | `ddbe37c3` #939 10-13 | genvmc lifecycle (#934) | Tests fail on old code (12) | none | 162/299/2 | no | genvmc IRX (menu) | none | KEEP |
| 33 | `fb00066f` #940 10-13 | Odd-size Neutrino VMC; PC-edited Favorites; Favorites speed | Regression from #938 | Favorites ~285 → ~12 calls | 175/174/0 | no | no | none | KEEP |
| 34 | `0614894d` direct 10-14 | Credits (in-program) | — | About text | 2/0/0 | no | no | n/a | KEEP |
| 35 | `f5f567fa` direct 10-14 | Credits | — | docs | 0/0/2 | no | no | n/a | KEEP |
| 36 | `2fcc8bbf` direct 10-14 | Credits | — | docs | 0/0/2 | no | no | n/a | KEEP |
| 37 | `2cd2b966` #944 10-14 | About layout | Display overflow | **Financial Support section removed** | 19/0/0 | no | no | none | KEEP (confirm removal was wanted) |
| 38 | `6a3f12f2` #942 10-14 | FREEZEDIAG flavour (`RIPTFRZ.TXT`) | Diagnostic | Diagnostic flavour only | 1056/377/54 | yes (flavour, IOP module) | yes, all `#ifdef INGAMEDIAG` | none | KEEP (gated) |
| 39 | `c5800e4f` direct 10-14 | RE4 report notes | — | docs | 0/0/42 | no | no | n/a | KEEP |
| 40 | `634f2dd2` #945 10-15 | Favorites durability; VMC superblock; RA binary chunks | Speculative; RA parse source-proven | **Full card: Favorites edits fail** | 57/65/10 | no | no | none | **SIMPLIFY** (restore fallback) |
| 41 | `bda9de23` #953 10-15 | Defaults docs | Reported doc mismatch | docs | 0/0/60 | no | no | n/a | KEEP |
| 42 | `d0f4e64b` #951 10-15 | IGR pad-buffer lifetime across IOP reset | Source-proven; RE4 candidate | none intended | 41/75/37 | no | **yes** (padhook, syshook) | none | KEEP (per #984 work) |
| 43 | `0f2b5e69` #952 10-15 | Coverflow L1/R1 animation (#949) | Reported | Page keys animate | 7/57/2 | no | no | none | KEEP |
| 44 | `c32348e7` #947 10-15 | DESR DVR ISO discovery + Neutrino | Feature | HDD list on DESR; off since #955 | 461/179/86 | yes | no | none | KEEP parked |
| 45 | `2b838e09` #959 10-16 | IGR asm `$gp`/flush, keep `padOpen_hooked`; Favorites Triangle freeze | Reported (Discord) | Triangle reads CFG synchronously | 223/235/0 | no | **yes** (asm.S, padhook) | none | KEEP |
| 46 | `2ee8292c` #964 10-16 | Hide/show `_LGO` art | Request (eliminator) | New toggle, default On | 39/47/11 (+46 lng) | no | no | none | KEEP |
| 47 | `ad43082f` #962 10-16 | VMC/PADEMU hooks across SIO2MAN versions (upstream #1785) | Speculative ("may improve") | **SDK SIO2MAN in every game IOP** | 227/139/13 | no | **yes** (iopmgr, mcemu, pademu, module list) | none | **REVERT** |
| 48 | `06864626` #963 10-16 | Per-game parental lock (upstream #1779) | Feature | New per-game toggle; prompts | 196/132/15 | no | no | none | KEEP |
| 49 | `8a477379` #966 10-16 | Parental lock fail-closed | Review findings | none | 80/52/0 | no | no | none | KEEP |
| 50 | `33ab3fe4` #967 10-16 | Fade handoffs to black | Feature (PR said leave unmerged) | **+8 frames every launch/exit** | 50/0/0 | no | no | none | **REVERT** |
| 51 | `4e88737a` #960 10-16 | Masked pattern scanner overread | Source-proven | none | 5/60/0 | no | **yes** (util.c) | none | KEEP |
| 52 | `cb4da858` #961 10-16 | Config null deref on alloc failure | Speculative | none | 55/160/4 | no | no | none | KEEP |
| 53 | `6e22d874` direct 10-16 | GAME_SAVE_CHANGES on null `itemConfig` | Source-proven | none | 2/2/0 | no | no | none | KEEP |
| 54 | `2bb6624c` #955 10-17 | PC CARD CF backend; DVR toggle; DEV9 ownership | Feature | 2 new Game Sources toggles; **HDD aborts if DEV9 fails** | 1931/599/146 (+12 lng) | **yes** (CF driver, bus lock, cdvdman variant, game mode) | yes (CF variant; shared `modmgr` start result) | none | **SIMPLIFY** (HDD early return) |
| 55 | `7e8350bb` direct 10-16 | Neutrino newest pre-release tag; cheat docs | — | Same `latest` today | 0/0/42 | no | no | n/a | KEEP |
| 56 | `0c55c6cb` #968 10-17 | Neutrino VMC budget prompt; Beat Down Mode 2 (#830, #831) | Reported | Prompt drops VMC; Mode 2 default for 4 IDs | 109/146/8 | no | no | none | KEEP |
| 57 | `b1f070d1` #970 10-17 | Reuse config in VMC resolver; drop one slot | Review findings (fixes #968 config leak) | Drops only one slot | 36/175/0 | no | no | none | KEEP |
| 58 | `eab6c37c` #971 10-17 | Settings save under low memory | Reported (cause unproven) | none | 160/305/2 | no | no | none | KEEP |
| 59 | `26f0c1fd` #973 10-18 | IGR sampling in alarm callback | Source-only; **made IGR worse on HW** | **IGR + power button dead in-game** | 123/284/19 | yes (alarm sampler) | **yes** (padhook) | none at merge; failed after | **REVERT** (#1004) |
| 60 | `b35ff38c` #975 10-18 | False RA module warning on exFAT (#974) | Reported | Warning gone | 36/48/0 | no | no | none | KEEP |
| 61 | `3cd7f89c` #977 10-18 | PSBBN Flow built-in theme (from #733) | Feature | New theme | 329/253/199 | renderer | no | none | **Nathan's call** (#733 rule) |
| 62 | `0ecf0963` #981 10-18 | DVR preflight rejects `-bsd` overrides (#976) | Source-proven | DVR only | 9/100/5 (+4 lng) | no | no | none | KEEP |
| 63 | `45382771` #980 10-18 | Tab selection under `menuSemaId` (#978) | Source-only | none (possible stall) | 21/117/2 | no | no | none | KEEP, watch |
| 64 | `0acfb235` #989 10-18 | Native VMC extent validation, accurate messages (#986) | Source-proven | Clearer VMC messages | 105/160/4 (+7 lng) | no | no | none | KEEP |
| 65 | `895d4b76` #990 10-18 | IGR request semaphore | Source-proven race in a broken design | none | 25/132/5 | adds to #973 | **yes** (padhook) | none | **REVERT** (#1004) |
| 66 | `989633df` #983 10-19 | Neutrino shared-fragment message | Reported (#830) | Message text | 2/38/2 (+3 lng) | no | no | none | KEEP |
| 67 | `db614310` #991 10-19 | Patched SDK FAT walker in shipped BDM IRX | Fault-injected only | none | 10/194/360 | **yes** (CI-patched SDK driver, hash gates) | no (menu IRX) | none | **SIMPLIFY** |
| 68 | `eedd342b` #992 10-19 | Logo check accepts fd 0 (#988) | Source-proven | Logo may show where it didn't | 2/82/2 | no | no | none | KEEP |
| 69 | `9dc31c54` #993 10-19 | iLink BDMA size table (#982) | Source-proven | iLink VCD driver check passes | 2/68/2 | no | no | none | KEEP |
| 70 | `78376273` direct 10-19 | Release titles, Latest enforcement | — | Release page titles | 0/37/40 | no | no | n/a | KEEP |
| 71 | `0bef301d` #995 10-19 | ZSO probe fd 0 | Source-proven | none | 11/61/4 | no | no | none | KEEP |
| 72 | `7988eff5` #994 10-19 | Contiguous native BDM VMC creation (#986) | Real problem (fragmented new cards) | Creation can fail on fragmented free space | 152/447/91 | builds on #991 | genvmc (menu) | none | KEEP (with #991 SIMPLIFY) |
| 73 | `38c2d96f` #998 10-19 | Docs refresh; wiki builder moved into source tree | Docs | docs/wiki ownership | 0/42/2085 | yes (docs-check workflow, in-tree wiki builder) | no | n/a | **Nathan's call** (wiki is owned by `riptopl-wiki/_tools/build.py`) |
| 74 | `2eb0d376` #999 10-19 | IGR interrupt-side suspension; Ember EIO skip | IGR source-only; Ember reproduced on FatFs images | IGR still dead; Ember lists on BDM | 40/501/176 | no | **yes** (padhook, freeze_diag) | none | **Split:** IGR REVERT (#1004), Ember KEEP |

## Notes for whoever acts on this

- **Undo order.** #1004 already removes the alarm IGR (rows 59, 65, 74 IGR). Next: revert #962 in full. Then
  #967. Then two small edits: restore the #945 Favorites fallback, and in #955 make `hddLoadModules` return early
  only when `sysIsPccfOwned()`. None of these touch another row's files except `src/system.c`. #962 and #955 both
  edit `sendIrxKernelRAM`, but different lines.
- **Bisect builds** (Beta = `rev-list --count` + 2):
  - #962: Beta-3980 (`2ee8292c`) vs Beta-3981 (`ad43082f`).
  - #955: Beta-3988.
  - #973: Beta-4023.
  - `0ab450a1`: Beta-3796.
- **Reviewer process.** Codex/ChatGPT PRs from 10-14 onward merged with "CodeRabbit rate limited, no approval
  claimed" and "Leave unmerged pending CI/HW" in their own text (#962, #963, #955, #967, #971). Nobody read the
  merged result end to end. The fix series around #986/#830 took six PRs (#968, #970, #983, #989, #991, #994) for
  one VMC topic.
