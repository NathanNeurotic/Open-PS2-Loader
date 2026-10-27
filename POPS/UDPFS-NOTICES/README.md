# UDPFS Assault credits and provenance

The adjacent usbd.irx.udpfs / usbhdfsd.irx.udpfs pair is the unmodified
[UDPFS Assault 1.0.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0.0)
network read/write release by Okeanos86. It replaces both the Alpha and USB-first
fallback drivers. All mass: requests, including VMC writes, use the server.

PROVENANCE.json records the verified archive and module SHA-256 hashes. NETWORK/
preserves the complete upstream README, configuration guide, licenses and notices.
The top-level reference documents mirror that same network release. No source
rebuild of these upstream binaries is claimed.

Optional IPCONFIG.DAT and UDPFSCONFIG.DAT come from the game device's POPS folder
and populate missing MC SYS-CONF files. Existing MC files are preserved.
See [RiptOPL setup](../../docs/VCD.md#pops-udpfs-with-bdm-udpfs-assault).

Credits: Okeanos, israpps' BDM Assault, krHACKen's POPSTARTER, Neutrino/UDPFS/UDPRDMA,
pcm720's udpfsd, Gageformer's Ember, and PS2SDK contributors. Complete notices and
licensing remain in the supplied upstream documents.
