/*
  Copyright 2009-2010, jimmikaelkael
  Licenced under Academic Free License version 3.0
  Review Open PS2 Loader README & LICENSE files for further details.
*/

#include <loadcore.h>
#include <stdio.h>
#include <sysclib.h>

#include "internal.h"
#include "ioplib_util.h"
#include "smsutils.h"

typedef struct ModuleStatus
{
    char name[56];
    u16 version;
    u16 flags;
    int id;
    u32 entry_addr;
    u32 gp_value;
    u32 text_addr;
    u32 text_size;
    u32 data_size;
    u32 bss_size;
    u32 lreserve[2];
} ModuleStatus_t;

// MODLOAD's exports pointers
static int (*LoadStartModule)(char *modpath, int arg_len, char *args, int *modres);
static int (*StartModule)(int id, char *modname, int arg_len, char *args, int *modres);
static int (*LoadModuleBuffer)(void *ptr);
static int (*StopModule)(int id, int arg_len, char *args, int *modres);
static int (*UnloadModule)(int id);
static int (*SearchModuleByName)(char *modname);
static int (*ReferModuleStatus)(int mid, ModuleStatus_t *status);

// modules list to fake loading
struct FakeModule
{
    const char *fname;
    const char *name;
    int id; // ID to return to the game.
    u8 flag;
    u16 version;
    s16 returnValue; // Typical return value of module. RESIDENT END (0), NO RESIDENT END (1) or REMOVABLE END (2).
};

enum FAKE_MODULE_ID {
    FAKE_MODULE_ID_DEV9 = 0xdead0,
    FAKE_MODULE_ID_USBD,
    FAKE_MODULE_ID_SMAP,
    FAKE_MODULE_ID_ATAD,
    FAKE_MODULE_ID_CDVDSTM,
    FAKE_MODULE_ID_CDVDFSV,
};

static struct FakeModule modulefake_list[] = {
#if defined(__USE_DEV9) || defined(USE_PCCF)
    {"DEV9.IRX", "dev9", FAKE_MODULE_ID_DEV9, FAKE_MODULE_FLAG_DEV9, 0x0208, 0},
#endif
    // Faked dynamically for BDM-USB and PADEMU
    {"USBD.IRX", "USB_driver", FAKE_MODULE_ID_USBD, FAKE_MODULE_FLAG_USBD, 0x0204, 2},
#if defined(SMB_DRIVER) || defined(HTTP_DRIVER) || defined(USE_BDM_UDP) || defined(UDPFS_DRIVER)
    {"SMAP.IRX", "INET_SMAP_driver", FAKE_MODULE_ID_SMAP, FAKE_MODULE_FLAG_SMAP, 0x0219, 2},
    {"ENT_SMAP.IRX", "ent_smap", FAKE_MODULE_ID_SMAP, FAKE_MODULE_FLAG_SMAP, 0x021f, 2},
#endif
#if defined(HDD_DRIVER) || defined(USE_BDM_ATA) || defined(USE_PCCF)
    {"ATAD.IRX", "atad_driver", FAKE_MODULE_ID_ATAD, FAKE_MODULE_FLAG_ATAD, 0x0207, 0},
#endif
    {"CDVDSTM.IRX", "cdvd_st_driver", FAKE_MODULE_ID_CDVDSTM, FAKE_MODULE_FLAG_CDVDSTM, 0x0202, 2},
    // Games cannot load CDVDFSV, but this exits to prevent games from trying to unload it. Some games like Jak X check if this module can be unloaded, ostensibly as an anti-HDLoader measure.
    {"CDVDFSV.IRX", "cdvd_ee_driver", FAKE_MODULE_ID_CDVDFSV, FAKE_MODULE_FLAG_CDVDFSV, 0x0202, 2},
    {NULL, NULL, 0, 0}};

//--------------------------------------------------------------
int getModInfo(char *modname, modinfo_t *info)
{
    iop_library_t *libptr;
    register int i;

    libptr = GetLoadcoreInternalData()->let_next;
    while (libptr != 0) {
        for (i = 0; i < 8; i++) {
            if (libptr->name[i] != modname[i])
                break;
        }
        if (i == 8)
            break;
        libptr = libptr->prev;
    }

    if (!libptr)
        return 0;

    info->version = libptr->version;
    info->exports = (void **)(((struct irx_export_table *)libptr)->fptrs);
    return 1;
}

//--------------------------------------------------------------
static const struct FakeModule *checkFakemodByFile(const char *path, const struct FakeModule *fakemod_list)
{
    // check if module is in the list
    while (fakemod_list->fname != NULL) {
        if (strstr(path, fakemod_list->fname)) {
            return fakemod_list;
        }
        fakemod_list++;
    }

    return NULL;
}

