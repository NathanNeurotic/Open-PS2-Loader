# SIO2MAN hook compatibility

VMC and controller emulation keep independent original callbacks for the v1 and v2 SIO2MAN export layouts. The SDK driver is embedded when MX4SIO, VMC or PADEMU needs it, and loaded before the block driver and emulation hooks. Existing module IDs are preserved. Game libraries registered later use the same version-aware hook installation.

When SDK export entries alias the same original function, the hooks update every alias and retain the actual original callback rather than chaining a hook back into itself. Installing the same hook twice leaves its saved originals intact. The MX4SIO block driver still requires a successful SIO2MAN load.

Adapted from Julian Uy's official OPL [PR #1785](https://github.com/ps2homebrew/Open-PS2-Loader/pull/1785), commits `e87ba6898eda6531196da6201a23676cbf60c92d` and `7af5fdbed6d8a7927a99b839de10f4df78c074a3`, with a repeated-installation guard for this fork.

The host regression compiles production installation, alias replacement and wrapper functions for VMC and PADEMU. It checks simultaneous v1/v2 tables, original callback dispatch, aliased entries, replacement tables, repeated installation and missing entries. Linux CI uses ASan/UBSan. Target builds and these host tests do not establish console compatibility: VMC saves/loads, controller emulation and MX4SIO must still be exercised on hardware, including games that replace SIO2MAN after launch.
