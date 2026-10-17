#ifndef PCCF_ATA_H
#define PCCF_ATA_H
#include "pcdiag_ata.h"

/* Persistent ATA session. Caller serializes all requests. */
typedef struct
{
    const pcdiag_ata_ops_t *ops;
    void *context;
    pcdiag_cis_trace_t trace;
    unsigned int ready, sectors, commands, sector_reads;
    unsigned int multi_commands;
    unsigned int lba48, flush_command, write_cache, write_commands;
    int (*issue_command)(void *context, unsigned int command, unsigned int lba, unsigned int count);
    void (*write_sector)(const unsigned char *buffer);
    int (*issue_read_sectors)(void *context, unsigned int lba, unsigned int count);
    unsigned int (*time_us)(void);
    void (*read_sector)(unsigned char *buffer);
    unsigned int fast_poll;
    char model[41], serial[21], firmware[9];
} pccf_ata_t;
int pccf_ata_attach(pccf_ata_t *ata, const pcdiag_ata_ops_t *ops,
                    void *context, pcdiag_cis_trace_t trace);
int pccf_ata_read(pccf_ata_t *ata, unsigned int lba, unsigned int count,
                  unsigned char *buffer);

int pccf_ata_write(pccf_ata_t *ata, unsigned int lba, unsigned int count, const unsigned char *buffer);

/* Production PC CARD host. No SPEED, DMA or DEV9 exports. */
int pccf_hw_start(pccf_ata_t *ata);
int pccf_hw_present(void);
void pccf_hw_stop(void);
#endif
