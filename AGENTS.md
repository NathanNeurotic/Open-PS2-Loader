# Agent instructions

RiptOPL is a PlayStation 2 loader based on Open PS2 Loader. Target pull
requests at `rebuild/main`.

## Working on changes

- Use a task branch. When repairing an existing PR, update its branch as
  requested. Preserve unrelated local changes.
- The maintainer handles PR merges. Do not merge a PR, publish a release or
  tag, or rewrite remote history unless the user requests it.
- Trace the reported behavior in the current source and make the smallest
  complete fix. Keep existing architecture and compatibility; avoid unrelated
  refactoring. Treat audit notes and earlier agent reports as leads to verify.
- Complete the authorized implementation and relevant checks before reporting
  back. Explain any remaining blocker and distinguish code inspection, host
  tests, PS2 builds, and actual hardware results.

## Code map

- `src/`, `include/`: EE menu/application source and headers.
- `ee_core/`: native game loader.
- `modules/`: IOP modules and device drivers.
- `.github/scripts/`: host regression checks.
- `.github/workflows/`: CI and publishing configuration.
- `docs/`: documentation sources; site/wiki generation scripts are under
  `.github/scripts/`.

Use `.c` and `.h` for C source and headers.

## Commands and validation

- `make`: build; requires the PS2SDK/toolchain configured by the Makefile.
- `make format`: format C source using the repository formatter.
- `make format-check`: check formatting. CI uses clang-format 12.0.1 and
  `.clang-format`, excluding paths in `.clang-format-ignore`.
- `python3 .github/scripts/test_<name>.py`: run the relevant host harnesses.
  Add a focused regression check for changed behavior where useful.
- `python3 .github/scripts/check_docs.py`: check documentation links; install
  `.github/requirements-docs.txt` when its Python dependencies are missing.

Feature PRs run the flavour build workflow. Inspect failures before claiming
validation passed. Do not change toolchain pins or publishing triggers as a
workaround for a failed build. Avoid reformatting unrelated files.

A host test, emulator run, or successful PS2 build does not verify hardware
behavior. For device, timing, or launch changes, state the remaining console
check. Include the source commit and build flavour when reporting build or
console results; `.github/workflows/flavours.yml` defines the variants.

## Language, configuration, and documentation

- Append new UI strings to the end of `lng_tmpl/_base.yml`; do not reorder
  existing entries. Language IDs are positional. Regenerate
  `include/lang_autogen.h` and `src/lang_internal.c` with the
  `tools/lang_compiler.py` commands in the Makefile. Run
  `python3 tools/audit_translations.py --strict`.
- For settings, check defaults, load, save, and live application. `src/opl.c`
  has interactive and mini/autolaunch config load paths; update both when
  the setting affects both. Preserve saved choices when a device is temporarily
  unavailable.
- Edit documentation sources rather than generated website/wiki output. Check
  `.github/scripts/site_sync.py` and `.github/scripts/wiki_sync.py` for mappings.
- For ports, verify the reference implementation, record its source commit in
  the PR, and check interactions specific to this fork.
