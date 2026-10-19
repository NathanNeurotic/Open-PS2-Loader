IOP_BIN = genvmc.irx
IOP_OBJS = genvmc.o imports.o
IOP_INCS += -I../../../include

ifeq ($(DEBUG),1)
IOP_CFLAGS += -DDEBUG
endif

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal
