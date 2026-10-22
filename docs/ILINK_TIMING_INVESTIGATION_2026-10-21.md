# i.LINK launch investigation — October 21, 2026

Baseline: `rebuild/main@2808a4cd579e4294c520e35149bbfc87d79cce45` (Beta 4202).
Related issue: [#1018](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/1018).
No reliable historical working baseline is assumed: the maintainer clarified that earlier successes
were intermittent and i.LINK launching has never been reliable on the reported setup.

## Result

Two copies of the shipped SBP-2 driver have a reproducible completion-ordering defect before the
first game read. A successful LOGIN leaves its response in the shared `statusFIFO`.
`ieee1394_InitializeFetchAgent` then publishes a dummy ORB and calls `ieee1394_Sync` without clearing
that old response. The wait can return on LOGIN's status and free the dummy ORB while the target
has not yet completed it. That is a source-confirmed lifetime race. Its role in FifthFox's failures
is not hardware-confirmed.

The initialization function also ignores the result of its wait and reports success after a failed
dummy completion. These defects are not repaired by extending the existing login budget or by
slowing game-visible CD/DVD completion.

The focused correction in this branch:

1. Clear the old FIFO **before** publishing the dummy ORB. Clearing it afterward would erase a fast
   enclosure's real completion delivered inside `iLinkTrWrite`.
2. Keep the dummy request alive until the completion wait returns, and propagate its error.
3. Preserve command/data lifetime after ambiguous pointer-publication errors; safe recovery remains
   separate work, as described below.
4. Apply the same changes to native/Neutrino's vendored driver and POPStarter's separate older copy.

No fixed sleep, link-speed cap, new compatibility mode, or per-game delay is introduced by this
correction. It synchronizes to the target's actual response, allowing immediate and slower responses.

## What the chat establishes

- Build 4107 lists games; Ember works; native OPL shows its PS2 logo but does not reliably launch;
  Neutrino and POPStarter also fail.
- Earlier native launches sometimes succeeded with the logo and compatibility modes. The older
  October 2 handoff records a Madagascar test with modes 1/3/6, a later drive swap and a Jak and
  Daxter test with four unspecified modes. These are not a reproducible baseline, per the
  maintainer's latest clarification.
- FifthFox **already tried Mode 8 in build 4121 and it failed**. He reports it is too slow and asks
  for adjustable speed or delay. Recommending Mode 8 again would ignore that result.
- Different drives/enclosures remain relevant. Their different response latencies are one reason
  a stale-response race could appear intermittent; this is an inference, not a measured explanation
  of this particular enclosure.

## The menu, logo and game do not share one continuous driver session

The menu reads through iomanX/BDM/FatFs. Native launch records the driver/device binding and passes
the fragment map to the embedded core. The EE core's `sysLoadElf` resets the IOP and reloads iLinkman
and IEEE1394_bd. The BDM CDVD driver waits for the selected raw device before servicing disc reads.
Native PS2LOGO is another loaded executable: its subsequent transition to the game reenters the
loader/reset path. Games can also request their own intercepted IOP resets.

Thus listing proves the menu read path works; it does not prove that each reconstructed session
finished the fetch-agent handshake or can read subsequent game sectors. The new test specifically
exercises the source boundary between LOGIN and the fetch-agent request.

Sources: `src/bdmsupport.c:2621`, `:2745`, `:2817`; `src/system.c:2773`;
`ee_core/src/main.c:163`; `ee_core/src/syshook.c:91`; `ee_core/src/iopmgr.c:247`;
`modules/iopcore/cdvdman/device-bdm.c:186` (line numbers at the baseline).

## Why Mode 8 did not test a startup delay

`cdvdman_read_sectors` schedules the Accurate Reads timer, immediately calls the storage reader,
then waits for the timer after the read if necessary. Mode 8 selects 81,920 IOP ticks per disc sector
and limits chunks to eight disc sectors; Mode 1 uses 33,512 ticks for DVD. Neither inserts a delay
before the first underlying request. `ProbeZSO` also reads the initial raw sector before this pacing
loop. A command that never completes prevents the loop from reaching its completion wait at all.

Sources: `modules/iopcore/cdvdman/cdvdman.c:281`, `:299`, `:359`, `:375`, `:409`.

Consequently, an adjustable first-read delay, inter-command interval, and minimum game-visible
read duration would be three different experiments. The present correction addresses a demonstrated
handshake/lifetime fault first. It does not establish that no timing option will be needed later.

## Link speed was checked separately

The vendored POPStarter manager and PS2SDK iLinkman at pin `329e2bb4` already cap transactions at S100
when the PS2 is the bus root. The block driver derives command speed and payload from its allocated
transaction. A generic claim that the existing root-node S100 workaround is missing would be wrong.
The actual speed, payload and topology of FifthFox's failed launch have not been measured.

Pinned source: [PS2SDK iLink.c](https://github.com/ps2dev/ps2sdk/blob/329e2bb43287e16af16c4dde1c614e2662c24468/iop/iLink/iLinkman/src/iLink.c).

## Reproduction and validation

`python .github/scripts/test_ilink_sbp2_completion.py` compiles the production initialization,
submission, fetch-agent reset, status parser and wait functions from **both** driver copies. It tests successful
dummy responses at 50 us, 500 us, 20 ms and 250 ms, a response arriving during pointer publication,
failed dummy status, stale successful LOGIN status, exhausted submission retries, a lost pointer
acknowledgment with failed resets and a later real completion, a missing dummy completion, and
successful and failed regular commands. Dummy success uses SBP-2 status 0x0b, already accepted by ProcessStatus.

Against the unchanged baseline, the final fixture reproduces twelve failed assertions in each driver: accepting
stale status, early request-buffer release, false initialization success, and releasing a dummy
request whose completion never arrived. After the fix the fixture and existing reconnect/readiness fixtures pass.
The host guard escapes the simulated endless wait; it is **not** a production timeout.

Commands:

```text
python .github/scripts/test_ilink_sbp2_completion.py
python .github/scripts/test_ilink_bd_reset.py
python .github/scripts/test_ilink_bd_assault_reset.py
python .github/scripts/test_bdma_shipped_pairs.py
python .github/scripts/test_bdma_stale_pair.py
python .github/scripts/test_accurate_read_rate.py
```

Full/mini IEEE1394_bd and POPStarter's combined driver build in the exact CI container
`ghcr.io/ps2dev/ps2dev@sha256:8fba50ecc2229acd7f8da63d34302f12939b7d4fa6848dda1e6a0ce083321a11`.
All three checked-in POPStarter copies and the size validator are updated to that build:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| IEEE1394_bd.irx | 11177 | `8d14f0e64ed40c6151db835de9c524c078f2d012632326d72cc4ed746d9a4f4e` |
| IEEE1394_bd_mini.irx | 7089 | `da1b581b6adcc7c171e846224dac8e844d55d4b1afe4b48f042ba595ddded895` |
| usbhdfsd.irx.ilink | 22025 | `aec8f3d6b15af7024bb62120488ed1b83526c4f852add6161185a1232017edc2` |

These are host/build/package results. No console or game acceptance is claimed.

## Remaining boundary and console check

An accepted command whose status never arrives still has an unbounded wait in the driver. Returning
after an arbitrary timeout without aborting/quiescing the target could leave it accessing a released
ORB or reused data buffer. This branch does not introduce that unsafe timeout. ORB identity/status
correlation and safe recovery from a lost completion remain separate work if the controlled test
reaches that failure.

The earlier draft also returned immediately when all command-pointer writes reported failure.
Final review removed that change: iLinkman's `iLinkPHTSendData` can return a split timeout or missing
acknowledgment **after starting the transaction**. That is not proof the target rejected the pointer.
Its fetch-agent reset error is also only logged. Returning could therefore release the stack ORB
and let callers reuse a data buffer still accessible by the target. The fixture now reproduces
this accepted-but-unacknowledged case with failed resets and a delayed completion; the earlier
draft fails three assertions per driver, while the narrowed correction preserves the request.
The original no-completion wait remains until recovery can prove target quiescence. No new
production timeout or speculative reset/recovery mechanism is added.

Manager source: [pinned PS2SDK iLink_DMA.c](https://github.com/ps2dev/ps2sdk/blob/329e2bb43287e16af16c4dde1c614e2662c24468/iop/iLink/iLinkman/src/iLink_DMA.c),
with the same path in POPStarter's vendored manager. This review does not establish enclosure behavior.

Test this one candidate with the same drive/enclosure and game, first native OPL with the same
settings and Mode 8 off. Repeat launches to distinguish intermittent success from reliability.
Record logo off/on separately. Test Neutrino using the matching replacement mini module and
POPStarter using the matching updated pair; neither core's result proves the others.
Do not mix these driver changes with new delays or automatic persistent mode selection during the
first comparison. If this candidate still fails, record the last completed stage before selecting
the next timing experiment. Keep #1018 open until gameplay is verified for each affected core.
