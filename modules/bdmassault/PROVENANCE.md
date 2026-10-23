# BDMAssault variant driver pairs — embedded provenance

These are the POPSTARTER BDMA driver variant pairs OPL embeds (gzipped) and pastes to
`mc?:/POPSTARTER/{usbd.irx, usbhdfsd.irx}` when the launch-time equip finds no user-supplied copy on
any device (maintainer directive 2026-07-21: "POPSLoader has modules embedded in the elf, and then
pastes them according to the VCD device if needed"). User-supplied files on the seek path
(Custom POPSTARTER dir → boot device POPS/ → game device POPS/) always win; embedded is the final
fallback — the same external-beats-embedded order POPSLoader ships.

## Bytes (vendored 2026-07-21, sha256)

| file | bytes | sha256 |
|---|---|---|
| usbd.irx.usbexfat | 48500 | 5ea4818ba1cf5207f6d7cadb4c13b5afa88c37c260750c21155b079a8c18f369 |
| usbhdfsd.irx.usbexfat | 34508 | 70a369e47745e7f995fa771edbbfed086727b759fba915a7070c0fbcf061dd34 |
| usbhdfsd.irx.mx4sio | 14993 | 61525fab3b340aaef467eb3a08ce16e35aca98fe742982a7a151c5c7e1ffa00a |
| usbd.irx.mmce | 11841 | 0fed25d9eecdd263d4617ad5c8eeb2c5307c799aa97962b62b40a0e63e3adac8 |
| usbhdfsd.irx.mmce | 19733 | 9f7b77848935f0d8e9bd792b997910777352f8d480dc32d99a04e6e8653779ab |
| usbd.irx.ata | 42749 | 4e1d39365854747117a08f8a8d843937614590ea072cf2b70f6e4c2ebbf3c6ee |
| usbhdfsd.irx.ata | 21837 | 1cc865cd09997bd708e9e102c0f0f1f17f352b7844b282fcfa6a00f38609db9c |
| usbd.irx.ilink | 48500 | 5ea4818ba1cf5207f6d7cadb4c13b5afa88c37c260750c21155b079a8c18f369 |
| usbhdfsd.irx.ilink | 27145 | 5b7de8d1ff749e8ca2ad8ef0c705ce76f5799d1c2dcedf5393dbf4cd7a58e6c8 |

**Dedupe (verified by sha256):** `usbd.irx.mx4sio` and `usbd.irx.ilink` are byte-identical to
`usbd.irx.usbexfat` (all are copies of `bdm_assault.irx`).

## Sources

- **usbexfat + mx4sio + mmce pairs**: checked-in binaries of saildot4k/POPSLoader at commit
  `ed2d5db59ded6bf014c64231ea6db3fa54689a36` (bin/POPSLDR/*), fetched via
  raw.githubusercontent.com. POPSLoader also vendors the full MX4SIO build source
  (iop/embed/BDMASSAULT_MX4SIO/ + SourceCode tarball, AFL v2.0).
- **usbexfat upstream project**: israpps/BDMAssault (AFL v2.0; its README documents pasting the
  pair into mc?:/POPSTARTER/). It publishes NO GitHub releases — the POPSLoader-checked-in copies
  are the canonical distributed bytes.
- **ata pair**: saildot4k/ATA-Assault release tag `latest` (published 2026-06-22; 42749 + 21837 B).
  WARNING: that tag is MUTABLE, which is exactly why the bytes are vendored here with sha256s.
- **mmce pair caveat**: exact upstream build source unpinned (mmceman-family; distributed via
  POPSLoader). Confirm lineage with saildot4k when convenient.
- **ilink pair & source**: `usbd.irx.ilink` is identical to `usbd.irx.usbexfat` (`bdm_assault.irx`).
  `usbhdfsd.irx.ilink` source is vendored under `modules/bdmassault/ilink_bd_assault/`, adapted from
  `israpps/BDMAssault` (branch `ilink`). Upstream imported `cdvdman` (ordinals 22 & 64: `sceCdRI` and
  `sceCdRM`) to query the console GUID/model, which crashes POPSTARTER because POPSTARTER does not
  load `cdvdman`. The vendored source removes `cdvdman` imports and substitutes a static Sony OUI
  EUI-64 GUID and model string, building cleanly with PS2SDK/Docker.
  Since #1018 it also logs back in after POPSTARTER's IOP reset (login retried for up to 5 s instead
  of ~0.8 s), polls TEST UNIT READY a bounded number of times, and offers the drive to BDM only after
  a successful warm-up; see `ilink_bd_assault/README.md`. The previous build was 21609 bytes,
  sha256 `9b47d90b03804ea9ef47c3702911d83d488405cc64285b62073ce88a7b6bfc63`.
  The October 21 completion-ordering correction also clears stale LOGIN status before the dummy
  ORB and propagates its completion error. Command-pointer errors preserve the existing wait:
  missing acknowledgments do not prove rejection, and safe target quiescence remains separate work.
  Before that correction the #1024 binary was 21977 bytes, sha256
  `8f9a9e4e6984a58435fe7e24e1e5832f027dc537b3274bc4220245bbe1844714`.
  The October 22 audit corrects the older driver's reversed SBP-2 data direction, releases the
  embedded manager's TX semaphore on generation changes, cancels pending response alarms after
  errors, and drains unhandled RX data with TTY disabled. Transfers use the reported logical block
  size and are bounded by the ORB/write-buffer byte limit; capacity counts include the last LBA.
  The previous 22025-byte binary was sha256
  `aec8f3d6b15af7024bb62120488ed1b83526c4f852add6161185a1232017edc2`.
  The follow-up lifetime pass matches SBP-2 and manager responses to their active requests,
  retains target-visible storage after uncertain timeouts, unwinds manager resources when the
  combined startup fails, and accepts completed extended SCSI GOOD status. The 22185-byte
  binary from the first pass was sha256
  `9470a41a4c2b6e977e25295a6948111873a631a4218ec5efef16c5196e819bc8`.
  The generation-change follow-up reports a bus reset consistently across transmit and response
  waits. Its preceding 27081-byte binary was sha256
  `cba6f974fb39af5746e3305819d83635e3bedc7dc8c44a9055c3381575993334`.
  The current binary was obtained from the `popstarter-ilink-driver` job in
  [Actions run 39899569001](https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/39899569001),
  source head `d77554b63c4bdcc262c44a1ab80e2ed454e7ded8`. The downloaded artifact ZIP had sha256
  `e3e7e2d6263e9fcdc457fdd78c2b7f08cc35d9823e8ce526482001d5d40524c8`;
  its `ilink_bd_assault.irx` is the 27145-byte binary in the table above.
  This remains a candidate pending console acceptance.
  **Rebuilt from source:** the bytes above are the output of `make` in that directory inside
  `ps2dev/ps2dev@sha256:8fba50ecc2229acd7f8da63d34302f12939b7d4fa6848dda1e6a0ce083321a11` (the
  PS2DEVPINNED container), which also reproduces the 21609-byte build from its source exactly. CI
  (`popstarter-ilink-driver` in `.github/workflows/flavours.yml`) rebuilds it on every PR and fails
  unless `modules/bdmassault/`, `POPS/` and the `Example/` kit all carry exactly that output.

## License

All three source projects carry the Academic Free License v2.0 (LICENSE in this directory is
israpps/BDMAssault's copy) — the same license family as OPL itself (AFL v3.0). POPSLoader (GPL-3)
shipping these identical blobs embedded is direct redistribution precedent.

## Re-vendor

Fetch from the pinned POPSLoader commit / a NEW ATA-Assault release, recompute sha256, update the
table above, and re-verify the usbd usbexfat==mx4sio dedupe still holds (if it stops holding, add
the mx4sio usbd as an eighth file AND a new embedded symbol + table row in src/vcdsupport.c).
