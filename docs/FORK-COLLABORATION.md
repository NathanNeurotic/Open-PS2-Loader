# Learning across PS2 loader projects

Current comparison: [Full ecosystem fork-gap refresh - October 29, 2026](FORK-GAP-FULL-REFRESH-2026-10-29.md) (301 provenance records; 152 stable families). Source/branch/release evidence and console acceptance are recorded separately.

RiptOPL and RIPPS2 exchange useful UI and backend work. Preserve attribution and compare the
actual source and runtime contract before calling a difference a gap. Other projects, including
LUNA, YAOPL and upstream OPL, can provide equally useful correctness and design references.

The [current fork report](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html)
provides pinned revisions, stable record IDs and a deduplicated capability list. The
[October 29 ecosystem reconciliation](FORK-GAP-ECOSYSTEM-AUDIT-2026-10-29.md) checks 141 repository identities
(138 canonical repositories), current release metadata and wrapper dependency pins. Its
292 provenance records include overlap, experiments, tools and intentional alternatives;
they are not counts of defects or promised ports. Unchanged source findings retain their
earlier assessment dates. No new physical-console evidence was obtained.

## Evidence to retain for a candidate

| Evidence | What it establishes |
| --- | --- |
| Exact commit, numbered patch and imported upstream pin | Which implementation was examined and which changes are shared ancestry |
| Release tag and release API metadata | What was published; beta wording and GitHub prerelease status can differ |
| Host test with actual extracted functions | A bounded behavior under its fixtures; keep compiler skips and environment failures visible |
| Target build | Toolchain, symbols and packaging fit; not console timing or game acceptance |
| Emulator/lab observation | Behavior in that environment; retain emulator and setup details |
| Physical-console report | The specified console, device, firmware, game and steps; not universal compatibility |

An older plan can disagree with newer source. A README-only release announcement is weaker
implementation evidence than a source diff. A new fork's name does not prove the named feature
exists. A count of commits includes merges, tests and shared fixes; it is not a feature count.

## Current reconciliation — October 29

The [current audit](FORK-GAP-ECOSYSTEM-AUDIT-2026-10-29.md) supersedes availability wording in the
[October 28 historical status](FORK-GAP-STATUS-2026-10-28.md). RIPPS2 integration
A–H is merged in both editions (RiptOPL #99 / legacy #1084), as are Grid/multi-view
themes, the YAOPL hardening batch (#142 / #1114), and native OPL UDPBD/UDPFS IMG
launch support (#153 / #1123). The exact current source baselines and pending PR heads
are pinned in the audit; merged source does not establish console acceptance.

RIPPS2 release 121 and development build 124 are reviewed separately. LUNA must be
followed through its wrapper gitlinks: frontend `luna@f640a4e8` is newer than the
unchanged tracked `main` branch. YAOPL task numbers differ between the two planning
handoffs; match mechanisms and merged commits, not unchecked boxes or numbers alone.

Disc ripping, the CD player and HDD partition changes remain declined local scope.
The magnified single-pass HD renderer and external-only runtime packaging are
intentional design alternatives. The withdrawn [YAOPL](https://github.com/yaopl/yaopl) remap is deferred; read-only
UDPBD requires coordinated capability/write/VMC policy. Preserve [akilluminati47](https://github.com/akilluminati47),
[belomaxorka](https://github.com/belomaxorka), [dnunezx](https://github.com/dnunezx), juankyt505, Blayr and other original authors in any future work.

## Historical October 25 candidate triage

This table records the earlier research leads. Current merged/partial/declined dispositions
are in the October 29 audit; do not revive a completed or declined item from this table.

| Candidate | Practical next work | Main regression risk |
| --- | --- | --- |
| RIPPS2 artwork aliases | Define precedence for existing names, OPL Manager aliases and PS1 IDs; keep exact directory names and bounded negative lookups | Extra network IO, ambiguous aliases, stale artwork index |
| RIPPS2 external-Neutrino option detection | Reconcile known versions and explicit overrides with our existing argument preflight and ORBIT integration | Rejecting a working fork or sending unsupported options; its unknown/packed fallback remains permissive |
| RIPPS2 MMCE busy/launch waiting | Compare firmware contracts and history/GameID ordering; define timeout and cancel behavior before implementation | Indefinite waits, controller starvation, writes to the wrong emulated card |
| RIPPS2 library snapshots and recent page | Separate persistent cache, refresh policy, source identity and lazy launch | Stale lists and launching from a different replacement device |
| YAOPL hardening/MMCE | Reconcile individual fixes and tests against current RiptOPL; identify already-shared fixes first | Duplicating fixes or changing active SIO2/IGR contracts |
| OPL-volume proof of concept | Build and inspect SPU2 ownership, RPC reset/rebind and GS DMA scheduling first | Game audio writes, active-framebuffer races and rendering interference |

Storage deletion, conversion, save/card management and in-game overlays require separate review
from cosmetic UI work. Preserve existing-file safety, recoverable staging and failure evidence;
do not import a large patch stack just to gain a small path or naming fix. Performance candidates
such as selective FreeType modules or magnified HD need measured size, memory and rendering
tradeoffs as well as language/theme compatibility checks.

## Sharing results

For a useful exchange, describe the original mechanism, its author and pin, the behavior in this
fork, changes needed for compatibility and the checks actually performed. Acknowledge a shared
fix once. Report a failed result with the same precision as a win: it narrows the next experiment.

Keep proposed ports in small reviewable PRs and leave merge decisions to the maintainer. Do not
close a hardware report because a host harness passes. This audit authorizes documentation
updates; its candidate list does not itself implement or validate any port.
