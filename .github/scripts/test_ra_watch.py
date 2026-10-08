"""Exercise production watch validation, persistent layout and EE sampling on a host.

Hardware clock and DMA calls are stubbed; this does not establish console timing.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
watch = (root / 'src/rawatch.c').read_text(encoding='utf-8')
ee = (root / 'ee_core/src/ra.c').read_text(encoding='utf-8')


def function(source, name):
    match = re.search(r'^[^\n{};]+\b' + name + r'\([^\n]*\)\n\{', source, re.M)
    return source[match.start():source.index('\n}', match.end()) + 2]


prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "modules/network/common/ra_snap.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define LOG(...) ((void)0)
static unsigned int gWatchList[RA_WATCH_MAX];
static int gWatchCount, gWatchBytes, gNodeCount;
static struct ra_node gNodeList[RA_NODE_MAX];
static char gWatchStartup[16];
static u32 *gBlockList;
static struct ra_node *gBlockNodes;
static void *gBlockSnap;
static void raLaunchNote(const char *s, int a, int b) {(void)s; (void)a; (void)b;}
'''
loader = '\n'.join(function(watch, n) for n in (
    'CheckEntries', 'TakeNodes', 'ClearWatchList', 'SetWatchList', 'align64',
    'PlaceWatchBlock', 'GetWatchBlockList', 'GetWatchBlockNodes', 'GetWatchBlockSnap'))

ee_body = ee[ee.index('#define RA_START_DELAY'):ee.rindex('#endif')]
ee_body = ee_body.replace(function(ee, 'ra_ticks'),
                          'static u32 ra_ticks(void) { return ++clock_ticks; }')
stubs = r'''
struct EECoreConfig_t {
    u32 *raWatchList; int raWatchCount, raSnapBytes;
    void *raNodeList; int raNodeCount; void *raSnapBuf; char GameID[16];
};
static struct EECoreConfig_t g_ee_core_config;
#define USE_LOCAL_EECORE_CONFIG struct EECoreConfig_t *config = &g_ee_core_config
#define RA_PROBE 0
static u8 memory[0x02000000];
#define UNCACHED_SEG(x) ((uintptr_t)(x) < sizeof(memory) ? (uintptr_t)(memory + (uintptr_t)(x)) : (uintptr_t)(x))
typedef struct {void *src, *dest; int size, attr;} SifDmaTransfer_t;
static unsigned ra_snap_iop = 1, transfers, clock_ticks;
static int isceSifDmaStat(int id) {(void)id; return -1;}
static int isceSifSetDma(SifDmaTransfer_t *dma, int n) {
    assert(n == 1 && dma->size <= RA_SNAP_TOTAL);
    transfers++; return transfers;
}
static void RA_OverlayOnVblank(unsigned n) {(void)n;}
'''
tests = r'''
static u8 block[40000] __attribute__((aligned(64)));
static u32 packet[4 + RA_WATCH_MAX];
static void list(unsigned count, unsigned width) {
    struct ra_watch_file *h = (void *)packet;
    h->magic = RA_WATCH_MAGIC; h->version = RA_WATCH_VERSION;
    h->count = count; h->bytes = count * width;
    for (unsigned i = 0; i < count; i++) packet[4+i] = RA_WATCH_PACK(0x80001, width);
}
static void prepare(void) {
    g_ee_core_config.raWatchList = GetWatchBlockList();
    g_ee_core_config.raWatchCount = gWatchCount;
    g_ee_core_config.raSnapBytes = gWatchBytes;
    g_ee_core_config.raNodeList = GetWatchBlockNodes();
    g_ee_core_config.raNodeCount = gNodeCount;
    g_ee_core_config.raSnapBuf = GetWatchBlockSnap();
    RA_SetupWatchList(); ra_snap_dma_id = 0; ra_frames = RA_START_DELAY;
}
int main(void) {
    assert(sizeof(struct ra_snap) == 64);
    list(4096, 1);
    assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") == 4096);
    void *end = PlaceWatchBlock(block + 1);
    assert(end <= (void *)(block + sizeof(block)) && ((uintptr_t)end & 63) == 0);
    assert(((uintptr_t)gBlockList & 63) == 0 && ((uintptr_t)gBlockSnap & 63) == 0);
    assert((u8 *)gBlockSnap >= (u8 *)(gBlockList + 4096));
    prepare(); assert(ra_snap_every == 2);
    unsigned before = transfers;
    for (int i=0; i<6; i++) RA_OnVblank();
    assert(transfers == before + 3);
    list(2700, 4); assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") == 2700);
    PlaceWatchBlock(block); prepare(); assert(ra_snap_every == 3);
    before = transfers;
    for (int i=0; i<6; i++) RA_OnVblank();
    assert(transfers == before + 2);
    list(4096, 4);
    assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") < 0);
    list(1, 3); assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") == -8);
    list(1, 4); ((struct ra_watch_file *)packet)->bytes = 3;
    assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") == -8);
    list(1, 4); assert(SetWatchList(packet, sizeof(packet), "SLUS_210.65") == 1);
    PlaceWatchBlock(block); prepare(); assert(ra_snap_every == 1);
    memory[0x80001]=0x12; memory[0x80002]=0x34;
    memory[0x80003]=0x56; memory[0x80004]=0x78;
    ra_snap_send();
    assert(!memcmp((u8 *)gBlockSnap + RA_SNAP_HDR, memory + 0x80001, 4));
    assert(((struct ra_snap *)gBlockSnap)->read_cycles > 0);
    gBlockList[0] = RA_WATCH_PACK(0x1FFFFFF, 4); ra_snap_send();
    assert(!memcmp((u8 *)gBlockSnap + RA_SNAP_HDR, "\0\0\0\0", 4));
    gBlockList[0] = RA_WATCH_PACK(0x80001, 2); gWatchBytes = 2; prepare();
    ra_snap_send(); assert(!memcmp((u8 *)gBlockSnap + RA_SNAP_HDR, memory + 0x80001, 2));
    gWatchList[0] = RA_WATCH_PACK(0x80000, 1);
    gWatchBytes = 1; gNodeCount = 1;
    gNodeList[0].w = RA_NODE_PACK(0, 0, 4); gNodeList[0].offset = 0x80001;
    PlaceWatchBlock(block); prepare(); memory[0x80000] = 0;
    ra_snap_send();
    assert(!memcmp((u8 *)gBlockSnap + RA_SNAP_HDR + 1, "\0\0\0\0\0\0\0\0", 8));
    ClearWatchList(); assert(PlaceWatchBlock(block + 1) == block + 1);
    assert(!GetWatchBlockList() && !GetWatchBlockNodes() && !GetWatchBlockSnap());
    puts("PASS: watch ceilings, malformed lists, persistent layout, cadence, unaligned/bounded reads, null chains");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ra-watch-') as work:
    path = Path(work) / 'watch.c'
    exe = Path(work) / 'watch'
    path.write_text(prefix + loader + stubs + ee_body + tests, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-fno-strict-aliasing', '-Wall', '-Wextra',
                    '-Werror', '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast',
                    '-I', str(root), str(path), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
