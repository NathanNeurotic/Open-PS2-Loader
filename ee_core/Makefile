# Copyright 2009-2010, Ifcaro, jimmikaelkael & Polo
# Copyright 2006-2008 Polo
# Licenced under Academic Free License version 3.0
# Review OPNPS2LD README & LICENSE files for further details.
#
# Copyright 2001-2004, ps2dev - http://www.ps2dev.org
# Licenced under Academic Free License version 2.0
# Review ps2sdk README & LICENSE files for further details.
#
# Standard Makefile

EE_BIN = ee_core.elf
.DEFAULT_GOAL := all
EE_SRC_DIR = src/
EE_OBJS_DIR = obj/

GSMCORE_EE_OBJS = gsm_engine.o gsm_api.o dve_reg.o
IGSCORE_EE_OBJS = igs_api.o
CHEATCORE_EE_OBJS = cheat_engine.o cheat_api.o

EE_OBJS = main.o syshook.o iopmgr.o modmgr.o util.o patches.o patches_asm.o \
	  padhook.o cd_igr_rpc.o tlb.o asm.o crt0.o $(GSMCORE_EE_OBJS) $(CHEATCORE_EE_OBJS)
MAPFILE = ee_core.map

EE_INCS := -I$(PS2SDK)/ee/include -I$(PS2SDK)/common/include -I$(PS2SDK)/ports/include -Iinclude -I.
EE_CFLAGS = -D_EE -Os -G0 -Wall $(EE_INCS)

ifeq ($(EESIO_DEBUG),1)
    EE_CFLAGS += -D__EESIO_DEBUG
endif

ifeq ($(DTL_T10000),1)
    EE_CFLAGS += -D_DTL_T10000
endif

# Experimental 1080p raster handler (DTV_1080P in gsm_engine_adv.S + its dispatch). The .S files are
# preprocessed, so -DGSM_1080P gates the #ifdef blocks. Forwarded from the top Makefile's GSM1080P=1.
ifeq ($(GSM1080P),1)
    EE_CFLAGS += -DGSM_1080P
endif

ifeq ($(LOAD_DEBUG_MODULES),1)
EE_CFLAGS += -D__LOAD_DEBUG_MODULES
    ifeq ($(DECI2_DEBUG),1)
    EE_CFLAGS += -D__DECI2_DEBUG
    endif
    ifeq ($(TTY_APPROACH),UDP)
    EE_CFLAGS += -DTTY_UDP
    else ifeq ($(TTY_APPROACH),PPC_UART)
    EE_CFLAGS += -DTTY_PPC
    endif
endif

ifeq ($(IGS),1)
EE_OBJS += $(IGSCORE_EE_OBJS)
EE_CFLAGS += -DIGS
endif

# RetroAchievements, forwarded from the top Makefile's RETROACHIEVEMENTS=1. The
# define also reaches coreconfig.h and modules.h, which grow a field and an enum
# member under it -- so a stale obj/ here reads EECoreConfig_t through the wrong
# offsets and loads the wrong module blob. Run make clean when switching it.
ifeq ($(RETROACHIEVEMENTS),1)
EE_OBJS += ra.o ra_overlay.o ra_pulse.o
EE_CFLAGS += -DRETROACHIEVEMENTS
endif

# In-game freeze report, forwarded from the top Makefile's INGAMEDIAG=1 (the FREEZEDIAG flavour).
# Run make clean when switching it: padhook.o and iopmgr.o change with it.
ifeq ($(INGAMEDIAG),1)
EE_OBJS += freeze_diag.o
EE_CFLAGS += -DINGAMEDIAG
endif

