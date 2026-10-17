/* CPU loads remain on a 16-bit external bus, AINC=0. Each 32-bit
   instruction consumes two consecutive ATA words from the same port. */
static void pio_read_sector(unsigned char *buffer)
{
    unsigned int i, v;
    if (pio_cpu32 && !((unsigned long)buffer & 3)) {
        u32 *out = (u32 *)buffer;
        for (i = 0; i < 128; i += 8) {
            out[i] = HW_R32(CARD(0)); out[i+1] = HW_R32(CARD(0));
            out[i+2] = HW_R32(CARD(0)); out[i+3] = HW_R32(CARD(0));
            out[i+4] = HW_R32(CARD(0)); out[i+5] = HW_R32(CARD(0));
            out[i+6] = HW_R32(CARD(0)); out[i+7] = HW_R32(CARD(0));
        }
    } else if (!pio_cpu32 && !((unsigned long)buffer & 1)) {
        u16 *out = (u16 *)buffer;
        for (i = 0; i < 256; i += 8) {
            out[i] = HW_R16(CARD(0)); out[i+1] = HW_R16(CARD(0));
            out[i+2] = HW_R16(CARD(0)); out[i+3] = HW_R16(CARD(0));
            out[i+4] = HW_R16(CARD(0)); out[i+5] = HW_R16(CARD(0));
            out[i+6] = HW_R16(CARD(0)); out[i+7] = HW_R16(CARD(0));
        }
    } else {
        /* Same MMIO width for misaligned destinations; never unaligned lw/sw. */
        for (i = 0; i < 512; i += pio_cpu32 ? 4 : 2) {
            v = pio_cpu32 ? HW_R32(CARD(0)) : HW_R16(CARD(0));
            buffer[i] = v; buffer[i+1] = v >> 8;
            if (pio_cpu32) { buffer[i+2] = v >> 16; buffer[i+3] = v >> 24; }
        }
    }
}
