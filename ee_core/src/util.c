/*
  Copyright 2009-2010, Ifcaro, jimmikaelkael & Polo
  Copyright 2006-2008 Polo
  Licenced under Academic Free License version 3.0
  Review Open PS2 Loader README & LICENSE files for further details.

  Some parts of the code are taken from HD Project by Polo
*/

#include "ee_core.h"
#include "iopmgr.h"
#include "util.h"
#include "coreconfig.h"

extern void *cdvdman_irx;
extern int size_cdvdman_irx;

extern void *cdvdfsv_irx;
extern int size_cdvdfsv_irx;

extern void *_end;

/* Do not link to strcpy() from libc */
void _strcpy(char *dst, const char *src)
{
    strncpy(dst, src, strlen(src) + 1);
}

/* Do not link to strcat() from libc */
void _strcat(char *dst, const char *src)
{
    _strcpy(&dst[strlen(dst)], src);
}

/* Do not link to strncmp() from libc */
int _strncmp(const char *s1, const char *s2, int length)
{
    const char *a = s1;
    const char *b = s2;

    while (length > 0) {
        if ((*a == 0) || (*b == 0))
            return -1;
        if (*a++ != *b++)
            return 1;
        length--;
    }

    return 0;
}

/* Do not link to strcmp() from libc */
int _strcmp(const char *s1, const char *s2)
{
    register int i = 0;

    while ((s1[i] != 0) && (s1[i] == s2[i]))
        i++;

    if (s1[i] > s2[i])
        return 1;
    else if (s1[i] < s2[i])
        return -1;

    return 0;
}

/*----------------------------------------------------------------------------------------*/
/* This function format g_ipconfig with ip, netmask, and gateway                          */
/*----------------------------------------------------------------------------------------*/
void set_ipconfig(void)
{
    USE_LOCAL_EECORE_CONFIG;
    const char *SmapLinkModeArgs[4] = {
        "0x100",
        "0x080",
        "0x040",
        "0x020"};

    memset(g_ipconfig, 0, IPCONFIG_MAX_LEN);
    g_ipconfig_len = 0;

    // add ip to g_ipconfig buf
    strncpy(&g_ipconfig[g_ipconfig_len], config->g_ps2_ip, 16);
    g_ipconfig_len += strlen(config->g_ps2_ip) + 1;

    // add netmask to g_ipconfig buf
    strncpy(&g_ipconfig[g_ipconfig_len], config->g_ps2_netmask, 16);
    g_ipconfig_len += strlen(config->g_ps2_netmask) + 1;

    // add gateway to g_ipconfig buf
    strncpy(&g_ipconfig[g_ipconfig_len], config->g_ps2_gateway, 16);
    g_ipconfig_len += strlen(config->g_ps2_gateway) + 1;

    // Add Ethernet operation mode to g_ipconfig buf
    if (config->g_ps2_ETHOpMode != ETH_OP_MODE_AUTO) {
        strncpy(&g_ipconfig[g_ipconfig_len], "-no_auto", 9);
        g_ipconfig_len += 9;
        strncpy(&g_ipconfig[g_ipconfig_len], SmapLinkModeArgs[config->g_ps2_ETHOpMode - 1], 6);
        g_ipconfig_len += 6;
    }
}

/*----------------------------------------------------------------------------------------*/
/* This function retrieve a pattern in a buffer, using a mask                             */
/*----------------------------------------------------------------------------------------*/
u32 *find_pattern_with_mask(u32 *buf, unsigned int bufsize, const u32 *pattern, const u32 *mask, unsigned int len)
{
    unsigned int i, j;

    len /= sizeof(u32);
    bufsize /= sizeof(u32);

    if (len == 0 || bufsize < len)
        return NULL;

    for (i = 0; i <= bufsize - len; i++) {
        for (j = 0; j < len; j++) {
            if ((buf[i + j] & mask[j]) != pattern[j])
                break;
        }
        if (j == len)
            return &buf[i];
    }

    return NULL;
}

/*----------------------------------------------------------------------------------------*/
/* Copy 'size' bytes of 'eedata' from EE to 'iopptr' in IOP.                              */
/*----------------------------------------------------------------------------------------*/
void CopyToIop(void *eedata, unsigned int size, void *iopptr)
{
    SifDmaTransfer_t dmadata;
    register int id;

    dmadata.src = eedata;
    dmadata.dest = iopptr;
    dmadata.size = size;
    dmadata.attr = 0;

    do {
        id = SifSetDma(&dmadata, 1);
    } while (!id);

    while (SifDmaStat(id) >= 0) {
        ;
    }
}

/*----------------------------------------------------------------------------------------*/
/* Initialize User Memory.                                                                */
/*----------------------------------------------------------------------------------------*/
void WipeUserMemory(void *start, void *end)
{
    unsigned int i;

    for (i = (unsigned int)start; i < (unsigned int)end; i += 64) {
        __asm__ __volatile__(
            "\tsq $0, 0(%0) \n"
            "\tsq $0, 16(%0) \n"
            "\tsq $0, 32(%0) \n"
            "\tsq $0, 48(%0) \n" ::"r"(i));
    }
}

/*----------------------------------------------------------------------------------------*/
/* NOP delay.                                                                             */
/*----------------------------------------------------------------------------------------*/
void delay(int count)
{
    int i, ret;

    for (i = 0; i < count; i++) {
        ret = 0x01000000;
        while (ret--)
            asm("nop\nnop\nnop\nnop");
    }
}

/*----------------------------------------------------------------------------------------*/
/* for debug colors                                                                           */
/*----------------------------------------------------------------------------------------*/
void BlinkColour(u8 x, u32 colour, u8 forever)
{
    u8 i;
    do {
        delay(2);
        BGCOLND(0x000000); // Black
        //foo
        for (i = 1; i <= x; i++) {
            delay(1);
            BGCOLND(colour); // Chosen colour
            delay(1);
            BGCOLND(0x000000); // Black
        }
    } while (forever);
}
