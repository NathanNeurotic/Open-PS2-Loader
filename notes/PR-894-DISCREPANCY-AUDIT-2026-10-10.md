# PR 894 discrepancy inventory — October 10, 2026

Review only. No production fixes, commits, pushes, review requests or merges were
performed for this audit. The user requested discrepancies before a fixing plan.

## Scope and exact state

- PR: https://github.com/NathanNeurotic/Open-PS2-Loader/pull/894
- Local and published head: `4d855301c20ffe7c1eda2cddc2a9e2790b7fce6d`.
- Base `rebuild/main`: `8fae5f19807466ce31fa7424969d00be42e66aa3`.
- 123 changed files, 7,469 additions and 903 deletions; 74 source/header/build
  files under src, include, ee_core and modules were included in source review.
- Review covered storage refresh/readiness, PS1/PS2 launch paths, module ownership,
  watch/hash identity, network discovery and handoff, event transport, browser,
  production versus experimental graphics, settings, themes, CI and documentation.
- All 14 returned inline review threads are resolved. The latest CodeRabbit
  review submission is on `148f7aedf6ec00d447638bb9fc9e71cf62f57010`, not this head;
  its state is COMMENTED, not APPROVED. Resolution is not current-head approval.
- Current-head build-flavours and both Korium workflows succeeded. Formatting
  failed. GitHub reports open, mergeable, mergeable_state=unstable.
- A pre-existing local whitespace-only change in src/opl.c:4918 corrects the
  formatter failure. It remains uncommitted. Existing untracked build material
  was preserved. This audit adds this note and local counterexample material.

## Confirmed discrepancies in added RA behavior

### R1 — P1: PS1 preparation checks an address, not launch network readiness

Locations: src/rapopslaunch.c:40; modules/network/rapops/rapops.c:106-109;
modules/network/smap-ingame/smap.c:118-263; src/ranet.c:723-736 for comparison.

After a successful support check, disconnect Ethernet while the menu stack
retains a static IP. raPopsPrepare still writes MODULE_9.IRX: ethGetNetConfig
reports configuration, not physical link. Unlike raLaunchNetworkUp on PS2, the
PS1 path checks neither NetMan link status nor DHCP completion. The injected
module starts SMAP synchronously. Its PHY negotiation can retry indefinitely
without a cable. Optional achievements can therefore prevent POPStarter startup
rather than leaving a normal untracked game.

The local prepare counterexample compiles the production preparation function
with the existing PS1 fixture's valid-address stub. It installs the module
without consulting link/DHCP readiness. The indefinite-wait consequence follows
the SMAP source; it has not been reproduced on a console in this audit.

### R2 — P2: PS1 Caduceus launches skip the promised per-launch session check

Locations: src/rapopslaunch.c:17-73; modules/network/rapops/rapops.c:125;
src/ranet.c:738-760; docs/RETROACHIEVEMENTS.md:32.

With a saved, guarded watch list and a usable IP, PS1 preparation does not probe
the Caduceus session before installing telemetry. The bridge probes later in
raudp discovery, after POPStarter has already loaded the instrumentation.
PS2 explicitly verifies the session before handoff and clears the watch list
when offline. The documentation's claim that every tracked Caduceus launch
rechecks its session and boots uninstrumented when offline is consequently false
for PS1. This is separate from R1: a live Ethernet link can have an offline session.

### R3 — P2: explicit Xerabora host pin is lost in the POPS launch ABI

Locations: modules/network/common/rapops_cfg.h:23;
src/rapopslaunch.c:63-72; modules/network/rapops/rapops.c:125;
modules/network/raudp/raudp.c:799,1198-1202.

The EE prepares cfg->host from the verified/configured peer, but rapops_cfg has
no explicit-host flag. rapops emits only '1' or '3'. RAUDP's bit 4 is therefore
always clear for this launch path. Xerabora active discovery selects broadcast
instead of the configured unicast host. A different responder can win, and a
host across a router will not receive the broadcast. PS2 carries the bit correctly.
The compiled production flag assignment yields flags=1, pinned=0.

