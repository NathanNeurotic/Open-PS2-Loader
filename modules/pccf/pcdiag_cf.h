#ifndef PCDIAG_CF_H
#define PCDIAG_CF_H
#include "pcdiag_cis.h"

/* This interface deliberately has no card-write or ATA-command operation.
   set_access changes only the host selector and its bus-width bit.
   The owner must restore both host registers after this function returns. */
typedef struct
{
    unsigned char (*read8)(void *context, unsigned int offset);
    unsigned short (*read16)(void *context, unsigned int offset);
    void (*set_access)(void *context, unsigned int space, unsigned int width);
    void (*wait_ms)(void *context, unsigned int milliseconds);
} pcdiag_cf_ops_t;

/* 0: observed; 1: profile or COR does not permit memory-index-zero probe. */
int pcdiag_cf_probe(const pcdiag_cis_info_t *info, const pcdiag_cf_ops_t *ops,
                    void *context, pcdiag_cis_trace_t trace);
#endif
