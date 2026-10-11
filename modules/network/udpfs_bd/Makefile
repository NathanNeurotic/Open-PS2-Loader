IOP_BIN := udpfs_bd.irx

IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_CFLAGS += -mno-check-zero-division -DFEATURE_UDPFS_BD -DUDPRDMA_MAX_SOCKETS=1
IOP_INCS := -Iinclude -Isrc -I../udpfs_smap/include -I../udpfs_ministack/include
IOP_OBJS = main.o udprdma.o udpfs_core.o udpfs_bd.o imports.o exports.o

all:: $(IOP_BIN)

# A change in the canonical transport source must invalidate BOTH variants'
# per-module objects on incremental builds, not only on clean CI builds.
$(IOP_OBJS_DIR)udpfs_core.o: ../udpfs_shared/src/udpfs_core.c
$(IOP_OBJS_DIR)udprdma.o: ../udpfs_shared/src/udprdma.c

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
