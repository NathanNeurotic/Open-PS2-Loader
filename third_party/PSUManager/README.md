# PSUManager core (vendored)

The files in `src/core/` are copied without modification from
[PSUManager](https://git.techwritescode.dev/techwritescode/PSUManager) by
**techwritescode**, at upstream commit
`6c4d371ebda0709814c87c4b01f9a1a5b817c71b`. They are dedicated to the
flat PlayStation 2 `.psu` save format; the GUI, platform integration, and
installer are outside the release packager's scope. The upstream project is
made available under CC0 1.0 Universal; see [LICENSE](LICENSE).

RiptOPL's release packager writes deterministic timestamps into
`APP_RIPTOPL.psu` and `APP_RIPTOPL-RA.psu`. The independent C++ validator in
`.github/scripts/verify_psu_with_psumanager.cpp` loads each save through this
vendored core and compares every member byte for byte with the corresponding
direct `APPS/APP_RIPTOPL*` folder before packaging. Keeping the upstream reader,
writer, date code, and tests here also preserves the format implementation for
future maintenance. This code runs on the release host; it is not linked into
the PS2 ELF or included in installable ZIPs.
