#include "part_driver.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sysmem.h>

#include <bdm.h>
#include "gpt_types.h"

#include "module_debug.h"

void GetGPTPartitionNameAscii(gpt_partition_table_entry *pPartition, char *pAsciiBuffer)
{
    // Loop and perform the world's worst unicode -> ascii string conversion.
    for (int i = 0; i < sizeof(pPartition->partition_name) / sizeof(u16); i++)
        pAsciiBuffer[i] = (char)pPartition->partition_name[i];
}

int part_connect_gpt(struct block_device *bd)
{
    int ret;
    void *buffer = NULL;
    gpt_partition_table_header *pGptHeader;
    gpt_partition_table_entry *pGptPartitionEntry;
    u32 entriesPerSector;
    int endOfTable = 0;
    char partName[37] = {0};
    int partIndex;
    int mountCount = 0;

    M_DEBUG("%s\n", __func__);

    // Like the MBR probe, inspect only a whole device, not a nested partition.
    // The allocator takes a signed byte count; both complete sectors must fit.
    if (bd->sectorOffset != 0 || bd->sectorSize < 512 || bd->sectorSize > 0x3fffffff ||
        (bd->sectorSize & (bd->sectorSize - 1)) != 0 || bd->sectorCount < 2)
        return -EINVAL;

    // Allocate scratch memory for parsing the partition table.
    buffer = AllocSysMemory(ALLOC_FIRST, bd->sectorSize * 2, NULL);
    if (buffer == NULL) {
        M_DEBUG("Failed to allocate memory\n");
        return -ENOMEM;
    }

    pGptHeader = (gpt_partition_table_header *)buffer;
    pGptPartitionEntry = (gpt_partition_table_entry *)((u8 *)buffer + bd->sectorSize);

    // Read the GPT partition table header from the block device.
    ret = bd->read(bd, 1, pGptHeader, 1);
    if (ret != 1) {
        // Failed to read gpt partition table header.
        M_DEBUG("Failed to read GPT partition table header %d\n", ret);
        FreeSysMemory(buffer);
        return -1;
    }

    // Check the partition table header signature.
    if (memcmp(pGptHeader->signature, EFI_PARTITION_SIGNATURE, sizeof(EFI_PARTITION_SIGNATURE)) != 0) {
        // GPT partition table header signature is invalid.
        M_DEBUG("GPT partition table header signature is invalid: %s\n", pGptHeader->signature);
        FreeSysMemory(buffer);
        return -1;
    }

    // Calculate how many partition entries there are per sector.
    entriesPerSector = bd->sectorSize / sizeof(gpt_partition_table_entry);
    u64 tableSectors = (u64)pGptHeader->partition_count / entriesPerSector +
                       (pGptHeader->partition_count % entriesPerSector != 0);
    // Only the fixed entry layout below is supported. Check table and usable
    // ranges before any partition-table read or inclusive-length arithmetic.
    if (pGptHeader->header_size < sizeof(*pGptHeader) || pGptHeader->header_size > bd->sectorSize ||
        pGptHeader->partition_entry_size != sizeof(gpt_partition_table_entry) || pGptHeader->partition_count == 0 ||
        pGptHeader->first_lba < 2 || pGptHeader->first_lba > pGptHeader->last_lba || pGptHeader->last_lba >= bd->sectorCount ||
        pGptHeader->partition_table_lba < 2 || pGptHeader->partition_table_lba >= pGptHeader->first_lba ||
        tableSectors > pGptHeader->first_lba - pGptHeader->partition_table_lba) {
        FreeSysMemory(buffer);
        return -EINVAL;
    }
    // Header/table CRC validation remains separate from these geometry checks.

    // Loop through all the partition table entries and attempt to mount each one.
    M_PRINTF("Found GPT disk '%08x...'\n", *(u32 *)&pGptHeader->disk_guid);
    for (u32 i = 0; i < pGptHeader->partition_count && endOfTable == 0;) {
        // Check if we need to buffer more data, GPT usually uses LBA 2-33 for partition table entries. Typically there will
        // only be a couple partitions at most, so we buffer one sector at a time to avoid making needless allocations for all sectors at once.
        if (i % entriesPerSector == 0) {
            // Read the next sector from the block device.
            ret = bd->read(bd, pGptHeader->partition_table_lba + (i / entriesPerSector), pGptPartitionEntry, 1);
            if (ret != 1) {
                // Failed to read the next sector from the drive.
#ifdef DEBUG
                u64 lba = pGptHeader->partition_table_lba + (i / entriesPerSector);
                DEBUG_U64_2XU32(lba);
                M_DEBUG("Failed to read next partition table entry sector lba=0x%08x%08x\n", lba_u32[1], lba_u32[0]);
#endif
                FreeSysMemory(buffer);
                return -1;
            }

            // Parse the two partition table entries in the structure.
            for (u32 x = 0; x < entriesPerSector && i < pGptHeader->partition_count; x++, i++) {
                // Check if the partition type guid is valid, the header will list the maximum number of partitions that can fit into the table, so
                // we need to check if the entries are actually valid.
                if (memcmp(pGptPartitionEntry[x].partition_type_guid, NULL_GUID, sizeof(NULL_GUID)) == 0) {
                    // Stop scanning for partitions.
                    endOfTable = 1;
                    break;
                }

                // Perform some sanity checks on the partition.
                if (pGptPartitionEntry[x].first_lba < pGptHeader->first_lba || pGptPartitionEntry[x].last_lba > pGptHeader->last_lba ||
                    pGptPartitionEntry[x].first_lba > pGptPartitionEntry[x].last_lba) {
                    // Partition entry data appears to be corrupt.
                    M_DEBUG("Partition entry %d appears to be corrupt (lba bounds incorrect)\n", i);
                    continue;
                }

                // Print the partition info and create a pseudo block device for it.
                GetGPTPartitionNameAscii(&pGptPartitionEntry[x], partName);
                u64 first_lba = pGptPartitionEntry[x].first_lba;
                u64 last_lba = pGptPartitionEntry[x].last_lba;
                u64 attribute_flags = pGptPartitionEntry[x].attribute_flags;
                U64_2XU32(first_lba);
                U64_2XU32(last_lba);
                U64_2XU32(attribute_flags);
                M_PRINTF("Found partition '%s' type=%08x unique=%08x start=0x%08x%08x end=0x%08x%08x attr=0x%08x%08x\n", partName, *(u32 *)&pGptPartitionEntry[x].partition_type_guid,
                         *(u32 *)&pGptPartitionEntry[x].partition_unique_guid, first_lba_u32[1], first_lba_u32[0], last_lba_u32[1], last_lba_u32[0], attribute_flags_u32[1], attribute_flags_u32[0]);

                // Check for specific GPT partition types we should ignore.
                if (memcmp(pGptPartitionEntry[x].partition_type_guid, MS_RESERVED_PARTITION_GUID, sizeof(MS_RESERVED_PARTITION_GUID)) == 0 ||
                    memcmp(pGptPartitionEntry[x].partition_type_guid, EFI_SYSTEM_PARTITION, sizeof(EFI_SYSTEM_PARTITION)) == 0)
                    continue;

                // Check if the partition should be ignored.
                if ((pGptPartitionEntry[x].attribute_flags & GPT_PART_ATTR_IGNORE) != 0)
                    continue;

                // TODO: Check type specific partition flags: read-only, hidden, etc.

                if ((partIndex = GetNextFreePartitionIndex()) == -1) {
                    // No more free partition slots.
                    M_PRINTF("Can't mount partition, no more free partition slots!\n");
                    continue;
                }

                // Create the pseudo block device for the partition.
                part_set_parent(partIndex, bd);
                g_part_bd[partIndex].parNr = i + 1;
                g_part_bd[partIndex].parId = 0;
                g_part_bd[partIndex].sectorOffset = bd->sectorOffset + pGptPartitionEntry[x].first_lba;
                g_part_bd[partIndex].sectorCount = pGptPartitionEntry[x].last_lba - pGptPartitionEntry[x].first_lba + 1;
                bdm_connect_bd(&g_part_bd[partIndex]);
                mountCount++;
            }
        }
    }

    // Free our scratch buffer.
    FreeSysMemory(buffer);
    return mountCount > 0 ? 0 : -1;
}
