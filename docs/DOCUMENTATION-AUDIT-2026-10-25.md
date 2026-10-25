# Documentation and fork audit — October 25, 2026

Source baseline: `rebuild/main` at `55261de1381ae70ecfdfb2054f9cafbcfcd586cf`.
Pages baseline: `20d21131f414080a07d9bd4303ea9a35f8b57a07`.
The [earlier October audit](DOCUMENTATION-AUDIT-2026-10.md) remains historical evidence.

## Coverage and method

The baseline inventory covers all 85 tracked Markdown documents and 36 website HTML pages,
2,576 local links and 674 external URLs. New documents and pages are added to the final check.
The scope includes README/release guidance, source references, historical plans and notices,
website navigation/search, and the wiki builder's guide and reference mappings. Structural
coverage is exhaustive for these tracked Markdown and top-level HTML surfaces; semantic
verification concentrates on current user instructions, changed features and the new fork work.
It does not establish the correctness of every historical statement or external project.

The final machine-readable [validation and inventory](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-10-25/validation.json)
records check results. The [fork report](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html)
retains exact source pins, comparison limits, every stable ID and separate release/development evidence.

## Findings and changes

| Surface | Finding and disposition |
| --- | --- |
| Fork comparison | Previous 248-record draft had not been published. Preserve it as dated evidence; refresh current work to 258 records / 118 capability/design families |
| RIPPS2 | Build 114 is released; Build 115 source implements several items still described as a plan. Reconstruct both exact trees and inspect/test the mechanisms separately |
| Discovery | Compare six newly created upstream forks. Add YAOPL and volume-overlay candidates; do not infer native CHD support from an unchanged branch's name |
| README | Add a direct diagnostic route and collaboration/evidence route; preserve the existing companion version pairing and generated catalogue ownership |
| Installation/core guidance | Add one guide tying package, actual core, transport, failing stage, recovery and controlled comparison together |
| MMCE | Explain runtime accessibility after GameID switching and capture firmware/card state; upstream failures do not prove our runtime has the same cause |
| Core-specific IGR | Keep standard Neutrino distinct from LUNA's modified runtime, native OPL and PS1 cores. Existing IGR guide remains the core-specific reference |
| Source checker | Normalize source-relative document names to POSIX paths. Windows previously misidentified four intentionally preserved upstream archive links as new failures |
| Missing draft artifact | Add the historical draft's missing validation pointer and produce current validation evidence; do not invent earlier successful publication |
| External links | Replace inaccessible RiptOPL #317 link with explicit historical text. Retain valid stargazers and historical artifact references with their context |
| Wiki | Add both new source references, diagnostic guide and homepage routes, then regenerate from committed source/Pages inputs |
| Search | Regenerate from the final HTML and check idempotence, rather than manually maintaining a second content list |

## Surface review

| Area | Review outcome |
| --- | --- |
| Home / getting started / installation / releases | Keep complete-kit versus loose-ELF distinctions, current standard/RA channels, default settings and support-file placement; add diagnostic navigation |
| USB / MMCE / HDD / PC CARD CF / DESR / SMB / network boot / HTTP / NBD | Preserve per-device, per-core and experimental boundaries. Add MMCE diagnosis context; do not copy RIPPS2's PC Card toggle policy into RiptOPL instructions |
| Game formats / ZSO / Neutrino / PS1 / VMC / cheats / RA | Retain format/core matrix, ORBIT versus standard runtime and paired-client requirements. No implication that a newer upstream release is a validated replacement |
| Controls / IGR / GSM / PADEMU / settings / favorites / themes / coverflow / languages / Unicode | Keep current controls/defaults and format-specific support. Distinguish RIPPS2-only controls, translation hashes, cache policy and artwork aliases from implemented RiptOPL settings |
| Troubleshooting / credits / historical plans | Expand diagnostic routing, preserve attribution and historical evidence. Do not remove useful links just because anonymous requests are blocked |
| Wiki mappings / aliases / source-section references | Regenerate with the owned builder; retain existing page names and anchors, and validate all generated internal links |

## External reachability

The 674-URL baseline sweep observed 556 HTTP 200, 95 HTTP 429, 18 HTTP 403,
three HTTP 404, one HTTP 503 and one unresolved request. These are observations of that run,
not a statement that 118 links are broken. Rate limits/access errors remain inconclusive.
The issue #317 URL also returns an authenticated API 404. The stargazers page's 404 does not
invalidate the repository badge. The RA artifact reference occurs in a historical record;
anonymous artifact 404s alone do not establish expiry or nonexistence.

The [URL evidence](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-10-25/external-links.json)
records origins and redirects. Live external reachability can change after publication.

## Validation limits

Selected RIPPS2 host checks passed for both exact source snapshots, including synthetic APA
and master-cache checks, plus Build 115 artwork and external-runtime tests. These are bounded
host results, not independent console acceptance. Documentation checks cover local links,
anchors, duplicate IDs, search regeneration and wiki conversion. No PS2 program was run, no
foreign implementation was ported, and no gameplay/save durability result is claimed.

Use [Maintaining documentation](MAINTAINING-DOCS.md) for source ownership and publication
commands. Maintainer review/merge remains separate from preparing source and Pages PRs.
