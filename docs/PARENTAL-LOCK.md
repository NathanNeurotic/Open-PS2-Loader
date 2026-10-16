# Per-game parental lock

Set a parental lock password in Settings, then open a PS2 game's Compatibility settings and enable **Parental Lock**. Save the game settings. RiptOPL stores `$ParentalLock=1` in that game's CFG. The toggle is off when the key is absent. Saving a lock without a configured password shows a warning; the lock becomes effective when a password is configured.

A locked game asks for the password on every launch, including from Favorites and Last Played autostart. Unlocking the settings menu does not authorize later game launches. Cancel or an incorrect password keeps the user in the menu before automatic VMC creation or game teardown. The selected startup is checked again after the modal prompt to avoid launching a replacement row after a device refresh.

**Test Changes** checks the stored lock before applying unsaved edits, so testing an unsaved unlock still requires authorization. A newly enabled test lock also prompts. Command-line HDD/BDM shortcuts have no initialized password UI: locked shortcuts return to the normal menu rather than launching. The existing master-password recovery behavior remains available. Removing game settings also removes the per-game lock key.

Adapted from Tom Weeks' official OPL [PR #1779](https://github.com/ps2homebrew/Open-PS2-Loader/pull/1779), commit `154fb8aff228221f46d17d79b96eec4a61699bdb`, with coverage for this fork's test-launch and command-line paths. The fork already disables the Last Played countdown after one attempt, so the upstream countdown workaround is not duplicated.

Host regressions compile the production password policy and Test Changes function against controlled UI/config callbacks. They exercise repeated prompts, cancellation, wrong/correct/master passwords, unsaved lock removal, newly locked test settings, allocation failure and no-password behavior. Integration checks cover normal launch ordering, Favorites config forwarding, shortcut fallback and one-shot autostart. Linux CI enables ASan/UBSan. Console UI, controller input and launch behavior remain to be verified on hardware.

Removing a stored game lock through Save Changes or Remove Settings requires fresh game-lock authorization. A cancelled or incorrect password leaves the live configuration and both save writes untouched. Test Changes refuses the launch if a temporary config cannot be allocated; it never applies test edits to the live config as a fallback.
