# Documentation audit — October 19, 2026

For the current refresh, see the [October 25 documentation and fork audit](DOCUMENTATION-AUDIT-2026-10-25.md).
The revisions and outcomes below are the earlier baseline.

Baseline: [`rebuild/main` at 7988eff5](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/7988eff5),
[`gh-pages` at e8561ca8](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/e8561ca8),
and wiki `8b9a756`. The local checkout was on an August-era forensic branch; it was clean
and is preserved. This refresh starts from the current publishing branch, not that snapshot.

## Scope and evidence

The audit inventories all 64 baseline tracked Markdown files, all 35 website HTML pages,
their navigation/search assets and the wiki's generated guides, mappings and provenance.
It checks current user guidance against the matching source references, release workflows,
merged changes and relevant implementation. Integration plans, dated incident records,
third-party notices and old changelogs retain historical context instead of being rewritten
as current instructions. License texts and imported component notices remain intact.

The baseline structural check covered 2,117 local links. Four apparent failures were links
in a verbatim upstream README that refer to its original archive layout; the adjacent
provenance note already explains them. The real missing target was the site's old
`docs/wiki/Unicode-Game-Titles.md` link. The repeatable checker now records that distinction.

[External-link evidence](audit/2026-10-external-links.json) records all 536 baseline external
URLs, origins, HTTP results and redirects. Of these, 509 returned 200, 18 returned 403,
eight returned 404, and one timed out. These are reachability observations, not proof that
every remotely linked feature or download works. Follow-up authenticated checks established:

- Artwork runs `37143714039` and `37143757153` return 404: retain their IDs as historical
  evidence and remove them as download links.
- Unicode artifact `11747219931` and RA artifact `11722644208` **exist and were not expired**;
  both expire October 26 according to GitHub metadata. Their anonymous 404s are not evidence
  of expiration. Unicode setup now points to current releases rather than a short-lived preview.
- `KrahJohlito/wOPL`, `APA-OPL/hdl-dump` and LUNA's moving `NHDDL_FIDELITY.md` URL return 404.
  Preserve Krah's credit without the dead link, use the maintained ps2homebrew HDL-Dump
  repository, and retain the pinned LUNA implementation as evidence.
- The stargazers 404 is a GitHub UI result, not grounds to remove the valid repository badge.
  Forum 403s and the MEGA timeout are inconclusive; useful provenance links remain.

## Corrections and consolidation

| Finding | Correction and source of truth |
| --- | --- |
| README still advertised widescreen, boot audio and SFX defaults after defaults changed | Link the feature overview to [DEFAULTS.md](DEFAULTS.md), `setDefaults()` and the actual theme picker; remove repeated old tutorials |
| The controls reference still inferred Confirm from console region | Fresh RiptOPL settings select Circle in `setDefaults()`; describe tables as a reference layout and follow the active hints |
| PC CARD CF and the DVR opt-in were still described as unmerged #955 | Mark implementation merged, both toggles Off by default, and retain outstanding console validation and device exclusions |
| Install page listed retired unlabelled RA assets | Separate standard inceBtion/Korium and the two-theme `rolling-ra` channel; document shared app replacement and current ELF/PSU names |
| Required Neutrino was described as an optional omitted download | Current `rolling-release.yml` fails packaging on missing/incomplete Neutrino; distinguish standard upstream development runtime from the RA kit's ORBIT pin |
| Neutrino page conflated the bundle for local games with a separate network-only install | One complete standard runtime serves supported local and UDP launches; DESR and RA have distinct runtime requirements |
| Old argument editor limits and examples contradicted `guiShowNeutrinoArgsConfig` | Full-value keyboard, 255-character saved string, 14-entry / 256-byte launch preflight; valid `-gsm=fp2` example; expert override/DVR rules |
| UDPFS page required manual IP edits and called its core selector editable | Describe automatic TOML synchronization, its manual-IP fallbacks, and the locked core selector, including resolved Favorites |
| UDPFS promised direct ZSO/CSO/CHD loading | Explain scanner/launch restrictions and server-dependent virtual `.iso` exposure; no claim of direct compressed-file Neutrino support |
| A cheat-page callout said Neutrino cheats were unavailable while the same page described them | Distinguish native PS2RD, post-v1.8.0 Neutrino development cheats and ORBIT's older base; retain mastercode requirements |
| VMC site guidance predated merged layout checks and reservation | Explain new native BDM reservation, existing-file preservation, explicit failures and core-specific fallback prompts; link [VMC.md](VMC.md) |
| VMC page implied Favorites were interchangeable across forks | State the one-way OFAV import and preserve-original advice |
| Parental-lock guides said any game could launch | Separate session settings authorization from per-game launch locks; include Favorites, Last Played, Test Changes and stored-lock removal |
| Per-game OSD and Game ID descriptions were wrong | OSD hooks override game-visible config, not EEPROM; `$DNAS` is a disc authentication ID, not the CFG/artwork startup serial |
| New Logo Artwork control missing from site reference | Document independent LGO/ICO/game-launch-logo controls with the actual On default |
| Scattered setup details were stale | Correct UL files/root `ul.cfg`, SMB Version/ETH-prefix menu paths, canonical POPS release folder, app-art ELF extension, NBD Start button, and DualSense-in-VARIANTS downloads |
| PS3 guide invented EE hardware on COK-002 and suggested PS2 APA treatment of the PS3 disk | Use CECHA/B EE+GS and CECHC/E GS-only scope with hardware references; remove unsafe/unsubstantiated storage and universal entry-point claims |
| Source plans and DONE ledgers read as current instructions | Add dated-record banners and a [current documentation index](README.md); preserve historical evidence |
| External-tools catalog repeated on release and Home pages | Releases links to the Home catalog; update the generator so it does not restore the duplicate |
| Companion announcement still called RIPPS2 an unreleased alpha web theme | Its current upstream README offers a downloadable PS2 ELF; link its releases instead of preserving an expired development forecast |
| Wiki missed new devices/recovery guides and repeated entire site/source references | Add explicit coverage, retain old page names/anchors as source-section indexes, and move the builder into the reviewed source tree |

