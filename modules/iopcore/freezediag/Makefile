# In-game freeze report writer (INGAMEDIAG flavour only): see freezediag.c.
# The formatter is ee_core's, shared so the host test covers what runs here.

IOP_BIN  = freezediag.irx
IOP_OBJS = freezediag.o freeze_diag_format.o imports.o

IOP_INCS += -I../../../ee_core/include
IOP_CFLAGS += -DFREEZEDIAG_BUILD=\"$(FREEZEDIAG_BUILD)\"

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal

$(IOP_OBJS_DIR)freeze_diag_format.o: ../../../ee_core/src/freeze_diag_format.c
	$(DIR_GUARD)
	$(IOP_C_COMPILE) -c $< -o $@
