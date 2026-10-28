/* Private, versioned RiptOPL BDM allocation contract. Shared by EE/IOP/driver.
 * Success is a positive magic value; an unsupported ioctl returning zero fails.
 */
#ifndef VMC_ALLOC_H
#define VMC_ALLOC_H
#define VMC_ALLOC_CAPS        0x564D4300
#define VMC_ALLOC_RESERVE     0x564D4301
#define VMC_ALLOC_VERIFY      0x564D4302
#define VMC_ALLOC_V1          0x564D0101
#define VMC_CREATE_CONTIGUOUS 1
/* Ported from RIPPS2 build 114 (akilluminati47/RIPPS2): a volume's free KB, total KB, cluster bytes and FatFs fs_type
 * (1 FAT12, 2 FAT16, 3 FAT32, 4 exFAT), four u32 into the devctl's out buffer. Drive Status shows it. f_getfree reads
 * exFAT's bitmap or FAT32's FAT once (FAT32 trusts a valid FSINFO), then keeps the count. Same number as RIPPS2's. */
#define BDM_DEVCTL_VOLINFO    0x52500002
typedef struct
{
    unsigned int version;
    unsigned int bytes;
} vmc_alloc_request_t;
#endif
