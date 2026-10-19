/* Academic Free License 2.0. Called under the BDM filesystem lock. */
static int vmc_allocate_contiguous(FIL *file, const vmc_alloc_request_t *request, int reserve)
{
    bd_fragment_t extent;
    u64 sectors;
    FRESULT result;
    if (request->version != VMC_ALLOC_V1 ||
        (request->bytes != 8 * 1048576U && request->bytes != 16 * 1048576U &&
         request->bytes != 32 * 1048576U && request->bytes != 64 * 1048576U))
        return -EINVAL;
    if (file->obj.fs == NULL || !(file->flag & FA_WRITE) ||
        (file->obj.fs->fs_type != FS_FAT12 && file->obj.fs->fs_type != FS_FAT16 &&
         file->obj.fs->fs_type != FS_FAT32 && file->obj.fs->fs_type != FS_EXFAT))
        return -EINVAL;
#if FF_MAX_SS != FF_MIN_SS
    if (file->obj.fs->ssize != 512)
        return -EINVAL;
#else
    if (FF_MAX_SS != 512)
        return -EINVAL;
#endif
    if (reserve) {
        if (file->obj.objsize != 0 || file->fptr != 0)
            return -EEXIST;
        result = f_expand(file, request->bytes, 1);
        if (result != FR_OK)
            return result == FR_DENIED ? -ENOSPC : -EIO;
    }
    if (file->obj.objsize != request->bytes || f_sync(file) != FR_OK)
        return -EIO;
    memset(&extent, 0, sizeof(extent));
    if (get_frag_list(file, &extent, sizeof(extent)) != 1)
        return -EIO;
    sectors = request->bytes / 512U;
    if (extent.count < sectors || extent.sector > 0xFFFFFFFFULL ||
        sectors - 1 > 0xFFFFFFFFULL - extent.sector)
        return -EOVERFLOW;
    return VMC_ALLOC_V1;
}
