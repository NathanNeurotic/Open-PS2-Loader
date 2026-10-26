# UDPFS BDMA integration

The accepted integration uses UDPFS Assault 1.0.0 as the sole UDPFS POPSTARTER
BDMA driver. The old Alpha and USB-first fallback are replaced, not retained as
additional modes. Existing mode 6 and the .udpfs suffix/marker remain stable.

- Bundle the unmodified 44,597-byte udp_fs_assault.irx and 34,508-byte companion.
- Reuse the existing BDMA mode, equip, card-population and UDPFS launch flow.
- Equip automatically from the game's POPS folder, without any USB requirement.
- Preserve matching installed pairs and replace retired Alpha/USB-first pairs.
- Independently populate each missing IPCONFIG.DAT/UDPFSCONFIG.DAT from that same
  game POPS folder into MC SYS-CONF; preserve existing MC files and optional absence.
- Reuse the settings editor with effective MC0/MC1 precedence, verified writes
  and recoverable backups. Preserve unrelated SMB settings.
- Preserve Ember's existing UDPFS backend.
- Ship exact upstream hashes, notices and matching POPS files with CI artifacts.
- RA PR previews refresh current POPS support files before validating an older
  borrowed standard kit. Published kits retain strict same-revision validation.

The upstream archive hash and module hashes are in
[PROVENANCE.json](../POPS/UDPFS-NOTICES/PROVENANCE.json). Upstream source:
[UDPFS Assault 1.0.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0.0).

Host checks cover all shipped pairs, upgrades from both retired UDPFS drivers,
missing-only configuration population, write/readback/rollback failures, no-USB
launch, manual pairs and package hashes/notices. The RA packaging regression also
reproduces the exact formerly failing CI input. Current target-build acceptance
is tracked in PR #1050 CI; physical-console acceptance remains pending.

Console checks: cold/repeated IOP resets, controls, no-USB startup, actual VMC
save/reload paths, read-only/offline server and reconnection. Use disposable VMCs
for interrupted-save tests. The server must allow writes; prolonged interruptions
can leave incomplete saves. Existing VMCs are not migrated and POPS UDPFS RA is
unsupported. See [setup](VCD.md#pops-udpfs-with-bdm-udpfs-assault).
