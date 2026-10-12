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
contain raagent.irx and the ORBIT-RA provenance marker.

v1.0.2 supports direct watch entries with at most 1,216 snapshot bytes. Pointer
chains and larger lists must remain untracked with this runtime. It speaks the
xeRAbora protocol; Caduceus compatibility and console unlock cards are not claimed.
Do not automatically replace this pin when a new release appears. The matching
watch workflow reports upstream changes for a compatibility review.
