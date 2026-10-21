"""UDPFS must deliver every byte of a reply, including the last byte of an odd-sized one (#1010).

modules/network/udpfs_smap/src/xfer.c smap_fifo_read() copies a received frame out of the SMAP RX
FIFO: DMA for whole blocks, then PIO for the rest. Upstream's PIO tail stored whole words and then
one halfword, and had no step for a single trailing byte. So whenever a read ended on an odd byte
count -- the last packet of every file whose size is odd -- the caller got the right length back but
the final byte was never written, and the buffer kept whatever it held before. A tester's whole
Neutrino folder, copied from a UDPFS share to a memory card, came out like that: every odd-sized
file ended in a stray byte, and the NUL that ended i_dev9_hidden.toml stopped Neutrino with "bad
control char in comment" before any UDPFS game could start.

This compiles the real smap_fifo_read (extracted) against a simulated FIFO that holds a frame
padded to 4 bytes, as the hardware does, and checks every byte count a packet can carry at every
DMA block size: all bytes delivered, nothing written past the end, and no read past the frame.
It fails on the upstream code.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
xfer = root / 'modules/network/udpfs_smap/src/xfer.c'


def read(path):
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


def extract_function(source, signature):
    """Full text of the C function whose definition starts with `signature` (comment aware)."""
    start = source.find(signature)
    if start < 0:
        return None
    i = source.index('{', start)
    depth = 0
    while i < len(source):
        if source.startswith('//', i):
            i = source.index('\n', i)
            continue
        if source.startswith('/*', i):
            i = source.index('*/', i) + 2
            continue
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    return None


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;

/* One received frame in the RX FIFO, stored padded to a multiple of 4 bytes like the hardware does. */
static u8 fifo[4096];
static u32 rd_ptr, frame_end;
static int bad_access;

static u32 pop(int n)
{
    u32 v = 0;
    int k;

    if (rd_ptr % 4 != 0 || rd_ptr + (u32)n > frame_end)
        bad_access = 1;
    for (k = 0; k < n; k++)
        v |= (u32)fifo[(rd_ptr + k) % sizeof(fifo)] << (8 * k);
    rd_ptr += n;
    return v;
}

/* The register accesses smap_fifo_read makes, mapped onto the simulated FIFO. */
#define SMAP_REG16(reg) REG16_##reg
#define SMAP_REG32(reg) REG32_##reg
#define REG16_SMAP_R_RXFIFO_RD_PTR rd_ptr
#define REG16_SMAP_R_RXFIFO_DATA ((u16)pop(2))
#define REG32_SMAP_R_RXFIFO_DATA pop(4)
#define DMAC_TO_MEM 0

static int dev9DmaTransfer(int ctrl, void *addr, int bcr, int dir)
{
    u32 n = ((u32)bcr >> 16) * ((u32)bcr & 0xFFFF) * 4;

    (void)ctrl;
    (void)dir;
    if (((uintptr_t)addr % 4) != 0 || rd_ptr % 4 != 0 || rd_ptr + n > frame_end)
        bad_access = 1;
    else
        memcpy(addr, fifo + rd_ptr, n);
    rd_ptr += n;
    return 0;
}

static struct
{
    volatile u8 *smap_regbase;
} SmapDriverData;
static u16 g_current_frame_ptr;
static u16 g_dma_max_block_size;

@FIFO_READ@

static u8 dst[2048 + 16] __attribute__((aligned(4)));

int main(void)
{
    static const u16 frame_starts[] = {0, 1536};
    static const u16 offsets[] = {0x2C, 0x30, 0x34, 0x40};
    static const u16 block_sizes[] = {128, 256, 512};
    static const u8 fills[] = {0x00, 0xFF};
    int failures = 0;
    u32 i;

    for (i = 0; i < sizeof(fifo); i++)
        fifo[i] = (u8)(i * 7 + 3);

    for (u32 f = 0; f < sizeof(frame_starts) / sizeof(frame_starts[0]); f++)
    for (u32 o = 0; o < sizeof(offsets) / sizeof(offsets[0]); o++)
    for (u32 b = 0; b < sizeof(block_sizes) / sizeof(block_sizes[0]); b++)
    for (u32 bytes = 1; bytes <= 1460; bytes++)
    for (u32 v = 0; v < sizeof(fills); v++) {
        u32 offset = offsets[o];
        u32 length = offset + bytes; /* the data ends the frame, as a UDP payload does */
        const u8 *src;

        g_current_frame_ptr = frame_starts[f];
        g_dma_max_block_size = block_sizes[b];
        frame_end = g_current_frame_ptr + ((length + 3) & ~3u);
        src = fifo + g_current_frame_ptr + offset;
        memset(dst, fills[v], sizeof(dst));
        rd_ptr = 0xFFFF;
        bad_access = 0;

        smap_fifo_read(offset, dst, bytes);

        if (memcmp(dst, src, bytes) != 0) {
            u32 k = 0;
            while (dst[k] == src[k])
                k++;
            if (failures++ < 8)
                printf("%u bytes at offset 0x%X (DMA blocks of %u): byte %u not delivered (got 0x%02X, want 0x%02X)\n",
                       bytes, offset, block_sizes[b], k, dst[k], src[k]);
        }
        for (i = bytes; i < bytes + 8; i++) {
            if (dst[i] != fills[v]) {
                if (failures++ < 8)
                    printf("%u bytes at offset 0x%X: wrote past the end at byte %u\n", bytes, offset, i);
                break;
            }
        }
        if (bad_access && failures++ < 8)
            printf("%u bytes at offset 0x%X: unaligned FIFO access or read past the frame\n", bytes, offset);
    }

    if (failures > 8)
        printf("... %d failures in all\n", failures);
    return failures != 0;
}
'''


def compile_and_run(name, source):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / (name + '.c')
        exe = tmp / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(source, encoding='utf-8')
        cmd = ['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-variable', str(src), '-o', str(exe)]
        try:
            build = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        except subprocess.TimeoutExpired:
            return ['%s: gcc did not finish within 120 s' % name]
        if build.returncode != 0:
            return ['%s did not compile:\n%s' % (name, build.stderr)]
        try:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=60)
        except subprocess.TimeoutExpired:
            return ['%s: did not finish within 60 s' % name]
        if run.returncode != 0:
            return (run.stdout.strip().splitlines() or ['%s exited %d' % (name, run.returncode)])
    return []


fifo_read = extract_function(read(xfer), 'void smap_fifo_read(uint16_t offset, void *dst, uint32_t bytes)')
if fifo_read is None:
    failures = ['smap_fifo_read not found in %s' % xfer.relative_to(root)]
else:
    failures = compile_and_run('fifo_tail', HARNESS.replace('@FIFO_READ@', fifo_read))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('UDPFS SMAP RX: every byte count delivered whole, nothing past the end')
