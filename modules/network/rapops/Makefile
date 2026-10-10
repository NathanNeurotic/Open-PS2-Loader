IOP_BIN  = rapops.irx
IOP_OBJS = rapops.o blobs.o imports.o

IOP_INCS += -I../common -I../../iopcore/common
IOP_CFLAGS += -DDEV9_IRX='"$(PS2SDK)/iop/irx/ps2dev9.irx"' \
               -DSMSUTILS_IRX='"../SMSUTILS/SMSUTILS.irx"' \
               -DSMSTCPIP_IRX='"../SMSTCPIP/SMSTCPIP.irx"' \
               -DSMAP_IRX='"../smap-ingame/smap.irx"' \
               -DRAUDP_IRX='"../raudp/raudp.irx"' \
               -DRAPULL_IRX='"../rapull/rapull.irx"'

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal
