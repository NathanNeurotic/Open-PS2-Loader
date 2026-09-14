# ps2sdk iop/fs/libbdm, built as the static library bdm.irx links against (see ../ORIGIN.txt).
IOP_LIB := libbdm.a
# Only the library is built here; Makefile.iopglobal warns when IOP_BIN is unset, so name one.
IOP_BIN := libbdm-unused.irx
IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_INCS := -Isrc/include -Iinclude

IOP_OBJS := bd_defrag.o bd_cache.o

all:: $(IOP_LIB)

$(IOP_OBJS_DIR):
	mkdir -p $@

clean::
	rm -f -r $(IOP_LIB) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