## Website coverage

Every page was included in the structural/link inventory and content/status sweep. A page left
unchanged was retained because the sweep found no justified correction, not because its hardware
paths were newly tested.

| Area | Pages and disposition |
| --- | --- |
| Entry and packages | `index`, `getting-started`, `install`, `releases`: defaults, complete kits, channels, duplicate catalog and root layout corrected |
| Local storage | `usb`, `mmce`: existing device/setup qualifications retained; `hdd`: merged CF status and allocation wording reconciled |
| Special hardware | `pc-card-cf`, `psx-dvr`: merged/opt-in status corrected; `ps3-bc`: hardware and inherited-support scope corrected |
| Network | `smb`, `network-boot`, `nbd`: paths, file layout, IP synchronization, core and format restrictions corrected; `http`: existing experimental/conformance scope retained |
| Cores and saves | `neutrino`, `cheats`, `per-game-settings`, `vmc`: runtime, arguments, locks and VMC corrections; `ps1-vcd`: UDPFS Files scope, all four Ember per-game settings and the confirmed loose-file scan defect reconciled |
| Interface | `controls`, `settings`, `themes`, `pademu`: defaults and missing behavior corrected; `coverflow`, `favourites`, `languages`: current guides retained |
| Other references | `unicode-titles`: durable release/wiki links; `zso`: maintained tool link and HTTP exclusion; `credits`: dead link removed, attribution retained |
| Recovery and history | `troubleshooting`: VMC reservation/fallback wording aligned; `igr`: EE alarm, retained notifications, Mode 6/RA behavior, power-button limits, return-path restrictions and Ember's lack of IGR corrected; `gsm`: recovery guide retained; `fork-gaps`: dated comparison preserved with broken evidence URL removed |
| Generated content | `retroachievements` regenerated from its current Markdown owner; `data/search-index.json` regenerated from final pages |

## Validation and limits

Use [the maintenance commands](MAINTAINING-DOCS.md) to reproduce the local-link, search/render
and wiki conversion checks. Wiki conversion validates internal targets and preserves imported
text, tables and code examples. Existing source-section bookmarks remain available through
the short indexes. The wiki remains a separate Git repository; its publication is a normal
history-preserving push, while source and website changes use two PRs because their base
branches differ.

This is a documentation and publication-tooling change. It supplies no new PS2 or PS3 hardware
results. Native BDM VMC save/reboot acceptance, CF/DESR, the newer RA/HTTP paths and iLink
handoffs retain their stated validation limits. Moving upstream releases and package assets
must still be checked at the time of a later update.
