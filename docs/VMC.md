# VMC creation and recovery

Virtual memory cards are file-backed PS2 save cards. Per-game VMC settings select the card name and slot; an existing card should be preserved rather than recreated as a first diagnostic. See [the VMC guide](https://nathanneurotic.github.io/Open-PS2-Loader/vmc.html) for configuration and supported devices.

## Failed creation versus layout warnings

Back up VMC/<name>.bin before deleting, resizing or recreating a card. Deletion removes its saves. A format/write error, unfinished progress or missing file is different from a completed card with a layout warning. Check destination path, write permission, free space and the device/server connection.

Changing the size of an existing VMC is refused without modifying the image. Back up its saves, then use the explicitly confirmed **Delete** action before creating a card of another size. An existing image with an invalid size is protected too. New card creation and reuse of a card at the requested size keep their existing behavior.

A full console restart can clear a stuck creation session, but does not change a file's disk fragmentation. Recreating the card is not guaranteed to allocate one extent, even with plenty of free space.

Native OPL on FAT32/exFAT BDM storage requires a contiguous VMC sector range; do not bypass launch-time write guards. Native APA/PFS uses bounded inode/block mapping. MMCE uses a separate file-backed contract; unsupported layout queries are unknown, not proof of fragmentation.

Neutrino's BDM mapper supports multiple extents and shares a 64-fragment budget across the game and cards in the bundled runtime. If that combined count exceeds the limit, the prompt reports the current count and asks whether to skip the named VMC and use the physical memory card in that slot. Even a contiguous VMC can exceed the budget when the game already uses all 64 entries. Declining returns to the menu. This is different from native OPL requiring a single-extent VMC; it does not mean that a fragmented VMC always fails under Neutrino. APA/PFS VMC backing is not available under bundled Neutrino. Record the selected core and exact failure stage.

Report card size/path, PS2 model, exact build, device, filesystem, VMC/PADEMU state, error text, and whether the same unchanged file works after restart. An already expanded Custom ELF path from older config save behavior must be re-entered after updating; repeated save/reload should preserve it after #885.

For confirmed source defects and validation limits, see [the creation/cancellation audit](VMC-AUDIT-2026-10-08.md). [PR #889](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/889) addresses a semaphore leak after failed writes and core-aware creation warnings. Console and device-specific validation remains separate from build and host-test results.
