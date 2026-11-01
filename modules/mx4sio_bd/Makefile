# ps2sdk MX4SIO with the partial-transfer retry fix; see ORIGIN.md.
# Keep full/mini objects separate so changing variants never reuses stale objects.
ifeq ($(MINI),1)
IOP_BIN := mx4sio_bd_mini.irx
IOP_OBJS_DIR := obj_mini/
IOP_CFLAGS += -DMINI_DRIVER
else
IOP_BIN := mx4sio_bd.irx
IOP_OBJS_DIR := obj/
endif
IOP_SRC_DIR := src/
IOP_INCS := -Isrc
IOP_OBJS := spi_sdcard_crc7.o spi_sdcard_driver.o crc16.o ioplib.o sio2man_hook.o mx4sio.o imports.o
IOP_LIBS += -lgcc

all:: $(IOP_BIN)

$(IOP_OBJS_DIR):
	mkdir -p $@
$(IOP_OBJS_DIR)build-imports.c: | $(IOP_OBJS_DIR)
MX4SIO_OBJ_DEPS := $(wildcard src/*.h) src/imports.lst Makefile
$(addprefix $(IOP_OBJS_DIR),$(IOP_OBJS)): $(MX4SIO_OBJ_DEPS)

clean::
	rm -f -r mx4sio_bd.irx mx4sio_bd_mini.irx obj/ obj_mini/ *.notiopmod*.elf

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