### R4 — P2: routed active discovery requires the remote host's ARP entry

Locations: modules/network/raudp/raudp.c:769-775 and 858-861.

For a configured off-subnet peer, IP routing resolves the gateway's MAC, not the
remote PC's MAC. Passive SMB/HTTP discovery handles this. Active discovery only
accepts RAO1 when etharp_lookup_mac(peer_ip) succeeds. A valid reply through the
gateway therefore never completes discovery for USB/MMCE/POPS active telemetry.

A compiled production ra_discover counterexample supplies a valid remote RAO1
and only gateway ARP. Passive returns 1. Active continues retrying until the
fixture's bounded escape. This remains a host network simulation, not hardware proof.

### R5 — P2: verified-peer cache saves only the first SMB IP octet

Locations: src/ranet.c:141,161,168; include/opl.h:119;
.github/scripts/test_ra_verified_peer.py:43.

Production pc_ip is int[4], but its cache is u8[4]. memcpy/memcmp of four bytes
cover only pc_ip[0] on PS2, ignoring the last three octets. Remembering peer 42,
then changing pc_ip[3] from 10 to 11, still returns peer 42. The existing test
substitutes u8 pc_ip[4] and therefore incorrectly passes this very scenario.
Network-page Apply explicitly forgets the peer, so the common UI path mitigates
this; the cache's independent settings-binding guarantee is still broken.

## Inherited Ember/PS1 hardening gaps relevant to Vapor

These are present in the base commit too. Do not describe them as regressions
introduced by this PR or as a proven explanation for Vapor's console.

### E1 — P2: scan errors become successful empty/partial enumerations

Locations: src/cuesupport.c:155-161,225-226,240-257.

A child folder opendir failure is treated as 'not a game'. Neither the parent
nor child readdir loop distinguishes error from end-of-directory. With a readable
core and Tomba!/CDROM.CUE, injecting EIO for the child open returns zero games;
injecting EIO in the parent enumeration also returns zero. Successful reads that
end early can similarly publish a partial list. In addition, when both the core
and games directory cannot open, !coreReadable forces an empty result regardless
of the directory error. That last behavior intentionally protects legacy drivers
that collapse not-found errors; hardening must preserve that compatibility.

### E2 — P2: failed Ember half plus empty POPS half discards the previous list

Location: src/cuesupport.c:840-868.

ps1FillGameList downgrades either failed half to zero. If the other half is
genuinely empty, total becomes zero, the old list is freed and success is returned.
The comment then incorrectly says both scans reached the device. A production
function fixture with POPS=0, Ember=-1 and an existing row returns 0 and NULL.
Publishing one successful nonempty half remains valuable; preserving that behavior
must be considered separately from the empty-plus-error case.

### E3 — recovery gap: PS1 scan failure does not schedule bounded recovery

Locations: src/bdmsupport.c:1536-1560,1606-1612,1663-1671.

The PS1 path scans on connect/view/manual-refresh events and preserves its old
count for a negative result, but has no separate failed/partial PS1 scan state or
bounded retry. A never-populated list can remain empty until another explicit
event. The L3 dirty fix makes that action reach the scanner; it does not distinguish
a failed filesystem operation from an empty successful scan. Do not restore endless
idle rescans: prior queue starvation/spinner problems are documented in this code.

## Other coverage, documentation and integration discrepancies

- T1: the verified-peer test changes pc_ip's production type (R5).
- T2: gateway tests exercise only passive discovery. They do not cover active
  routed replies (R4). The POPS builder's actual flag-to-parser contract is missing (R3).
- T3: the PS1 'offline' preparation fixture models ethGetNetConfig returning -1.
  It does not model a retained IP with cable disconnected, pending DHCP, or an
  offline Caduceus session (R1/R2).
- T4: the exact Vapor-layout fixture supplies successful directory reads. It is
  evidence for path/extension acceptance, not device readiness or read recovery (E1-E3).
