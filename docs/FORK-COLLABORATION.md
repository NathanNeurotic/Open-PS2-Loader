# Learning across PS2 loader projects

RiptOPL and RIPPS2 exchange useful UI and backend work. Preserve attribution and compare the
actual source and runtime contract before calling a difference a gap. Other projects, including
LUNA, YAOPL and upstream OPL, can provide equally useful correctness and design references.

The [current fork report](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html)
provides pinned revisions, stable record IDs and a deduplicated capability list. Its October 25
snapshot covers 128 previously tracked repository identities and six newly created upstream
forks. A source-head sweep is bounded evidence, not an exhaustive search of all PS2 development.

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

## October 28 status

[Fork-gap status: 2026-10-28](FORK-GAP-STATUS-2026-10-28.md) supersedes the status of the table
below. In short: the RIPPS2 audit of build 119 (`95299389`) credits **akilluminati47** for its
findings, and the owner agreed a port plan (PRs A to H) on 2026-10-28 in which every port lands in
both this repository and [RiptOPL](https://github.com/NathanNeurotic/RiptOPL). The MMCE busy wait
and RIPPS2's artwork aliases are in that plan (PRs A and B); external-Neutrino option detection is
not scheduled. The pad fixes and the `imgdrv` rename were declined, as were disc ripping, the CD
player and every HDD partition change. No port PR is open yet, and nothing is tested on hardware.

## October 25 candidate triage

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
