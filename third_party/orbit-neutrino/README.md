# ORBIT Neutrino runtime for the RA edition

Pinned binary distribution: [ORBIT v1.0.2](https://github.com/danielnuld/ps2-launcher/releases/tag/v1.0.2).
Source: [danielnuld/ps2-launcher at 7a88a6a5](https://github.com/danielnuld/ps2-launcher/tree/7a88a6a5fdc935001d977497460716762edef404/third_party/neutrino-igr).

Daniel / ORBIT supplies the modified Neutrino loader, EE core and achievement agent.
Neutrino is by Maximus32; the achievement protocol and original agent work are by
hacan359 / xeRAbora. The Neutrino fork is AFL-3.0. Preserve its LICENSE and the
source reference with the distributed runtime. The GPL-3.0 ORBIT launcher is not
bundled or linked into RiptOPL.

The packer verifies the complete upstream ZIP digest and extracts only neutrino/.
Ordinary packages retain the official upstream runtime. Only the RA package may
contain raagent.irx, the ORBIT-RA provenance marker and the RA-EDITION-NEUTRINO.txt
label. The RA kit keeps the folder name neutrino/ for RA setups; the label marks it
as the RA build's Neutrino (v1.8.0 base, no Neutrino cheats) so it is not mistaken
for the standard kit's runtime.

v1.0.2 sends each snapshot in one packet: sets whose direct values exceed 1,216
bytes stay untracked. It reads the direct entries only, so a pointer-chain tail is
ignored (xeRAbora PROTOCOL.md) and chain-based achievements do not unlock; the
handoff passes direct entries only. It speaks the xeRAbora wire protocol, which is
also what Caduceus's engine receives, so both RA modes use it. Console unlock
cards are not claimed.
Do not automatically replace this pin when a new release appears.
`.github/workflows/orbit-neutrino-watch.yml` checks ORBIT's latest release on Neutrino
Watch's schedule and opens the "ORBIT Neutrino RA runtime update" issue when it differs
from this pin (a newer tag, or the same tag with a replaced archive). It never edits the pin.
