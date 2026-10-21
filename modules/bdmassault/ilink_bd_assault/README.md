# ilink_bd_assault (iLink BDM Driver for POPSTARTER)

This directory contains the source code for `ilink_bd_assault.irx`, which is deployed as `POPS/usbhdfsd.irx.ilink` and `modules/bdmassault/usbhdfsd.irx.ilink`.

## Origin & Lineage
- **Upstream Project**: [israpps/BDMAssault](https://github.com/israpps/BDMAssault) (branch: `ilink`, directory: `__ilink_bd_assault`)
- **License**: Academic Free License (AFL) v2.0 (see `../LICENSE`)

## POPSTARTER Compatibility Modifications
Upstream `israpps/BDMAssault`'s `ilink_bd_assault` failed to run under POPSTARTER on real hardware because it imported `cdvdman` (ordinals 22 & 64: `sceCdRI` and `sceCdRM`) to query the console ID and model string when generating the EUI-64 GUID.

POPSTARTER strips/omits `cdvdman`, causing the IOP module loader to immediately abort with an unresolved import error when attempting to load `usbhdfsd.irx`.

The following changes were made:
1. **`src/imports.lst`**: Removed the `cdvdman_IMPORTS` block (`I_sceCdRI`, `I_sceCdRM`).
2. **`src/iLinkman/src/iLink_internal.c`**: Replaced the `GetConsoleIDs()` implementation with a static Sony OUI EUI-64 GUID (`0x0800460123456789ULL`) and static model string (`"SCPH-39000"`), eliminating the runtime dependency on `cdvdman`.
3. **`src/iLinkman/src/include/iLink_internal.h`**: Added clean prototypes for `malloc` and `free` to satisfy modern GCC (GCC 14/15).
4. **`src/exports.tab` & `Makefile`**: Positioned `exports.o` first in `IOP_OBJS` and moved `_funcret()` after `END_EXPORT_TABLE` so `iopfixup` correctly constructs the IRX module export headers.

## Reconnecting after POPSTARTER's IOP reset (#1018)
With i.LINK storage every core listed games but only Ember, the one PS1 core that keeps the IOP, booted. The driver never logs out of the drive (`SBP2_LOGOUT_REQUEST` is defined but never sent) and an IOP reset ends it without warning, so after POPSTARTER's reset the drive still holds the previous driver's exclusive login for its SBP-2 reconnect hold: 1 s for the `MANAGEMENT_ORB_RECONNECT(0)` every login here asks for, longer on bridges that round it up. The same three changes as OPL's own copy of the driver (`modules/ilink/IEEE1394_bd`, PR #1022), marked "RiptOPL" in the sources:

5. **`src/IEEE1394_bd/src/sbp2_driver.c` `initConfigureSBP2Device`**: the LOGIN is retried every 200 ms for up to 5 s of elapsed time (`GetSystemTime`/`SysClock2USec`, already in `src/imports.lst`). It was 5 tries 200 ms apart (~0.8 s), inside the hold, and nothing retried until the next bus reset, which POPSTARTER never causes.
6. **`src/IEEE1394_bd/src/scsi.c` `scsi_warmup`**: TEST UNIT READY is asked at most 300 times, 100 ms apart (30 s, enough for a cold 3.5" drive). It looped with no limit and no delay. A READ CAPACITY block length of 0 is a failure (the capacity printf divided by it). This older driver has no READ CAPACITY(16) path, so the matching change in OPL's copy has nothing to apply to here.
7. **`src/IEEE1394_bd/src/scsi.c` `scsi_connect`**: the drive is offered to BDM only after a successful warm-up, and a failed attempt frees its slot so the next bus reset can bring the drive up. It ignored `scsi_warmup`'s result.

`.github/scripts/test_ilink_bd_assault_reset.py` compiles the real `scsi.c` and `initConfigureSBP2Device` against simulated drives and a simulated clock; it fails on the sources before these changes. Not yet confirmed on hardware.

## SBP-2 completion ordering (2026-10-21, #1018)

Fetch-agent initialization also inherited a separate race: LOGIN's response remained in the shared
status FIFO, so the dummy ORB's wait could consume that old response and free its buffer before the
target completed it. Clear the FIFO before publishing the dummy request (never after, since a fast
bridge can reply inside the pointer write), and propagate the dummy completion's error. Command
submission errors now return to SCSI instead of waiting indefinitely for a status.

`.github/scripts/test_ilink_sbp2_completion.py` exercises these real functions in both driver copies
with immediate and delayed target replies, stale LOGIN status, failed dummy status and failed
submission. The new binary is 22,041 bytes; its hash is recorded in `../PROVENANCE.md`. This is a
source/host-tested correction, not a confirmed repair of FifthFox's enclosure. No read-delay or
transfer-speed setting is added by it.

## Building
The checked-in binaries are built in the PS2DEVPINNED container, which reproduces both the pre-#1018 build (21609 bytes) and the current one byte for byte:
```bash
docker run --rm -v "${PWD}:/src" -w /src ps2dev/ps2dev@sha256:8fba50ecc2229acd7f8da63d34302f12939b7d4fa6848dda1e6a0ce083321a11 sh -c "apk add --no-cache make && make clean && make"
```
Or directly in an environment with the PS2SDK IOP toolchain (`mipsel-none-elf-gcc` and `iopfixup`):
```bash
make clean && make
```
Other toolchains build a working module with different bytes. The output `ilink_bd_assault.irx` is identical to `modules/bdmassault/usbhdfsd.irx.ilink`, `POPS/usbhdfsd.irx.ilink` and the `Example/` kit's copy; the `popstarter-ilink-driver` job in `.github/workflows/flavours.yml` rebuilds it on every PR, fails if any copy differs, and uploads the build as an artifact. After a source change, replace all three copies and update the pinned size/sha256 in `src/vcdsupport.c`, `../PROVENANCE.md` and `docs/VCD.md`.
