IOP_BIN := udpfs_ioman.irx

IOP_SRC_DIR := src/
IOP_OBJS_DIR := obj/
IOP_CFLAGS += -mno-check-zero-division -DFEATURE_UDPFS_IOMAN -DUDPRDMA_MAX_SOCKETS=1
IOP_INCS := -Iinclude -Isrc -I../udpfs_smap/include -I../udpfs_ministack/include
IOP_OBJS = main.o udprdma.o udpfs_core.o udpfs_ioman.o imports.o exports.o

all:: $(IOP_BIN)

# A change in the canonical transport source must invalidate BOTH variants'
# per-module objects on incremental builds, not only on clean CI builds.
$(IOP_OBJS_DIR)udpfs_core.o: ../udpfs_shared/src/udpfs_core.c
$(IOP_OBJS_DIR)udprdma.o: ../udpfs_shared/src/udprdma.c

clean::
	rm -f -r $(IOP_BIN) $(IOP_OBJS_DIR)

# Makefile.iopglobal tracks no header dependencies: rebuild every object when a header it can
# include (or this Makefile) changes, so an incremental build never links a stale IRX.
UDPFS_OBJ_DEPS := $(wildcard include/*.h) $(wildcard src/*.h) $(wildcard ../udpfs_smap/include/*.h) $(wildcard ../udpfs_ministack/include/*.h) Makefile
$(addprefix $(IOP_OBJS_DIR),$(IOP_OBJS)): $(UDPFS_OBJ_DEPS)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
