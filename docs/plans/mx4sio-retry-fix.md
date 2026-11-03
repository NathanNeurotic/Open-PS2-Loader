# MX4SIO partial-transfer retry fix

Status: implemented; host regressions and target driver builds pass.
**Not tested on a physical PS2 or SD card.**

The local driver applies PS2HomeDeveloper's [ps2dev/ps2sdk#936](https://github.com/ps2dev/ps2sdk/pull/936),
head `a67be52bb285dd72998c86aba476d5fa3c516c57`. Partial reads and writes advance
the sector alongside the buffer, and write setup uses the remaining count.
Source revision, license and build portability adjustments are recorded in
[ORIGIN.md](../../modules/mx4sio_bd/ORIGIN.md).

Make builds local full/mini drivers in separate object directories instead of
embedding the SDK IRX. RiptOPL's ps2build also embeds the local mini driver in
release and full driver in debug configurations. With the embedded driver fixed,
CDVDMAN permits four-sector MX4SIO VMC erase batches and still rejects short
counts. POPStarter's separate BDM Assault binaries and external Neutrino
installations are outside this change.

## Automated evidence

- `test_mx4sio_retry.py` compiles the actual production retry functions over a
  fault-injected sector device: 19 partial/zero-progress, exhaustion, recovery,
  begin/stop failure and zero-count scenarios. Restoring each of the three
  original bugs makes the executable test fail.
- `test_vmc_write_result.py` exercises the production MCEMU/CDVDMAN chain,
  including MX4SIO erase batches, negative errors and short counts.
- Both tests run in CI, with ASan/UBSan on Linux.
- Full/mini IRXs build with ps2build GCC and LLVM and the ps2homebrew Make SDK.
- The existing host: boot gate remains unchanged.

## Remaining console acceptance

Use a disposable VMC with backed-up saves. Record console, adapter, SD card,
exact ELF and build flavor. Create/format the VMC, save in a game, reboot and
load it again. Repeat saves/erases, verify neighboring saves, and copy the VMC
back to inspect filesystem/content integrity. Test existing and new VMCs.
Compare timings with the single-sector build separately from correctness.

Physical partial-transfer failure injection was unavailable. Host tests verify
retry bookkeeping, not SIO2 timing or real-card recovery. No speed improvement
or console acceptance is claimed.

Remove this temporary vendor once every supported SDK image/package includes
the correction and equivalent regressions pass against its driver source.
## SD write acceptance accounting

The imported transmit ISR counted a sector before testing the response token and
programming completion. It now counts only accepted, programmed sectors, so a
rejection cannot be skipped or turn a last-sector failure into full success.
The production ISR -> write transfer -> retry chain has 19 additional cases:
CRC rejection, write rejection and programming timeout at the first, middle and
last sectors, both transient and persistent. Restoring the old counting order
fails the executable regression. Together the retry tests exercise 38 cases.