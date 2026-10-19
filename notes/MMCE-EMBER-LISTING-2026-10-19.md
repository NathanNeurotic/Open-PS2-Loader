# MMCE: Ember games never list

Investigated against `rebuild/main` at `2eb0d376` after Nathan reported Ember titles missing on
MMCE. POPSTARTER titles on the same card still listed.

## Root cause: mmceman reports end of directory as an error

The MMCE list does scan Ember. `mmceUpdateGameList()` passes the card root (`mmceN:/`, from
`mmceGetDeviceRoot()`) to `ps1FillGameList()`, the same entry point BDM uses. The failure is in
how a directory listing ends on this driver:

1. **Card firmware** (sd2psXtd `ps2_mmceman_fs.c`): DREAD calls `sd_iterate_dir`, whose
   `openNext` fails once the folder has no next entry. The card then answers status `0x1`. Every
   listing ends this way. The firmware's DOPEN is `sd_open`, which opens files as well as folders,
   so a loose file opened as a folder hits the same reply on its first DREAD.
2. **mmceman** (`mmce_fs_dread`, pin `db3e93f0`): any non-zero status returns `-1`, the same value
   as an SIO2 timeout.
3. **EE glue** (ps2sdk `329e2bb4`): `__fileXioDreadHelper` maps the negative to `-ENOENT`, and
   `getdents` runs `__transform_errno` twice, leaving `errno = EPERM`. newlib's `readdir()` returns
   NULL.
4. **Scanner**: since `0ab450a1` (2026-10-10, PS1 scan hardening), `cueScanDir()` and
   `cueEntryIsGame()` treat a NULL `readdir()` with `errno` set as a failed read. On MMCE that
   described every completed listing. `ps1FillGameList()` then logged `EMBER scan failed --
   publishing the POPSTARTER half alone this pass`.

The VCD scan never checks `errno` after `readdir()`, which is why POPS titles kept appearing.

## Fix

`.github/patches/mmceman-fs-dread-eof.patch` makes `mmce_fs_dread` return `0` (end of directory)
for the card's status reply. Timeouts and garbled replies still return `-1`, so the 10-10 hardening
still keeps the last-good list when the bus really fails mid-scan. `install_coherent_mmce.sh`
applies it after the three existing mmceman patches. Every release workflow already builds mmceman
through that script. The card sends the same status for a handle it no longer holds (bad fd), which
is now also read as "nothing more to list".

## Evidence

`.github/scripts/test_ember_mmce_dread.py` compiles the pinned `mmce_fs_dopen`/`mmce_fs_dread`
with the repo's patches, the pinned SDK fileXio dread helper, `getdents` and `__transform_errno`,
and the production Ember scanner. Only the SIO2 transfer is replaced, by a card that answers like
the firmware. Layout: `EMBER/games/{Spyro,Crash}` with images, plus a loose `readme.txt` and an
image-less `EmptyGroup/`.

- Without the new patch: `cueScanDir("mmce0:/")` returns `-1`. The test requires this baseline to
  fail.
- With it: 2 rows; a timeout during the listing or inside a game folder returns `-1`; no
  `EMBER/games` returns 0.

This is a host model of the driver and firmware protocol. No console run.

## Same contract elsewhere (fixed by the same patch, not separately tested)

- `src/artindex.c` (since `8754d198`, 2026-10-08) rejects a directory index when `readdir()` ends
  with `errno` set. On MMCE every `ART/` sweep counted as failed, so cover lookups fell back to one
  open per title on the shared SIO2 bus.
- `vcdRaModuleStatus()` in `src/vcdsupport.c` (`cb39ade5`) only uses its directory walk after a
  FatFs-specific `EINTR`. That path is not reached on MMCE.

## Open lead

On success `mmce_fs_dread` returns the card's iterator id, and `__fileXioDreadHelper` passes it
through as the dirent result. If the card ever returned iterator id 0, `getdents` would read it as
end of directory and stop the listing early. The firmware hands out the first free file slot as
the iterator; whether slot 0 is always taken by then is unverified. Not observed; noted for a future
report of "only some entries list".
