"""Regression test for APA cache transaction atomicity, journal preservation, and eviction safety.

Verifies that staging, commit, destination write, and barrier failures safely
abort partial writes, preserve the on-disk recovery journal, retain dirty
cache state, and prevent dirty buffers on the free list from being clobbered.
No device or disk image is opened. Only temporary C source/executable files
are created. Run from any directory with Python and GCC available.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source_dir = root / 'modules/hdd/apa/src'


def source(name):
    return '\n'.join(line for line in
                     (source_dir / name).read_text(encoding='utf-8').splitlines()
                     if not line.startswith('#include'))


prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32; typedef int32_t s32; typedef uint16_t u16;
#define APA_PRINTF(...) ((void)0)
#define APA_DRV_NAME "hdd"
#define APA_CACHE_FLAG_DIRTY 1
#define APA_IO_MODE_READ 0
#define APA_IO_MODE_WRITE 1
#define BLKIO_DIR_READ 0
#define BLKIO_DIR_WRITE 1
#define APA_SECTOR_SECTOR_ERROR 6
#define APA_SECTOR_APAL 8
#define APA_SECTOR_APAL_HEADERS 10
#define APAL_MAGIC 0x4150414c
typedef struct { u32 checksum; unsigned char bytes[1020]; } apa_header_t;
typedef struct sapa_cache {
 struct sapa_cache *next,*tail; u16 flags,nused; s32 device; u32 sector;
 union { apa_header_t *header; u32 *error_lba; };
} apa_cache_t;
typedef struct { u32 magic; s32 num; u32 sectors[126]; } apa_journal_t;
static apa_journal_t saved;
static apa_header_t staged[3], destination[2];
static int scenario, stage_calls, log_calls, header_calls, flush_calls;
static int journal_count_at_header;
static void *apaAllocMem(int size) { return calloc(1,(size_t)size); }
static void apaFreeMem(void *p) { free(p); }
static u32 journalCheckSum(apa_header_t *p) { (void)p; return 0; }
void apaCacheLink(apa_cache_t *,apa_cache_t *);
void apaCacheFree(apa_cache_t *);
apa_cache_t *apaCacheAlloc(void);
int apaJournalWrite(apa_cache_t *);
int apaJournalFlush(s32);
int apaJournalReset(s32);
void apaJournalAbort(void);
int apaWriteHeader(s32,apa_header_t *,u32);
static int apaReadHeader(s32 d,apa_header_t *h,u32 l) {
 (void)d;(void)h;(void)l; assert(!"probe unexpectedly read a header"); return -EIO;
}
static void apaSaveError(s32 d,void *h,u32 l,u32 e) {
 (void)d;(void)h;(void)l;(void)e; assert(!"unexpected error-record write");
}
static int blkIoDmaTransfer(int device,void *buffer,u32 sector,u32 count,int dir) {
 assert(device==0 && dir==BLKIO_DIR_WRITE);
 if(sector==APA_SECTOR_APAL) {
  assert(count==1); log_calls++;
  if(scenario==2 && log_calls==1) return -1;
  saved=*(apa_journal_t*)buffer;
 } else if(sector>=10 && sector<=14) {
  assert(count==2 && !(sector&1)); stage_calls++;
  if(scenario==1 && stage_calls==1) return -1;
  staged[(sector-10)/2]=*(apa_header_t*)buffer;
 } else {
  assert(count==2 && (sector==0x40000 || sector==0x80000)); header_calls++;
  if(header_calls==1) journal_count_at_header=saved.num;
  if(scenario==3 && header_calls==1) return -1;
  destination[sector==0x80000]=*(apa_header_t*)buffer;
 }
 return 0;
}
static int blkIoFlushCache(int device) {
 assert(device==0); flush_calls++;
 if(scenario==4 && flush_calls==1) return -1;
 if(scenario==5 && flush_calls==3) return -1;
 return 0;
}
'''

tests = r'''
int main(void) {
 for(scenario=0;scenario<=5;scenario++) {
  memset(&saved,0,sizeof(saved)); saved.magic=APAL_MAGIC;
  memset(staged,0,sizeof(staged)); memset(destination,0,sizeof(destination));
  journalBuf=saved;
  stage_calls=log_calls=header_calls=flush_calls=0; journal_count_at_header=-1;
  assert(apaCacheInit(3)==0);
  int err; apa_cache_t *entries[2];
  for(int i=0;i<2;i++) {
   entries[i]=apaCacheGetHeader(0,i?0x80000:0x40000,APA_IO_MODE_WRITE,&err);
   assert(entries[i] && err==0);
   memset(entries[i]->header,0x5a+i,sizeof(apa_header_t));
   entries[i]->flags|=APA_CACHE_FLAG_DIRTY;
  }
  int ret=apaCacheFlushAllDirty(0);
  int dirty=(entries[0]->flags|entries[1]->flags)&APA_CACHE_FLAG_DIRTY;
  int changed0=destination[0].bytes[0]!=0;
  int changed1=destination[1].bytes[0]!=0;
  printf("scenario=%d ret=%d header_attempts=%d journal_count_at_first_header=%d "
         "dirty=%d remaining_journal=%ld changed=%d,%d\n",
         scenario,ret,header_calls,journal_count_at_header,dirty,(long)saved.num,
         changed0,changed1);
  if(scenario==0) {
   /* Scenario 0: Normal success */
   assert(ret==0 && header_calls==2 && dirty==0 && saved.num==0);
   assert(changed0 && changed1);
   assert(journal_count_at_header==2);
  } else if(scenario==1) {
   /* Scenario 1: First staging write fails -> no destination writes, dirty kept, journal not committed */
   assert(ret!=0 && header_calls==0 && dirty!=0 && saved.num==0);
   assert(!changed0 && !changed1);
  } else if(scenario==2) {
   /* Scenario 2: Journal commit write fails -> no destination writes, dirty kept, journal not committed */
   assert(ret!=0 && header_calls==0 && dirty!=0 && saved.num==0);
   assert(!changed0 && !changed1);
  } else if(scenario==3) {
   /* Scenario 3: First destination write fails -> subsequent destination writes aborted,
      dirty kept, committed journal on disk PRESERVED */
   assert(ret!=0 && header_calls==1 && dirty!=0 && saved.num==2);
   assert(!changed0 && !changed1);
   assert(journal_count_at_header==2);
  } else if(scenario==4) {
   /* Scenario 4: Commit flush barrier fails -> no destination writes, dirty kept */
   assert(ret!=0 && header_calls==0 && dirty!=0);
   assert(!changed0 && !changed1);
  } else if(scenario==5) {
   /* Scenario 5: Post-destination barrier fails -> headers written, dirty kept, journal PRESERVED */
   assert(ret!=0 && header_calls==2 && dirty!=0 && saved.num==2);
   assert(changed0 && changed1);
   assert(journal_count_at_header==2);
  }
  apaCacheFree(entries[0]); apaCacheFree(entries[1]); apaCacheDeinit();
 }

 /* Test: Dirty buffer eviction safety */
 {
  assert(apaCacheInit(3)==0);
  int err;
  apa_cache_t *e1=apaCacheGetHeader(0,0x10000,APA_IO_MODE_WRITE,&err);
  apa_cache_t *e2=apaCacheGetHeader(0,0x20000,APA_IO_MODE_WRITE,&err);
  assert(e1 && e2 && err==0);
  e1->flags|=APA_CACHE_FLAG_DIRTY;
  e2->flags|=APA_CACHE_FLAG_DIRTY;
  apaCacheFree(e1); // e1 freed to free list, but remains DIRTY
  /* Allocation of a new sector must skip dirty e1 and allocate clean e3 */
  apa_cache_t *e3=apaCacheGetHeader(0,0x30000,APA_IO_MODE_WRITE,&err);
  assert(e3 && err==0 && e3!=e1);
  e3->flags|=APA_CACHE_FLAG_DIRTY;
  apaCacheFree(e3);
  apaCacheFree(e2);
  /* Now all 3 buffers in cache are dirty with nused==0.
     Attempting to allocate a 4th sector must fail with -ENOMEM rather than clobbering dirty data */
  apa_cache_t *e4=apaCacheGetHeader(0,0x40000,APA_IO_MODE_WRITE,&err);
  assert(e4==NULL && err==-ENOMEM);
  /* apaCacheAlloc must also return NULL when all free buffers are dirty */
  apa_cache_t *alloc_fail=apaCacheAlloc();
  assert(alloc_fail==NULL);
  apaCacheDeinit();
 }

 puts("PASS: transaction atomicity, journal preservation on destination/barrier failure, "
      "and dirty-buffer eviction protection");
 return 0;
}
'''

apa = source('apa.c')
write_header = apa[apa.index('int apaWriteHeader('):apa.index('int apaGetFormat(')]
with tempfile.TemporaryDirectory(prefix='apa-transaction-') as temp:
    c, exe = Path(temp) / 'probe.c', Path(temp) / 'probe'
    c.write_text(prefix + source('cache.c') + source('journal.c') +
                 write_header + tests, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
