IOP_BIN := udpfs_ministack.irx

IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_CFLAGS += -mno-check-zero-division
IOP_INCS := -Iinclude -Isrc -I../udpfs_smap/include
# exports.o MUST be first + _retonly defined after the export table (see src/exports.tab) so
# ps2dev:latest iopfixup doesn't reject _retonly as a value-0 .text symbol. Keep on re-vendor.
IOP_OBJS = exports.o main.o ministack_arp.o ministack_eth.o ministack_ip.o ministack_udp.o udptty.o imports.o

all:: $(IOP_BIN)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
