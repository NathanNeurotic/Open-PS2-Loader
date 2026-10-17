/* RiptOPL CF partition validation. No filesystem writes. */
#ifndef PCCF_MBR_H
#define PCCF_MBR_H
static unsigned int pccf_le32(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}
static int pccf_mbr_valid(const unsigned char *sector, unsigned int sectors)
{
    int usable = 0;
    if (!sector || sector[510] != 0x55 || sector[511] != 0xaa)
        return 0;
    for (int i = 0; i < 4; i++) {
        const unsigned char *part = sector + 446 + i * 16;
        unsigned int start = pccf_le32(part + 8), count = pccf_le32(part + 12);
        if (part[4] == 0xee)
            return 0;
        if (part[4] != 0x0b && part[4] != 0x0c && part[4] != 0x07)
            continue;
        if ((part[0] != 0 && part[0] != 0x80) || !start || !count || start >= sectors || count > sectors - start)
            return 0;
        usable = 1;
    }
    return usable;
}
#endif
