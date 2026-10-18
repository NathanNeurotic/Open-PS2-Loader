/* PS2SDK bdmfs_fatfs fragment walker; Academic Free License 2.0.
 * RiptOPL #986: fail closed on FAT errors and corrupt chains.
 */
static int get_frag_list(FIL *file, void *rdata, unsigned int rdatalen)
{
    bd_fragment_t *f = (bd_fragment_t*)rdata;
    int iMaxFragments = rdatalen / sizeof(bd_fragment_t);
    int iFragCount = 0;
    FATFS *fs;
    struct block_device *bd;
    u64 clusters, clusterBytes, visited;
    DWORD eof, iClusterStart;

    if (file == NULL || file->obj.fs == NULL || (rdata == NULL && rdatalen != 0))
        return -EINVAL;
    fs = file->obj.fs;
    if (fs->csize == 0 || fs->n_fatent <= 2)
        return -EIO;
    if (file->obj.objsize == 0)
        return 0;

#if FF_MAX_SS != FF_MIN_SS
    clusterBytes = (u64)fs->csize * fs->ssize;
#else
    clusterBytes = (u64)fs->csize * FF_MAX_SS;
#endif
    if (clusterBytes == 0)
        return -EIO;
    clusters = (file->obj.objsize - 1) / clusterBytes + 1;
    if (clusters > fs->n_fatent - 2)
        return -EIO;

    switch (fs->fs_type) {
        case FS_FAT12: eof = 0xFF8; break;
        case FS_FAT16: eof = 0xFFF8; break;
        case FS_FAT32: eof = 0x0FFFFFF8; break;
#if FF_FS_EXFAT
        case FS_EXFAT: eof = 0x7FFFFFF8; break;
#endif
        default: return -EINVAL;
    }

    bd = fatfs_fs_driver_get_mounted_bd_from_index(fs->pdrv);
    if (bd == NULL)
        return -ENODEV;

    iClusterStart = file->obj.sclust;
    DWORD iClusterCurrent = iClusterStart;

    // The file length bounds traversal even for a cyclic/corrupt FAT chain.
    for (visited = 0; visited < clusters; visited++) {
        if (iClusterCurrent < 2 || iClusterCurrent >= fs->n_fatent)
            return -EIO;
        DWORD iClusterNext = get_fat(&file->obj, iClusterCurrent);
        // FatFs uses these values for disk/internal errors, not end-of-chain.
        if (iClusterNext == 0xFFFFFFFF || iClusterNext < 2)
            return -EIO;
        if (visited + 1 == clusters) {
            if (iClusterNext < eof)
                return -EIO; // too long or cyclic; no complete mapping was proven
        } else if (iClusterNext >= fs->n_fatent) {
            return -EIO; // premature end, bad cluster, or invalid cluster number
        }

        if (iClusterNext != (iClusterCurrent + 1)) {
            // Fragment or file end
            M_DEBUG("fragment: %uc - %uc + 1\n", iClusterStart, iClusterCurrent + 1);
            if (iFragCount < iMaxFragments) {
                u64 sector = clst2sect(fs, iClusterStart) + bd->sectorOffset;
                u64 count = (u64)(iClusterCurrent - iClusterStart + 1) * fs->csize;
                if (count > 0xFFFFFFFF)
                    return -EOVERFLOW;
                f[iFragCount].sector = sector;
                f[iFragCount].count  = count;
                DEBUG_U64_2XU32(sector);
                M_DEBUG(" - sectors: 0x%08x%08x count %u\n", sector_u32[1], sector_u32[0], f[iFragCount].count);
            }
            if (iFragCount == 0x7FFFFFFF)
                return -EOVERFLOW;
            iFragCount++;
            iClusterStart = iClusterNext;
        }
        iClusterCurrent = iClusterNext;
    }

    return iFragCount;
}
