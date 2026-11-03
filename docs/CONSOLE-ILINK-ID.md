# Per-game console i.LINK ID

In a PS2 game's Compatibility settings, **Console i.LINK ID** optionally replaces the eight-byte console identifier returned by the native OPL engine's CDVDMAN. Enter exactly 16 hexadecimal digits, for example `0123456789ABCDEF`. Digits are in response-byte order, without reversal. Saving uses uppercase. Empty or `0000000000000000` uses the real console ID and removes the override.

The per-game CFG key is `$ILinkID`. Existing CFG files need no migration. Invalid input is rejected before settings are applied. An invalid manually edited value shows the existing localized invalid-ID message before launch, records a diagnostic, and uses the real console ID. Each launch initializes all eight bytes, preventing inheritance from the previous game.

This setting is available only for native OPL PS2 launches. It is disabled for Neutrino and PS1/POPSTARTER launches. The separately pinned RA/ORBIT runtime is unchanged. It does not change the existing Disc ID/DNAS setting, a storage drive's identity, firmware, or IEEE-1394 bus configuration.

The requester proposes using this for console-bound game content. Source and host checks verify the ID response; content decryption and game compatibility are NOT TESTED on hardware. This is not a demonstrated fix for Tales of Rebirth.

Reference behavior: [ps2max32/neutrino at 1bff25bcfa02e192f5b35cadbe53648786813974](https://github.com/ps2max32/neutrino/blob/1bff25bcfa02e192f5b35cadbe53648786813974/iop/cdvdman_emu/src/scmd.c): a nonzero configured ID succeeds without SCMD 0x12; zero uses hardware.

The implementation adds eight bytes to the common launch block. EE patching and every embedded CDVDMAN backend must be rebuilt together. It adds no IOP allocation, thread, polling, or per-frame work. Native GCC measurements show sceCdRI growing from 104 to 232 bytes of code.

Host coverage executes parsing, UI normalization, native responses, default hardware status, null status pointers, GUID/model helpers, next-game reset, backend layouts and patch-zone restore. Console acceptance must compare returned IDs with/without the setting, launch a second game unset, and separately test any console-bound content using backed-up copies.

