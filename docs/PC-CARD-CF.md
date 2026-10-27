# PC CARD CompactFlash (experimental)

This backend targets Japanese SCPH-10000, SCPH-15000 and SCPH-18000 PC CARD
consoles with compatible CF/ATA adapters. RiptOPL hardware testing is outstanding;
PS2CF's own observations do not establish that this integration boots correctly.
Expansion-bay PS2, Slim and DESR machines are excluded.

Enable **PC CARD CF (experimental)** in Game Sources. It is off by default.
The CF toggle permits the BDM page to start without changing the saved BDM start
mode. ROM versions 0100/0101/0120 with Japanese region are eligibility hints only:
the IOP driver also checks controller revision 0x20, idle/present card, CF CIS,
ATA identity/capacity, and bounded MBR partitions before publishing a block device.

Use MBR FAT32/exFAT storage with the existing CD/, DVD/, ART/ and CFG/ layout.
CF appears as its own named BDM source and retains normal RiptOPL title/artwork
semantics. Existing APA/HDD, USB, MX4SIO, MMCE and network configurations remain
independent. The standard APA source is not replaced based on ROM version.

## Ownership and limits

CF needs exclusive PC CARD access. Existing DEV9/HDD/network ownership blocks
CF initialization; an established CF session blocks later DEV9 initialization.
A failed CF probe releases its claim and restores the driver-owned host settings.
The GUI never resets an already powered PC CARD merely because the ROM qualifies.
Restart to release a successfully initialized CF session. Start RiptOPL from a
memory card or another independent device for initial testing; inheriting CF
ownership from another launcher is intentionally not assumed safe.

CF uses the native PS2 core and a separate read-only game driver. Neutrino and
PS1/Ember/POPStarter over CF are not supported. CF-hosted VMC assignments are
refused, and automatic CF VMC creation is skipped. Use a physical memory card.
Live RetroAchievements telemetry and network game-debug builds over CF are
unsupported; existing devices retain their current RA paths.

During game launch/repeated game IOP resets, an explicit loader-owned handoff
allows the CF game driver to reinitialize its own powered adapter. IGR's CDVD
shutdown releases the CF device before resetting the IOP. These lifecycle paths
are implemented and modeled in host tests; cold/repeat boot, IGR return, Mode 6,
FMVs and card removal must still be verified on actual early consoles.

## DESR DVR switch

**DESR DVR ISOs (experimental)** is also off by default. Enable it and the HDD
source to permit the existing read-only DESR scanner. Hardware detection remains
mandatory; the toggle cannot make a normal PS2 a DESR. Launch still requires the
external DVR-capable Neutrino described in DESR-DVR.md.

## Provenance

The CF driver and transfer tests are adapted from mihhru/PS2CF 1.0, pinned at
9b6ed3702b59a87512426952e003125a5b4f0e3c. The driver keeps its original component
notices and PS2SDK AFL-2.0 license. PS2CF's OPL work is AFL-3.0. This integration
imports no firmware, FMCB card images, game data or GPL mymc tooling.

Failed CF detection is attempted once per explicit request. Changing the CF toggle permits another attempt (Refresh does not: a CF page only exists once the driver has loaded); unrelated hotplug events do not. NBD cannot run while CF owns the PC CARD slot. Restart OPL with CF disabled to use the PC CARD network adapter. An IOP reset alone does not release CF bus ownership.
