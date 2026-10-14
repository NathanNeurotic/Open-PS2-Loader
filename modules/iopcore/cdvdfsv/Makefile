IOP_BIN = cdvdfsv.irx
IOP_OBJS = cdvdfsv.o searchfile.o ncmd.o scmd.o imports.o exports.o

IOP_INCS += -I../common

# In-game freeze report (top Makefile INGAMEDIAG=1, the FREEZEDIAG flavour). Run make clean when switching it.
ifeq ($(INGAMEDIAG),1)
IOP_CFLAGS += -DINGAMEDIAG
endif

ifeq ($(DEBUG),1)
IOP_CFLAGS += -DDEBUG
endif

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal
