"""Exercise production BDM startup cleanup with injected resource failures."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (root / path).read_text()
    start = source.index(signature + '\n{')
    return source[start:source.index('\n}', start) + 2]


production = function('modules/bdm/src/bdm.c', 'int bdm_init()')
production += '\n' + function('modules/bdm/src/main.c', 'int _start(int argc, char *argv[])').replace('int _start(', 'int bdm_start(')
prefix = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#define M_DEBUG(...) ((void)0)
#define M_PRINTF(...) ((void)0)
#define MAJOR_VER 1
#define MINOR_VER 1
#define MODULE_NO_RESIDENT_END 1
#define MODULE_RESIDENT_END 0
#define TH_C 1
#define MAX_CONNECTIONS 20
struct { void *bd, *cbd, *fs; } g_mount[MAX_CONNECTIONS];
static void *g_fs[MAX_CONNECTIONS];
static int bdm_event=-1, bdm_thread_id=-1;
typedef struct { int attr,option,bits; } iop_event_t;
typedef struct { int attr,option,priority,stacksize; void (*thread)(void*); } iop_thread_t;
struct irx_export_table { int dummy; } _exp_bdm;
static int fail, exported, releases, events, threads, partition_init;
static void bdm_thread(void *p) { (void)p; }
static int RegisterLibraryEntries(struct irx_export_table *p) {
 (void)p; if(exported) return -1; exported=1; return 0;
}
static int ReleaseLibraryEntries(struct irx_export_table *p) {
 (void)p; assert(exported); exported=0; releases++; return 0;
}
static int CreateEventFlag(iop_event_t *p) { (void)p; if(fail==1) return -1; events++; return 10; }
static int DeleteEventFlag(int id) { assert(id==10 && events==1); events--; return 0; }
static int CreateThread(iop_thread_t *p) {
 assert(p->priority==0x30); if(fail==2) return -2; threads++; return 20;
}
static int StartThread(int id,void *p) { (void)p; assert(id==20); return fail==3 ? -3 : 0; }
static int DeleteThread(int id) { assert(id==20 && threads==1); threads--; return 0; }
static void part_init(void) { partition_init++; }
'''
tests = r'''
int main(void) {
 for(fail=1;fail<=3;fail++) {
  int before=releases;
  assert(bdm_start(0,NULL)==MODULE_NO_RESIDENT_END);
  assert(!exported && !events && !threads && !partition_init && releases==before+1);
 }
 fail=0;
 assert(bdm_start(0,NULL)==MODULE_RESIDENT_END);
 assert(exported==1 && events==1 && threads==1 && partition_init==1);
 int before=releases;
 assert(bdm_start(0,NULL)==MODULE_NO_RESIDENT_END);
 assert(exported==1 && releases==before && events==1 && threads==1 && partition_init==1);
 puts("PASS: event/thread/start failure cleanup, successful retry, and duplicate registration isolation");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='bdm-startup-') as temp:
    c = Path(temp) / 'test.c'
    exe = Path(temp) / 'test'
    c.write_text(prefix + production + tests)
    subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
