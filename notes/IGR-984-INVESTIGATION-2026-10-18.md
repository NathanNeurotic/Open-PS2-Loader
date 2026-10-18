# IGR #984 investigation and cloud continuation checkpoint

October 18, 2026. Evidence-only handoff; no new IGR runtime fix or tester candidate.

## Current instruction and scope

The maintainer requested pushing the current work for a cloud agent, then supplied a failed post-#973 console retest and asked to investigate existing issues/PRs and official OPL before proposing another fix. Do not equate passing CI, a merge, or a plausible defect with resolving this report. Avoid another broad community tester chase.

Authoritative repository: NathanNeurotic/Open-PS2-Loader, `rebuild/main`, verified at `453827719ad6631dd9d08077a6312abafb784418`. This branch contains only this investigation note.

## Reporter evidence

[Issue #984](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/984) already transcribes the new screenshot and has additional investigation comments. Read its current comments, not only the initial body.

- Earlier build: `v1.2.0-Beta-3979-Korium-4b62ff8-OFFICIALROLLING`; SCPH-39001, official NA adapter, BDM internal exFAT, Mode 6 off. GTA San Andreas, NFS Most Wanted, Midnight Club 3 DUB Edition Remix and PES 5 had no IGR; RE4 and other games still responded. Games reportedly played normally.
- Latest build: `v1.2.0-Beta-4032-Korium-c4b707a-OFFICIALROLLING`; reporter lists controller IGR failure for PES 2008 `SLES_549.13`, RE4 `SLUS_211.34`, GTA SA `SLUS_209.46`, NFS Most Wanted Black Edition `SLUS_213.51`, PES 2005 `SLES_535.44`, and MGS3 Subsistence Disc 2 (reported as `SLUS_211.34`, duplicating RE4; do not trust that last ID without independent confirmation).
- Latest message does not establish physical power-button results, separate controller reset versus shutdown results, selected core, PADEMU state, or that every earlier configuration detail was rechecked. Do not silently fill those gaps.
- Source ancestry verified locally: #841 is present in original Korium commit `4b62ff82`; #973 source commit `c94698170bb0c01145b825dcc1891a9b183f6983` is present in tested Korium commit `c4b707a758a2cba13a53d6bbe223b58f05e31735`.
- Therefore the original failure predates #973. Latest RE4 result suggests an expanded failure, but does not isolate the introducing commit.

## Relevant history, including a rejected hypothesis

1. [Official OPL #1762](https://github.com/ps2homebrew/Open-PS2-Loader/pull/1762), merged at `33bc51c5cc2391cbc3b0df62af64d902ffa91780`, removed standard VBLANK monitoring. A priority-127 thread samples input, registers a one-shot alarm, then sleeps; the alarm callback only wakes it. Reported acceptance covered SMB Fatal Fury Battle Archives 2, Ratchet & Clank 3 and Ocean Commander, not our whole title/storage matrix.
2. [RiptOPL #841](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/841) adapted that approach while keeping RA's VBLANK path.
3. [#951](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/951) invalidated dead pad DMA pointers across IOP resets. [#959](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/959) retained installed pad hooks to avoid live-RAM rescans and fixed assembly caller context/cache handling. Preserve those safeguards.
4. [#973](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/973), merged at `26f0c1fdd43582b1d95724175ca803de3e87913c`, moved input sampling into the alarm callback and promoted/woke the worker only after a request. Final source commit `c9469817`; final PR head `da1f5d5f`. It passed source/host/native/CI validation without console acceptance.
5. [#985](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/985) is CLOSED, UNMERGED, WITHDRAWN UNSAFE. Its privilege-restoration premise was incorrect: `ee_kmode_enter()` returns the already-masked Status, so masking that return to recover the old KSU always produces zero. The proposed restoration could leave a user-mode callback in kernel mode. Do not reopen, merge, or distribute it.
6. [#731](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/731) concerns a triggered reset choosing the wrong saved ELF path; [#717](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/717) concerns gameplay controllers not working in much older SMB releases. Neither is evidence for the current no-response cause.

## Important independent upstream match

[Official OPL issue #1787](https://github.com/ps2homebrew/Open-PS2-Loader/issues/1787) is OPEN. Its reporter says PES 2013 `SLES_556.69`, SMB, Mode 2, SCPH-90004:

- Beta-2248: IGR works.
- Beta-2250 and Beta-2267: IGR does not work; issue implicates #1762.

[A second tester](https://github.com/ps2homebrew/Open-PS2-Loader/issues/1787#issuecomment-6117121851) reports the same three-version boundary on SCPH-90008, redump image, without PADEMU/VMC/GSM. This is corroborating upstream evidence for a regression across the polling transition. It is not proof that our six games share the same fault or that changing only #973 will fix it.

Official master inspected at `b3a2199795fe89ba7e2dd7b843354472dff2c3eb` still uses worker sampling and an alarm callback that only calls `iWakeupThread`. It is a comparison baseline, not an already-fixed implementation to copy blindly.

## SDK contracts independently checked

PS2SDK master observed at `329e2bb43287e16af16c4dde1c614e2662c24468`. Primary sources:

- [alarm.c](https://github.com/ps2dev/ps2sdk/blob/329e2bb43287e16af16c4dde1c614e2662c24468/ee/kernel/src/srcfile/src/alarm.c): `SetAlarmInternal` captures caller GP. The handler removes the expired alarm and frees its ID BEFORE invoking the callback. It switches to the saved GP and calls `InvokeUserModeCallback`. Thus a recurring IGR alarm does not inherently leak its own slot; do not assume ordinary rearming fails from exhaustion.
- [dispatch.s](https://github.com/ps2dev/ps2sdk/blob/329e2bb43287e16af16c4dde1c614e2662c24468/ee/kernel/src/srcfile/src/dispatch.s): callback dispatch sets KSU=user; it is not an ordinary kernel-mode C interrupt call.
- [kernel.h](https://github.com/ps2dev/ps2sdk/blob/329e2bb43287e16af16c4dde1c614e2662c24468/ee/kernel/include/kernel.h): `ee_kmode_enter` returns masked Status. Independently verified in the installed ps2build SDK header as well.
- Current `src/system.c::sysLaunchLoaderElf` intentionally preserves the alarm patch at `0x00082000` by wiping from `0x00084000`. Resident `ee_core` disables its own patched initialization; actual live dispatcher/Timer 3 ownership still needs runtime measurement. Normal launch intentionally preserves the patched path, so do not treat an unpatched ROM dispatcher as the default without evidence.

Confirmed source limitation: `SetAlarm`/`iSetAlarm` failure leaves recovery pending, with retry only at a later pad-open. A game that never reopens its pad can lose monitoring for that session. The report contains no measured failed alarm return, so this is a recovery gap, not an established root cause.

## Additional compiled-code audit from this continuation

Reviewed an existing locally linked standard EE core built with ps2build/GCC 15.3.1, `-G0 -Os`, PADEMU and IGS enabled. This is NOT the reporter's downloaded OFFICIALROLLING ELF and must not be presented as exact-artifact validation.

- Staged `padhook.c` and current main `padhook.c` SHA256 both: `99caa721fe1b7f587a602f00370ae2c0ebf3e9be783f6a24a23ece6e80713054`.
- Local unstripped standard ELF SHA256: `5cf91e9e4448992153ea304d4f87819021cc7ea1cf967cc618d911c89506e7d2`.
- `IGR_Poll_Alarm` at `0x895e4` has the input check inlined. Direct callees are `DIntr`, `EIntr`, `iChangeThreadPriority`, `iSetAlarm`, and tail-call `iWakeupThread` (a trampoline to its syscall stub). Examined helpers are register/syscall wrappers. This path has no GP-relative data access in this local build.
- `Install_IGR` at `0x89cd4` uses absolute data addresses. The callback may inherit game GP through a pad-open registration, as #984 notes, but the inspected generated callback does not demonstrate a dependency on that GP. A GP-only patch is therefore unsupported by this artifact; other configurations/SDK/kernel paths remain unproven.
- Disassembly can be regenerated with the EE objdump using `-d` on a matching unstripped core. Keep exact input SHA, compiler/options and SDK version with results; inspect direct/tail-call dependencies rather than relying only on C `-G0` assumptions.

Local evidence paths (not available to cloud automatically): `build/igr-pr973-audit/build/native-igr/ps2.yaml`, its staged source and linked ELF; `build/igr-standard-disassembly.txt`. The prior `build/IGR-CURRENT-CHECKPOINT.md` has historical build details. This tracked note captures the material findings without requiring those local artifacts.

## Next work: isolate a failing stage before designing a fix

1. Read current #984 comments and official #1787. Compare pre-#841 and post-#841 behavior separately from pre/post-#973. Use RE4 as a formerly responding title, and distinguish the PES upstream regression from our title variants.
2. Build a development-only, minimally invasive stage record for: pad hook captured; worker created/started; initial alarm return; first callback; rearm return/count; stable live pad/frame progress; combo latched; worker promotion/wake return; worker entered; shutdown stage. No print/file I/O in the callback. Preserve evidence across a stalled game if possible.
3. Validate the alarm/kernel contracts against real SDK implementation or a controlled EE/PCSX2 probe before depending on host mocks. Include callback user mode, freed alarm slot, GP capture, generation invalidation, game timer/IOP transitions and both initial registration routes (DMA hook and pad-open).
4. Inspect the exact reported or replacement OFFICIALROLLING core/artifact, not only this alternate local compiler build. Verify packaging/build flags and source provenance.
5. Only after the first failed stage is isolated, propose a narrow fix. Preserve no-VBLANK compatibility in standard builds, RA/Mode 6 behavior, hook lifetime safeguards, VMC/controller behavior and bounded recovery. Do not blindly restore VBLANK or add a priority-0 polling loop.
6. No root cause is established and no new IGR runtime fix was authored in this continuation. Keep #984 open; eventual source/CI success alone is not its closure criterion.

## Other work already published

- #974 closed/fixed through merged #975; #976 closed through merged #981 (`0ecf0963`); #978 closed through merged #980 (`45382771`). All final build flavours/host groups and formatting passed. PSBBN Flow #977 and website #979 are already merged.
- Preserve `test/korium-audit-remediation`: closed tracking PR #687 is unnecessary, but the branch remains a production release dependency. Korium Sync succeeded after the final main merge (run `39134072687`); later release publication must be checked live, not inferred.
- [PR #983](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/983), branch `codex/neutrino-vmc-budget-message`, head `c33c6a0b5bc6e6667a6e93b0c1a4458092bb6050`, is OPEN/UNMERGED. It only corrects Neutrino's misleading shared-fragment-budget prompt and updates its fixture/docs. All 7 ELF builds + 6 host jobs pass in run `39134549721`; format run `39134549847` passes; CodeRabbit status success and no unresolved threads at checkpoint. Freshly recheck reviews/head/mergeability before any eventual merge.
- Maintainer clarified Davood probably means native/upstream OPL VMCs. #983 is NOT a proven fix for that report. Native BDM VMC writes still require contiguous backing; earlier false-warning/creation fixes did not add fragmented native mcemu support. Existing data must not be reformatted/recreated as a first diagnostic.
- Original Windows checkout has five superseded uncommitted IGR files. They were preserved, not pushed over the merged implementation. The authoritative #973 source is already remote; do not revive the old dirty diff as a new candidate.
