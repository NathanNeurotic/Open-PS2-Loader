# mbedTLS 3.6.7 (vendored subset)

TLS for the RiptOPL **RetroAchievements edition** only: the HTTPS game-ID lookup on
retroachievements.org that ORBIT also performs. Standard and Korium builds do not compile or link it.

- Upstream: <https://github.com/Mbed-TLS/mbedtls>, release **mbedtls-3.6.7** (3.6 LTS), 2026-07-07.
- Source: the release archive `mbedtls-3.6.7.tar.bz2`, not the git tag, because only the archive
  carries the generated sources (`library/psa_crypto_driver_wrappers_no_static.c`, `library/error.c`,
  `library/version_features.c`, `library/ssl_debug_helpers_generated.c`).
- Archive SHA-256: `a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6`
  (matches `mbedtls-3.6.7-sha256sum.txt` and the release notes).
- Vendored: `library/`, `include/` and `LICENSE`, byte-for-byte. Nothing else from the archive.
- Configuration: `riptopl_mbedtls_config.h` (RiptOPL's own file), passed with `MBEDTLS_CONFIG_FILE`.

## Licence

mbedTLS is dual-licensed `Apache-2.0 OR GPL-2.0-or-later`. Used under the Apache-2.0 licence.
RiptOPL takes no GPL code. The licence text is `LICENSE`; the RA release package ships it as
`LICENSE-MBEDTLS.txt` next to the ELF.

## Updating

Download the new release archive, check its SHA-256 against the release notes, replace `library/`
and `include/` wholesale, update the version and hash above, and run
`.github/scripts/test_mbedtls_vendor.py` plus the RA host TLS test.