- D1: docs/RETROACHIEVEMENTS.md:341 still says HDD/APA support checking refuses,
  despite the new raw HDL hasher. Row 11 is also duplicated in that test table.
- D2: docs/RETROACHIEVEMENTS.md:415 says PS1 browsing directs users to the account
  library, but menuOpenSelectedVcdAchievements now requests a selected USB VCD hash.
- D3: include/hdl_layout.h:3 describes lengths as logical sectors. Production
  and existing CDVDMAN actually divide part_size (bytes) by 2048; part_offset is
  a logical sector and data_start is a raw 512-byte sector. This is a comment error,
  not evidence that the hasher's current conversion is wrong.
- D4: modules/network/common/ra_snap.h:85 documents only flags 0..3 and omits bit 4.
  RAUDP's parser comment also says netmask/gateway are unused although it now uses them.
- D5: new PS1 refusal/module-hygiene dialogs contain hardcoded English. They are
  outside the otherwise localized RA notice paths; language-isolation tests do not
  establish complete localization.
- I1: PS2 Favorites still lack itemGet/itemGetPrefix and fall through the support
  action without a notice. USB VCD Favorites receive explicit source resolution.
  This is inherited behavior, not a newly introduced regression, but the route
  parity claim needs to stay limited to the paths actually handled.
- I2: POPS module/thread startup error handling is weaker than the PS2 RA path:
  rapops ignores start_buffer results, start_rapull retains its allocated list
  when reader startup fails, and rapull ignores StartThread's result. Optional
  startup failure can retain unused IOP resources. This is a source-observed
  integration risk; no console memory-exhaustion consequence is claimed here.
- I3: passive SMB/HTTP transmission to a separate same-subnet RA companion relies
  on that peer being present in the *new in-game* ARP table. The menu's discovery
  does not carry its MAC through the IOP reset, and passive discovery issues no
  ARP query. A different SMB server does not guarantee that entry. Verify this
  topology; do not treat dedicated-host menu tests as end-to-end proof.
- C1: current-head format CI fails on spacing of the new src/opl.c:4918 comment.
  The existing local whitespace correction is not part of the published PR yet.
- C2: PR validation prose links e13e31ae and an old artifact. It explicitly names
  that checkpoint, but it is not a current-head acceptance record. Final validation
  wording/artifact references will need refreshing after the eventual fixes.

## Report status and remaining acceptance gaps

- Vapor Ember non-listing remains unresolved. The maintainer reports the same
  known working setup on a fresh properly formatted USB drive also failed for him,
  and knows of no independent reproduction. That weakens a simple layout/format
  explanation but does not identify a firmware, USB-controller or console defect.
- Missing CFG metadata can explain absent Genre/Developer/Description in the
  screenshot, independently of game discovery. Fresh defaults/title fallback have
  code and host evidence; the tester's current visual acceptance is not established.
- Physical power-button no-action report remains open. Latch/state/thread fixes
  address source defects, but they do not prove resolution after extended gameplay.
- Intermittent Neutrino reset is explicitly unverified in the PR body.
- Korium background comparison artifacts built; the photographic/root-cause
  question remains unresolved without the controlled console/display comparison.
- USB FAT32/exFAT PS1 startup, memory acquisition after 25 seconds, legitimate
  unlocks, normal/Favorites/remembered launch parity and cleanup remain console gates.
- Real APA hash performance, Caduceus end-to-end sessions, passive SMB/HTTP notices,
  shared NIC ownership and IGR/power behavior need their applicable hardware checks.
- PS1 scratchpad, frame synchronization and POPS cache/SIF behavior are explicitly
  documented limits. Experimental GS card DMA remains disabled by default; its
  unsafe transfer-ownership problem is not reopened as an enabled production defect.

## Validation performed for this audit

- Ten existing host scripts passed: verified peer, client mode, Caduceus host,
  launch resources, browser, L3 rescan, Ember scan, HDD lifetime, language switching
  and theme metadata. They do not cover the counterexamples above.
