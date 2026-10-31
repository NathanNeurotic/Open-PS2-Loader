# MX4SIO driver provenance

Source: ps2dev/ps2sdk, commit `2c670453980fcc3fe46ead6399b730b12c8556eb`,
`iop/sio/mx4sio_bd/src`. Copyright notices are retained; license: AFL-2.0 (LICENSE).

The runtime changes are the three retry corrections from PS2HomeDeveloper's
[ps2dev/ps2sdk#936](https://github.com/ps2dev/ps2sdk/pull/936), head
`a67be52bb285dd72998c86aba476d5fa3c516c57`:

- Advance the read sector by the completed sectors alongside the buffer.
- Pass the remaining count to the write begin/ACMD23 pre-erase hint.
- Advance the write sector by the completed sectors alongside the buffer.

The successful full-transfer path and public API are unchanged. Makefile is a
local adaptation for installed SDKs and separate full/mini object directories.
RiptOPL also defines local ps2build targets; release and debug builds both embed
these sources, replacing the SDK binary. This does not replace POPStarter's
separate BDM Assault binaries or an externally installed Neutrino runtime.

Remove this temporary vendor once all supported build images/packages carry
these corrections and the retry regression passes against their source.
Host fault injection and target compilation do not establish SD-card/console
acceptance. Use a disposable VMC with backups for real-card save/readback testing.


Build portability adjustments: use SDK u32 for WaitEventFlag result storage,
and guard GCC optimization pragmas from Clang. No casts hide pointer-type errors.
