#ifndef PCDIAG_ATA_H
#define PCDIAG_ATA_H
#include "pcdiag_cf.h"

#define PCDIAG_ATA_POLL_LIMIT_MS 2000U
#define PCDIAG_ATA_READ_LIMIT    6U
#define PCDIAG_ATA_LBA28_SECTORS 0x10000000U

/* Command callback accepts only IDENTIFY (EC, lba=0) and one-sector
   READ SECTORS (20, LBA28). There is no data-write operation. */
typedef struct
{
    const pcdiag_cf_ops_t *memory;
    int (*issue_read_command)(void *context, unsigned int command, unsigned int lba);
} pcdiag_ata_ops_t;

/* Called only after a complete qualifying CIS and an index-zero COR.
   0: IDENTIFY and LBA0 read succeeded; 1: initial register map rejected;
   negative: command/transfer/IDENTIFY failure. Host owner restores MMIO. */
int pcdiag_ata_observe(const pcdiag_ata_ops_t *ops, void *context,
                       pcdiag_cis_trace_t trace);
#endif