static const struct FakeModule *checkFakemodByName(const char *modname, const struct FakeModule *fakemod_list)
{
    // check if module is in the list
    while (fakemod_list->fname != NULL) {
        if (strstr(modname, fakemod_list->name)) {
            return fakemod_list;
        }
        fakemod_list++;
    }

    return NULL;
}

static const struct FakeModule *checkFakemodById(int id, const struct FakeModule *fakemod_list)
{
    // check if module is in the list
    while (fakemod_list->fname != NULL) {
        if (id == fakemod_list->id) {
            DPRINTF("checkFakemodById() module is on fakelist!!!\n");
            return fakemod_list;
        }
        fakemod_list++;
    }

    return NULL;
}

//--------------------------------------------------------------
static int Hook_LoadStartModule(char *modpath, int arg_len, char *args, int *modres)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_LoadStartModule() modpath = %s freeram = %d\n", modpath, QueryTotalFreeMemSize());

    mod = checkFakemodByFile(modpath, modulefake_list);
    if (mod != NULL && mod->flag) {
        *modres = mod->returnValue;
        return mod->id;
    }

    return LoadStartModule(modpath, arg_len, args, modres);
}

//--------------------------------------------------------------
static int Hook_StartModule(int id, char *modname, int arg_len, char *args, int *modres)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_StartModule() id=%d modname = %s freeram = %d\n", id, modname, QueryTotalFreeMemSize());

    mod = checkFakemodById(id, modulefake_list);
    if (mod != NULL && mod->flag) {
        *modres = mod->returnValue;
        return mod->id;
    }

    return StartModule(id, modname, arg_len, args, modres);
}

//--------------------------------------------------------------
static int Hook_LoadModuleBuffer(void *ptr)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_LoadModuleBuffer() modname = %s freeram = %d\n", ((char *)ptr + 0x8e), QueryTotalFreeMemSize());

    mod = checkFakemodByName(((char *)ptr + 0x8e), modulefake_list);
    if (mod != NULL && mod->flag)
        return mod->id;

    return LoadModuleBuffer(ptr);
}

//--------------------------------------------------------------
static int Hook_StopModule(int id, int arg_len, char *args, int *modres)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_StopModule() id=%d arg_len=%d freeram=%d\n", id, arg_len, QueryTotalFreeMemSize());

    mod = checkFakemodById(id, modulefake_list);
    if (mod != NULL && mod->flag) {
        *modres = 1; // Module unloads and returns NO RESIDENT END
        return mod->id;
    }

    return StopModule(id, arg_len, args, modres);
}

//--------------------------------------------------------------
static int Hook_UnloadModule(int id)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_UnloadModule() id=%d freeram\n", id, QueryTotalFreeMemSize());

    mod = checkFakemodById(id, modulefake_list);
    if (mod != NULL && mod->flag)
        return mod->id;

    return UnloadModule(id);
}

//--------------------------------------------------------------
static int Hook_SearchModuleByName(char *modname)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_SearchModuleByName() modname = %s\n", modname);

    mod = checkFakemodByName(modname, modulefake_list);
    if (mod != NULL && mod->flag)
        return mod->id;

    return SearchModuleByName(modname);
}

//--------------------------------------------------------------
static int Hook_ReferModuleStatus(int id, ModuleStatus_t *status)
{
    const struct FakeModule *mod;

    DPRINTF("Hook_ReferModuleStatus() modid = %d\n", id);

    mod = checkFakemodById(id, modulefake_list);
    if (mod != NULL && mod->flag) {
        memset(status, 0, sizeof(ModuleStatus_t));
        strcpy(status->name, mod->name);
        status->version = mod->version;
        status->id = mod->id;
        return id;
    }

    return ReferModuleStatus(id, status);
}

//--------------------------------------------------------------
// Point every module that imports the library at its export table again, after a hook changed it.
void relinkExports(modinfo_t *info)
{
    iop_library_t *lib = (iop_library_t *)((u32)info->exports - 0x14);

    struct irx_import_table *table;
    struct irx_import_stub *stub;

    FlushDcache();

    // go through each table that imports the library
    for (table = lib->caller; table != NULL; table = table->next) {
        // go through each import in the table
        for (stub = (struct irx_import_stub *)table->stubs; stub->jump != 0; stub++) {
            // patch the stub to jump to the address specified in the library export table for "fno"
            stub->jump = 0x08000000 | (((u32)lib->exports[stub->fno] << 4) >> 6);
        }
    }

    FlushIcache();
}

