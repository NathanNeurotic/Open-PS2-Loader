#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <types.h>
#include "../../modules/pccf/pccf_ata.h"
static unsigned int pio_data_timing = 0x001a10bb, pio_cpu32, pio_settle_us = 1000;
static unsigned int calls, fault;
static void pio_read_sector(unsigned char *b) { (void)b; }
static void pccardTrace(const char *f, ...) { (void)f; }
int pccf_ata_read(pccf_ata_t *a, unsigned int l, unsigned int n, unsigned char *b)
{
    unsigned int i;
    ++calls;
    assert(l < a->sectors && n <= a->sectors - l && n == 8);
    for (i = 0; i < n * 512; ++i)
        b[i] = (l + i + i / 8) & 255;
    if (fault == 1 && a->read_sector)
        b[1] ^= 1;
    if (fault == 2 && calls == 2)
        b[2] ^= 1;
    if (fault == 3 && a->read_sector) {
        a->ready = 0;
        return -1;
    }
    return 0;
}
#include "../../modules/pccf/pccf_pio_profile.inc"
int main(void)
{
    pccf_ata_t a;
    memset(&a, 0, sizeof(a));
    a.sectors = 0x1de0000;
    a.ready = 1;
    strcpy(a.model, "TS16GCF133");
    assert(pio_profile(&a) == 0 && calls == 9);
    assert(pio_data_timing == 0x001a101b && pio_cpu32 && !pio_settle_us && a.fast_poll && a.read_sector);
    calls = 0;
    strcpy(a.model, "INIC-2051 CompactFlash Card");
    assert(pio_profile(&a) == 0 && calls == 9 && pio_data_timing == 0x001a102b);
    fault = 1;
    calls = 0;
    assert(pio_profile(&a) < 0 && calls == 3);
    fault = 2;
    calls = 0;
    assert(pio_profile(&a) < 0 && calls == 2);
    fault = 3;
    calls = 0;
    assert(pio_profile(&a) < 0 && !a.ready);
    memset(&a, 0, sizeof(a));
    strcpy(a.model, "UNKNOWN");
    calls = 0;
    assert(pio_profile(&a) == 0 && !calls && !a.read_sector);
    puts("PASS CF profiles: CF/MicroSD timing, all reference comparisons, corruption/protocol failure, conservative unknown card");
}
