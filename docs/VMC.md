# VMC creation and recovery

Virtual memory cards are file-backed PS2 save cards. Per-game VMC settings select the card name and slot; an existing card should be preserved rather than recreated as a first diagnostic. See [the VMC guide](https://nathanneurotic.github.io/Open-PS2-Loader/vmc.html) for configuration and supported devices.

## Failed creation versus layout warnings

Back up VMC/<name>.bin before deleting, resizing or recreating a card. Deletion removes its saves. A format/write error, unfinished progress or missing file is different from a completed card with a layout warning. Check destination path, write permission, free space and the device/server connection.

Changing the size of an existing VMC is refused without modifying the image. Back up its saves, then use the explicitly confirmed **Delete** action before creating a card of another size. An existing image with an invalid size is protected too. New card creation and reuse of a card at the requested size keep their existing behavior.

A full console restart can clear a stuck creation session, but does not change a file's disk fragmentation. Existing fragmented cards are not repaired by restarting. The native BDM creation path described below reserves one extent for a new card or reports failure; a new HDD (APA/PFS) card requests all of its space up front, and other creation paths still allocate incrementally.

Release builds rebuild the BDM filesystem module with a bounded FAT-chain walker. Failed reads, invalid links, early chain termination and cycles are refused rather than reported as a usable contiguous layout. Local legacy Make builds should run `python3 .github/scripts/install_safe_bdmfs.py` in their SDK build environment first; set `PS2SDKSRC` if SDK sources and installation use separate paths. The installer checks the original walker revision, uses immutable content-verified SDK/FatFs sources when the image omits them, compiles against the installed SDK's BDM/import headers, and checks the resulting IRX marker before replacing the module used by the loader. The guarded walker validates mappings without relocating existing VMCs. The same rebuilt driver also provides the versioned reservation API used for new native BDM cards below.

Native OPL on FAT32/exFAT BDM storage requires a contiguous VMC sector range; do not bypass launch-time write guards. Native APA/PFS uses bounded inode/block mapping. MMCE uses a separate file-backed contract; unsupported layout queries are unknown, not proof of fragmentation.

Native launch warnings distinguish a confirmed fragmented card from a disk address outside the core's 32-bit sector range, an unavailable layout query, and a PFS mapping that exceeds the native block-table limit. A read or mapping error is not proof of fragmentation. Rejected cards stay inactive; accepting the prompt uses the physical memory card in the named slot, and declining returns to the menu. Existing VMC files and saves are not modified by these checks.

Neutrino's BDM mapper supports multiple extents and shares a 64-fragment budget across the game and cards in the bundled runtime. If that combined count exceeds the limit, the prompt reports the current count and asks whether to skip the named VMC and use the physical memory card in that slot. Even a contiguous VMC can exceed the budget when the game already uses all 64 entries. Declining returns to the menu. This is different from native OPL requiring a single-extent VMC; it does not mean that a fragmented VMC always fails under Neutrino. APA/PFS VMC backing is not available under bundled Neutrino. Record the selected core and exact failure stage.

Report card size/path, PS2 model, exact build, device, filesystem, VMC/PADEMU state, error text, and whether the same unchanged file works after restart. An already expanded Custom ELF path from older config save behavior must be re-entered after updating; repeated save/reload should preserve it after #885.

For historical source defects and validation limits, see [the creation/cancellation audit](VMC-AUDIT-2026-10-08.md). The fixes in [PR #889](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/889) for a semaphore leak and core-aware creation warnings are merged. Console and device-specific validation remains separate from build and host-test results.

## New native BDM cards: contiguous reservation

Native BDM creation requests a private versioned capability from the bundled FAT driver before opening a destination. The driver must return the exact positive version token; an old driver's zero/default response is not success. The destination is opened exclusively as a new file, without truncation. A file that appears after the menu's absence check is preserved.

The driver enables FatFs `f_expand` and reserves the complete card allocation before formatting. Reservation does not initialize data: genvmc still writes every cluster and the complete card structures. Successful creation requires a synchronized, single-extent mapping within the native 32-bit sector range; a failed final verification or close is reported as failure. Only this job's newly created incomplete file is removed on failure or cancellation.

This policy applies to native BDM card creation, including Favorites and automatic creation. Neutrino and non-BDM sources retain their existing allocation behavior. Existing cards are reused or rejected by the existing checks and are never relocated/reformatted by the allocation request. Unsupported drivers, unsupported sector sizes and unavailable contiguous space fail explicitly. Reservation and filesystem I/O can delay cancellation; power-loss recovery and damaged-media behavior require separate validation.

This allocation path was merged in [PR #994](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/994). Host fault injection, disposable FAT32/exFAT image tests and native builds do not establish real-console save, reboot and load acceptance. The image fixture uses the pinned FatFs, runs the actual genvmc formatter and verifies its superblock/root directory across remount, also writes and reads every byte of a synthetic card, verifies create-new collision refusal, and rejects reservation when fragmented free space has no large enough contiguous run.

## New HDD cards: PFS reservation and map check

Native OPL maps a card on the HDD through a short PFS block table: the file's inode plus at most nine data segments. PFS grows a file one write at a time from small free runs, so on a used OPL partition a new card could land in more pieces than that table holds. A new HDD card (VMC dialog, Favorites, or automatic creation) therefore asks PFS for every zone of the card in one request before formatting, which takes the largest free runs first. The request is best effort: if PFS refuses it, the card is formatted as before. genvmc still writes every cluster; the reservation does not change the card's contents.

When creation finishes, the loader reads the new card's block map exactly as the launch check does. If it has more pieces than the native table holds, the message says so at once instead of at launch; the card is still kept, and Neutrino is unaffected. Free space on the OPL partition and create the card again, or copy a card in.

pfs0: is mounted write-back, so before either check reads a card's inode from the disk the loader commits the PFS cache. The inode must carry PFS's own magic and checksum; a sector PFS has not committed, or any read or sync failure, is reported as a layout that cannot be verified, and the card stays inactive. Nothing in these checks writes to APA; they read the inode and flush PFS metadata only. Existing cards are never relocated.

Host tests run the real formatter over a fake PFS file (one whole-card request before the first write, identical card bytes, refusal tolerated), the real inode reader against committed, uncommitted, foreign and edited sectors, and the launch and completion checks together. They do not establish real-console acceptance on a fragmented PFS partition.
