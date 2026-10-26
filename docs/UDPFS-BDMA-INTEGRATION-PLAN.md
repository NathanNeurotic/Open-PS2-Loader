# UDPFS BDMA integration

Date: 2026-10-26. Status: implemented locally; host checks and standard/RA target
builds pass. Physical-console acceptance remains pending. No release was published.
Initial source baseline: a1b3452ff0e7bbfeacd5aa7d6c4d8bb1fd967fd2.

## Accepted scope

Treat both releases as ordinary BDMA modes tied to UDPFS. Reuse the existing
mode selector, equip, card population and UDPFS launch callback. No separate
transport preference or new Ember backend is required.

- Keep mode 6 / marker `udpfs` for USB-first VCD fallback and update its Alpha
  binary to BDM-UDPFS Assault 1.0. Append mode 7 / `udpfsnet` for UDPFS Assault
  1.0.0, which serves every mass: request and network VMC writes.
- Put both loose pairs in POPS/. Automatic UDPFS launch equip uses only the
  selected game's POPS folder, never an unrelated device's drivers.
- Preserve a matching equipped pair, including a markerless manual pair.
  The installed network-only mode remains selected on UDPFS launches.
- Populate each missing DAT independently from that same game-device POPS folder
  to MC SYS-CONF. Any existing copy on MC0 or MC1 wins. Run this even when the
  driver pair is already equipped. Absent source files remain optional.
- Use the existing UDPFS settings editor for the effective MC files. Respect
  per-file MC0/MC1 precedence and explicit replacement confirmation. Verify
  writes; retain backups if restoration fails. Never depend on MC rename.
- Keep Ember's existing inherited udpfs: filesystem handoff.

## Upstream inputs

[BDM-UDPFS Assault 1.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0)
supplies the 79,501-byte fallback module.
[UDPFS Assault 1.0.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0.0)
supplies the 44,597-byte network module. Both use the identical 34,508-byte
usbd_bd_assault.irx companion.

Archive and installed module SHA-256 digests are recorded in
[PROVENANCE.json](../POPS/UDPFS-NOTICES/PROVENANCE.json). The downloaded archives
matched GitHub's published digests. Binaries are unchanged. Each release's
instructions and notices are preserved under POPS/UDPFS-NOTICES/USB-FALLBACK/
and NETWORK/. No reproducible source rebuild of those binaries is claimed.

IPCONFIG.DAT is a PS2 IP/netmask/optional gateway line. UDPFSCONFIG.DAT is the
server IP; absent/empty server config allows discovery. Each runtime file is
looked up at mc0:/SYS-CONF/, then mc1:/SYS-CONF/. USB-first also supports
mass:/SYS-CONF/, but our automatic population targets MC. The Alpha runtime
location mass:/POPS/ no longer applies. The source remains the game's POPS/.

## Validation completed

- All seven external shipped pairs pass both production pair validators.
- Stale/missing pairs are rejected; explicit game-device POPS never substitutes
  an unrelated source. Existing local-mode equip tests pass.
- 55 production config/population checks cover independent missing DATs,
  MC0/MC1 precedence, existing-file preservation, optional defaults, parser
  errors, size bounds, low space, partial writes, readback corruption, failed
  restoration and retained backup protection.
- Production launch tests cover USB fallback, network-only without USB, matching
  markerless/manual pairs, automatic equip off, skip-on-valid, missing/stale
  drivers and errors before teardown.
- ZIP payload tests require both upstream pairs and redistribution notices;
  missing companions/notices and changed driver bytes are rejected.
- MC folder/icon regression tests, PSU timestamp and RA packaging tests pass.
- English and 33 language overlays parse; strict translation audit passes with
  pre-existing upstream format warnings. Tracked documentation link audit passes.
- Standard and RetroAchievements target builds pass in an isolated snapshot with
  the existing opl-build:local image and local dependencies. They are validation
  builds, not official release/CI or hardware acceptance.

## Remaining acceptance

Test on PS2: cold/repeated POPSTARTER IOP resets, controls, USB precedence,
network-only without USB, actual VMC save/reload paths, read-only/unavailable
server and reconnection. Use disposable VMCs for interrupted-save tests.
Network writes are not atomic; upstream documents incomplete VMCs after prolonged
save interruptions. Network R/W mode requires a writable server. Existing saves
are not migrated. POPS UDPFS RA remains unsupported.

See [VCD setup](VCD.md#pops-udpfs-with-bdm-udpfs-assault) for user instructions.
