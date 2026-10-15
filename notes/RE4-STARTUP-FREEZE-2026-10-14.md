# Resident Evil 4 startup freeze — October 14, 2026

Status: **unresolved; user report plus historical compatibility evidence, not a reproduced defect**.

## New report

Reporter: **V3ditata** (PS2 Scene Discord, `#opl-development`, October 14, 2026).

- Console: SCPH-39001.
- Title: Resident Evil 4 (NTSC-U), `SLUS_211.34`.
- Cheats: **off**, as reported.
- Compatibility Mode 6 (Disable IGR): **off**, as reported.
- Symptom: game progresses to its opening license / content warning / Dolby Pro Logic II sequence, then crashes/freezes and shows a uniform light pink image.
- Reset attempt: L1 + L2 + R1 + R2 + Start + Select had no visible effect.

**Not reported:** exact RiptOPL revision/ELF flavour, image source and filesystem, whether native OPL core or Neutrino, VMC enablement/card, GSM/PADEMU settings, ISO/ZSO format, image provenance/checksum, or whether this same game worked on a specific earlier revision. Do not infer internal exFAT from other testers' reports.

## Interpret the IGR observation correctly

Per [RiptOPL IGR documentation](../docs/IGR.md), in-game pad hooks attach only after the game opens a controller through `scePadPortOpen` / `scePad2CreateSocket`; the combo can legitimately fail at early startup screens. Also, a hard hang can starve the polling thread. A nonresponsive reset combo **does not independently establish an IGR bug**.

With Mode 6 off, the ordinary IGR hook is eligible; turning Mode 6 *on* disables it and is a diagnostic compatibility comparison, not a permanent fix without a passing reproduction.

## Historical compatibility lead: VMC

The [Open PS2 Loader compatibility list for SLUS_211.34](https://www.ps2homebrew.org/Open-PS2-Loader-Compatibility-list/List/R/SLUS_211.34.html) records a working ISO on **SCPH-39001**, OPL **1.2.0 beta 1901** over **USB**, with **VMC: NO**, **IGR: YES**. This is a historical working configuration, **not** proof that all Resident Evil 4 revisions fail with VMC.

A [PSX-Place support discussion](https://www.psx-place.com/threads/my-ps2-freezes-in-the-first-loading-screen-solved.41622/) separately includes an anecdotal Resident Evil 4 VMC incompatibility report. Treat it as a hypothesis until independently reproduced.

## Recommended minimal diagnostic sequence

1. **Record first**: exact RiptOPL build/revision and flavour, launch core, storage/device and filesystem, image type, whether a VMC is attached, plus GSM/PADEMU options. Do not change several settings together.
2. **If VMC is enabled**, compare exactly one launch with VMC disabled in per-game settings; preserve the existing VMC and saves. Do not delete/recreate/format it for this test.
3. **If VMC is already off**, a single comparative launch with Mode 6 on can help distinguish pad-hook incompatibility. IGR will **intentionally** be unavailable in this comparison.
4. Only if still reproducible, compare the same image/source/core/settings against a specifically identified known-good older ELF and the current ELF. If source is internal exFAT, log whether OPL native or Neutrino was selected, but do not assume exFAT caused the fault.
5. With an isolated regression, inspect the affected handoff: VMC attachment/settings, game image sector reads and BDM/ATA transport, in-game OPL core and pad hook. Prefer a targeted host regression test over speculative delay/retry changes.

## Relationship to other freeze investigations

The earlier separately reported online/in-game freeze was discussed with **internal exFAT**, the **native OPL core**, and possibly **DNAS-related cheats**. The new Resident Evil 4 screenshot says cheats off and is at game startup, but **does not establish identical storage or core settings**. Keep these two cases distinct unless a controlled reproduction shows a common underlying cause.

No source fix or real-console reproduction is claimed here. The documented compatibility observation is not a current RiptOPL test.

## Follow-up and pad-lifetime repair candidate

The screenshots supplied in the repair task identify the same reporter, V3ditata.
Their earlier report names internal exFAT and ISO games. A subsequent matrix on
`3941-Korium-dba97ff-OFFICIALROLLING` reports working play with Mode 6 on, with
either cheat setting, and crashes with Mode 6 off, also with either cheat setting.
The latest screenshot supplies SCPH-39001, `SLUS_211.34`, no visible response to
the reset combo, and **VMC off** (the reporter uses an MMCE card). This does not
independently establish the current game source, exact diagnostic ELF, or when
the pink screen appeared relative to the reset attempt.

Source inspection found a pad-buffer lifetime gap: `Install_IGR` preserves live
state on repeated installation, but `New_SifSetDma` did not invalidate that state
before rebooting the IOP. The old libpad DMA producer ends at reboot; the EE
worker can retain its pointer and interpret subsequently reused memory as input.
The polling reader also lacked protection against preemption between its pointer
check and reads, while pad installation updates that pointer and its offsets.

The candidate invalidates pad tracking before each intercepted IOP reset, rearms
pad-hook discovery, and protects the short input snapshot with interrupt-state
preservation. Pad reopen publishes its layout and buffer atomically and restarts
its liveness counters. Pending IGR requests, the worker and physical power-button
state remain intact. It does not force Mode 6, change worker priority, or restore
a VBLANK IGR handler in standard builds.

Host regressions exercise reused memory containing a fake reset combo, pad
reacquisition, pending-state and interrupt-state preservation, and invalidation
before successful/failed resets in both standard and RA configurations.
These establish the source defect and repair behavior, **not that this defect
caused the tester's RE4 freeze**.

Console gate: same image, save, source and settings; cheats/VMC/Mode 6 off;
repeat startup and Mercenaries stage selection, sustained play, then deliberate
IGR. Check another title that resets its IOP, plus the standard and RA paths.
Keep the existing Mode 6 workaround available until this candidate is accepted
on the affected console. No hardware pass is claimed.