//--------------------------------------------------------------
void hookMODLOAD(void)
{
    struct FakeModule *modlist;

    // get modload export table
    modinfo_t info;
    getModInfo("modload\0", &info);

    // hook modload's LoadStartModule function
    LoadStartModule = (void *)info.exports[7];
    info.exports[7] = (void *)Hook_LoadStartModule;

    // hook modload's StartModule function
    StartModule = (void *)info.exports[8];
    info.exports[8] = (void *)Hook_StartModule;

    // hook modload's LoadModuleBuffer
    LoadModuleBuffer = (void *)info.exports[10];
    info.exports[10] = (void *)Hook_LoadModuleBuffer;

    // Clear the flags of unused modules
    for (modlist = modulefake_list; modlist->fname != NULL; modlist++)
        modlist->flag &= cdvdman_settings.common.fakemodule_flags;

    // check modload version
    if (info.version > 0x102) {
        DPRINTF("MODLOAD supports unloading\n");
        // hook modload's ReferModuleStatus
        ReferModuleStatus = (void *)info.exports[17];
        info.exports[17] = (void *)Hook_ReferModuleStatus;

        // hook modload's StopModule
        StopModule = (void *)info.exports[20];
        info.exports[20] = (void *)Hook_StopModule;

        // hook modload's UnloadModule
        UnloadModule = (void *)info.exports[21];
        info.exports[21] = (void *)Hook_UnloadModule;

        // hook modload's SearchModuleByName
        SearchModuleByName = (void *)info.exports[22];
        info.exports[22] = (void *)Hook_SearchModuleByName;
    } else {
        // Change all REMOVABLE END values to RESIDENT END, if modload is old.
        for (modlist = modulefake_list; modlist->fname != NULL; modlist++) {
            if (modlist->returnValue == 2)
                modlist->returnValue = 0;
        }
    }

    // fix imports
    relinkExports(&info);
}

//--------------------------------------------------------------
/* Per-game fix (IOPCORE_COMPAT_IOP_PAD, set by sbPrepare from a title list): some games write past the
   end of the IOP buffers they allocate. .hack//Infection overruns three of them, 25344, 3328 and 2304
   bytes long, by 1280, 768 and 1792 bytes and hangs loading into "The World" on USB, HDD and UDPBD alike
   (neutrino #92). Those three get the overrun plus 256 bytes more, so it lands in memory nobody else
   owns. Every other allocation gets 256 bytes, like neutrino's Mode 7: a flat 2 KB on every block
   (neutrino p-membo2k) runs the IOP out of RAM on some setups and black-screens the game (neutrino #148).
   If the larger block does not fit, the size asked for is used: the pad never makes an allocation fail. */
#define IOP_PAD_SIZE 256

static const struct
{
    int size; // the overrun block, rounded up to SYSMEM's 256-byte units
    int pad;
} iop_pad_blocks[] = {
    {25344, 1280 + IOP_PAD_SIZE},
    {3328, 768 + IOP_PAD_SIZE},
    {2304, 1792 + IOP_PAD_SIZE},
};

static int iopPadFor(int size)
{
    int rounded = (size + 255) & ~255;
    unsigned int i;

    for (i = 0; i < sizeof(iop_pad_blocks) / sizeof(iop_pad_blocks[0]); i++) {
        if (rounded == iop_pad_blocks[i].size)
            return iop_pad_blocks[i].pad;
    }
    return IOP_PAD_SIZE;
}

static void *(*AllocSysMemory_org)(int mode, int size, void *ptr);

static void *Hook_AllocSysMemory(int mode, int size, void *ptr)
{
    void *result = NULL;

    // A fixed-address request (pbuf_realloc grows a block in place) must keep its exact extent.
    if (mode != ALLOC_ADDRESS && size > 0 && size <= 0x7FFFFFFF - (1792 + IOP_PAD_SIZE))
        result = AllocSysMemory_org(mode, size + iopPadFor(size), ptr);
    if (result == NULL)
        result = AllocSysMemory_org(mode, size, ptr);

    return result;
}

void hookAllocSysMemory(void)
{
    modinfo_t info;
    int oldstate;

    if (!getModInfo("sysmem\0\0", &info))
        return;

    CpuSuspendIntr(&oldstate);
    AllocSysMemory_org = (void *)info.exports[4];
    info.exports[4] = (void *)Hook_AllocSysMemory;
    CpuResumeIntr(oldstate);

    // The modules already loaded (THREADMAN's thread stacks among them) take the pad too, as in neutrino.
    relinkExports(&info);
}
