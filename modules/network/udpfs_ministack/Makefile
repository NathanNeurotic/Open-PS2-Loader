IOP_BIN := udpfs_ministack.irx

IOP_OBJS_DIR := obj/
IOP_CFLAGS += -mno-check-zero-division
IOP_INCS := -Iinclude -Isrc -I../udpfs_smap/include
IOP_OBJS = main.o ministack_arp.o ministack_eth.o ministack_ip.o ministack_udp.o udptty.o imports.o exports.o

all:: $(IOP_BIN)

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
