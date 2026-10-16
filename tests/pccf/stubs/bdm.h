#include <types.h>
struct block_device
{
    void *priv;
    char *name;
    unsigned int devNr, parNr;
    unsigned char parId;
    unsigned int sectorSize;
    u64 sectorOffset, sectorCount;
    int (*read)(struct block_device *, u64, void *, u16);
    int (*write)(struct block_device *, u64, const void *, u16);
    void (*flush)(struct block_device *);
    int (*stop)(struct block_device *);
    char *path;
};
void bdm_connect_bd(struct block_device *bd);
