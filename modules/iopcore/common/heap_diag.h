/*
  IOP heap record (INGAMEDIAG flavour only).

  CDVDMAN hooks SYSMEM's AllocSysMemory and FreeSysMemory while a game runs and keeps this record of
  the blocks the game's IOP modules allocate, the allocations that failed, the lowest free memory
  seen and the modules loadcore lists. It changes no allocation: sizes, order and addresses are the
  game's own. Some games overrun their own IOP buffers (.hack//Infection, SLUS_202.67, fills the
  overrun with 0xFF; neutrino issue #92), and how far past each block's end the 0xFF run reaches is
  the size of the guard a per-game fix needs.

  ee_core reads this record straight from IOP RAM (KSEG1 0xBC000000), so it also works when the IOP
  is dead: it scans for magic + check + self. check is written at run time, so the module's file
  image, which the IOP may still hold, never contains the pair. Shared by CDVDMAN, ee_core and the
  formatter, so it uses plain C types only.
*/

#ifndef HEAP_DIAG_H
#define HEAP_DIAG_H

#define HEAP_DIAG_MAGIC   0x50414548 // "HEAP"
#define HEAP_DIAG_CHECK   0xAFBEBAB7 // ~HEAP_DIAG_MAGIC
#define HEAP_DIAG_VERSION 1

#define HEAP_DIAG_BLOCKS  96 // live blocks; when full, the oldest is dropped (evicted)
#define HEAP_DIAG_FAILS   8  // the last failed allocations
#define HEAP_DIAG_MODULES 24

// How far past a block's end ee_core looks for the overrun's 0xFF run.
#define HEAP_DIAG_TAIL_SCAN 2048

#define HEAP_DIAG_IOP_RAM_SIZE (2 * 1024 * 1024)

typedef struct heap_diag_block
{
    unsigned int addr; // 0: empty slot
    unsigned int size; // as the caller asked for it
    unsigned int ra;   // the caller's return address
    unsigned int seq;  // allocation number; for a failed one, the mode
} heap_diag_block_t;

typedef struct heap_diag_module
{
    char name[8]; // the first 8 characters, not necessarily terminated
    unsigned int text_start;
    unsigned int size; // text + data + bss
} heap_diag_module_t;

typedef struct heap_diag_iop
{
    unsigned int magic;
    unsigned int check;
    unsigned int self; // this record's IOP address
    unsigned int version;

    unsigned int allocs;        // successful allocations seen
    unsigned int frees;         // frees of a tracked block
    unsigned int fails;         // allocations that returned NULL
    unsigned int unknown_frees; // frees of a block allocated before the hook or evicted
    unsigned int evicted;       // live blocks dropped because the table was full
    unsigned int free_now;      // QueryTotalFreeMemSize after the last allocation or free
    unsigned int free_min;      // the lowest free_now
    unsigned int largest_min;   // the lowest QueryMaxFreeMemSize after an allocation
    unsigned int module_count;  // modules loadcore listed (may exceed HEAP_DIAG_MODULES)
    unsigned int fail_next;     // next slot of failed[]
    unsigned int reserved[2];

    heap_diag_block_t blocks[HEAP_DIAG_BLOCKS];
    heap_diag_block_t failed[HEAP_DIAG_FAILS];
    heap_diag_module_t modules[HEAP_DIAG_MODULES];
} heap_diag_iop_t;

// sizeof is checked by the host test; it is copied in 16-byte blocks.
#define HEAP_DIAG_IOP_SIZE 2112

// What ee_core keeps after reading the record: the record and, per block, the 0xFF run after it.
typedef struct heap_diag_snapshot
{
    unsigned int found;    // 1: a record was found in IOP RAM
    unsigned int found_at; // its IOP address
    unsigned int reserved[2];
    unsigned short tail_ff[HEAP_DIAG_BLOCKS]; // 0xFF bytes right after blocks[i] (up to HEAP_DIAG_TAIL_SCAN)
    heap_diag_iop_t iop;
} heap_diag_snapshot_t;

#define HEAP_DIAG_SNAPSHOT_SIZE (16 + 2 * HEAP_DIAG_BLOCKS + HEAP_DIAG_IOP_SIZE)

#endif
