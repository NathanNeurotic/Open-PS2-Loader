"""Check production APA recovery error handling with an in-memory I/O stub.

No device is opened. Failed recovery must preserve the saved journal for retry.
An optional historical journal.c path checks the regression against older code.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (Path(sys.argv[1]) if len(sys.argv) > 1 else
          root / 'modules/hdd/apa/src/journal.c').read_text(encoding='utf-8')
source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32; typedef int32_t s32;
#define APA_PRINTF(...) ((void)0)
#define APA_DRV_NAME "hdd"
#define APAL_MAGIC 0x4150414c
#define APA_SECTOR_APAL 8
#define APA_SECTOR_APAL_HEADERS 10
#define BLKIO_DIR_READ 0
#define BLKIO_DIR_WRITE 1
typedef struct { u32 magic; s32 num; u32 sectors[126]; } apa_journal_t;
typedef struct { u32 checksum; unsigned char bytes[1020]; } apa_header_t;
typedef struct { int device; u32 sector; apa_header_t *header; } apa_cache_t;
static apa_journal_t saved;
static apa_header_t staged[2], destination[2], scratch;
static apa_cache_t entry={.header=&scratch};
static int io_calls,fail_io,flush_calls,fail_flush,alloc_fail,in_use;
static int journal_writes,metadata_writes;
static char trace[64]; static int trace_len;
static void record(char c) { assert(trace_len<63); trace[trace_len++]=c; trace[trace_len]=0; }
static int blkIoDmaTransfer(int device,void *buffer,u32 sector,u32 count,int direction) {
 assert(device==0); io_calls++;
 record(direction==BLKIO_DIR_READ?'R':'W');
 if(fail_io==io_calls) return -1;
 if(sector==APA_SECTOR_APAL) {
  assert(count==1);
  if(direction==BLKIO_DIR_READ) memcpy(buffer,&saved,sizeof(saved));
  else { saved=*(apa_journal_t*)buffer; journal_writes++; }
 } else if(sector==260 && direction==BLKIO_DIR_WRITE) {
  assert(count==2); /* Last of the 126 staged-header slots. */
 } else if(sector==10 || sector==12) {
  assert(count==2);
  if(direction==BLKIO_DIR_READ) memcpy(buffer,&staged[(sector-10)/2],sizeof(scratch));
  else memcpy(&staged[(sector-10)/2],buffer,sizeof(scratch));
 } else {
  assert(count==2 && (sector==0x40000 || sector==0x80000));
  memcpy(&destination[sector==0x80000],buffer,sizeof(scratch)); metadata_writes++;
 }
 return 0;
}
static int blkIoFlushCache(int device) {
 assert(device==0); flush_calls++; record('F'); return fail_flush==flush_calls?-1:0;
}
static apa_cache_t *apaCacheAlloc(void) {
 if(alloc_fail) return NULL;
 assert(!in_use); in_use=1; return &entry;
}
static void apaCacheFree(apa_cache_t *p) { assert(p==&entry && in_use); in_use=0; }
static u32 journalCheckSum(apa_header_t *p) { (void)p; return 0; }
'''
tests = r'''
static void setup(void) {
 memset(&saved,0,sizeof(saved)); saved.magic=APAL_MAGIC; saved.num=2;
 saved.sectors[0]=0x40000; saved.sectors[1]=0x80000;
 memset(staged,0x5a,sizeof(staged)); memset(destination,0,sizeof(destination));
 io_calls=flush_calls=journal_writes=metadata_writes=trace_len=0;
 fail_io=fail_flush=alloc_fail=in_use=0; trace[0]=0;
}
int main(void) {
 /* The OSD/ATAD startup path skips restore/reset after successful unlock.
    Its first transaction must still publish a recognizable journal. */
 setup();
 entry.device=0; entry.sector=0x40000; scratch=staged[0];
 assert(apaJournalWrite(&entry)==0);
 entry.sector=0x80000; scratch=staged[1];
 assert(apaJournalWrite(&entry)==0 && apaJournalFlush(0)==0);
 assert(saved.magic==APAL_MAGIC && saved.num==2);
 assert(saved.sectors[0]==0x40000 && saved.sectors[1]==0x80000);
 assert(strcmp(trace,"WWFWF")==0);
 puts("PASS: first transaction has a valid journal without prior restore/reset");
 /* Fail each recovery I/O before the clear operation, including after one
    metadata entry has already been replayed. The saved record must survive. */
 for(int fail=1;fail<=5;fail++) {
  setup(); apa_journal_t before=saved; fail_io=fail;
  assert(apaJournalRestore(0)==-EIO);
  assert(memcmp(&saved,&before,sizeof(saved))==0 && journal_writes==0 && !in_use);
  fail_io=0; io_calls=flush_calls=trace_len=0;
  assert(apaJournalRestore(0)==0 && saved.magic==APAL_MAGIC && saved.num==0);
  assert(memcmp(destination,staged,sizeof(staged))==0 && !in_use);
 }
 setup(); assert(apaJournalRestore(0)==0);
 assert(strcmp(trace,"RRWRWFWF")==0);
 assert(metadata_writes==2 && journal_writes==1 && saved.num==0);
 assert(memcmp(destination,staged,sizeof(staged))==0);
 puts("PASS: failed journal/header read or replay write preserves recovery data; retry and flush ordering pass");
 setup(); saved.num=0;
 assert(apaJournalRestore(0)==0 && io_calls==1 && journal_writes==0 && flush_calls==0);
 for(int test=0;test<3;test++) {
  setup();
  if(test==0) saved.magic=0;
  if(test==1) saved.num=-1;
  if(test==2) saved.num=127;
  apa_journal_t before=saved;
  assert(apaJournalRestore(0)==-EIO && io_calls==1 && journal_writes==0);
  assert(memcmp(&saved,&before,sizeof(saved))==0 && !in_use);
 }
 setup(); alloc_fail=1;
 assert(apaJournalRestore(0)==-ENOMEM && journal_writes==0 && metadata_writes==0);
 setup(); fail_flush=1; apa_journal_t before=saved;
 assert(apaJournalRestore(0)==-EIO && journal_writes==0);
 assert(memcmp(&saved,&before,sizeof(saved))==0 && !in_use);
 setup(); fail_io=6;
 assert(apaJournalRestore(0)==-EIO && journal_writes==0 && !in_use);
 setup(); fail_flush=2;
 assert(apaJournalRestore(0)==-EIO && journal_writes==1 && !in_use);
 puts("PASS: empty/invalid journals, allocation failure and reset/flush failures");
 /* Invalid/full append state must not modify the header or issue I/O. */
 for(int test=0;test<3;test++) {
  setup(); journalBuf.magic=APAL_MAGIC;
  journalBuf.num=test==0?-1:test==1?126:127;
  apa_header_t before=scratch;
  assert(apaJournalWrite(&entry)==-EIO && io_calls==0);
  assert(memcmp(&scratch,&before,sizeof(scratch))==0);
 }
 setup(); journalBuf.num=125;
 assert(apaJournalWrite(&entry)==0 && io_calls==1 && journalBuf.num==126);
 assert(journalBuf.sectors[125]==entry.sector);
 assert(apaJournalWrite(&entry)==-EIO && io_calls==1);
 puts("PASS: journal append capacity rejects invalid/full state before I/O");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='apa-recovery-') as temp:
    c, exe = Path(temp) / 'test.c', Path(temp) / 'test'
    c.write_text(prefix + source + tests)
    subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
