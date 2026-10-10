/* HDLoader game-partition header, shared by HDD enumeration and the
   read-only RetroAchievements hasher. Matches the game core's 1024-byte
   HDL descriptor; part offsets/lengths use 2048-byte logical sectors,
   while data_start is in raw ATA 512-byte sectors. */
#ifndef HDL_LAYOUT_H
#define HDL_LAYOUT_H

#define HDL_LAYOUT_PARTS 65
typedef struct
{
    unsigned int part_offset;
    unsigned int data_start;
    unsigned int part_size;
} hdl_layout_part_t;

typedef struct
{
    unsigned int checksum;
    unsigned int magic;
    char gamename[160];
    unsigned char hdl_compat_flags;
    unsigned char ops2l_compat_flags;
    unsigned char dma_type;
    unsigned char dma_mode;
    char startup[60];
    unsigned int layer1_start;
    unsigned int discType;
    int num_partitions;
    hdl_layout_part_t part_specs[HDL_LAYOUT_PARTS];
} hdl_layout_header_t;

typedef char hdl_layout_header_must_be_1024_bytes[(sizeof(hdl_layout_header_t) == 1024) ? 1 : -1];

#endif
