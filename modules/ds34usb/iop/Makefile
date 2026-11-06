IOP_BIN = ds34usb.irx
IOP_OBJS = ds34usb.o smsutils.o imports.o padprofile.o # padprofile: RIPPS2 build 129, .pad

IOP_INCS += -I../../../include/ -I../../../ # -I../../../: src/padfile.c finds include/padfile.h

# Experimental PS5 DualSense (USB) support, off by default (see the top-level DUALSENSE flag).
ifeq ($(DUALSENSE),1)
IOP_CFLAGS += -DDS5_ENABLE
endif

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal

# No header dependencies are generated here, and padprofile.c builds PADEMU's padprofile.c with the launcher's
# src/padfile.c: rebuild what reads the .pad block when that code changes.
$(IOP_OBJS_DIR)padprofile.o: ../../pademu/padprofile.c ../../pademu/padprofile.h ../../../src/padfile.c ../../../include/padfile.h
$(IOP_OBJS_DIR)ds34usb.o: ../../pademu/padprofile.h ../../../include/padfile.h
