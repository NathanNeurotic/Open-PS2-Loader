/*
# _____     ___ ____     ___ ____
#  ____|   |    ____|   |        | |____|
# |     ___|   |____ ___|    ____| |    \    PS2DEV Open Source Project.
#-----------------------------------------------------------------------
# Copyright 2001-2004, ps2dev - http://www.ps2dev.org
# Licenced under Academic Free License version 2.0
# Review ps2sdk README & LICENSE files for further details.
#
# APA journal related routines
*/

#include <errno.h>
#include <iomanX.h>
#ifdef _IOP
#include <sysclib.h>
#else
#include <string.h>
#endif
#include <stdio.h>
#include <hdd-ioctl.h>

#include "libapa.h"
#include "hdd_blkio.h"

//  Globals
// OSD/ATAD startup can skip restore/reset before the first metadata transaction.
static apa_journal_t journalBuf = {.magic = APAL_MAGIC};

int apaJournalFlush(s32 device)
{ // this write any thing that in are journal buffer :)
    if (blkIoFlushCache(device))
        return -EIO;
    if (blkIoDmaTransfer(device, &journalBuf, APA_SECTOR_APAL, 1, BLKIO_DIR_WRITE))
        return -EIO;
    if (blkIoFlushCache(device))
        return -EIO;
    return 0;
}

int apaJournalReset(s32 device)
{
    memset(&journalBuf, 0, sizeof(apa_journal_t));
    journalBuf.magic = APAL_MAGIC;
    return apaJournalFlush(device);
}

void apaJournalAbort(void)
{
    journalBuf.magic = APAL_MAGIC;
    journalBuf.num = 0;
}

int apaJournalWrite(apa_cache_t *clink)
{
    if (journalBuf.num < 0 ||
        (u32)journalBuf.num >= sizeof(journalBuf.sectors) / sizeof(journalBuf.sectors[0]))
        return -EIO;
    clink->header->checksum = journalCheckSum(clink->header);
    if (blkIoDmaTransfer(clink->device, clink->header,
                         (journalBuf.num << 1) + APA_SECTOR_APAL_HEADERS, 2, BLKIO_DIR_WRITE))
        return -EIO;
    journalBuf.sectors[journalBuf.num] = clink->sector;
    journalBuf.num++;
    return 0;
}

int apaJournalRestore(s32 device)
{ // copies the journal from the HDD and erases the original.
    int ret, i;
    u32 sector;
    apa_cache_t *clink;

    APA_PRINTF(APA_DRV_NAME ": checking log...\n");
    ret = blkIoDmaTransfer(device, &journalBuf, APA_SECTOR_APAL, sizeof(apa_journal_t) / 512, BLKIO_DIR_READ) == 0 ? 0 : -EIO;
    // A failed read does not establish that the journal is empty or invalid.
    // Preserve it so a subsequent recovery attempt can retry the same record.
    if (ret != 0)
        return ret;
    if (journalBuf.magic != APAL_MAGIC || journalBuf.num < 0 ||
        (u32)journalBuf.num > sizeof(journalBuf.sectors) / sizeof(journalBuf.sectors[0]))
        return -EIO;
    if (journalBuf.num == 0)
        return 0;

    clink = apaCacheAlloc();
    if (clink == NULL)
        return -ENOMEM;
    for (i = 0, sector = APA_SECTOR_APAL_HEADERS; i < journalBuf.num; i++, sector += 2) {
        ret = (blkIoDmaTransfer(device, clink->header, sector, 2, BLKIO_DIR_READ) == 0) ? 0 : -EIO;
        if (ret != 0)
            break;

        ret = (blkIoDmaTransfer(device, clink->header, journalBuf.sectors[i], 2, BLKIO_DIR_WRITE) == 0) ? 0 : -EIO;
        if (ret != 0)
            break;
    }
    apaCacheFree(clink);
    if (ret != 0)
        return ret;

    return apaJournalReset(device);
}
