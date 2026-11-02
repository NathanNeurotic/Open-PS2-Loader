IOP_OBJS = pademu.o sys_utils.o imports.o exports.o padmacro.o ds34common.o

ifeq ($(USE_USB),1)
IOP_BIN = usb_pademu.irx
IOP_CFLAGS += -DUSB
IOP_OBJS_DIR = obj.usb/
# padprofile: the .pad USB pad profiles (RIPPS2 build 129). USB only: the Bluetooth driver never reads them.
IOP_OBJS += ds34usb.o padprofile.o
endif

ifeq ($(USE_BT),1)
IOP_BIN = bt_pademu.irx
IOP_CFLAGS += -DBT
IOP_OBJS_DIR = obj.bt/
IOP_OBJS += ds34bt.o
endif

ifeq ($(VMC),1)
IOP_CFLAGS += -DVMC
endif

IOP_CFLAGS += -DUSE_SMSUTILS
IOP_INCS += -I../../include/ -I../../ # -I../../: src/padfile.c finds include/padfile.h

include $(PS2SDK)/Defs.make
include ../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal

# No header dependencies are generated here, and padprofile.c builds the launcher's src/padfile.c into PADEMU: rebuild
# what reads the .pad block when that code changes.
$(IOP_OBJS_DIR)padprofile.o: padprofile.h ../../src/padfile.c ../../include/padfile.h
$(IOP_OBJS_DIR)pademu.o $(IOP_OBJS_DIR)ds34usb.o: padprofile.h ../../include/padfile.h
