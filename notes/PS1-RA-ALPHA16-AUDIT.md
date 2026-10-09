# October 9, 2026 integration audit

The starting checkout was clean at `a88144821aa1b8ea9d6bfcd02ecaefeb441b6eaf`,
on `fix/bdm-hdd-library-recovery`, behind the published PR #894 head. Integration
work uses a separate checkout based on that published head,
`cbc7bef56b41dcf6bf4f7d145c6c480a0f868b07`, preserving the original checkout.
All console changes belong to [PR #894](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/894).

## Published work retained

- RiptOPL `rebuild/main`: `8fae5f19807466ce31fa7424969d00be42e66aa3`, including
  #898's SMB explicit-refresh recovery and #899's paired account browser.
- #894's merge already reconciles #899 with its own Caduceus work. The separate
  obsolete `ra_browser.c` implementation is removed; `achievements.c` remains
  the browser implementation. The host browser tests cover this integration.
- PS2-Servers `main`: `270ec375f293f0024d1c8ea60170bcfc04bdc642`, including
  #219's optional desktop library and #220's batch import/artwork setup work.
- PS2-Servers #218 remains open at
  `6d027fb367482e2d452917b43b328b00455b2e47`; its desktop parity work is separate
  from the PS1 telemetry requirement. Its published checks were successful at
  audit time. Green checks are not a console acceptance result.

## Confirmed gaps and corrections

Before this change the RA support action rejected every PS1 row. The VCD launch
path installed neither a POPS reader nor a telemetry bridge. PS1 disc-ID display
support and an alpha.16 PC engine did not make that launch path achievement-capable.

The reference is hacan359/Open-PS2-Loader
`531aad4584d65d1779b744739b81402150c7669c`, together with its preceding VCD hashing
changes. The port retains RiptOPL's filename-based configuration identity, separate
PS1/mixed views, POPStarter resolver, memory-card preparation and USB driver selector.
It does not copy the reference's replacement listing/launcher/driver-management code.

The reference unconditionally overwrites `POPS/MODULE_9.IRX`. RiptOPL instead
recognizes its own module in the RA build, removes stale copies before BDM POPStarter launches,
and refuses an occupied user slot only when telemetry would actually be installed.
PS2SDK's FAT driver translates create/truncate/append but does not enforce
`O_EXCL`, so the refusal is explicit and tested with an open stub that ignores
that flag. Failed PS1 memory reads suppress the snapshot rather than publishing
an invented zero frame or treating failed reads as fresh memory.

#894's sender arguments also differ from the upstream reference. The POPS bridge
uses the current argument layout, including Caduceus mode and companion address.
PS1 hashing preserves RiptOPL's bounded ISO directory parser and physical-disc
implementation; synthetic fixtures check hashes independently with Python MD5.

## PS2-Servers disposition

Current main already vendors the alpha.16 client, shared protocol and rcheevos.
Game loading resolves image hashes, and Caduceus forwards hash-based lookup and
the existing telemetry stream. This console port adds no protocol messages or
server-side settings. No PS2-Servers code change is required for this parity scope.
The PS2-Servers checkout contains untracked `.worktrees/` and `scratch/` material;
it was preserved and not reset, cleaned or updated to a different local branch.

## Remaining acceptance work

1. Review and run the updated #894 build matrix at the final commit.
2. Test USB FAT32 and exFAT on the same console: support check, POPStarter boot,
   play beyond the 25-second reader delay, sustained telemetry and an actual unlock.
3. Test normal and Favorite launches, remembered launches, disabled telemetry,
   no watch list, companion offline, write failure and a user-owned MODULE_9.IRX.
4. Recheck #894's existing PS2 paths: HDD enumeration/Favorites, SMB explicit refresh,
   Caduceus account browser and pulse notices. Production card DMA stays disabled.
5. Keep MMCE, APA HDD, network PS1, MX4SIO/iLink PS1 telemetry and physical PS1 discs
   outside the supported scope. Command-line BDM autolaunch remains PS2-image-only.

Host checks, a linked ELF and CI artifacts cannot establish POPS SIF service timing,
cache coherence, scratchpad coverage or compatibility across game titles. The reader
inherits the reference's PS1 RAM location and 25-second startup delay; its reads are
not synchronized to a game frame. These remain explicit hardware limitations.

RA isolation follow-up: module ownership cleanup and USB RA eligibility are compiled
only in the RA flavour. Standard-build CI rejects their symbols and the rapops blob.
Switching a USB stick back to a standard build requires removing the RA-created
MODULE_9.IRX once; the standard loader does not manage RA files.
The host PS1 suite also compiles the production sender header builder against the
unmodified xeRAbora alpha.16 snapshot parser and protocol headers. Direct values,
pointer-node pairs, serial identity, duplicate suppression and stale-list refusal
pass. Existing client-mode tests cover Caduceus routing and legacy xeRAbora flags.
This is protocol/host evidence, not a running-client or console test.
