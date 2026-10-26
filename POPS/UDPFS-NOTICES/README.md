# UDPFS Assault credits and provenance

The adjacent `.udpfs` pair is Okeanos86's BDM-UDPFS Assault 1.0 (USB-first,
read-only VCD fallback). The `.udpfsnet` pair is UDPFS Assault 1.0.0 (network-only,
read/write). Both pairs are included unchanged. Their companion IRX is identical.

- [BDM-UDPFS Assault 1.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0)
- [UDPFS Assault 1.0.0](https://github.com/Okeanos86/BDMAssault/releases/tag/1.0.0)
- [RiptOPL setup](../../docs/VCD.md#pops-udpfs-with-bdm-udpfs-assault)

`USB-FALLBACK/` and `NETWORK/` preserve each release's README, configuration guide,
licenses and third-party notices. `PROVENANCE.json` records downloaded archive
hashes and every installed module's hash and byte length. Relative upstream links
refer to the original source/archive layout. No reproducible source build of these
modules is claimed by this integration.

Okeanos's work builds on israpps' BDM Assault and PS2SDK. POPSTARTER is by krHACKen;
network protocol work comes from Neutrino/UDPFS/UDPRDMA, and udpfsd is by pcm720.
See each release's notices for complete attribution and licensing.

Optional IPCONFIG.DAT and UDPFSCONFIG.DAT come from the game device's POPS folder
and populate missing MC SYS-CONF files. Existing MC files are preserved.
