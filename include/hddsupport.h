#ifndef __HDD_SUPPORT_H
#define __HDD_SUPPORT_H

#include "include/iosupport.h"
#include "include/hdd.h"

#define HDD_MODE_UPDATE_DELAY MENU_UPD_DELAY_NOUPDATE

#define HDL_GAME_NAME_MAX 64

// APA Partition
#define APA_IOCTL2_GETHEADER 0x6836

typedef struct
{
    char partition_name[APA_IDMAX + 1];
    char name[HDL_GAME_NAME_MAX + 1];
    char startup[8 + 1 + 3 + 1];
    u8 hdl_compat_flags;
    u8 ops2l_compat_flags;
    u8 dma_type;
    u8 dma_mode;
    u8 disctype;
    u32 layer_break;
    u32 start_sector;
    u32 total_size_in_kb;
} hdl_game_info_t;

typedef struct
{
    u32 count;
    hdl_game_info_t *games;
} hdl_games_list_t;

// HDD PS1/VCD store: PS1 .VCD games live on dedicated APA partitions __.POPS / __.POPS0..9 (each a
// PFS filesystem with GameName.VCD at its root). This is the sorted, deduped list of which __.POPS*
// partitions are present, enumerated from the APA partition table.
typedef struct
{
    int count;
    char (*names)[APA_IDMAX + 1]; // malloc'd array of partition labels, e.g. "__.POPS", "__.POPS3"
} hdd_pops_list_t;

typedef struct
{
    u32 start;
    u32 length;
} apa_subs;

#include "include/mcemu.h"
typedef struct
{
    int active;                 /* Activation flag */
    apa_subs parts[5];          /* Vmc file Apa partitions */
    pfs_blockinfo_t blocks[10]; /* Vmc file Pfs inode */
    int flags;                  /* Card flag */
    vmc_spec_t specs;           /* Card specifications */
} hdd_vmc_infos_t;

typedef enum {
    HDD_LOADMODULES_STATUS_ERROR = -2,
    HDD_LOADMODULES_STATUS_UNK = -1,
    HDD_LOADMODULES_STATUS_NOERROR,
    HDD_LOADMODULES_STATUS_ALREADYLOADED,
    HDD_LOADMODULES_STATUS_BUSYLOADING,
    HDD_LOADMODULES_STATUS_COUNT,
} hdd_loadmodules_status;

int hddCheck(void);
u32 hddGetTotalSectors(void);
int hddIs48bit(void);
int hddSetTransferMode(int type, int mode);
void hddSetIdleTimeout(int timeout);
void hddSetIdleImmediate(void);
int hddGetHDLGamelist(hdl_games_list_t *game_list);
void hddFreeHDLGamelist(hdl_games_list_t *game_list);
// Enumerate the present __.POPS / __.POPS0..9 APA partitions (HDD PS1/VCD store). Fills a sorted,
// deduped list; returns the count (0 on none/error). Free via hddFreePopsPartitionList.
int hddGetPopsPartitionList(hdd_pops_list_t *list);
void hddFreePopsPartitionList(hdd_pops_list_t *list);
int hddSetHDLGameInfo(hdl_game_info_t *ginfo);
int hddDeleteHDLGame(hdl_game_info_t *ginfo);

void hddInit(item_list_t *itemList);
item_list_t *hddGetObject(int initOnly);
int hddLoadModules(void);
void hddLoadSupportModules(void);
void hddLaunchGame(item_list_t *itemList, int id, config_set_t *configSet);
int hddIsPresent();

#endif
