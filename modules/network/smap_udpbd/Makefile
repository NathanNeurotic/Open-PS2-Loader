IOP_BIN := smap_udpbd.irx

IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_CFLAGS += -mno-check-zero-division
IOP_INCS := -Isrc/include
# exports.o MUST be first + _retonly defined after the export table (see src/exports.tab) so
# ps2dev:latest iopfixup doesn't reject _retonly as a value-0 .text symbol. Local change from
# the upstream NHDDL recipe; see ORIGIN.txt.
IOP_OBJS = exports.o main.o smap.o xfer.o ministack.o udpbd.o udptty.o imports.o

all:: $(IOP_BIN)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
