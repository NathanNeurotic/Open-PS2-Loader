/*
  In-game freeze report (INGAMEDIAG flavour only).

  CDVDMAN keeps this record of its disc reads and VMC sector I/O while a game runs. When the
  player presses the IGR combo after a freeze, ee_core asks CDVDFSV for it over the existing IGR
  RPC (server 0x80000598, function FREEZE_DIAG_RPC_FNO) before the IOP is reset, and writes it
  into the report on the memory card. Shared by CDVDMAN, CDVDFSV and ee_core, so it uses plain
  C types only.

  Times are IOP system-clock ticks (36.864 MHz), split into hi/lo words.
*/

#ifndef FREEZE_DIAG_H
#define FREEZE_DIAG_H

#define FREEZE_DIAG_MAGIC   0x5A524644 // "DFRZ"
#define FREEZE_DIAG_VERSION 1

// IGR RPC function number for "send the record" (1 is the shutdown request).
#define FREEZE_DIAG_RPC_FNO 2

#define FREEZE_DIAG_IOP_TICKS_PER_MS 36864

// Values for vmc_last_op / vmc_busy_op.
#define FREEZE_DIAG_VMC_READ  1
#define FREEZE_DIAG_VMC_WRITE 2

typedef struct freeze_diag_iop
{
    unsigned int magic;
    unsigned int version;
    unsigned int now_hi, now_lo; // when the record was handed over

    // Disc reads, as the game sees them (cdvdman_read_sectors).
    unsigned int reads;
    unsigned int read_errors;
    unsigned int eom_hits; // reads refused or cut short by the media size
    unsigned int last_err;
    unsigned int last_lsn;
    unsigned int last_sectors;
    unsigned int media_lsn_count;
    unsigned int max_read_ms;
    unsigned int slow_reads; // device reads that took longer than one second

    // A device read that started and has not returned yet.
    unsigned int busy;
    unsigned int busy_lsn;
    unsigned int busy_sectors;
    unsigned int busy_start_hi, busy_start_lo;

    // VMC sector I/O through CDVDMAN's exports (MCEMU on BDM and MMCE).
    unsigned int vmc_ops;
    unsigned int vmc_last_op;
    unsigned int vmc_last_lba;
    unsigned int vmc_busy;
    unsigned int vmc_busy_op;
    unsigned int vmc_busy_lba;
    unsigned int vmc_busy_start_hi, vmc_busy_start_lo;

    unsigned int reserved[2]; // keeps the size a multiple of 16 for the SIF DMA
} freeze_diag_iop_t;

// sizeof is checked by the host test; the SIF DMA needs a multiple of 16.
#define FREEZE_DIAG_IOP_SIZE 112

#endif
