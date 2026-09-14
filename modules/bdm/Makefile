# ps2sdk iop/fs/bdm (Block Device Manager) linked against the local libbdm (see ORIGIN.txt).
IOP_BIN := bdm.irx
IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_INCS := -Isrc -Isrc/include -Ilibbdm/include

IOP_OBJS := main.o bdm.o part_driver.o part_driver_mbr.o part_driver_gpt.o imports.o exports.o
IOP_LIBS += libbdm/libbdm.a -lgcc # __udivdi3

all:: $(IOP_BIN)

# Always enter the library build so an edited cache source relinks the IRX.
.PHONY: libbdm/libbdm.a
libbdm/libbdm.a:
	$(MAKE) -C libbdm

obj/bdm.notiopmod.elf bdm.notiopmod.elf: libbdm/libbdm.a

# Some Makefile.iopglobal vintages only mkdir the obj dir inside the build-imports recipe --
# pre-create it so the first compile step cannot fail on a missing directory.
$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-exports.c $(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR) *.notiopmod*.elf
	$(MAKE) -C libbdm clean

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
