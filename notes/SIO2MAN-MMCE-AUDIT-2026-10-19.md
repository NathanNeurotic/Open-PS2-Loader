# SIO2MAN / MMCE in-game audit — 2026-10-19

Read-only audit. No code changed, nothing committed. Checked out: `fix/igr-vblank-sampler-984` @ 22804855 (PR #1004 head).
ZERO HW: every conclusion below comes from reading source, binaries' build logs and CI logs. Nothing here was run on a console.

## Verdict (short)

**PR #962 (ad43082f, merged 2026-10-16) is the most likely cause of the MMCE black screen.** It loads PS2SDK's
`sio2man.irx` into the game IOP for every mode except DISC and CF, MMCE included, *before* `mmcedrv`. Our in-game
`mmcedrv.irx` is deliberately the **stock ps2-mmce v2.1.1** prebuilt, whose SIO2 lock was written for the *game's own*
SIO2MAN. Paired with the SDK sio2man it can hold its lock forever. The next CD read through `mmcedrv` then blocks, and the
game never gets past the black screen. Upstream OPL has the same sio2man load but **no in-game MMCE mode**, so nobody
upstream ever ran this combination.

Pairing rule that explains both this report and the July failure (#56/#68):

| in-game SIO2MAN | mmcedrv | result |
|---|---|---|
| game's own (rom0 SIO2MAN / XSIO2MAN) | stock v2.1.1 | field-proven (everything before Oct 16) |
| **SDK sio2man (since #962)** | **stock v2.1.1** | **mismatched lock → can deadlock (this report)** |
| game's own | rebuilt from MMCE_PIN db3e93f0 | lock is a no-op → bus contention (July HW failure on PS2DEVLATESTSDK) |
| SDK sio2man | rebuilt from MMCE_PIN db3e93f0 | what the new hook was designed for; never built or tested here |

## 1. PR #962 vs upstream #1785 (e87ba689 + 7af5fdbe)

### Load order (same as upstream)
- `ee_core/src/iopmgr.c:215` loads `OPL_MODULE_ID_SIO2MAN` unconditionally, before the per-mode `switch`. Upstream does the same.
  For `MMCE_MODE` the switch then loads `OPL_MODULE_ID_MMCEDRV` (`iopmgr.c:263-264`), so the SDK sio2man is already resident when mmcedrv starts.
- `src/system.c:948` packs `sio2man_irx` when `modules & (CORE_IRX_MX4SIO | CORE_IRX_VMC)` or PADEMU is on.
  `CORE_IRX_VMC` is set for every mode except DISC_MODE and BDM_CF_MODE (`system.c:2466-2467`). Upstream sets it unconditionally.
  **So every MMCE, HDD, USB, SMB, iLink and UDPBD game has loaded the SDK sio2man in-game since Oct 16**, whether or not VMC or PADEMU is used.
- `sio2man_irx` is `$(PS2SDK)/iop/irx/freesio2.irx` (`Makefile:1150`), an alt name of the SDK sio2man.

### Behavioural differences vs upstream master (SIO2-relevant only)
1. **iopmgr.c**: we keep the SIO2MAN load result and start MX4SIOBD only if it loaded (`sio2manLoaded > 0`). Upstream starts MX4SIOBD regardless.
   We also have `MMCE_MODE`, `HTTP_MODE`, `BDM_CF_MODE` and RA `DISC_MODE` cases that upstream does not have. **The MMCE case is the one that matters here.**
2. **system.c**: same packing condition as upstream. The entry sits after iLink and before MX4SIO instead of before USBD. That only changes table order;
   ee_core loads modules by ID, so it has no runtime effect.
3. **mcemu.c** (beyond upstream):
   - Re-install guard: `InstallSio2manHook` returns early if export #25 already points at our own wrapper. This stops a hook being saved as its own original.
   - Hooks export **#24** (`mc_transfer_init`) with `hookSio2McInit_{1,2}`, which records `sio2TransferVersion` after the matching init takes the lock. Upstream only reads #24.
   - `Sio2McEmu(sd, ver)` unlocks and relocks with the **caller's** table version (`sio2McUnlock(ver)` / `sio2McLock(ver)`).
     Upstream always prefers the v2 functions (`psio2_transfer_reset[1] ? … : [0]`).
     On the SDK sio2man this matters: the v1.2 table's #24 is `sio2_mc_transfer_init_possiblysdk13x`, which sets the SDK-1.3 auto-reset flag, and the v2 one does not.
     Ours re-arms the flag the caller set. Upstream clears it, so an old MCMAN's next transfer would not auto-reset and the SDK semaphore would leak (an upstream risk we do not have).
   - DMA path (`hookDmac_request`) records `temp_packet_version = sio2TransferVersion` when the SIO2-in DMA starts, and passes it to `Sio2McEmu`.
   - Not from #962: `MMCE_DRIVER` variant (`mmce_mcemu.irx`, device-mmce.c), SMB `fname[80]`.
4. **pademu.c**: the same re-install guard as mcemu. Comment fixes only.
5. `mcemu_sys.c`, `mcemu_var.c` and `pademu/sys_utils.c` are identical to upstream master.

### Is SDK sio2man first safe?
What the SDK sio2man does (ps2sdk `iop/sio/sio2man/src/sio2man.c`, unchanged since 2026-05-24):
- It registers **two** libraries named `sio2man`, v2.7 and v1.2 (`_exp_sio2man1.name[7]=0`). The game's own `rom0:SIO2MAN` (1.1) or IOPRP/rom0 `XSIO2MAN` (1.2) then fails
  `RegisterLibraryEntries`. The game's PADMAN/MCMAN link to the SDK tables instead.
- There is a single `m_transfer_semaphore`. In the v1.2 table, entries #23/#24 are the `*_possiblysdk13x` inits.
  They set `m_sdk13x_curflag` (totalflag starts at 3), and `sio2_transfer` then calls `sio2_transfer_reset()` **internally**, not through the export table.

**MMCE_MODE: not safe with our stock mmcedrv.** The v2.1.1 `sio2man_hook.c` (in `mmceman/src`, linked into mmcedrv):
- If `sio2man` is already loaded, it takes the "already loaded" branch. `ioplib_getByName` walks from `let_next`, so it finds the most recently registered table (the v1.2 one).
  It hooks only that table, and **does not install the loadcore `RegisterLibraryEntries` hook**. The v2.7 table is never hooked.
- Its lock is its own `lock_sema`. The hooked transfer_init does `WaitSema(lock_sema)`, and only the *exported* #26/#50 reset does `SignalSema(lock_sema)`.
  mmcedrv's own reads take the same `lock_sema` (`sio2man_hook_sio2_lock`).
- With the SDK v1.2 table, an SDK-1.3-style PADMAN/MCMAN calls init (#23/#24) and transfer (#25). The SDK auto-resets inside `sio2_transfer`, so the exported reset is never called.
  **`lock_sema` is never signalled. The game's next pad/MC init and mmcedrv's next CD read both block forever.**
  Before #962 the same game had a genuine `rom0:SIO2MAN` 1.1, which v2.1.1 refuses to hook (`lib->version > IRX_VER(1,1)` only), so there was no lock and no deadlock.
- XPADMAN/XMCMAN-style modules call the exported reset, so mmcedrv's lock survives them.
  But with the auto-reset flag set, the SDK semaphore can be signalled twice (`sio2_transfer` internal reset plus the explicit reset), which weakens the SDK's own pad/MC exclusion.
  Whether that hurts depends on whether the module calls `sio2_mtap_change_slot` first (that clears the flag). Not determinable without HW.
- The fixed hook (mmceman db3e93f0, cccc366) is designed for exactly this world. It hooks both tables (`g_hook_data[2]`), but only versions 1.2 and 2.7.
  It filters the MMCE port in `sio2_transfer`, and locks through the SDK v2 table's `pad_transfer_init`/`transfer_reset`, i.e. the single SDK semaphore.
  **Without the SDK v2.7 table its lock is a no-op.** That explains why the July rebuilt mmcedrv failed in-game, when no SDK sio2man was loaded in-game.

**Games whose IOPRP/rom0 loads XSIO2MAN (non-MMCE):** the game's XSIO2MAN no longer stays resident, and its X-modules run on the SDK v1.2 table. This is upstream's design ([uyjulian](https://github.com/uyjulian)).
The double-signal risk above applies to every mode, not just MMCE. Upstream has the same exposure. It is unverified on our side.

**PADEMU:** pademu hooks #25/#49/#51 on both SDK tables (via the existing scan and the loadcore hook) and dispatches to the saved originals. That is safe on its own and matches upstream.
On an MMCE game it loads *after* mmcedrv (`iopmgr.c:378-385`), so it saves mmcedrv's wrappers as its "originals". Both chains then run, and the deadlock above applies equally.
mcemu loads after mmcedrv too (`iopmgr.c:371-376`). If VMC is active it calls `psio2_transfer_reset[ver]`, which may be mmcedrv's wrapper.

### Which ps2sdk sio2man the rolling images ship
- Container digests from the job logs (`Digest:` line):

  | flavour | ≤ 2026-10-12 22:16 UTC | ≥ 2026-10-13 09:53 UTC (incl. PR #1004 run 39307587341) |
  |---|---|---|
  | OFFICIALROLLING (`ps2homebrew:main`) | sha256:8de60681… | sha256:f92b5260… |
  | PS2DEVROLLING (`ps2dev:latest`) | sha256:2729b842… | sha256:5476fdfb… |

  Both images rolled once, overnight Oct 12→13. They have not changed since, so every build from Oct 13 to PR #1004 uses the same SDK.
- ps2sdk commits in that window: only #939 (`erl` id names, EE side). The sio2man source (`iop/sio/sio2man`) was last changed on 2026-05-24 (a move refactor).
  The `exports.tab` was last changed on 2025-03-29. **The sio2man exports did not change around Oct 13.** The export layout is v2.7 + v1.2, as described above.
- Stock `mmcedrv.irx` is **11337 bytes** and `mmceigr.irx` is 1369 bytes in every rolling and pinned job checked (Oct 9, 13, 15, 16, 18, 19). Same size as the field-proven July binary.

## 2. In-game MMCE driver pipeline

- `OPL_MODULE_ID_MMCEDRV` ← `$(MMCE_ASSETS_DIR)/mmcedrv.irx` (`Makefile:621`), with `MMCE_ASSETS_DIR = $(PS2SDK)/iop/irx`.
  That is the container's **stock ps2sdk-ports prebuilt (ps2-mmce v2.1.1, 979dd77e)**. `install_coherent_mmce.sh` rebuilds only `mmceman.irx`, from `MMCE_PIN=db3e93f0`, and
  explicitly keeps the stock `mmcedrv`/`mmceigr`.
- `mmce_cdvdman.irx` is built from our `modules/iopcore/cdvdman` with `USE_MMCE=1` (`Makefile:660-661`). `mmce_mcemu.irx` is built from `modules/mcemu` with `USE_MMCE=1` (`Makefile:744-745`).
- **No changes since Oct 9** to `install_coherent_mmce.sh`, `.github/patches/mmceman-*.patch` (last 2026-08-19), the `MMCE_PIN`, or the Makefile's MMCE rules.
  The Oct 18 patch work (`ad73d8c0`, `472811d5`, …) is `bdmfs-*` / `install_safe_bdmfs.py`, which is BDM only.
- All three existing patches, and PR #1005's new `mmceman-fs-dread-eof.patch` (open, not merged), modify **`mmceman/src/mmce_fs.c` only**. mmcedrv does not link `mmce_fs.o`
  (its objects are `exports ioplib sio2man_hook mmce_sio2 imports mmcedrv`). **No patch touches the in-game driver.** PR #1005 cannot affect in-game MMCE.
- ⚠ **The install script's justification is wrong.** It says mmcedrv's source is "UNCHANGED between the v2.1.1 pin and MMCE_PIN (`git diff v2.1.1..db3e93f0 -- mmcedrv` is empty)".
  That diff only covers the `mmcedrv/` directory, which holds just the Makefile. The sources live in `mmceman/src/`.
  Between 979dd77e and db3e93f0, cccc366 rewrote `sio2man_hook.c` (+231/−211), `mmce_sio2.c`, `ioplib.c` and `mmcedrv.c`, all of which mmcedrv links.
  The July "rebuilt mmcedrv fails, stock works" result is real, but the reason is the pairing rule above, not toolchain noise.
- The ps2-mmce OPL fork (local ref `ps2mmce/mmce_support` e5547968, 2025-11-24, may be stale) loads MMCEDRV in-game **without** any SIO2MAN.

## 3. Symptom: MMCE game shows the PS2 logo, then black screen forever (PR #1004 build, standard flavour)

The logo appearing proves that the first OPL reset, cdvdman and mmcedrv read the image correctly at that point.
The PS2LOGO stage does not touch pads or memory cards, so a SIO2 lock problem would not show there.
The failure starts after the game's own IOP reset, when it loads PADMAN/MCMAN and starts pad/MC transfers alongside CD reads.

Ranked:

1. **mmcedrv v2.1.1 lock deadlock on the SDK sio2man (introduced by #962).** Mechanism in §1.
   Confirm it with any one of these:
   - **Build pair:** `2ee8292c` (last commit before #962, run 38926619721) vs `ad43082f` (run 38954278717), same flavour and same game.
     If 2ee8292c boots and ad43082f black-screens, that confirms it. Artifacts expire about Oct 30.
   - **Game dependence:** early/SDK-1.3-era titles (old rom0 PADMAN/MCMAN, no IOPRP X-modules) should hang every time. Titles shipping XSIO2MAN/XPADMAN may boot.
   - **One-line diagnostic build:** skip `LoadOPLModule(OPL_MODULE_ID_SIO2MAN…)` when `config->GameMode == MMCE_MODE` (or drop the SIO2MAN entry when `CORE_IRX_MMCE`). If the game boots, that confirms it.
   - **OFFICIALROLLING-FREEZEDIAG:** if IGR still fires, `RIPTFRZ.TXT` should show the game's pad/MC thread and the cdvdman read thread both blocked on a semaphore.
2. **SDK auto-reset double-signal / pad-MC collision on the SDK v1.2 table (all modes, upstream design).** Not MMCE-specific.
   The same game from USB or HDD on the same build would also misbehave, more likely as a pad/save hang than a black screen. Confirm by booting the same title from USB.
3. **Unhooked SDK v2.7 table.** v2.1.1 hooks only one table and drops its loadcore hook in the already-loaded path.
   Any IOP module bound to `sio2man` 2.x would transfer without mmcedrv's lock and collide with MMCE reads (corrupt reads, a hang).
   Few game modules import 2.x. More plausible on rom1/DVD-player-era IOPRPs. Confirmed by the same build pair, plus a title whose IOPRP ships SIO2MAN ≥ 2.0.
4. **Oct 11 ee_core reset-path guards** (`8971a595`, `6693d5e5`, `d4f91ac3`, `d71111c1`, `7f6222d9`). These cover all modes and can abort the game's own IOP reset (e.g. an oversized or odd reset packet).
   That would black-screen on USB/HDD too. Confirm by booting the same title from another device on the same build. To isolate it, test a build from `a73fb2e4` (Oct 11 04:22, before them) against one after.
5. **Toolchain or image roll on Oct 13.** Unlikely: the sio2man source and exports are unchanged, stock mmcedrv is the same size, and it would not single out MMCE.
   Confirm by comparing OFFICIALPINNED (digest a1b1f87f, Aug 13) with OFFICIALROLLING at the same commit. If both black-screen, the toolchain is excluded.
6. **PADEMU or VMC on the MMCE game** (if enabled for that title): extra hook layers over mmcedrv's wrappers, with the same deadlock as #1 plus mcemu calling a wrapped reset.
   Confirm with PADEMU and VMC off for the title.

## Fix direction (not done here)
- Minimal, restores the field-proven pair: do not load the SDK sio2man in-game for `MMCE_MODE`.
  Gate it in `iopmgr.c` and/or skip it in `system.c` when `CORE_IRX_MMCE`. PADEMU on MMCE then falls back to the pre-#962 loadcore-hook path, as before Oct 16.
  The IGR bootcard path (`padhook.c:448`) reloads MMCEDRV after a clean reset without the SDK sio2man, so it is unaffected.
- Alternative: ship mmcedrv rebuilt from db3e93f0 **only together with** the SDK sio2man in-game. It has never been tested in that combination. Needs HW.
- Also fix the incorrect "mmcedrv source unchanged" claim in `install_coherent_mmce.sh`.

## Out of scope, noted
- HDD IGR dead (the PR #1004 artifact): nothing in this audit is HDD-specific. HDD games also get the SDK sio2man in-game since #962, which changes the pad path IGR reads from.
  Worth one A/B with the same build pair as §3 #1.
