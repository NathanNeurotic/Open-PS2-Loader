#ifndef ZSO_H
#define ZSO_H

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <tamtypes.h>

#define ZSO_MAGIC 0x4F53495A // ZISO

// The index cache covers 256 sectors (512KB of data) at a time; ziso_read_sector() reads larger
// requests in slices of that size.
#define ZISO_IDX_MAX_ENTRIES 257

#define MIN(x, y) ((x < y) ? x : y)

// CSO Header (same for ZSO)
typedef struct
{
    u32 magic;       // 0
    u32 header_size; // 4
    u64 total_bytes; // 8
    u32 block_size;  // 16
    u8 ver;          // 20
    u8 align;        // 21
    u8 rsv_06[2];    // 22
} ZISO_header;


// block offset cache, reduces IO access
extern u32 *ziso_idx_cache;
extern int ziso_idx_start_block;

// header data that we need for the reader
extern u32 ziso_align;
extern u32 ziso_total_block;

// temp block buffer (2048 bytes)
extern u8 *ziso_tmp_buf;

// 0, or -1 for a header the reader cannot read (align above 11, or blocks other than 2048 bytes):
// the file is then not handled as a ZSO image.
int ziso_init(ZISO_header *header, u32 first_block);
int ziso_read_sector(u8 *buf, u32 sector, unsigned int count);

// This must be implemented by isofs/cdvdman/frontend
extern void *ziso_alloc(u32 size);
extern int read_raw_data(u8 *addr, u32 size, u32 offset, u32 shift);

#endif
