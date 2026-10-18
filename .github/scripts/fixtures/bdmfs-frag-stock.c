/* Original PS2SDK fragment walker; AFL-2.0. Fault-injection fixture. */
static int get_frag_list(FIL *file, void *rdata, unsigned int rdatalen)
{
    bd_fragment_t *f = (bd_fragment_t*)rdata;
    int iMaxFragments = rdatalen / sizeof(bd_fragment_t);
    int iFragCount = 0;

    // Get the block device backing the file so we can get the starting LBA of the file system.
    struct block_device* bd = fatfs_fs_driver_get_mounted_bd_from_index(file->obj.fs->pdrv);

    DWORD iClusterStart = file->obj.sclust;
    DWORD iClusterCurrent = iClusterStart;

    do {
        DWORD iClusterNext = get_fat(&file->obj, iClusterCurrent);
        if (iClusterNext != (iClusterCurrent + 1)) {
            // Fragment or file end
            M_DEBUG("fragment: %uc - %uc + 1\n", iClusterStart, iClusterCurrent + 1);
            if (iFragCount < iMaxFragments) {
                u64 sector = clst2sect(file->obj.fs, iClusterStart) + bd->sectorOffset;
                f[iFragCount].sector = sector;
                f[iFragCount].count  = clst2sect(file->obj.fs, iClusterCurrent) - clst2sect(file->obj.fs, iClusterStart) + file->obj.fs->csize;
                DEBUG_U64_2XU32(sector);
                M_DEBUG(" - sectors: 0x%08x%08x count %u\n", sector_u32[1], sector_u32[0], f[iFragCount].count);
            }
            iFragCount++;
            iClusterStart = iClusterNext;
        }
        iClusterCurrent = iClusterNext;
    } while(iClusterCurrent < file->obj.fs->n_fatent);

    return iFragCount;
}
