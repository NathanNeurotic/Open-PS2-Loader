# RiptOPL no-IOP-reset child loader (see loader.c). Built like NHDDL's loader:
# a tiny ELF linked into BIOS-unused memory (0x84000) so it can overwrite user
# memory with the target ELF while OPL's IOP state stays untouched.

EE_LINKFILE := linkfile
EE_CFLAGS = -D_EE -Os -G0 -Wall
EE_CFLAGS += -fdata-sections -ffunction-sections
EE_LDFLAGS = -Wl,-zmax-page-size=128
EE_LDFLAGS += -s -Wl,--gc-sections

EE_BIN = elfldr.elf

EE_OBJS = loader.o

EE_LIBS =

all: $(EE_BIN)

clean:
	rm -f -r $(EE_OBJS) $(EE_BIN)

include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.eeglobal
