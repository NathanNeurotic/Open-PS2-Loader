# _____     ___ ____     ___ ____
#  ____|   |    ____|   |        | |____|
# |     ___|   |____ ___|    ____| |    \    PS2DEV Open Source Project.
#-----------------------------------------------------------------------
# Copyright 2001-2004, ps2dev - http://www.ps2dev.org
# Licenced under Academic Free License version 2.0
# Review ps2sdk README & LICENSE files for further details.

IOP_CFLAGS += -mno-check-zero-division

IOP_BIN := iLinkman.irx
IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_INCS := -Iinclude -Isrc/include -Isrc

IOP_OBJS := exports.o iLink.o iLink_PHY.o iLink_internal.o iLink_crom.o iLink_intr.o iLink_TxRx.o iLink_DMA.o imports.o

all:: $(IOP_BIN)

$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)

ILINKMAN_DEPS := $(wildcard include/*.h) $(wildcard src/include/*.h) src/imports.lst src/exports.tab Makefile
$(addprefix $(IOP_OBJS_DIR),$(IOP_OBJS)): $(ILINKMAN_DEPS)

clean::
	rm -f -r iLinkman.irx obj/ *.notiopmod*.elf

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
