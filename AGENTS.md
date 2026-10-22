# AGENTS.md — instructions for AI coding agents working in this repository

This is the canonical instruction file for this repo. If you arrived via
`CLAUDE.md` or another tool-specific file, this is the document that counts.
Human contributors are welcome to read it too — it is mostly the project's
working rules written down in one place.

## What this project is

RiptOPL — a fork of Open-PS2-Loader (game/USB loader for PlayStation 2), with
its own EE loader (`src/`, `ee_core/`), IOP modules (`modules/`), the
Neutrino/POPStarter integration, and an extensive host-side test and
documentation apparatus. The main development line is **`rebuild/main`**.
`master` is the old lineage — do not target it.

## Authority and branches

- **The maintainer (NathanNeurotic) personally handles all merges.** Agent
  work ends at a branch or a pull request that is ready for his review.
- Work only on your own agent branch (e.g. `codex/…`, `sable/…`, or the
  convention your tool uses). **Never commit to `rebuild/main`, `master`, or
  anyone else's branch.**
- No merges, releases, tags, or destructive operations (history rewrites,
  force pushes, branch/file deletion outside your own branch) without the
  maintainer's explicit authorization.
- Pull requests for unfinished work are **drafts**. A PR description must say
  plainly what is proven, what is only host-tested, and what still needs
  hardware verification. Reference the issue a PR addresses; do not close
  issues from a PR unless the maintainer asked for that.

## Engineering cycle

The project's standard, in the maintainer's words: **slim, optimized,
compatible, resilient code.**

1. **Clean baseline first.** Start from current `rebuild/main`; note the
   exact commit you branched from.
2. **Isolate the fault.** Root-cause in source before changing anything.
   Verify claims against the current code — status notes, audit documents
   and other agents' reports are leads, not truth. This repo has been
   audited by several agents; their notes live in `notes/` and `docs/`,
   and they are sometimes stale or wrong.
3. **Smallest viable fix.** Minimal, isolated, evidence-backed changes.
   No speculative modifications, no overengineering, no unrelated
   refactoring, no premature "while I'm here" work. Preserve existing
   architecture, semantics and compatibility.
4. **Validate before proceeding.** Run the relevant tests (below), then
   stop and report. Do not stack a second change on an unvalidated first
   one.

## A build is not proof

- This software runs on real PS2 hardware, and hardware behaviour routinely
  differs from source-level reasoning and from emulators. **Never present a
  successful build, a host test, or an emulator result as console-verified.**
- Anything touching IOP modules, device drivers (SMAP, UDPFS/UDPBD, BDM,
  i.LINK, MMCE…), timing, or the launch path needs a real-hardware result
  before it can be called done. If you cannot test on hardware, say so and
  specify the console test that would decide the question.
- Bug reports and test reports must name the **build flavour** they ran
  (see Builds) — identical source built by different toolchains has
  produced different behaviour in this project (see the header of
  `.github/workflows/flavours.yml`).

## Builds and CI

- `.github/workflows/flavours.yml` builds four flavours — pinned vs rolling
  × ps2dev vs official ps2homebrew toolchain. Push builds run only on the
  integration branches; **feature branches are built via their pull
  request**, so open the (draft) PR to get a build.
- Rolling releases publish from `rebuild/main` only. Do not add triggers
  that publish from other branches.
- **Format gate:** CI checks all tracked `.c`/`.h` with clang-format
  12.0.1 against `.clang-format` (see `check-format.yml`). Match the
  existing style; do not reformat files you are not otherwise changing.

## Tests

- There is a large host-side test suite in `.github/scripts/test_*.py`
  (~145 harnesses covering parsers, config, artwork, languages, themes,
  network support code and more). Find and run the harnesses that cover
  your change; if you change behaviour they pin down, update them in the
  same style — that upkeep is part of the change.
- Host tests are logic checks. They are not a PS2 build and not hardware
  evidence, and must not be reported as either.

## Repository-specific rules

- **Language strings are append-only.** New UI strings go at the **tail**
  of `lng_tmpl/_base.yml` — never insert in the middle, never reorder.
  String indices are positional; mid-file insertions renumber everything
  after them. Regenerate with `tools/lang_compiler.py` and run
  `tools/audit_translations.py` after adding strings.
- **Docs and wiki are generated.** The website and the GitHub wiki are
  produced from `docs/` and the mappings in
  `.github/scripts/wiki_sync.py`. Change the sources; do not hand-edit
  generated wiki/gh-pages output.
- **Audit and investigation notes** belong in `notes/` (dated, in the
  existing style). A note's conclusions are hypotheses until verified in
  code — label them that way.
- **Fork-gap / upstream ports:** when porting from another OPL fork or
  from ps2sdk, fetch the actual reference diff, adapt it to this repo's
  idiom instead of copying blindly, and record provenance (source repo +
  commit) in the PR. Check second-order effects the original didn't have
  here — e.g. anything that changes decorated display text can affect
  sorting, because list sorting uses the shown text.
- **Config changes:** new settings need a key in `include/config.h`, a
  default in `setDefaults()`, load in **both** config load paths
  (interactive and the mini/autolaunch path) if the setting can matter at
  launch, and save. Check for dual load paths before assuming one edit
  covers it.

## Reporting back

When you finish a piece of work, report: the branch and base commit, the
root cause or design decision with file:line evidence, exactly which
files changed, which tests ran and their results, and what remains
unproven (build, format gate, hardware). Distinguish *verified*,
*inferred* and *unknown* explicitly. If you were wrong about something
earlier in the session, say so plainly and correct it.
