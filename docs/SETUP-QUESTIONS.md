# Setup questions and reporting launch failures

## Which build should I download?

The ready-to-copy app and the unsuffixed standalone release ELF deliberately prefer **OFFICIALROLLING** when available. **PS2DEVPINNED** is the recommended conservative comparison build because its toolchain is pinned. These are different policies: the package default is not a claim that a moving SDK is the most reproducible choice.

Use a named flavour from the same release when comparing behavior. Record its complete suffix; a successful build does not prove that it boots on your console. Keep the disk, configuration and selected core unchanged during a comparison. A failure in one flavour is evidence to investigate, not proof by itself of an SDK defect.

## Does Browser mean the memory-card browser?

Exiting to **Browser** hands control to the PS2's **OSDSYS** system interface. Seeing OSDSYS is expected. The eventual screen also depends on the console's installed boot/menu modifications. This option does not launch wLaunchELF's file browser. If you want a particular homebrew menu, configure its ELF as the exit target instead.

## Why is another language unavailable?

English is built in. Other menu languages need the matching `lang_*.lng` files and, when required, their fonts on an enabled, readable source. Keep the language pack aligned with your build: older packs can lack new strings, which fall back to English. Apply the interface language and save settings to retain it across boots. This is separate from a game's language setting and the console's OSDSYS language.

## Neutrino worked, then returned to OSDSYS

Follow [the complete Neutrino installation and path guide](NEUTRINO.md). RiptOPL may remain in `APPS/`; moving its own folder to the card root is not a general fix. An explicit Neutrino path must point to an ELF accompanied by its complete installation.

Record the exact build, game, game device, Neutrino installation path/version, selected core, VMC state and forced video setting. Include any displayed error and whether failure occurs before or after Neutrino takes control. Compare with forced video off and physical memory cards only after recording the original settings. A reset alone cannot distinguish an ELF handoff problem, runtime module failure, game incompatibility or unsupported launch option.

## More noise at startup

Enabling an internal HDD source can initialize and spin up the disk even if another source is the startup page. Describe whether the noise comes from the HDD, optical drive or fan, and which sources are enabled. A report of increased noise alone does not identify a software regression or justify changing disk power behavior.

## RiptOPL, Neutrino and other frontends

Neutrino is a game-loading core; RiptOPL can launch it or use OPL's native core. LUNA is another frontend for Neutrino. Choosing a frontend and choosing a core are separate decisions. Consult each project's own release and supported-device documentation before moving a working setup; a different frontend is not automatically a fix for a storage or runtime problem.
