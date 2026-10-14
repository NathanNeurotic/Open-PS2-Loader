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
