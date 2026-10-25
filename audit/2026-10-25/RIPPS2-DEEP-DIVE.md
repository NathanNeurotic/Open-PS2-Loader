# RIPPS2 collaboration review — October 25, 2026

RIPPS2 and RiptOPL share ancestry and exchange work. This review looks for useful mechanisms in both directions and preserves author credit. A difference is not automatically a defect, a finished feature or an instruction to port it.

## Exact revisions and reconstruction

- RiptOPL publishing source: `55261de1381ae70ecfdfb2054f9cafbcfcd586cf`.
- RIPPS2 main: `e1e3504f4a8bfd6b2f88425d284eb845393cfcb9`, Build 115 in progress.
- Published v1.1.4-beta: `f59abffde0794debdadaee526c175414a4b12b21`, Build 114. GitHub marks this beta-named release **non-prerelease**; publication occurred October 24 in America/Los_Angeles (October 25 UTC).
- b114: `20fcc576a2c01b172a095796f2b1bfa63c596238`; no longer the sole place where Build 114 exists.
- Imported RiptOPL upstream: `57c45b4fcc922ba00fed949c634caea0a2900c63`, revision 4224. RiptOPL changes after that import must be reconciled separately.

The source was reconstructed from the previous pinned Build 113 tree and each exact numbered patch, with pinned test/asset files. No upstream shell build script was executed. [Pins](focused-refs.json), [changed-source comparisons](comparisons.json), [host checks](host-checks.json) and [all tracked refs](repository-heads.json) make the review reproducible.

## What changed since the previous deep dive

Build 114 has shipped. Its master library, waiting rows, hidden games, cleanup planning, ISO/ZSO conversion, named color sweeps and smaller font configuration must now be described as released source rather than unreleased b114 work. Release status does not establish safe deletion, uninterrupted conversion or save durability on every backend.

Subsequent hotfixes add MMCE rename probing before conversion, remove RIPGRID sidebar strips and suppress background HDD error boxes. The MMCE firmware requirement and absence of a free-space check belong beside conversion claims, not buried in a changelog.

Build 115 implementation is present on main despite an older plan opening with “nothing built yet.” The numbered patch and testable functions carry more weight than that stale plan header. Main adds artwork aliases, runtime-aware Neutrino arguments, MMCE busy/wait handling, Trust Cache, input analog-mode retry, a Recent Games page and early-console PC Card/HDD UI consolidation. The plan's remaining proposals are not all delivered.

## Wins worth carrying between the projects

| Mechanism | Why it helps | Review before adoption |
| --- | --- | --- |
| External Neutrino capability detection | Avoid unsupported options causing an immediate return to Browser | Unknown tags, strings/config heuristics, packed ELFs, ORBIT flags, explicit user arguments, aggregate argument budget |
| Artwork aliases and real filename lookup | Accept OPL Manager artwork and mixed-case JPEG names without renaming libraries | Alias precedence, cache invalidation, PFS case sensitivity, extra SMB/UDPFS misses, PS1 ID parsing |
| MMCE busy and game-card creation wait | Avoid reading while firmware is copying/creating a card | Firmware status contract, bounded wait/cancel, pad fairness, history writes before GameID, unrelated physical cards |
| Rename preflight | Discover unsupported commit semantics before an expensive conversion | Same-directory rename, unique scratch names, removal failure, firmware versions, no implied free-space guarantee |
| Master list / waiting rows / Trust Cache | Present useful libraries before manually started drives answer | Device replacement, duplicate serials, stale rows, memory limits, launch-time revalidation |
| Sidebar/grid focus ownership | Predictable navigation and source changes | Existing themes and controls, stale list snapshots, rendering cost, bounded selection |
| Selective fonts and single-pass HD | Potentially reduce memory and rendering pressure | Measure sections/VRAM and frame time; preserve CJK/custom TTF/CFF support and image quality |
| Recent Games page | Recover recent choices across inactive sources | Privacy/history policy, capped records, missing devices, per-core identity |

The existing [Build 113/114 deep dive](../2026-10-24/RIPPS2-DEEP-DIVE.md) retains the detailed source review of language hashes/RTL, sound conversion, screenshots, memory-card tools, write coordination and i.LINK. Its release/development labels are historical and are superseded above. Stable RI IDs remain in the current register.

## Safety and compatibility boundaries

RIPPS2's Neutrino reset path rewrites mass-unit paths only when no `-qb` is emitted. This is not a universal path fix: `-qb` inherits a mounted environment and RiptOPL's local/network dispatch must preserve the intended device. A typed drive family is still not a unique physical device when two devices share that family.

Deletion, conversion and memory-card tools need separate designs for existing files, shared saves, interrupted writes, failed rename, media removal and recovery. A read-only APA preflight can reject malformed headers; it cannot prove that all real disks are safe to modify. Keep these as separate investigations rather than a bundled parity port.

The Build 115 hardware plan reports a problematic MMCE launch and incomplete automatically created GameID cards. It also reports a successful HDD launch. Those are upstream observations for the stated setup, not our tests. Its later Neutrino Burnout 3 result is a **lab/emulator** observation; it must not be described as an independent physical-console success. Earlier i.LINK results remain separated by native OPL, Ember, ordinary Neutrino, POPStarter and RA/ORBIT.

## Shared wins and useful next experiments

RIPPS2 already imports RiptOPL fixes through its recorded upstream pin. YAOPL also explicitly credits fixes reviewed from RiptOPL. Shared code is acknowledged once rather than counted as a new competitive gap.

The first low-scope candidates are artwork interoperability and external-runtime option negotiation. For either, preserve the current loader/core contracts, make a small isolated change, run function-level host checks, then compare the same console/media/game against a control build. MMCE scheduling and storage-writing features need their own controlled work and hardware evidence. No implementation port is included in this documentation refresh.

No message was sent to another maintainer. These public, pinned findings provide a reviewable basis for sharing results when requested.
