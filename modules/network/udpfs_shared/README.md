# Shared UDPFS transport implementation

`udpfs_core.c` and `udprdma.c` are the canonical transport sources for both UDPFS
IOP drivers. The filesystem (`udpfs_ioman`) and block-device (`udpfs_bd`) driver
builds each compile these same sources through local single-include wrappers,
with their **existing**, distinct `FEATURE_UDPFS_IOMAN` and `FEATURE_UDPFS_BD` flags.

The per-variant `src/*.h`, `main.c`, module import lists, entry points,
registration names, and Makefiles remain separate. Do not co-load the variants:
both still depend on the mutually exclusive network stack selection.

Original source: rickgaiser/neutrino UDPFS transport, pinned source provenance
and local changes recorded in the respective `ORIGIN.txt` files.

When modifying shared transport code, run both IOP build variants and the
existing ACK-wrap, UDPFS file and UDPFS block driver tests. This consolidation
is source-only; it is not intended to alter packet formats, retries, timing,
compile flags, or published .IRX module names.
