# RiptOPL: what is left

The [full handoff](./COMMUNITY_REPORTS_HANDOFF_2026-10-02.md) has the reports
and technical detail. [#825](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/825)
(Ember settings save) and [#826](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/826)
(PS1 labels and menu guidance) are merged into `rebuild/main`. Builds and host
checks passed; the console check is still open.

## Finish line

1. On one real PS2, confirm an Ember setting changes `settings.txt` before
   launching the game.
2. With covers off, confirm a PS1 game is clearly marked and opens its PS1
   menu, while a PS2 game still opens its normal settings.
3. Fix anything those checks break, then do the final build/release check.
   Other reports stay tracked; they do not all need to be solved first.

## If tech wants to help

Pick **one**, whichever is interesting. A clear diagnosis is useful even
without a PR:

- **Neutrino arguments:** with [#835](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/835),
  turn on **Show Launch Arguments** and confirm on a console that a per-game
  `-logo` appears in the list.
- **PS1 error messages:** with [#836](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/836),
  remove `ember.elf`, `bios.bin` or `POPSTARTER.ELF` one at a time and confirm
  the games still list and the message names the right path.

Slow art (A1) is resolved: the reporter says the latest builds load artwork
normally.

The iLink reliability, PAL/NTSC CRT, and font reports remain in the full
handoff until someone can reproduce them. This is a pick-one list, not a job
assigned to tech.
