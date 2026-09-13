"""Exercise production BDM cache reads against a memory-only faulting device.

An optional SDK bd_cache.c path plus --expect-stale reproduces the historical
failed-refill bug. No physical disk is opened or written.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
args = [arg for arg in sys.argv[1:] if arg != '--expect-stale']
source = (Path(args[0]) if args else root / 'modules/bdm/src/bd_cache.c').read_text()
source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#define M_DEBUG(...) ((void)0)
#define DEBUG_U64_2XU32(x) ((void)0)
#define ALLOC_FIRST 0
struct block_device {
 void *priv; const char *name;
 unsigned devNr, parNr, parId, sectorSize;
 u64 sectorOffset, sectorCount;
 int (*read)(struct block_device*, u64, void*, u16);
 int (*write)(struct block_device*, u64, const void*, u16);
 void (*flush)(struct block_device*); int (*stop)(struct block_device*);
#if HAS_PATH
 const char *path;
#endif
};
static int allocations, fail_alloc;
static void *AllocSysMemory(int mode, size_t size, void *ptr) {
 (void)mode; (void)ptr;
 if(fail_alloc && --fail_alloc==0) return NULL;
 void *p=malloc(size); assert(p); memset(p,0,size); allocations++; return p;
}
static void FreeSysMemory(void *p) { assert(p); allocations--; free(p); }
static int calls, writes, fault, fault_result=-5;
static u16 last_count;
static int device_read(struct block_device *bd,u64 lba,void *buf,u16 count) {
 calls++; last_count=count;
 assert(lba < bd->sectorCount && count <= bd->sectorCount-lba);
 if(fault) { memset(buf,0xee,512); return fault_result; }
 memset(buf,0,count*bd->sectorSize);
 /* An old block elsewhere on the disk contains a plausible MBR. */
 if(lba!=0) {
  unsigned char *p=buf; p[446+4]=0x0c; p[446+8]=8; p[446+12]=64;
  p[510]=0x55; p[511]=0xaa;
 }
 return count;
}
static int device_write(struct block_device *bd,u64 lba,const void *buf,u16 count) {
 (void)bd; (void)lba; (void)buf; writes++; return count;
}
'''
# Include the production partition probes to verify full-read checks and the
# compatibility-preserving parent/callback setup in both SDK layouts.
if not args:
    names = ('include/mbr_types.h', 'include/gpt_types.h', 'include/part_driver.h',
             'part_driver.c', 'part_driver_mbr.c', 'part_driver_gpt.c')
    for name in names:
        text = (root / 'modules/bdm/src' / name).read_text()
        source += '\n' + '\n'.join(line for line in text.splitlines() if not line.startswith('#include'))
prefix += r'''
#define M_PRINTF(...) ((void)0)
#define U64_2XU32(x) ((void)(x))
struct file_system { void *priv; const char *name; int (*connect_bd)(struct block_device*); void (*disconnect_bd)(struct block_device*); };
static int mounted;
static void bdm_connect_bd(struct block_device *bd) { (void)bd; mounted++; }
static void bdm_disconnect_bd(struct block_device *bd) { (void)bd; }
static void bdm_connect_fs(struct file_system *fs) { (void)fs; }
static unsigned char sectors[3][512];
static int probe_result=1;
static int probe_read(struct block_device *bd,u64 lba,void *buf,u16 count) {
 (void)bd; assert(lba<3 && count==1); memcpy(buf,sectors[lba],512); return probe_result;
}
'''

tests = r'''
int main(void) {
 unsigned char out[8192];
 struct block_device bd={.name="ata",.sectorSize=512,.sectorCount=4096,.read=device_read,.write=device_write};
#if HAS_PATH
 bd.path="mass";
#endif
 struct block_device *cache=bd_cache_create(&bd);
 assert(cache && cache->name==bd.name && cache->sectorCount==bd.sectorCount);
#if HAS_PATH
 assert(cache->path==bd.path);
#endif
 /* Fill all slots through successful reads; no uninitialized-memory assumption. */
 for(int i=1;i<=32;i++) assert(cache->read(cache,16*i,out,1)==1);
 int before=calls;
 assert(cache->read(cache,512,out,1)==1 && calls==before);
 assert(out[510]==0x55 && out[511]==0xaa);
 /* Leave old bytes intact for the stale-data reproduction. */
 fault=1; fault_result=-5;
#if EXPECT_STALE
 /* Historical refill behavior is also wrong when a failed read touches nothing. */
 fault=2;
#endif
 memset(out,0x7b,sizeof(out));
 before=calls;
 int result=cache->read(cache,0,out,1);
 printf("Failed LBA0 refill: return=%d, stale MBR signature=%d, device calls=%d\n",result,out[510]==0x55 && out[511]==0xaa,calls-before);
#if EXPECT_STALE
 assert(result==1 && out[510]==0x55 && out[511]==0xaa);
 before=calls; assert(cache->read(cache,0,out,1)==1 && calls==before);
 puts("PASS: historical cache falsely succeeds and suppresses retry after failed refill");
#else
 assert(result==-5 && out[0]==0x7b && out[510]==0x7b);
 before=calls; assert(cache->read(cache,0,out,1)==-5 && calls==before+1);
 for(int short_read=0;short_read<8;short_read++) {
  fault_result=short_read; before=calls;
  assert(cache->read(cache,0,out,1)==-EIO && calls==before+1 && out[0]==0x7b);
 }
 /* Partial failure must invalidate the previous tag as well as the new one. */
 struct bd_cache *c=cache->priv;
 for(int i=0;i<BLOCK_COUNT;i++) c->weight[i]=10000;
 int victim=0;
 while(victim<BLOCK_COUNT && c->sector[victim]==UINT64_MAX) victim++;
 assert(victim<BLOCK_COUNT);
 c->weight[victim]=-100; u64 old_sector=c->sector[victim];
 fault_result=-5;
 assert(cache->read(cache,1000,out,1)==-5);
 fault=0; before=calls;
 assert(cache->read(cache,old_sector,out,1)==1 && calls==before+1 && out[0]!=0xee);
 /* A recovered device is retried; a successful refill is then reusable. */
 before=calls; assert(cache->read(cache,0,out,1)==1 && calls==before+1 && out[510]==0);
 before=calls; assert(cache->read(cache,0,out,1)==1 && calls==before);
 /* Existing cache write invalidation and direct reads still work. */
 assert(cache->write(cache,0,out,1)==1 && writes==1);
 before=calls; assert(cache->read(cache,0,out,1)==1 && calls==before+1);
 assert(cache->read(cache,4089,out,7)==7 && last_count==7);
 assert(cache->read(cache,4095,out,1)==1 && last_count==1);
 assert(cache->read(cache,100,out,8)==8 && last_count==8);
 before=calls;
 assert(cache->read(cache,4096,out,1)==-EIO);
 assert(cache->read(cache,4095,out,2)==-EIO);
 assert(cache->read(cache,UINT64_MAX,out,1)==-EIO);
 assert(cache->read(cache,UINT64_MAX,out,0)==0 && calls==before);
 bd_cache_destroy(cache); assert(allocations==0);
 /* Wider sectors bypass the fixed-size read-ahead cache. */
 bd.sectorSize=4096; cache=bd_cache_create(&bd);
 assert(cache->read(cache,8,out,1)==1 && last_count==1);
 bd_cache_destroy(cache); assert(allocations==0);
 bd.sectorSize=512;
 fail_alloc=1; assert(bd_cache_create(&bd)==NULL && allocations==0);
 fail_alloc=2; assert(bd_cache_create(&bd)==NULL && allocations==0);
 puts("PASS: failed/short refill, retry, eviction, cache hits, write invalidation, capacity, end-of-device, sector size and allocation failure");
 bd.read=probe_read;
 master_boot_record *mbr=(void*)sectors[0];
 mbr->boot_signature=MBR_BOOT_SIGNATURE;
 mbr->primary_partitions[0].partition_type=0x0c;
 mbr->primary_partitions[0].first_lba=8;
 mbr->primary_partitions[0].sector_count=64;
 for(int r=-1;r<=0;r++) {
  part_init(); mounted=0; probe_result=r;
  assert(part_connect_mbr(&bd)<0 && mounted==0 && allocations==0);
 }
 part_init(); probe_result=1; mounted=0;
 assert(part_connect_mbr(&bd)==0 && mounted==1 && allocations==0);
 assert(g_part_bd[0].priv==&g_part[0] && g_part[0].bd==&bd);
 assert(g_part_bd[0].read==part_read && g_part_bd[0].write==part_write);
 assert(g_part_bd[0].sectorOffset==8 && g_part_bd[0].sectorCount==64);
#if HAS_PATH
 assert(g_part_bd[0].path==bd.path);
#endif
 gpt_partition_table_header *gpt=(void*)sectors[1];
 memcpy(gpt->signature,EFI_PARTITION_SIGNATURE,8);
 gpt->first_lba=8; gpt->last_lba=4095; gpt->partition_table_lba=2; gpt->partition_count=4;
 gpt_partition_table_entry *entry=(void*)sectors[2];
 memcpy(entry->partition_type_guid,MS_BASIC_DATA_PARTITION_GUID,16);
 entry->first_lba=8; entry->last_lba=71;
 for(int r=-1;r<=0;r++) {
  part_init(); mounted=0; probe_result=r;
  assert(part_connect_gpt(&bd)<0 && mounted==0 && allocations==0);
 }
 part_init(); probe_result=1; mounted=0;
 assert(part_connect_gpt(&bd)==0 && mounted==1 && allocations==0);
 assert(g_part_bd[0].priv==&g_part[0] && g_part_bd[0].read==part_read);
 assert(g_part_bd[0].sectorOffset==8);
#if HAS_PATH
 assert(g_part_bd[0].path==bd.path);
#endif
 puts("PASS: MBR/GPT reject failed/short reads, preserve metadata and use partition callbacks");
#endif
#if EXPECT_STALE
 assert(writes==0);
 bd_cache_destroy(cache); assert(allocations==0);
#endif
 return 0;
}
'''
# A failure may leave the buffer unchanged or may partially overwrite it.
prefix = prefix.replace('if(fault) { memset(buf,0xee,512);', 'if(fault) { if(fault==1) memset(buf,0xee,512);')
with tempfile.TemporaryDirectory(prefix='bdm-cache-test-') as temp:
    c = Path(temp) / 'test.c'
    exe = Path(temp) / 'test'
    c.write_text(prefix + source + tests)
    layouts = (1,) if args else (0, 1)
    for has_path in layouts:
        subprocess.run([
            'gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-Wno-unused-function',
            f'-DHAS_PATH={has_path}', f"-DEXPECT_STALE={int('--expect-stale' in sys.argv)}",
            str(c), '-o', str(exe),
        ], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)
