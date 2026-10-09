/* POPStarter telemetry adapted from hacan359/Open-PS2-Loader 531aad45.
   Driver selection and ELF handoff remain owned by RiptOPL's VCD launcher. */
#ifdef RETROACHIEVEMENTS
#include "include/opl.h"
#include "include/ethsupport.h"
#include "include/extern_irx.h"
#include "include/supportbase.h"
#include "include/rahash.h"
#include "include/rawatch.h"
#include "include/ranet.h"
#include "include/rapopslaunch.h"
#include "modules/network/common/rapops_cfg.h"
#include <errno.h>

int raPopsPrepare(const char *root, const char *watchRoot, const char *vcdPath, int slotFree)
{
    char boot[16], watchKey[16], contentHash[33], path[256];
    unsigned char ip[4], mask[4], gw[4];
    unsigned char *irx;
    struct rapops_cfg *cfg = NULL;
    unsigned int i;
    int n, fd, off = 0, result = -1;
    unsigned int peer;

    if (!gRATelemetry)
        return 0;
    if (raVcdWatchKey(vcdPath, watchKey, sizeof(watchKey)) != 0 ||
        sbLoadWatchList(watchRoot, watchKey) <= 0 || GetWatchCount() <= 0)
        return 0; /* No support check/list: ordinary POPStarter launch. */
    /* A VCD replacement at the same path retains the same 15-byte protocol
       serial, but MUST NOT inherit another image's watch list. Rehash the
       executable rather than treating a matching path or timestamp as proof. */
    if (raHashVcd(vcdPath, boot, sizeof(boot), contentHash) != 0 ||
        !raVcdWatchGuardMatches(watchRoot, watchKey, contentHash))
        return 0; /* Missing/old guard: game boots normally, untracked. */
    if (!slotFree)
        return -1; /* FAT does not enforce O_EXCL: refuse the user-owned slot explicitly. */
    /* A stale watch list must never make an otherwise playable PS1 game
       unlaunchable when the adapter is down or has no usable IP. */
    if (ethGetNetConfig(ip, mask, gw) < 0 || !(ip[0] | ip[1] | ip[2] | ip[3]))
        return 0;
    if (snprintf(path, sizeof(path), "%sPOPS/MODULE_9.IRX", root) >= (int)sizeof(path))
        return -1;
    irx = malloc(size_rapops_irx);
    if (!irx)
        return 0; /* Optional telemetry: low memory must not block the game. */
    memcpy(irx, &rapops_irx, size_rapops_irx);
    for (i = 0; i + sizeof(*cfg) <= size_rapops_irx; i += 4) {
        if (memcmp(irx + i, RAPOPS_MAGIC, 8) == 0) {
            cfg = (struct rapops_cfg *)(irx + i);
            break;
        }
    }
    if (!cfg) {
        result = 0; /* No valid embedded config; nothing has been installed. */
        goto done;
    }
    n = snprintf(cfg->ipcfg, sizeof(cfg->ipcfg), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]) + 1;
    n += snprintf(cfg->ipcfg + n, sizeof(cfg->ipcfg) - n, "%u.%u.%u.%u", mask[0], mask[1], mask[2], mask[3]) + 1;
    n += snprintf(cfg->ipcfg + n, sizeof(cfg->ipcfg) - n, "%u.%u.%u.%u", gw[0], gw[1], gw[2], gw[3]) + 1;
    cfg->ipcfg_len = n;
    snprintf(cfg->game_id, sizeof(cfg->game_id), "%s", watchKey);
    cfg->client_mode = gRAMode == RA_MODE_CADUCEUS;
    peer = raNetPeerIP();
    if (peer) {
        const unsigned char *host = (const unsigned char *)&peer;
        snprintf(cfg->host, sizeof(cfg->host), "%u.%u.%u.%u", host[0], host[1], host[2], host[3]);
    }
    cfg->count = GetWatchCount();
    cfg->bytes = GetWatchBytes();
    cfg->node_count = GetNodeCount();
    if (!cfg->count || cfg->count > RA_WATCH_MAX || cfg->node_count > RA_NODE_MAX ||
        cfg->bytes + cfg->node_count * RA_NODE_PAIR_BYTES > RA_SNAP_MAX_BYTES)
        goto done;
    memcpy(cfg->list, GetWatchList(), cfg->count * sizeof(unsigned int));
    if (cfg->node_count)
        memcpy(cfg->nodes, GetNodeList(), cfg->node_count * sizeof(struct ra_node));
    /* Ownership/absence was checked before preparation. O_EXCL is only a supplementary
       guard on backends that implement it; PS2 FAT currently ignores that flag. */
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (fd < 0) {
        result = 0; /* Read-only/absent USB path: launch without telemetry. */
        goto done;
    }
    while (off < (int)size_rapops_irx) {
        n = write(fd, irx + off, size_rapops_irx - off);
        if (n <= 0)
            break;
        off += n;
    }
    result = off == (int)size_rapops_irx ? 0 : -1;
    if (close(fd) < 0)
        result = -1;
    if (result < 0 && unlink(path) == 0)
        result = 0; /* A failed install that was fully removed is safe to skip.
                       If removal fails, block to avoid booting a corrupt module. */
done:
    free(irx);
    return result;
}
#endif
