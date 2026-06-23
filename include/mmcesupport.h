#ifndef __MMCE_SUPPORT_H
#define __MMCE_SUPPORT_H

#include "include/iosupport.h"
#include "include/mcemu.h"

#define MMCE_MODE_UPDATE_DELAY MENU_UPD_DELAY_GENREFRESH

typedef struct
{
    int active;       /* Activation flag */
    int fd;           /* VMC fd */
    int flags;        /* Card flag */
    vmc_spec_t specs; /* Card specifications */
} mmce_vmc_infos_t;

void mmceInit(item_list_t *itemList);
item_list_t *mmceGetObject(int initOnly);
void mmceLoadModules(void);
void mmceLaunchGame(item_list_t *itemList, int fd, config_set_t *configSet);
// Push the selected game's disc id to a present MMCE card (SD2PSX/MemCard PRO2) for per-game folder
// switching. Self-probes mmce0:/mmce1: when no MMCE-tab prefix is set, so it works on ALL launch
// paths (USB/HDD/SMB), not just the MMCE tab. No-ops if the feature is off or no card answers (#261).
int mmceSendGameID(const char *startup);

#endif
