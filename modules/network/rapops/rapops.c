/*
  rapops: RetroAchievements telemetry under POPS.

  POPStarter loads MODULE_#.IRX after resetting the IOP with POPS's
  image, without arguments, and ee_core is not running. This module
  carries the network modules (blobs.S) and starts them with the
  arguments ee_core would give. OPL fills g_cfg in the copy it writes
  before the launch (src/bdmsupport.c).

  The snapshot comes from rapull, the reader on the IOP, started here
  with the list OPL wrote into g_cfg. No code of ours runs on the EE:
  the trojan route (lab/pops, patches 0006-0010) lost to this one.
*/

#include <tamtypes.h>
#include <loadcore.h>
#include <modload.h>
#include <sysmem.h>
#include "ra_snap.h"
#include "rapops_cfg.h"

#define MODNAME "rapops"
IRX_ID(MODNAME, 1, 0);

struct rapops_cfg g_cfg = {RAPOPS_MAGIC};

extern u8 rp_dev9[], rp_smsutils[], rp_smstcpip[], rp_smap[], rp_raudp[], rp_rapull[];

static int start_buffer(void *irx, int arglen, const char *args)
{
    int id, result;

    id = LoadModuleBuffer(irx);
    if (id < 0)
        return id;

    if (StartModule(id, MODNAME, arglen, args, &result) < 0)
        return -1;

    return result;
}

static void hex32(char *dst, u32 v)
{
    static const char hex[] = "0123456789abcdef";
    int i;

    for (i = 7; i >= 0; i--, v >>= 4)
        dst[i] = hex[v & 0xF];
}

/* The list must outlive this module, which unloads when _start
   returns, so it gets memory of its own. rapull's argv[1] is five hex
   words: the snapshot, the list, count, node count, bytes. */
static void start_rapull(void *snap)
{
    char args[5 * 9 + 16];
    u32 *list;
    int n, i;

    if (g_cfg.count == 0 || g_cfg.count > RA_WATCH_MAX || g_cfg.node_count > RA_NODE_MAX)
        return;

    list = AllocSysMemory(ALLOC_FIRST, (g_cfg.count + g_cfg.node_count * 2) * sizeof(u32), NULL);
    if (list == NULL)
        return;
    for (i = 0; i < (int)g_cfg.count; i++)
        list[i] = g_cfg.list[i];
    for (i = 0; i < (int)g_cfg.node_count; i++) {
        list[g_cfg.count + i * 2] = g_cfg.nodes[i].w;
        list[g_cfg.count + i * 2 + 1] = g_cfg.nodes[i].offset;
    }

    hex32(&args[0], (u32)snap);
    args[8] = ',';
    hex32(&args[9], (u32)list);
    args[17] = ',';
    hex32(&args[18], g_cfg.count);
    args[26] = ',';
    hex32(&args[27], g_cfg.node_count);
    args[35] = ',';
    hex32(&args[36], g_cfg.bytes);
    args[44] = '\0';
    n = 45;
    for (i = 0; i < 15 && g_cfg.game_id[i] != '\0'; i++)
        args[n + i] = g_cfg.game_id[i];
    args[n + i] = '\0';

    start_buffer(rp_rapull, n + i + 1, args);
}

int _start(int argc, char *argv[])
{
    char args[RA_ARG_MAX + 1 + RAPOPS_IPCFG_MAX];
    void *snap;
    int i, n;

    (void)argc;
    (void)argv;

    if (g_cfg.ipcfg_len <= 0 || g_cfg.ipcfg_len > RAPOPS_IPCFG_MAX ||
        g_cfg.count == 0 || g_cfg.count > RA_WATCH_MAX || g_cfg.node_count > RA_NODE_MAX ||
        g_cfg.bytes == 0 || g_cfg.bytes > RA_SNAP_MAX_BYTES ||
        g_cfg.bytes + g_cfg.node_count * RA_NODE_PAIR_BYTES > RA_SNAP_MAX_BYTES)
        return MODULE_NO_RESIDENT_END; /* not written by OPL */

    /* TODO: POPS may bring its own DEV9; whether ours then fails to load
       or replaces it is not known. SMAP needs either one. */
    start_buffer(rp_dev9, 0, NULL);
    start_buffer(rp_smsutils, 0, NULL);
    start_buffer(rp_smstcpip, 0, NULL);
    start_buffer(rp_smap, g_cfg.ipcfg_len, g_cfg.ipcfg);

    snap = AllocSysMemory(ALLOC_FIRST, RA_SNAP_TOTAL, NULL);
    if (snap == NULL)
        return MODULE_NO_RESIDENT_END;
    ((volatile struct ra_snap *)snap)->magic = 0; /* raudp sends nothing until rapull writes one */

    /* laid out as ee_core does it (iopmgr.c).
       TODO: no EE event buffer under POPS yet, so no notices in game. */
    hex32(&args[RA_ARG_SNAP], (u32)snap);
    args[RA_ARG_EVENT - 1] = ',';
    hex32(&args[RA_ARG_EVENT], 0);
    args[RA_ARG_RX - 1] = ',';
    args[RA_ARG_RX] = g_cfg.client_mode ? '3' : '1';
    args[RA_ARG_ID - 1] = ',';
    for (i = 0; i < RA_ARG_ID_MAX; i++)
        args[RA_ARG_ID + i] = ' ';
    for (i = 0; i < RA_ARG_ID_MAX && g_cfg.game_id[i] != '\0'; i++)
        args[RA_ARG_ID + i] = g_cfg.game_id[i];
    args[RA_ARG_HOST - 1] = ',';
    for (i = 0; i < 15 && g_cfg.host[i] != '\0'; i++)
        args[RA_ARG_HOST + i] = g_cfg.host[i];
    args[RA_ARG_HOST + i] = '\0';
    n = RA_ARG_HOST + i + 1;

    for (i = 0; i < g_cfg.ipcfg_len; i++)
        args[n + i] = g_cfg.ipcfg[i];
    n += i;

    start_buffer(rp_raudp, n, args);
    start_rapull(snap);

    /* the started modules live in their own memory; this frees the blobs */
    return MODULE_NO_RESIDENT_END;
}
