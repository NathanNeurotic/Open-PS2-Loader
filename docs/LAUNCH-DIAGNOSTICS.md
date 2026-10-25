# Launch diagnostics: identify the package, core and transport

Record the loader build and the core that actually launches the game before changing settings.
The same library row can use different runtimes. A working native OPL launch does not validate
Neutrino, POPStarter, Ember or an achievements runtime on that transport.

## Choose the matching installation

| Installation | What to preserve and check |
| --- | --- |
| Standard complete kit | Keep its supplied `neutrino/`, `EMBER/`, POPS support files and notices together. The loose loader ELF alone does not refresh them |
| RetroAchievements complete kit | Use its paired companion and pinned ORBIT Neutrino runtime; see [RA setup](RETROACHIEVEMENTS.md). A newer companion release is not automatically the tested pairing |
| PR/Actions artifact | Record PR, commit, workflow, flavour and artifact name. Read the artifact's contents rather than assuming it is a full install kit; see [test builds](TEST-BUILDS.md) |
| External or older runtime | Record the runtime version and actual path. RiptOPL's argument-length checks do not establish that an arbitrary runtime recognizes every option |

Keep the previous working kit as a recovery copy. Do not mix runtimes while also changing the
loader build and transport: that makes a useful before/after comparison difficult.

## Identify the failing stage

| Observation | First checks |
| --- | --- |
| Source does not appear | Source Start Mode, selected device/slot and hardware detection; then [setup questions](SETUP-QUESTIONS.md) |
| Source opens but a game is absent | Folder, filename and supported image format; see [format matrix](GAME-FORMATS.md). Refresh after changes. A listed cached game does not prove the device is present |
| Immediate return to Browser | Selected core, actual runtime and support-file paths, arguments and complete runtime configuration. Record the error verbatim; an unsupported option or malformed TOML is different from a game compatibility failure |
| Logo then black/white screen | Compare the same image/core/transport with the last working build; record compatibility modes, VMC, PADEMU, GSM and RA state |
| Freeze after gameplay starts | Record title serial/revision, time or action, core and transport, companion/server version and the full log. A network timeout is evidence of a failed request, not by itself the underlying cause |
| VMC creation or replacement fails | Preserve the existing card and recovery files. Use [VMC recovery](VMC.md); do not delete saves to test a hypothesis |
| Exit/reset behaves differently | Use the [core-specific IGR reference](IGR.md). Native OPL, external Neutrino and the PS1 cores have separate hooks and return-path rules |

## Keep transport and runtime evidence separate

| Path | Details that change the diagnosis |
| --- | --- |
| USB / MX4SIO / iLink / exFAT HDD | Actual device and filesystem, selected core, VMC/PADEMU state and whether another device changes mount ordering. A `massN:` alias belongs to a mounted environment; it is not a permanent physical drive identity |
| MMCE | Device/firmware, slot, source mode, GameID and IGR bootcard settings, and where the loader/runtime resides. A GameID switch changes the emulated `mcN:` card contents; keep the runtime accessible after switching |
| APA HDD | Console/adapter, APA installation and per-core VMC support. Preserve the disk; use [APA safety](APA-SAFETY.md) before repair or repartitioning |
| SMB | Server implementation/version, share and prefix, credentials, negotiated SMB version, wired topology and core |
| UDPFS / UDPBD | Protocol and server version, Core/standalone server mode, generated runtime configuration and selected device. Do not infer UDPBD behavior from a UDPFS result |
| HTTP | Server profile, catalogue and range support; see [HTTP limits](HTTP.md). Host conformance does not establish real-console game compatibility |

For MMCE, copying files or creating a per-game card can compete with loading and controller work.
First reproduce with a known complete card and record firmware/device state. A read-only launch
comparison is more useful than repeatedly recreating cards. For POPStarter and Ember, follow
[PS1 core and device restrictions](VCD.md) rather than applying PS2-core options.

## A useful controlled comparison

1. Preserve the working build, configuration and saves. Select one console, device and game image.
2. Record loader commit/flavour, external runtime path/version and companion/server version.
3. Reproduce with the current settings and record the last visible stage or exact message.
4. Change one variable. For an optional feature, disable that feature first; preserve the original
   settings so the result can be repeated. For a regression, compare a control and candidate build.
5. Verify the intended outcome: reaching a logo, reaching gameplay, save/load and returning to the
   loader are separate checks. A host test or build cannot substitute for any of them.

Share the smallest repeatable sequence, the complete relevant log and both outcomes. Remove
passwords/tokens from configuration excerpts. Keep reporter-owned issues open until the reporter
confirms the affected setup, unless the maintainer explicitly decides otherwise.

## Reading the fork comparison

The [fork-gap report](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html)
tracks source mechanisms, release descriptions, development work and design alternatives.
RIPPS2 Build 115's Trust Cache, Recent Games, artwork aliases and MMCE coordination are reviewed
as that project's work; this guide does not claim those settings exist in RiptOPL.
See [collaboration review practice](FORK-COLLABORATION.md) for how candidates become small,
credited changes with appropriate checks.
