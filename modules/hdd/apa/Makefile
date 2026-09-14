IOP_BIN := ps2hdd-osd.irx
IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_INCS := -Isrc

# The ps2sdk iop/hdd/apa-osd flag set (see ORIGIN.txt): OSD variant, DEV9 power-off callback, atad
# block device. Keep these identical to the SDK's apa-osd Makefile on re-vendor.
IOP_CFLAGS += -DAPA_OSD_VER -DAPA_USE_DEV9 -DAPA_USE_ATAD
IOP_CFLAGS += -DIOMANX_OLD_NAME_COMPATIBILITY=0 -DIOMANX_OLD_NAME_ADDDELDRV=0

IOP_OBJS := hdd_fio.o hdd_blkio.o hdd.o imports.o password.o misc.o cache.o apa.o journal.o free.o

all:: $(IOP_BIN)

# Some Makefile.iopglobal vintages only mkdir the obj dir inside the build-imports recipe --
# pre-create it so the first compile step cannot fail on a missing directory.
$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
