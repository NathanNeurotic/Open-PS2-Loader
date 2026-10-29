#include "lz4.h"
#include "zso.h"

#ifdef _IOP
#include <sysclib.h>
#endif

// block offset cache, reduces IO access
u32 *ziso_idx_cache = NULL;
int ziso_idx_start_block = -1;
// entries the last index read returned; only these hold offsets
static u32 ziso_idx_entries = 0;

// header data that we need for the reader
u32 ziso_align;
u32 ziso_total_block;

// block buffers
u8 *ziso_tmp_buf = NULL;

int ziso_init(ZISO_header *header, u32 first_block)
{
    // read_raw_data() divides by (2048 >> align): a larger shift divides by zero, or is undefined
    if (header->align > 11)
        return -1;
    // The reader indexes blocks of one 2048-byte sector. maxcso writes 16 KiB blocks for images of
    // 2 GiB and more, whose index would be read as the wrong sectors (belomaxorka / YAOPL 9ad4afeb).
    if (header->block_size != 2048)
        return -1;

    // read header information
    ziso_align = header->align;
    ziso_idx_start_block = -1;
    // calculate number of blocks without using 64bit division library
    u32 *total_bytes_p = (u32 *)&(header->total_bytes);
    ziso_total_block = (total_bytes_p[0] >> 11) | ((total_bytes_p[1] & 0x7ff) << 21);
    // allocate memory
    if (ziso_tmp_buf == NULL) {
        ziso_tmp_buf = ziso_alloc(2048 + sizeof(u32) * ZISO_IDX_MAX_ENTRIES + 64);
        if ((u32)ziso_tmp_buf & 63) // align 64
            ziso_tmp_buf = (void *)(((u32)ziso_tmp_buf & (~63)) + 64);
        if (ziso_tmp_buf) {
            ziso_idx_cache = (u32 *)(ziso_tmp_buf + 2048);
        }
    }
    return 0;
}

/*
  The meat of the compressed sector reader.
  Taken from ARK-4's Inferno 2 ISO Driver.
  Tailored for OPL.
  It's made to work with 2048 block size (matching DVD sector size) and LZ4 compression (ZSO).
  Reads at most ZISO_IDX_MAX_ENTRIES - 1 sectors, which the index cache covers at once.
  Returns the sectors decoded, 0 for an index that cannot be right, or -1 when a device read failed.
*/
static int ziso_read_slice(u8 *addr, u32 lsn, unsigned int count)
{

    u32 cur_block = lsn;

    // refresh index table if needed
    if (ziso_idx_start_block < 0 || lsn < ziso_idx_start_block || lsn + count >= ziso_idx_start_block + ziso_idx_entries - 1) {
        int r = read_raw_data((u8 *)ziso_idx_cache, ZISO_IDX_MAX_ENTRIES * sizeof(u32), lsn * 4 + sizeof(ZISO_header), 0);
        // A file-backed read can come back short, and the rest of the cache still holds the previous
        // window's offsets. Keep only the entries read, and fail unless they cover this request.
        ziso_idx_entries = (r > 0) ? (u32)r / sizeof(u32) : 0;
        if (ziso_idx_entries < count + 1) {
            ziso_idx_start_block = -1; // a failed read leaves the cache invalid, never half-trusted
            return -1;
        }
        ziso_idx_start_block = lsn;
    }

    u32 o_start = (ziso_idx_cache[cur_block - ziso_idx_start_block] & 0x7FFFFFFF);
    u32 o_end = (ziso_idx_cache[cur_block + count - ziso_idx_start_block] & 0x7FFFFFFF);

    // A corrupt or truncated index could place the compressed data outside the buffer: the offsets must
    // not decrease, and the blocks must fit the count * 2048 bytes the caller provides (a block is stored
    // in at most the 2048 bytes it decodes to). Checked before the subtraction is trusted as a size.
    for (unsigned int i = 1; i <= count; i++) {
        if ((ziso_idx_cache[cur_block - ziso_idx_start_block + i] & 0x7FFFFFFF) < (ziso_idx_cache[cur_block - ziso_idx_start_block + i - 1] & 0x7FFFFFFF))
            return 0;
    }
    if (o_end - o_start > (count * 2048) >> ziso_align)
        return 0;
    u32 compressed_size = (o_end - o_start) << ziso_align;

    // read all compressed data to the end of provided buffer to reduce IO
    u8 *c_buff = addr + (count * 2048) - compressed_size;
    if (read_raw_data(c_buff, compressed_size, o_start, ziso_align) != (int)compressed_size)
        return -1; // a short or failed read must not be decompressed as if it were the image

    // process each sector
    for (unsigned int i = 0; i < count; i++) {

        // read block offset and size from cache
        u32 b_offset = ziso_idx_cache[cur_block - ziso_idx_start_block];
        u32 b_size = ziso_idx_cache[cur_block - ziso_idx_start_block + 1];
        u32 topbit = b_offset & 0x80000000;         // extract top bit
        b_offset = (b_offset & 0x7FFFFFFF);         // remove top bit
        b_size = (b_size & 0x7FFFFFFF);             // remove top bit
        b_size = (b_size - b_offset) << ziso_align; // calculate size of compressed block

        // prevent reading more than a sector (eliminates padding if any)
        int r = MIN(b_size, 2048);

        // check top bit to determine if block is compressed or raw
        if (topbit == 0) {                                                 // block is compressed
            memcpy(ziso_tmp_buf, c_buff, r);                               // read compressed block into temp buffer
            LZ4_decompress_fast((char *)ziso_tmp_buf, (char *)addr, 2048); // decompress block
        } else {
            // move block to its correct position in the buffer
            memcpy(addr, c_buff, r);
        }

        cur_block++;
        addr += 2048;
        c_buff += b_size;
    }
    return cur_block - lsn;
}

/*
  Returns the sectors decoded (fewer near the end of the image, or up to an index that cannot be right),
  or -1 when a device read failed.
*/
int ziso_read_sector(u8 *addr, u32 lsn, unsigned int count)
{
    unsigned int done = 0;

    if (ziso_idx_cache == NULL) {
        return 0; // ziso_init could not allocate the index cache
    }

    if (lsn >= ziso_total_block) {
        return 0; // can't seek beyond file
    }

    if (lsn + count > ziso_total_block) {
        count = ziso_total_block - lsn; // adjust oob reads
    }

    // The index cache holds ZISO_IDX_MAX_ENTRIES offsets, so a larger read goes in slices. The game's whole
    // request reaches here when accurate reads are off; above 256 sectors it used to fail every time.
    while (done < count) {
        unsigned int n = count - done;
        if (n > ZISO_IDX_MAX_ENTRIES - 1)
            n = ZISO_IDX_MAX_ENTRIES - 1;
        int r = ziso_read_slice(addr + done * 2048, lsn + done, n);
        if (r < 0)
            return -1; // a device read failed: never report it as a short read
        done += r;
        if ((unsigned int)r != n)
            break;
    }
    return done;
}
