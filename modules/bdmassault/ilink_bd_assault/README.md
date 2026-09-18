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

## Building
To build `ilink_bd_assault.irx`:
```bash
docker run --rm -v "${PWD}:/src" -w "/src" opl-build:local sh -c "make clean && make"
```
Or directly in an environment with the PS2SDK IOP toolchain (`mipsel-none-elf-gcc` and `iopfixup`):
```bash
make clean && make
```
The output binary `ilink_bd_assault.irx` is identical to `POPS/usbhdfsd.irx.ilink`.
