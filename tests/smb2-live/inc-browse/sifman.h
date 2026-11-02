#include <string.h>
typedef struct
{
    void *src, *dest;
    int size, attr;
} SifDmaTransfer_t;
static inline int sceSifSetDma(SifDmaTransfer_t *d, int n)
{
    (void)n;
    memcpy(d->dest, d->src, d->size);
    return 1;
}
static inline int sceSifDmaStat(int id)
{
    (void)id;
    return -1;
}
