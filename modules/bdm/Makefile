IOP_BIN := bdm.irx
IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_INCS := -Isrc -Isrc/include
IOP_OBJS := exports.o main.o bdm.o part_driver.o part_driver_mbr.o part_driver_gpt.o bd_cache.o imports.o
IOP_LIBS += -lgcc

all:: $(IOP_BIN)

$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-exports.c $(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
