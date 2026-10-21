# Stash archive — exported 2026-10-21

The six entries that were in `git stash list` were exported here as binary-complete patches
(`git stash show -p --binary --include-untracked`) and then dropped. Restore one with
`git apply <file>` (plus `git stash` if you want it back as a stash). None of this content was
lost; the stash list is now empty so current work is easier to see.

| File | Was | Base | Assessment |
|---|---|---|---|
| `stash-0-igr-alarm-callback-wip.patch` | IGR alarm-callback WIP (padhook, IGR.md), found uncommitted 10-17 | `fix/issues-830-coderabbit-followups` | **Superseded.** The alarm-callback sampler was merged as #973/#990, made IGR worse on hardware (RE4 dead pad + power button on Beta-4032/4080), and was deliberately reverted by #1004. This WIP is a partial draft of that rejected design; the full version remains in git history. |
| `stash-1-migrate-riptopl-korium-wip.patch` | Korium migration WIP (menusys, mmcesupport, udpfssupport, ~17 files) | `migrate/riptopl-korium` | Judgment call. #1030 ("Merge current main into Korium") landed 10-21; this WIP's relationship to that merge is unverified. Kept as patch only. |
| `stash-2-prefix-sanitization-hardening.patch` | Path/prefix sanitization hardening + `test_sanitize_prefix.py` (Sept 26) | `docs/round-0926-repo` | Judgment call. The test file does not exist in current main, so at least part of this never landed. Kept as patch only. |
| `stash-3-test-340-3449-baseline-bins.patch` | Prebuilt compressed BDMA module blobs for an August test baseline | `test/340-3449-baseline` (PR #366 era) | Stale test fixtures from August. Almost certainly worthless, but archived anyway. |
| `stash-4-test-340-official-nav-parity-bins.patch` | Same module blobs, sibling baseline | `test/340-official-nav-parity` | Same as above. |
| `stash-5-gfx-bigger-icons-wip.patch` | Larger versions of 11 UI PNGs (udp_fs, usb, usb_bd, ...) | `master` (PR #150 era) | Very old artwork experiment. Kept as patch only. |
