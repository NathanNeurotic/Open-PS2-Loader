/*
  igrovl_stub.c ee_core's side of the in-game menu overlay (IGR_OVERLAY builds: the RetroAchievements editions)

  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  IGR_MenuRun and IGR_MboxLink as the rest of ee_core calls them, run by igrovl.elf, which the launcher put at
  IGROVL_BASE for this launch (ee_core/include/igrovl.h). Without it, or with one of another ABI, the menu cannot
  draw and the combo leaves the game as with the menu off.
*/

#if defined(IGR_MENU) && defined(IGR_OVERLAY)
#include "ee_core.h"
#include "coreconfig.h"
#include "cheat_api.h"
#include "cheat_engine.h"
#include "modmgr.h"
#include "util.h"
#include "igrmenu.h"
#include "igrovl.h"

extern u64 GSMSourceGSRegs[11];
extern u16 GSMSourceSetGsCrt[3];

static int igrovlFlushCache(int op)
{
    FlushCache(op);
    return 0;
}

static const igrovl_api_t igrovlApi = {
    &g_ee_core_config,
    (int (*)(const void *))CheatLiveApply,
    (int (*)(const void *, u32))CheatLiveFits,
    &codeentry,
    CopyToIop,
    LoadOPLModule,
    GSMSourceGSRegs,
    GSMSourceSetGsCrt,
    igrovlFlushCache,
    GsGetIMR,
    GsPutIMR,
};

static const igrovl_hdr_t *igrovlFind(void)
{
    const igrovl_hdr_t *h = (const igrovl_hdr_t *)IGROVL_BASE;

    if (!g_ee_core_config.IgrMenu || h->magic != IGROVL_MAGIC || h->abi != IGROVL_ABI)
        return NULL;
    return h;
}

int IGR_MenuRun(u16 (*buttons)(void))
{
    const igrovl_hdr_t *h = igrovlFind();

    return h != NULL ? h->run(&igrovlApi, buttons) : IGR_MENU_CANNOT_DRAW;
}

void IGR_MboxLink(void)
{
    const igrovl_hdr_t *h = igrovlFind();

    if (h != NULL)
        h->link(&igrovlApi);
}
#endif
