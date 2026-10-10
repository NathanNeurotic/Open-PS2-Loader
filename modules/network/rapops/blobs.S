/* The modules rapops starts, carried inside it. Paths come from the
   Makefile; each blob is 16-byte aligned for LoadModuleBuffer. */
#define BLOB(sym, path)  \
    .balign 16;          \
    .globl sym;          \
    sym:                 \
    .incbin path;        \
    .globl sym##_end;    \
    sym##_end:

    .section .data
BLOB(rp_dev9, DEV9_IRX)
BLOB(rp_smsutils, SMSUTILS_IRX)
BLOB(rp_smstcpip, SMSTCPIP_IRX)
BLOB(rp_smap, SMAP_IRX)
BLOB(rp_raudp, RAUDP_IRX)
BLOB(rp_rapull, RAPULL_IRX)