- `python build/pr894-discrepancy-audit.py` compiled production functions/expressions
  and reproduced R1/R2's missing preflight gates, R3, R4, R5, E1 and E2.
  The script uses local fake filesystem/network/IOP configuration inputs and writes
  only inside build/pr894-audit-tmp. Its expected observations are bugs, not passing
  regression tests or proof of hardware root cause.
- git diff --check against the base passed. No new build was required for this
  read-only audit; live CI results above are tied to the exact published head.
- No implementation/fix plan is adopted yet. This inventory is the input to the
  requested next planning step. A review cannot prove absence of further defects.

Live workflow evidence:

- Build and host groups: https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/38066948187
- Format failure: https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/38066948175
- Korium PR build: https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/38066948172
- Korium comparison: https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/38066948199


## Authorized remediation checkpoint - October 10

The initial sections above record the review before implementation. The user
subsequently requested fixes on the existing PR. The remediation keeps #894 as
the single review surface and does not merge or publish a release.

- R1/R2/T3: POPS now calls the shared PS2 link/DHCP/Caduceus preflight before
  testing the reserved module slot. Disconnected/static-IP, pending DHCP and
  offline-session counterexamples boot without installing optional telemetry.
- R3/T2: the embedded POPS configuration carries host_pinned; the real IOP
  builder emits all four Xerabora/Caduceus and automatic/pinned flag combinations.
- R4/T2: active and passive discovery share next-hop MAC resolution. Gateway
  substitution still requires a known mask and an off-subnet peer.
- R5/T1: the verified SMB cache and fixture use production int[4]; every octet
  is covered by the settings-binding regression.
- E1/T4: explicit parent/child open/enumeration failures discard the incomplete
  temporary scan. ENOENT/ENOTDIR and legacy collapsed child-open errors remain
  non-game entries; missing-core legacy EPERM/no-errno roots remain empty.
- E2: failed-half plus empty-half retains the previous list; a nonempty readable
  half still publishes, preserving the FifthFox compatibility correction.
- E3: BDM retries failed/partial PS1 scans at most twice on the existing idle
  cadence. Successful recovery stops retries; SELECT/L3 rearms them. PS2 scan and
  module-load retry policies are unchanged.
- I1: PS2 Favorites resolve a current source view and validated row identity
  before support checks; unavailable/stale rows receive a notice.
- I2: POPS validates network dependency/sender starts, allocates proportional
  snapshot capacity and releases failed reader-list allocations. Failed module
  start unloads its buffer. RAUDP/rapull delete dormant threads after failed
  starts; RAUDP also releases its exports. Reader setup failure releases its
  transferred list. A resident sender retains its snapshot if its reader fails,
  avoiding a dangling pointer; this is bounded to the game IOP lifetime.
- I3: passive discovery sends at most one successful raw ARP request for a
  missing peer/next hop. A busy transmitter defers the request within the bounded
  poll window. The game's stack owns reception and learning; no sockets/RX
  descriptor walking are added to the passive path.
- D1-D5/C1: corrected HDL units, support-check/browser docs, unique test numbers,
  flag/routing comments, localized shared PS1 dialogs and the formatter failure.
- C2: PR validation metadata is refreshed after exact-head CI; historical
  artifact/checkpoint links are not represented as validation of these fixes.

New production-code counterexamples are committed in
.github/scripts/test_pr894_hardening.py and run in RA CI. Existing scan, discovery,
verified-peer, POPS and BDM tests cover the new branches. Windows host checks skip
only the real-filesystem badge test because Windows cannot create PS2 colon paths;
Linux CI runs that fixture in full.

Remaining acceptance: Vapor's console report, PS1 POPS/DEV9 compatibility, cable
loss during the post-reset SMAP negotiation, actual companion/ARP interoperability,
25-second memory acquisition/unlocks, FAT32/exFAT startup, IGR/power, Neutrino reset
and Korium display comparison require console evidence. Preflight prevents the
confirmed stale-link injection path; it cannot eliminate a cable pull after the
check. These reports are not marked resolved by host tests or build success.
