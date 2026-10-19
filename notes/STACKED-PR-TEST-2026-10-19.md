# Combined PR hardware test — October 19, 2026

This integration branch combines the following exact PR heads for one test build.
It does not merge the original PRs or close their issues.

| PR | Change | Included head |
| --- | --- | --- |
| [#1001](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1001) | Skip absent-iLink discovery delay during argv Auto Loading | `a03b3131445952ec8ca2877a8803ec3e053798ec` |
| [#1002](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1002) | Install IGR independently of retained PadOpen patch state | `ff31ea733ab35a7fa9d7ed18f06dc8caea884818` |
| [#1003](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1003) | Inclusive fork capability website audit | `4d2efd21210f459d9fff72c7c5da8a3d0b7ee6d3` |
| [#1004](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1004) | VBLANK_END IGR sampler and Fatal Fury compatibility default | `22804855b22f3b23dcd8b462471024f5610b4f55` |
| [#1005](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1005) | Correct MMCE directory EOF so Ember titles list | `343bae1a887f08331f45162a15e5780a53778a5b` |

## One download

Use the integration PR's **build-flavours** run and download **OPL-OFFICIALROLLING**.
The artifact contains the loader ELF, `BUILD-MANIFEST.txt`, this guide, and the
website preview under `docs/stacked-pr-site/`. Keep the manifest with test results:
its commit identifies the combined build, rather than an individual source PR.
The RA and FREEZEDIAG flavours are optional follow-up builds from the same run.

## Integration decisions

- Keep #1002's independent installation and #1004's VBLANK sampler together.
  Their combined behavior installs VBLANK monitoring earlier during a game's IOP
  reset than #1004 alone. Boot/loading and repeated reset tests matter here.
- Retain #1002's real reset-caller regression, adapted to VBLANK registration.
  Retain #1004's removal of obsolete alarm-only tests and CI steps.
- #1003 targets the separate `gh-pages` history. Its complete, unmodified site
  tree is included under `docs/stacked-pr-site/` so links and assets work together.
  This preview is documentation; it adds no loader runtime feature.

## Console checks

1. Boot the combined OFFICIALROLLING ELF using the same storage and settings as
   the failing release. Record console model, game ID, storage, and manifest.
2. With Mode 6 off, launch **Resident Evil 4** and **GTA San Andreas** through
   native OPL on the internal exFAT HDD. Verify normal startup and gameplay, then
   test controller IGR, one physical power-button press, and a double press in
   separate runs. Repeat launch/reset cycles to exercise retained PadOpen state.
3. Repeat the relevant reset checks on USB and iLink. Test RA separately using
   the same run's OFFICIALROLLING-RA artifact if needed.
4. On MMCE, confirm Ember titles list alongside POPSTARTER titles, including a
   library with loose files and empty folders. Verify that rescanning works and
   that artwork still loads. The host regression also checks that real SIO2
   failures preserve the last-good list.
5. Check argv Auto Loading with no iLink drive present: the optional three-second
   discovery delay should disappear. If Auto Loading falls back to the menu,
   confirm that late iLink discovery still works. The GUI last-played countdown
   is a separate path.

Fatal Fury: Battle Archives Volume 2 keeps #1004's Mode 6 default. On the standard
loader, Mode 6 disables IGR. In the RA loader with achievements enabled, Mode 6
still installs a snapshot VBLANK handler and cannot avoid that title's known
handler incompatibility. See `docs/IGR.md` in the source branch.

## Website preview

From the extracted artifact directory, run:

```sh
python3 -m http.server 8000 --directory docs/stacked-pr-site
```

Open <http://localhost:8000/fork-gaps.html>. Check search/filter controls,
navigation, and narrow-screen layout. The source/feature-gate/licensing review
checklist remains on #1003; bundling the preview does not complete that audit.

## Reporting

Report each result with the flavour and manifest commit, game ID, storage,
Mode 6/RA settings, and whether failure occurred during boot, gameplay, reset,
power-off, or the next launch. This bundle is for combined testing; acceptance
of the individual fixes remains tracked by their original PRs.
