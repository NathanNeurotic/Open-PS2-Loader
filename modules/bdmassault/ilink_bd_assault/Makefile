IOP_BIN = ilink_bd_assault.irx

# IEEE1394_bd
IEEE1394_BD_OBJS = sbp2_driver.o main.o scsi.o

# iLinkman
ILINKMAN_OBJS = iLink.o iLink_PHY.o iLink_internal.o iLink_crom.o iLink_intr.o iLink_TxRx.o iLink_DMA.o

IOP_OBJS = exports.o $(IEEE1394_BD_OBJS) $(ILINKMAN_OBJS) imports.o
IOP_CFLAGS += -mno-check-zero-division -Wno-strict-aliasing -DREQ_CHECK_CONSOLE_VERSION
IOP_INCS += -Iinclude -Isrc/iLinkman/include -Isrc/
IOP_LDFLAGS = -lgcc

IOP_OBJS_DIR := obj/
IOP_SRC_DIR := src/
IOP_INC_DIR := $(IOP_SRC_DIR)include/

all: $(IOP_BIN) $(IOP_LIB)

clean:
	rm -rf $(IOP_OBJS_DIR) $(IOP_BIN) $(IOP_LIB) *.elf

rebuild: clean all
.PHONY: all clean rebuild

include $(PS2SDK)/Defs.make
include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal

$(IOP_OBJS_DIR)%.o: src/IEEE1394_bd/src/%.c
	$(DIR_GUARD)
	$(IOP_C_COMPILE) -c $< -o $@

$(IOP_OBJS_DIR)%.o: src/iLinkman/src/%.c
	$(DIR_GUARD)
	$(IOP_C_COMPILE) -c $< -o $@
