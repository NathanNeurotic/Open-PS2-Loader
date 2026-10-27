#include <string.h>
#include <kernel.h>
#include <sifrpc.h>
#include <delaythread.h>

#include "nbns.h"
#include "ioman.h"

static SifRpcClientData_t SifRpcClient;
static char RpcBuffer[64] ALIGNED(64);

int nbnsInit(void)
{
    // Bounded like HttpInit: if nbns.irx failed to load the server never appears, and an unbounded
    // spin would hang SMB startup on the IO worker forever. Without NBNS, name lookups fail cleanly
    // (nbnsFindName returns -1) and IP addresses keep working.
    for (int attempt = 0; attempt < 300; attempt++) {
        if (SifBindRpc(&SifRpcClient, 0x00001B13, 0) >= 0 && SifRpcClient.server != NULL)
            return 0;
        DelayThread(10000);
    }
    LOG("libnbns: bind timed out\n");
    nbnsDeinit();
    return -1;
}

void nbnsDeinit(void)
{
    memset(&SifRpcClient, 0, sizeof(SifRpcClientData_t));
}

int nbnsFindName(const char *name, unsigned char *ip_address)
{
    int result;

    if (SifRpcClient.server == NULL)
        return -1; // nbnsInit never bound (or timed out): no NBNS service to ask

    strncpy(RpcBuffer, name, 16);
    RpcBuffer[16] = '\0';

    if ((result = SifCallRpc(&SifRpcClient, NBNS_RPC_ID_FIND_NAME, 0, RpcBuffer, 17, RpcBuffer, sizeof(struct nbnsFindNameResult), NULL, NULL)) >= 0) {
        result = ((struct nbnsFindNameResult *)RpcBuffer)->result;
        memcpy(ip_address, ((struct nbnsFindNameResult *)RpcBuffer)->address, 4);
    }

    return result;
}
