# ps2sdk iop/iLink/IEEE1394_bd with RiptOPL's post-reset login and readiness fixes (see ORIGIN.txt).
# MINI=1 builds IEEE1394_bd_mini.irx without printf: the variant release builds embed and the
# Neutrino bundle ships. Each variant keeps its own object directory.
ifeq ($(MINI),1)
IOP_BIN := IEEE1394_bd_mini.irx
IOP_OBJS_DIR := obj_mini/
IOP_CFLAGS += -DMINI_DRIVER
else
IOP_BIN := IEEE1394_bd.irx
IOP_OBJS_DIR := obj/
endif

IOP_SRC_DIR := src/
IOP_INCS := -Isrc -Isrc/include
IOP_CFLAGS += -mno-check-zero-division
IOP_OBJS := sbp2_driver.o imports.o main.o scsi.o
IOP_LIBS += -lgcc # __udivdi3 in the full variant's capacity log

all:: $(IOP_BIN)

# Some Makefile.iopglobal vintages only mkdir the obj dir inside the build-imports recipe --
# pre-create it so the first compile step cannot fail on a missing directory.
$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)

# Makefile.iopglobal tracks no header dependencies: rebuild every object when a header it can
# include (or this Makefile) changes, so an incremental build never links a stale IRX.
ILINK_OBJ_DEPS := $(wildcard src/*.h) $(wildcard src/include/*.h) src/imports.lst Makefile
$(addprefix $(IOP_OBJS_DIR),$(IOP_OBJS)): $(ILINK_OBJ_DEPS)

clean::
	rm -f -r IEEE1394_bd.irx IEEE1394_bd_mini.irx obj/ obj_mini/ *.notiopmod*.elf

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