# In-game menu (beta), forwarded from the top Makefile's IGR_MENU=1. coreconfig.h's fields are always there;
# padhook.o, main.o and cheat_api.o change with it, so run make clean when switching it.
# The menu costs ~9 KB of ram84, more than this build's stack can give (the 3 KB ASSERT in linkfile), so these builds
# also drop ee_core's unreferenced code and data (dead util.c helpers and the libgcc they pull in): ~8 KB back.
ifeq ($(IGR_MENU),1)
# IGR_OVERLAY=1 (the RETROACHIEVEMENTS flavour): RA leaves no room for the menu in ram84, so ee_core keeps only
# igrovl_stub.o and the menu is built into igrovl.elf, an overlay the menu copies to IGROVL_BASE (0xCC000) only for
# a launch with In-Game Menu on (include/igrovl.h).
ifeq ($(IGR_OVERLAY),1)
EE_OBJS += igrovl_stub.o
EE_CFLAGS += -DIGR_OVERLAY
else
EE_OBJS += igrmenu.o igrmbox.o
endif
EE_CFLAGS += -DIGR_MENU -ffunction-sections -fdata-sections
endif

EE_OBJS := $(EE_OBJS:%=$(EE_OBJS_DIR)%)

EE_LDFLAGS = -nostartfiles -nostdlib -Tlinkfile -L$(PS2SDK)/ee/lib -s -Wl,-Map,$(MAPFILE)
ifeq ($(IGR_MENU),1)
EE_LDFLAGS += -Wl,--gc-sections
endif
EE_LIBS += -lpatches

ifeq ($(PADEMU),1)
EE_CFLAGS += -DPADEMU
endif

EE_LIBS += -lkernel -lgcc

$(EE_OBJS_DIR)%.o : $(EE_SRC_DIR)%.c
	@mkdir -p $(EE_OBJS_DIR)
	$(EE_CC) $(EE_CFLAGS) $(EE_INCS) -c $< -o $@

$(EE_OBJS_DIR)%.o : $(EE_SRC_DIR)%.S
	@mkdir -p $(EE_OBJS_DIR)
	$(EE_CC) $(EE_CFLAGS) $(EE_INCS) -c $< -o $@

$(EE_OBJS_DIR)%.o : $(EE_SRC_DIR)%.s
	@mkdir -p $(EE_OBJS_DIR)
	$(EE_AS) $(EE_ASFLAGS) $< -o $@

$(EE_BIN) : $(EE_OBJS)
	$(EE_CC) $(EE_CFLAGS) $(EE_LDFLAGS) -o $(EE_BIN) $(EE_OBJS) $(EE_LIBS)

# The overlay: igrmenu.c and igrmbox.c as they are, with what they take from ee_core reached through igrovl_api_t
# (include/igrovl_side.h). Same flags as ee_core, so it reads EECoreConfig_t with the same layout; no ee_core,
# libc or libkernel is linked in.
IGROVL_BIN = igrovl.elf
IGROVL_OBJS_DIR = $(EE_OBJS_DIR)igrovl/
IGROVL_OBJS = $(IGROVL_OBJS_DIR)igrovl_main.o $(IGROVL_OBJS_DIR)igrmenu.o $(IGROVL_OBJS_DIR)igrmbox.o

$(IGROVL_OBJS_DIR)igrovl_main.o : igrovl/igrovl_main.c
	@mkdir -p $(IGROVL_OBJS_DIR)
	$(EE_CC) $(EE_CFLAGS) -DIGR_OVERLAY_SIDE -c $< -o $@

$(IGROVL_OBJS_DIR)%.o : $(EE_SRC_DIR)%.c
	@mkdir -p $(IGROVL_OBJS_DIR)
	$(EE_CC) $(EE_CFLAGS) -DIGR_OVERLAY_SIDE -c $< -o $@

$(IGROVL_BIN) : $(IGROVL_OBJS)
	$(EE_CC) $(EE_CFLAGS) -nostartfiles -nostdlib -Tigrovl/linkfile -s -Wl,--gc-sections -Wl,-Map,igrovl.map \
		-o $(IGROVL_BIN) $(IGROVL_OBJS) -lgcc

ifeq ($(IGR_MENU)$(IGR_OVERLAY),11)
all: $(EE_BIN) $(IGROVL_BIN)
else
all: $(EE_BIN)
endif

clean:
	rm -f -r $(EE_OBJS_DIR) $(EE_BIN) $(MAPFILE) $(IGROVL_BIN) igrovl.map

clean_all:
	rm -f -r $(EE_OBJS_DIR) $(EE_BIN) $(MAPFILE) $(IGROVL_BIN) igrovl.map

include $(PS2SDK)/samples/Makefile.pref
