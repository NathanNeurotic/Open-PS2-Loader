#ifndef PCDIAG_CIS_H
#define PCDIAG_CIS_H

/* The caller supplies an already mapped attribute-memory read operation.
   This diagnostic cannot write hardware or follow addresses from a tuple. */
#define PCDIAG_CIS_BUS_LIMIT   0x1000U
#define PCDIAG_CIS_TUPLE_LIMIT 64U
typedef unsigned char (*pcdiag_cis_read_t)(void *context, unsigned int bus_offset);
typedef void (*pcdiag_cis_trace_t)(const char *format, ...);

/* A conservative profile for the read-only CF memory-map observation.
   Values are collected only from the bounded primary chain. */
typedef struct
{
    unsigned int complete;
    unsigned int malformed;
    unsigned int linked;
    unsigned int function_count;
    unsigned int function;
    unsigned int config_count;
    unsigned long config_base;
    unsigned int register_mask;
    unsigned int memory_index_zero;
} pcdiag_cis_info_t;

/* 0: END/link=FF; -1: truncated tuple; -2: byte/tuple bound reached. */
int pcdiag_cis_dump_info(pcdiag_cis_read_t read_byte, void *context,
                         pcdiag_cis_trace_t trace, pcdiag_cis_info_t *info);
int pcdiag_cis_cf_candidate(const pcdiag_cis_info_t *info);
#endif
