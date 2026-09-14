/*
  RiptOPL fork addition -- not part of ps2sdk. See table_fence.h and ../ORIGIN.txt.

  The one place the APA driver's block transfers reach the ATA driver: hdd_blkio.h routes
  blkIoDmaTransfer here, so every write -- cache flushes, journal replay, error records, raw
  HDIOC_WRITESECTOR, a format -- is checked by the same fence.
*/

#include <errno.h>
#include <iomanX.h>
#include <sysclib.h>
#include <stdio.h>
#include <atad.h>
#include <hdd-ioctl.h>

#include "libapa.h"
#include "hdd_blkio.h"
#include "table_fence.h"

extern apa_device_t hddDevices[]; // defined in hdd.c

// The fence reads raw bytes by offset. Prove at compile time that those offsets are this build's
// apa_header_t, so a re-vendor that changes the layout (e.g. enabling APA_SUPPORT_GPT) fails to
// build instead of silently checking the wrong fields.
typedef char apaFenceAssertSize[(sizeof(apa_header_t) == APA_FENCE_HEADER_WORDS * 4) ? 1 : -1];
typedef char apaFenceAssertNext[(__builtin_offsetof(apa_header_t, next) == APA_FENCE_OFS_NEXT) ? 1 : -1];
typedef char apaFenceAssertPrev[(__builtin_offsetof(apa_header_t, prev) == APA_FENCE_OFS_PREV) ? 1 : -1];
typedef char apaFenceAssertId[(__builtin_offsetof(apa_header_t, id) == APA_FENCE_OFS_ID) ? 1 : -1];
typedef char apaFenceAssertIdLen[(APA_IDMAX == APA_FENCE_ID_LEN) ? 1 : -1];
typedef char apaFenceAssertStart[(__builtin_offsetof(apa_header_t, start) == APA_FENCE_OFS_START) ? 1 : -1];
typedef char apaFenceAssertType[(__builtin_offsetof(apa_header_t, type) == APA_FENCE_OFS_TYPE) ? 1 : -1];
typedef char apaFenceAssertNsub[(__builtin_offsetof(apa_header_t, nsub) == APA_FENCE_OFS_NSUB) ? 1 : -1];
typedef char apaFenceAssertMbrMagic[(__builtin_offsetof(apa_header_t, mbr.magic) == APA_FENCE_OFS_MBRMAGIC) ? 1 : -1];
typedef char apaFenceAssertTypeMbr[(APA_TYPE_MBR == APA_FENCE_TYPE_MBR) ? 1 : -1];
typedef char apaFenceAssertMagic[(APA_MAGIC == APA_FENCE_MAGIC) ? 1 : -1];
typedef char apaFenceAssertErrorSectors[(APA_SECTOR_PART_ERROR < APA_FENCE_TABLE_SECTORS) ? 1 : -1];

int apaFencedDmaTransfer(int device, void *buf, u32 lba, u32 nsectors, int dir)
{
    if (dir == BLKIO_DIR_WRITE) {
        u32 totalLBA = (device >= 0 && device < BLKIO_MAX_VOLUMES) ? hddDevices[device].totalLBA : 0;

        if (!apaFenceWriteAllowed(lba, nsectors, buf, totalLBA)) {
            APA_PRINTF(APA_DRV_NAME ": refused a %lu-sector write at LBA %lu (APA table fence)\n",
                       (unsigned long)nsectors, (unsigned long)lba);
            return -EROFS;
        }
    }

    return sceAtaDmaTransfer(device, buf, lba, nsectors, dir);
}
