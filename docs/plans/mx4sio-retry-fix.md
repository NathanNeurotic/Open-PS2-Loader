# Plan: MX4SIO partial-transfer retry fix (deferred)

Status: planned, not implemented. NOT TESTED.

## Problem

`mx4sio_bd` (`iop/sio/mx4sio_bd/src/spi_sdcard_driver.c`) retries a partial multi-sector
transfer at the original sector with the buffer advanced. Writes can land on the wrong
sectors and still report success; reads can fill the buffer from the wrong sectors.
Upstream fix: [ps2dev/ps2sdk#936](https://github.com/ps2dev/ps2sdk/pull/936) by
[PS2HomeDeveloper](https://github.com/PS2HomeDeveloper), not merged.

Because of this, `bdm_writeSector` in `modules/iopcore/cdvdman/device-bdm.c` gives MX4SIO
("sdc") one sector per write, so MX4SIO gets no batched VMC erase.

## Plan

1. Build `mx4sio_bd.irx` and `mx4sio_bd_mini.irx` from source in our tree with the three
   #936 lines applied (`sector += results;` in both retry paths, `sectors_left` passed to
   `spisd_write_multi_begin`), instead of taking the prebuilt IRX from `$(PS2SDK)/iop/irx`.
   Keep provenance (upstream commit) next to the vendored source.
2. Remove the "sdc" single-sector special case in `bdm_writeSector` and update
   `.github/scripts/test_vmc_write_result.py` to expect batched erases on every BDM driver.
3. Drop the vendored copy once the fix reaches the SDK images we build with.

Deferred until tokens reset.
