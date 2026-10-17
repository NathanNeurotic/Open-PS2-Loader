/* v30 hardware-validated profiles. Unknown cards retain original PIO.
   Short validation after every IOP reset; no destructive timing sweep. */
static union { u32 words[1024]; unsigned char bytes[4096]; } profile_ref, profile_check;
static int pio_profile(pccf_ata_t *ata)
{
    unsigned int timing, sample, lba;
    if (!strcmp(ata->model, "TS16GCF133")) timing=0x001a101b;
    else if (!strcmp(ata->model, "INIC-2051 CompactFlash Card")) timing=0x001a102b;
    else {
        pccardTrace("CF: unknown model; conservative 16-bit PIO retained"); return 0;
    }
    if (ata->sectors<4096) return -1;
    for (sample=0;sample<3;++sample) {
        lba=sample==0 ? 0 : (sample==1 ? 2048 : ata->sectors/2);
        pio_data_timing=0x001a10bb; pio_cpu32=0; pio_settle_us=1000;
        ata->read_sector=NULL; ata->fast_poll=0;
        if (pccf_ata_read(ata,lba,8,profile_ref.bytes) ||
            pccf_ata_read(ata,lba,8,profile_check.bytes) ||
            memcmp(profile_ref.bytes,profile_check.bytes,4096)) return -1;
        pio_data_timing=timing; pio_cpu32=1; pio_settle_us=0;
        ata->read_sector=pio_read_sector; ata->fast_poll=1;
        if (pccf_ata_read(ata,lba,8,profile_check.bytes) ||
            memcmp(profile_ref.bytes,profile_check.bytes,4096)) return -1;
    }
    pccardTrace("CF: selected timing=%08lx CPU=32 settle=0 validated=3x4096", (unsigned long)timing);
    ata->commands=ata->multi_commands=ata->sector_reads=0;
    return 0;
}
