IOP_OBJS = cdvdman.o ioops.o ncmd.o scmd.o searchfile.o streaming.o ioplib_util.o smsutils.o imports.o exports.o ../../isofs/zso.o ../../isofs/lz4.o
USE_DEV9 ?= 0

ifeq ($(USE_HDD),1)
IOP_BIN  = hdd_cdvdman.irx
IOP_OBJS_DIR = obj.hdd/
IOP_OBJS += device-hdd.o atad.o
IOP_CFLAGS += -DHDD_DRIVER
USE_DEV9 = 1
endif

ifeq ($(USE_HDPRO),1)
IOP_BIN  = hdd_hdpro_cdvdman.irx
IOP_OBJS_DIR = obj.hdpro/
IOP_OBJS += device-hdd.o hdpro_atad.o
IOP_CFLAGS += -DHDD_DRIVER -DHD_PRO
ifeq ($(IOPCORE_DEBUG),1)
USE_DEV9 = 1
endif
endif

ifeq ($(USE_SMB),1)
IOP_BIN  = smb_cdvdman.irx
IOP_OBJS_DIR = obj.smb/
IOP_OBJS += device-smb.o smb.o
IOP_CFLAGS += -DSMB_DRIVER
USE_DEV9 = 1
IOP_INCS += -I../../network/common
endif

# smb_cdvdman with the SMB1 client (smb.c) swapped for the SMB 2.0.2/2.1 one (smb2.c). Same settings
# block and exports, so smb_mcemu serves VMCs for either. Launched when the resident browse driver
# is smb2man (Settings > Network > SMB Version = SMB2).
ifeq ($(USE_SMB2),1)
IOP_BIN  = smb2_cdvdman.irx
IOP_OBJS_DIR = obj.smb2/
IOP_OBJS += device-smb.o smb2.o smb2auth.o
IOP_CFLAGS += -DSMB_DRIVER
USE_DEV9 = 1
IOP_INCS += -I../../network/common
endif

ifeq ($(USE_HTTP),1)
IOP_BIN = http_cdvdman.irx
IOP_OBJS_DIR = obj.http/
IOP_OBJS += device-http.o
IOP_CFLAGS += -DHTTP_DRIVER
USE_DEV9 = 1
IOP_INCS += -I../../network/common
endif

ifeq ($(USE_BDM),1)
IOP_BIN  = bdm_cdvdman.irx
IOP_OBJS_DIR = obj.bdm/
IOP_OBJS += device-bdm.o
IOP_CFLAGS += -DBDM_DRIVER
IOP_LIBS += -L$(PS2SDK)/iop/lib -lbdm
ifeq ($(IOPCORE_DEBUG),1)
USE_DEV9 = 1
endif
endif

ifeq ($(USE_BDM_ATA),1)
IOP_BIN  = bdm_ata_cdvdman.irx
IOP_OBJS_DIR = obj.bdm_ata/
IOP_OBJS += device-bdm.o atad.o
IOP_CFLAGS += -DBDM_DRIVER -DUSE_BDM_ATA
IOP_LIBS += -L$(PS2SDK)/iop/lib -lbdm
USE_DEV9 = 1
ifeq ($(IOPCORE_DEBUG),1)
IOP_CFLAGS += -DDEV9_DEBUG
endif
endif

# OPL-core launch of a UDPBD / UDPFS (block) game: the BDM driver plus the real DEV9 core, so the
# network block chain the EE core loads after the IOP reset imports dev9 and bdm from cdvdman.
ifeq ($(USE_BDM_UDP),1)
IOP_BIN  = bdm_udp_cdvdman.irx
IOP_OBJS_DIR = obj.bdm_udp/
IOP_OBJS += device-bdm.o
IOP_CFLAGS += -DBDM_DRIVER -DUSE_BDM_UDP
IOP_LIBS += -L$(PS2SDK)/iop/lib -lbdm
USE_DEV9 = 1
endif

# OPL-core UDPFS Files games: udpfs_fhi, which the EE core reloads after the reset, imports dev9 from
# this cdvdman and reads the ISO by the server handle the menu kept open.
ifeq ($(USE_UDPFS),1)
IOP_BIN  = udpfs_cdvdman.irx
IOP_OBJS_DIR = obj.udpfs/
IOP_OBJS += device-udpfs.o
IOP_CFLAGS += -DUDPFS_DRIVER
USE_DEV9 = 1
endif

ifeq ($(USE_PCCF),1)
IOP_BIN = pccf_cdvdman.irx
IOP_OBJS_DIR = obj.pccf/
IOP_OBJS += device-bdm.o dev9-pccf.o
IOP_CFLAGS += -DBDM_DRIVER -DUSE_PCCF
IOP_LIBS += -L$(PS2SDK)/iop/lib -lbdm
endif

ifeq ($(USE_MMCE),1)
IOP_BIN  = mmce_cdvdman.irx
IOP_OBJS_DIR = obj.mmce/
IOP_OBJS += device-mmce.o
IOP_CFLAGS += -DMMCE_DRIVER
ifeq ($(IOPCORE_DEBUG),1)
USE_DEV9 = 1
endif
endif

IOP_INCS += -I../common

# In-game freeze report (top Makefile INGAMEDIAG=1, the FREEZEDIAG flavour). Run make clean when switching it.
ifeq ($(INGAMEDIAG),1)
IOP_CFLAGS += -DINGAMEDIAG
# The IOP heap record ee_core reads for the report (../common/heap_diag.h).
IOP_OBJS += heapdiag.o
endif

ifeq ($(IOPCORE_DEBUG),1)
IOP_CFLAGS += -D__IOPCORE_DEBUG
endif

ifeq ($(USE_DEV9),1)
ifeq ($(USE_PCCF),1)
$(error PCCF cannot share the real DEV9 driver)
endif
IOP_OBJS += dev9.o
IOP_CFLAGS += -D__USE_DEV9
endif

include $(PS2SDK)/Defs.make
include ../../Rules.bin.make
include $(PS2SDK)/samples/Makefile.iopglobal

ifeq ($(USE_HTTP),1)
$(IOP_OBJS): $(wildcard *.h ../common/*.h ../../isofs/*.h ../../network/common/*.h ../../network/common/*.inc) Makefile ../../Rules.bin.make
endif
