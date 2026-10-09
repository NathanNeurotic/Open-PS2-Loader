/*
  RA: what OPL writes into its copy of rapops (modules/network/rapops)
  before a PS1 launch. POPStarter loads that copy as MODULE_#.IRX
  without arguments, so the module carries its configuration: OPL
  finds the block by the magic and fills it in.
*/
#ifndef __RAPOPS_CFG_H__
#define __RAPOPS_CFG_H__

#include "ra_watch.h"

#define RAPOPS_MAGIC     "RIPTRA01"
#define RAPOPS_IPCFG_MAX 64

struct rapops_cfg
{
    char magic[8] __attribute__((nonstring)); /* RAPOPS_MAGIC */
    int ipcfg_len;                            /* 0: not configured, the module stays out */
    char ipcfg[RAPOPS_IPCFG_MAX];             /* "ip\0mask\0gateway\0", as SMAP takes it */
    char game_id[16];                         /* the serial, e.g. "SLUS_012.15" */
    unsigned int client_mode;
    char host[16];
    /* the watch list for rapull, the reader on the IOP; count 0: no list */
    unsigned int count;
    unsigned int bytes;
    unsigned int node_count;
    unsigned int list[RA_WATCH_MAX];
    struct ra_node nodes[RA_NODE_MAX];
};

#endif
