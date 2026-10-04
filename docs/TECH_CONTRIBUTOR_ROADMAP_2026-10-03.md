# RiptOPL contributor roadmap for tech — October 3, 2026

A roadmap is an ordered list of outcomes and the evidence needed to call each
one done. This is a starting menu for a contributor, not a promise of dates or
an assignment to fix everything. Pick one item, post the result, then choose
the next. The [community reports handoff](./COMMUNITY_REPORTS_HANDOFF_2026-10-02.md)
has the original reports, captures, source references, and open questions.

## Already shipped to `rebuild/main`

- [#824](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/824): preserved
  the reports and evidence for handoff.
- [#826](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/826): marked PS1
  rows and captions `[PS1]` and explained the PS1 save-card menu.
- [#825](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/825): saved
  per-game Ember settings from the menu before launch.

CI builds and host tests passed. These are source/build results; console
behavior still needs checking.

## Start here: verify the shipped changes

1. On a real PS2, open an Ember game's settings, change one value, confirm,
   and check `EMBER/games/<name>/settings.txt` **before launching**. Repeat with
   an unchanged dialog and with a managed value changed back to Default. Check
   that unrelated lines and comments survive. Start with one writable USB
   device, then test available SMB, HDD/PFS, MMCE, UDPFS, and Favorites paths.
   Record any failed or slow write and whether the menu reported it.
2. With cover art absent, check that PS1 and PS2 rows are distinguishable in
   PS1-only, Mixed, and Favorites views. Open a PS1 row's Triangle menu and
   check its save guidance. Confirm PS2 Game Settings and VMC behavior still
   work on PS2 rows. Try at least one CRT/theme combination.

For each result, report the build or commit, console, device, game and view,
steps, expected result, actual result, and a photo/video or log when useful.
One clear failure is enough to open a focused bug report or fix PR.

## Next investigations

| Area | First useful contribution | What would justify a code fix |
| --- | --- | --- |
| Slow artwork | Reproduce the 3248-versus-3420 report on the same console, storage, theme, and loose art set. Identify whether COV, ICO, or BG appears late; capture the existing Debug HUD timing. The ART770 and ART773 Korium test builds behaved similarly for a different tester. | A measured request, lookup, read, decode, or queue difference that supports a narrow change without reviving the earlier art-order regression. |
| iLink launch | Repeat one ISO on one drive/bridge across cold and warm starts. Record filesystem, exact modes, PS2 logo setting, loader core, Neutrino version, and full saved/effective arguments. Change one factor per run. The reported Neutrino success could not be repeated. | A repeatable failure and evidence of the failing handoff step. Do not add a universal delay based only on the logo correlation. |
| Missing PS1 prerequisite | Reproduce Aislinn's path with the exact missing file, game type (Ember folder or POPSTARTER VCD), storage device, and visible message or missing row. | One specific point where existing launch errors or scan behavior fail to guide the user. |
| PAL game on NTSC CRT | Capture the actual game output and identify the title, Neutrino build, CRT/cable, and whether the symptom is vertical roll or field shake. Compare the native OPL core's interlaced NTSC GSM option where possible. | A supported interlaced Neutrino path or a verified UI fix. Merely enabling the greyed compatibility picker at Default is ineffective in the inspected upstream core. |
| CRT menu font | Photograph the same settings page with standard interlaced and existing FLICKER-FREE interface modes, holding theme, cable, and camera settings constant. Check navigation response separately from text flicker/blur. | A demonstrated legibility or responsiveness improvement that does not degrade other modes. |

## Contribution path

For a source fix, use the `NathanNeurotic/Open-PS2-Loader` repository and target
`rebuild/main`. Keep one cause per PR, link the matching handoff report, run a
focused check and the relevant PS2 build, and label source/CI evidence
separately from console results. Preserve the maintainer's dirty
`migrate/riptopl-korium` checkout by working in an isolated branch or worktree.
`NathanNeurotic/RiptOPL` is a separate future migration repository.
