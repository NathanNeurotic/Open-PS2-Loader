# Our smbman.irx, replacing the stock one from ps2sdk.
#
# ps2sdk opens a file with NT_CREATE_ANDX only. A server that still holds
# the file for a session that is gone -- what a console leaves behind
# after running a game off the share -- refuses every NT open, whatever
# share mode it asks for, so the image can no longer be hashed although
# the game still boots off it: in-game OPL opens the old way, in
# compatibility mode, which the same server grants. The source is a copy
# of ps2sdk iop/network/smbman with the changes marked "RA fix".
# Candidate for upstreaming to ps2sdk.
IOP_BIN  = smbman.irx
IOP_OBJS = smbman.o smb_fio.o smb.o poll.o auth.o des.o md4.o imports.o

IOP_LIBS += -lgcc
IOP_INCS += -I$(PS2SDK)/common/include

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal
