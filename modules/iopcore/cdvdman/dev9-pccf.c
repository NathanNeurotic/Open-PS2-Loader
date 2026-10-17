/* Hardware-inert DEV9/ATAD imports for the exclusive PC CARD CF backend. */
#include <types.h>

int pccfDev9Unavailable(void)
{
    return -1;
}

void *pccfAtaInit(int device)
{
    (void)device;
    return 0;
}

int pccfAtaUnavailable(void)
{
    // ATAD ABI: ATA_RES_ERR_NODEV. Never access or reset the card bus.
    return -505;
}
