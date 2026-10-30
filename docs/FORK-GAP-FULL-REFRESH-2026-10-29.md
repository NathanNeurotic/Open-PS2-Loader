# Full ecosystem fork-gap refresh - October 29, 2026

This snapshot replaces the availability conclusions of the earlier October 29 reconciliation. It was collected late on October 29 in America/Los_Angeles; UTC evidence timestamps extend into October 30. Both sites retain the older reports and every stable anchor as dated history. Differences are opportunities for comparison, with shared work credited; they are not promised ports or a defect count.

> Publication update - October 30, 2026: the All Games/Apps changes (#195 / #1163) have now merged in both editions. The CPP-only list-rebuild follow-up #201, Coverflow variants (#199 / #1167), Grid integration (#196 / #1164), silent in-game pause (#200 / #1168), config-import changes (#190 / #1159) and menu-freeze diagnostics (#191 / #1160) remain open at this publication check. The repository/ref/release inventory below remains the explicitly dated late-October-29 source snapshot.

## Current baselines and coverage

| Edition | Source baseline | Pages baseline before this update |
| --- | --- | --- |
| RiptOPL C++/ps2build | [c136055c8515](https://github.com/NathanNeurotic/RiptOPL/commit/c136055c85157764d71e0b7122338a556d58e7e6) | 9b7c9e0518ba |
| Open-PS2-Loader legacy C | [3e6b4ec96be3](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/3e6b4ec96be338866aed08c9604084d82ec802f9) | 422cc158d08b |

All **141 tracked identities / 138 canonical repositories** were rechecked: **10 changed tracked refs, 131 unchanged, none unavailable**, relative to the previous October 29 ref inventory. YAOPL's old/new addresses are two identities for one canonical repository. Changed-head totals include both maintained editions and a following fork; they are not counts of independent upstream developments. All **138 canonical release collections** were checked, up to five entries each, resolving the 141 identities through canonical aliases.

The current register contains **301 stable records**, **152 capability/design families**, and 44 source groups. All previous 292 IDs and 143 family numbers remain. Nine new records cover freshly inspected mechanisms. Older, unchanged records retain their assessment dates: a fresh ref/release check is not a fresh function audit. Every recorded branch/tag ref is available in repository-heads.json.

The discovery check expanded to the newest 100 upstream OPL forks and all two RiptOPL forks. No additional identities created since October 25 appeared outside the existing inventory in that window. Older untracked forks and branches outside the reviewed source scopes remain outside this audit; this is not an exhaustive GitHub-wide comparison.

| Current classification | Records |
| --- | --- |
| Already present / equivalent scope | 27 |
| Companion / separate scope | 32 |
| Declined / outside local scope | 1 |
| Experimental source / unvalidated | 40 |
| Historical / withdrawn | 6 |
| Intentional design difference | 4 |
| Known upstream limitation | 4 |
| Merged / hardware unverified | 36 |
| Partial overlap / remaining difference | 35 |
| Prior source finding / reassess | 88 |
| Source comparison candidate | 28 |

## Changes already merged in both editions

The October 29 hardening/read-only UDPBD/SMAP batch and per-mode positions are merged in both editions, as the published report already records. They are not still-open implementation work. Both now also contain:

| Scope | Current behaviour and limits |
| --- | --- |
| Beta in-game menu | RIPPS2-derived OPL-core pause/resume, live cheats, exit and power off ([RiptOPL #184](https://github.com/NathanNeurotic/RiptOPL/pull/184), [legacy #1155](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1155)). Off by default; excluded from RA, IGS, freeze-report and EE SIO debug variants. Screenshot/Achievements pages, Neutrino and PS1 menus remain separate. Source documentation explicitly says hardware untested. |
| Display and themes | Saved-video-mode boot (#170/#1141), SD/HD layout keys and aspect positioning (#181/#1152), fallback List/Coverflow/PSBBN/Grid for every theme (#183/#1154), priority restoration after hires (#180/#1151), 720p/1080i forced 16:9 (#189/#1158). The separate MC boot-audio sidecar remains RI45. |
| Input and artwork | Missed pad reads retain held state; rumble alignment only when quiet (#188/#1157). PS1 cover/placeholder flicker was corrected (#174/#1144). These source changes do not identify the cause of every reported stall or establish console acceptance. |
| Runtime distribution | RA kit descriptions link the exact ORBIT Neutrino RA runtime they ship, with a pin-watch workflow (#192/#1161 and #194/#1162). This is artifact pairing/maintenance, not a protocol/gameplay acceptance result. |

The All Games/Apps changes (#195 / #1163) merged after the research snapshot and are present at the publication bases. The CPP-only list-rebuild follow-up #201, Coverflow variants (#199 / #1167), Grid integration (#196 / #1164), silent in-game pause (#200 / #1168), official-config import (#190 / #1159) and menu-freeze diagnostics (#191 / #1160) remain pending at publication. Their branch content is not folded into source availability. The in-game menu is credited to akilluminati47’s RIPPS2 and its ORBIT ancestry; multi-view/Grid remains credited to KrahJohlito and PSBBN Flow to darkladark.

## RIPPS2 release, companion and development states

RIPPS2 main is [5ebb5e0b4cc0](https://github.com/akilluminati47/RIPPS2/commit/5ebb5e0b4cc074742b184ed9892494d161e97e49). The source patch queue is byte-for-byte unchanged from the earlier 75-patch build 124 reconstruction (git diff of elf/patches returned no delta). Main's 14 later commits concern release/docs, Media Studio, tests and screenshots; they do not add build 125 runtime code.

**v1.2.4-beta/build124** is now released at b682a93c. GitHub sets prerelease=false while the product remains beta. This promotes builds122-124's launch transition, tar-merge and mode-position source from development status; it does not prove runtime or storage durability. RI42/RI46 are updated accordingly. RI47 remains an opt-in diagnostic mechanism even though its source is now tagged.

**Media Studio** is a distinct Windows companion release. It adds bounded AVI video conversion and packaging with ffmpeg/ffprobe alongside the existing audio/own-BIOS authoring toolchain. RI4/RI48 preserve companion scope; a media tool release is not a new game-loader version.

**b125@524c2cef7c40** is an unreleased, diverged development branch, not current main. Source inspection adds RI49 (tar folders/member writes), RI50 (64KiB/64-slot packed recent-CFG LRU cache), and RI51 (video controls and HD-cover download choice). The branch also changes legacy sidebar defaults and corrects the built-in theme's omitted launch_disc key. Preserve staged-write, invalidation, memory-pressure and interruption questions; no upstream setup/build scripts or storage probes were executed.

## YAOPL: shared fixes and a withdrawn policy

Canonical [yaopl/yaopl](https://github.com/yaopl/yaopl/commit/0889ac4d009567b168b283e6d6933af36df7c2e8) master is 0889ac4d0095, ten commits beyond the earlier pin. Its rc2 release at ee9cb9fa remains a prerelease and predates master's later message-wrap work; the mutable nightly is separate.

YAOPL removed its DualShock launch reset in 7094cd25. Our bounded digital/unlocked handoff remains in both defaults. YA-06 is therefore a current policy divergence with an upstream withdrawal, not a claim of current upstream parity. No console evidence here selects the universally correct behaviour.

YA-19 finds existing local overlap: both ee_core padhook implementations preserve the hook flag during polling pauses, mark both callbacks and publish patched instructions through kernel-context cache flushes. YA-20 narrows the remaining comparison: local interactive message boxes already wrap, while YAOPL shares a helper across warnings, text screens, confirmations and removal prompts too. Width, height, UTF-8/CJK behaviour, truncation and each actual consumer need review before any port. Withdrawn YA-11 remapping stays deferred.

## LUNA and runtime dependency pins

Wrapper c1205fbd now pins **nhddl luna@1c97889d34ce**. Its historical tracked frontend ref is **legacy**, not main, and is unchanged at4e8f4e6b. The earlier prose called that tracked ref main; this refresh corrects it. The five added frontend commits refine CubeGlass quick/game menus, padding/text fit, per-appearance effects colour and circular Space Flight stars; they do not add another VMC-storage backend.

Neutrino fff99d98, native OPL c533f939 and PSXCore 5d4de02f pins are unchanged. The previously inspected whole-card PS1/PS2 lifecycle, 4MiB direction-aware art reuse, paired long-argv and MMCE restore mechanisms remain differentiated comparisons. Existing local VMC Saves/creation, async caches and safe argv refusal overlap. Native/Neutrino/PSXCore flags cannot be transplanted without their paired runtimes. v3.1.3 release assets are not automatically this development wrapper.

## Development branches and companion repositories

| Project | Current source assessment |
| --- | --- |
| Titan | Default 2a69c259 is unchanged. Arena branch d442d58dc858 adds bounded scan/art alternation and separate prefetch/decode buffers (T11), plus DEX operation snapshots/ribbon (T12). Source inspection covers the scheduler, asset owner/publication and diagnostics contract; no target/runtime/performance result is claimed. |
| PS2TVCRT | Default 42c33b5b is unchanged. The changed alternate branch diverges and includes unrelated translation/emulator/workbench content. It is retained as branch metadata, not promoted to new default/released loader capabilities. |
| Launchstation | Current 2b1d95581a93 is six commits ahead. Game-ID splits stage .PART cards and verify final copies; combined card-save listings and PSU sets are LS2. Moving file-copy chunks to the worker keeps progress drawing but retains direct destination replacement. Safety-copy and ordinary-copy paths have distinct guarantees. |
| POPSLoader | Current 453c8da1 adds versioned ZIP publishing/docs. Loader/driver code did not change in this interval. Source naming changes do not retroactively rename assets of existing releases; link to release collections rather than fabricate a new asset URL. |
| PS2SP | Fourteen catalogue/discovery/deployment commits; complete local comparison lists 543 changed paths, beyond the API's 300-path cap. This is catalogue metadata review, not source/acceptance review of every listed app. |
| Diegoprofeta/RiptOPL | Head 48df5255 is an ancestor of our current RiptOPL default; it follows our theme work rather than providing an independent implementation delta. |
| Unchanged references | OPL-JUMP, Blayr, xeRAbora client, PSXCore, PS2-Servers and other tracked refs/releases were refreshed. Prior source findings remain dated; no change is inferred from activity timestamps alone. Rolling release assets can change without a new tag name, so release metadata is retained separately. |

## Actionable comparisons and evidence limits

The immediate source comparisons are YA-20's remaining message consumers, RI42's archive merge/recovery contract, RI49/RI50's branch-only archive/cache ownership, and the scheduler/buffer invariants in T11. Whole-card VMC/PSU workflows remain separate from game-launch requirements. Hardware-sensitive controller and in-game-menu changes need affected-console evidence; this audit does not port them.

Disc ripping/CD-player/HDD partition writes remain declined local scope. Single-pass magnified HD and external-only runtime packaging remain optional design alternatives. Shared/imported fixes, intentional choices, tools and experiments stay in the register without being counted as defects.

Read the [Pages evidence set](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-10-29-refresh/FULL-REFRESH.md) and the [current searchable register](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html#at-a-glance). Local validation covers documents/generated indexes, anchors/resources, register/family totals and browser behaviour when available; its exact outcomes are recorded separately. No new PS2 build, emulator session, physical-console/gameplay, save durability, storage probe or performance acceptance was performed.
