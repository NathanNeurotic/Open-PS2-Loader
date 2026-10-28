"""Compile native tab navigation and async config publication with lock-aware host stubs."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/menusys.c').read_text(encoding='utf-8')


def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


functions = '\n'.join(function(signature) for signature in (
    'static void menuFolderResetLeaving(', 'static void menuNextH()',
    'static void menuPrevH()', 'static void _menuLoadConfigAsync()',
))
program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { int serial; } config_set_t;
typedef struct item_list item_list_t;
struct item_list { int mode; config_set_t *(*itemGetConfig)(item_list_t *,int); int (*itemTextId)(item_list_t *); };
typedef struct { struct { int id; } item; } Row;
typedef struct { int visible; item_list_t *userdata; Row *current; char *text; int text_id; } Item;
typedef struct menu_list { Item *item; struct menu_list *next,*prev; } menu_list_t;
static menu_list_t *selected_item, *replaceOnLock;
static int menuItemShown(const Item *item) { return item->visible; }
static int itemConfigId=-1, menuSemaId=1, depth, waits, signals, sounds, resets, queues;
static unsigned int itemConfigGeneration;
static item_list_t *itemConfigList;
static config_set_t *itemConfig;
static unsigned char itemConfigWorkerPending;
static int levels[3], reads, frees, switchDuringRead, refuseQueue;
static menu_list_t *targetOnUnlock;
#define IO_MENU_UPDATE_DEFFERED 2
#define SFX_CURSOR 1
static void WaitSema(int id) {
 assert(id==menuSemaId && depth==0); depth=1;waits++;
 if(replaceOnLock) {selected_item=replaceOnLock;replaceOnLock=NULL;}
}
static void SignalSema(int id) {
 assert(id==menuSemaId && depth==1);
 if(targetOnUnlock) {
  assert(selected_item==targetOnUnlock && itemConfigId==-1 && itemConfigGeneration>0);
  targetOnUnlock=NULL;
 }
 depth=0;signals++;
}
static int folderModeSupported(int mode) {assert(depth==1);return mode<3;}
static int folderDepth(int mode) {assert(depth==1);return levels[mode];}
static void folderReset(int mode) {assert(depth==1);levels[mode]=0;resets++;}
static int title(item_list_t *list) {assert(depth==1);return 100+list->mode;}
static int ioPutRequest(int type,void *data) {
 assert(depth==1 && type==IO_MENU_UPDATE_DEFFERED && data);queues++;
 return refuseQueue?-1:0;
}
static void sfxPlay(int id) {assert(depth==0 && id==SFX_CURSOR);sounds++;}
static void configFree(config_set_t *cfg) {assert(!depth && cfg);frees++;free(cfg);}
@FUNCTIONS@
static config_set_t *readConfig(item_list_t *list,int id) {
 assert(!depth && list && id==7);reads++;
 if(switchDuringRead && reads==1) {
  menuNextH();
  if(switchDuringRead==2)menuPrevH();
  // Model the next settled request while the original worker still owns its latch.
  WaitSema(menuSemaId);
  itemConfigId=selected_item->item->current->item.id;
  itemConfigList=selected_item->item->userdata;
  itemConfigGeneration++;
  SignalSema(menuSemaId);
 }
 config_set_t *cfg=malloc(sizeof(*cfg));assert(cfg);cfg->serial=reads;return cfg;
}
int main(void) {
 item_list_t sources[3]={{0,readConfig,title},{1,readConfig,title},{2,readConfig,title}};
 Row row={{7}};
 Item items[3]={{1,&sources[0],&row,"folder",0},{0,&sources[1],&row,NULL,0},{1,&sources[2],&row,"folder",0}};
 menu_list_t pages[3]={{&items[0],&pages[1],NULL},{&items[1],&pages[2],&pages[0]},{&items[2],NULL,&pages[1]}};
 selected_item=&pages[0];levels[0]=2;itemConfigId=7;itemConfigGeneration=9;
 targetOnUnlock=&pages[2];menuNextH();
 assert(selected_item==&pages[2] && itemConfigGeneration==10 && itemConfigId==-1);
 assert(levels[0]==0 && resets==1 && queues==1 && sounds==1);
 assert(items[0].text==NULL && items[0].text_id==100);
 int oldWaits=waits;menuNextH();
 assert(waits==oldWaits+1 && itemConfigGeneration==10 && sounds==1 && resets==1);
 levels[2]=1;refuseQueue=1;targetOnUnlock=&pages[0];menuPrevH();
 assert(selected_item==&pages[0] && itemConfigGeneration==11 && resets==2 && queues==2 && sounds==2);
 menuPrevH();assert(itemConfigGeneration==11 && sounds==2);
 // Only hidden neighbors remain: balance the lock, with no invalidation or sound.
 pages[1].next=NULL;menuNextH();assert(selected_item==&pages[0] && itemConfigGeneration==11);
 pages[1].next=&pages[2];
 // The selected page may change while acquiring the semaphore; traverse the locked selection.
 replaceOnLock=&pages[2];menuPrevH();assert(selected_item==&pages[0] && itemConfigGeneration==12);
 selected_item=NULL;menuNextH();menuPrevH();assert(!depth && waits==signals);
 // Both a tab switch and A -> B -> A must discard the old read and publish only the new generation.
 for(int scenario=1;scenario<=2;scenario++) {
  selected_item=&pages[0];itemConfigId=7;itemConfigList=&sources[0];
  itemConfig=NULL;itemConfigWorkerPending=1;reads=frees=0;switchDuringRead=scenario;
  _menuLoadConfigAsync();
  assert(reads==2 && frees==1 && itemConfig && itemConfig->serial==2);
  assert(itemConfigList==selected_item->item->userdata && itemConfigId==7);
  assert(!itemConfigWorkerPending && !depth && waits==signals);
  configFree(itemConfig);itemConfig=NULL;
 }
 puts("menu selection: locked traversal/invalidation, hidden tabs, folder reset, no-op/null moves and stale async reads passed");
}
'''.replace('@FUNCTIONS@', functions)

with tempfile.TemporaryDirectory() as directory:
    src = Path(directory) / 'selection.c'
    exe = Path(directory) / ('selection.exe' if os.name == 'nt' else 'selection')
    src.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
