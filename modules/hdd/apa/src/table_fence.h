/*
  RiptOPL fork addition -- not part of ps2sdk. See ../ORIGIN.txt and docs/APA-SAFETY.md.

  THE APA TABLE WRITE FENCE.

  LBA 0-1 hold the __mbr header, the root of the partition table. LBA 6 and 7 hold the SDK's error
  records. On an Advanced Format 512e drive -- almost every modern hard disk -- LBA 0-7 are ONE
  physical 4K sector, so an interrupted or misdirected write to any of them can leave the whole
  partition table unreadable ("Connected: YES, Formatted: NO"), even though every game is still on
  the disk.

  So this build lets exactly one kind of write into that sector: a complete, checksummed __mbr
  header at LBA 0, which is what a legitimate partition delete or a journal replay writes. Error
  records, partial writes, a partition header aimed at the wrong sector and anything else are
  refused before they reach the drive.

  Pure functions over raw bytes, so .github/scripts/test_apa_table_safety.py can compile and test
  this exact file on the host. Byte offsets are asserted against apa_header_t in table_fence.c.
*/

#ifndef APA_TABLE_FENCE_H
#define APA_TABLE_FENCE_H

#define APA_FENCE_TABLE_SECTORS 8 // LBA 0-7: one physical sector on 512e drives

#define APA_FENCE_MAGIC        0x00415041 // 'APA\0'
#define APA_FENCE_TYPE_MBR     0x0001
#define APA_FENCE_OFS_CHECKSUM 0x000
#define APA_FENCE_OFS_MAGIC    0x004
#define APA_FENCE_OFS_NEXT     0x008
#define APA_FENCE_OFS_PREV     0x00C
#define APA_FENCE_OFS_ID       0x010
#define APA_FENCE_OFS_START    0x040
#define APA_FENCE_OFS_TYPE     0x048
#define APA_FENCE_OFS_NSUB     0x04C
#define APA_FENCE_OFS_MBRMAGIC 0x100
#define APA_FENCE_ID_LEN       32
#define APA_FENCE_HEADER_WORDS 256 // sizeof(apa_header_t) / 4

static inline u32 apaFenceWord(const unsigned char *p, unsigned int offset)
{
    return (u32)p[offset] | ((u32)p[offset + 1] << 8) | ((u32)p[offset + 2] << 16) | ((u32)p[offset + 3] << 24);
}

// Mirrors apaReadHeader's own acceptance of the MBR sector in this (non-GPT) build: magic, the
// full 1 KB checksum and the Sony MBR magic -- plus the invariants every formatter writes (id
// "__mbr", start 0, MBR type, no sub-partitions) and, when the capacity is known, links that point
// inside the disk.
static inline int apaFenceIsValidMbrHeader(const unsigned char *header, u32 totalLBA)
{
    static const char mbrMagic[] = "Sony Computer Entertainment Inc.";
    static const char mbrId[] = "__mbr";
    u32 sum = 0;
    unsigned int i;

    if (apaFenceWord(header, APA_FENCE_OFS_MAGIC) != APA_FENCE_MAGIC)
        return 0;
    for (i = 1; i < APA_FENCE_HEADER_WORDS; i++)
        sum += apaFenceWord(header, i * 4);
    if (sum != apaFenceWord(header, APA_FENCE_OFS_CHECKSUM))
        return 0;
    for (i = 0; i < sizeof(mbrMagic) - 1; i++) {
        if (header[APA_FENCE_OFS_MBRMAGIC + i] != (unsigned char)mbrMagic[i])
            return 0;
    }
    // "__mbr" as a C string, the way the driver compares ids: bytes after the terminator are not
    // checked, so a formatter's leftover padding cannot turn a legitimate table edit into a refusal.
    for (i = 0; i < sizeof(mbrId); i++) {
        if (header[APA_FENCE_OFS_ID + i] != (unsigned char)mbrId[i])
            return 0;
    }
    if (apaFenceWord(header, APA_FENCE_OFS_START) != 0)
        return 0;
    if ((apaFenceWord(header, APA_FENCE_OFS_TYPE) & 0xFFFF) != APA_FENCE_TYPE_MBR)
        return 0;
    if (apaFenceWord(header, APA_FENCE_OFS_NSUB) != 0)
        return 0;
    if (totalLBA != 0 &&
        (apaFenceWord(header, APA_FENCE_OFS_NEXT) >= totalLBA || apaFenceWord(header, APA_FENCE_OFS_PREV) >= totalLBA))
        return 0;
    return 1;
}

// Every write the APA driver issues passes through here. Returns 1 when it may reach the drive.
static inline int apaFenceWriteAllowed(u32 lba, u32 nsectors, const void *buf, u32 totalLBA)
{
    if (nsectors == 0 || lba >= APA_FENCE_TABLE_SECTORS)
        return 1;

    // The write touches the table's physical sector. Only a whole __mbr header at LBA 0 may.
    return lba == 0 && nsectors == 2 && buf != 0 && apaFenceIsValidMbrHeader((const unsigned char *)buf, totalLBA);
}

#endif /* APA_TABLE_FENCE_H */
