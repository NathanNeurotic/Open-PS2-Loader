IOP_OBJS = main.o pccf_hw.o pccf_ata.o pcdiag_cis.o pcdiag_cf.o imports.o
IOP_CFLAGS += -DPCCF_SETTLE_US=1000 -fno-strict-aliasing
IOP_OPTFLAGS = -O2
ifeq ($(GAME_DRIVER),1)
IOP_BIN = pccf_game.irx
IOP_OBJS_DIR = obj.game/
IOP_CFLAGS += -DGAME_DRIVER
else
IOP_BIN = pccf_bd.irx
IOP_OBJS_DIR = obj.gui/
endif
include $(PS2SDK)/Defs.make
include ../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal

# Every translation unit shares pccf_ata_t and inline hardware helpers.
# SDK rules do not generate header dependencies for this module.
$(IOP_OBJS): $(wildcard *.h *.inc) Makefile
