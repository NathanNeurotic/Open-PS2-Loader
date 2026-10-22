"""Exercise production UDPFS language discovery across late mounts and failed listings."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/udpfssupport.c').read_text(encoding='utf-8')


def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


discover = function('static void udpfsDiscoverLanguages(')
waiter = function('static void udpfsSetWaitingForServer(')
needs = function('static int udpfsNeedsUpdate(')
assert needs.index('udpfsDiscoverLanguages();') < needs.index('libViewConsumeDirty(')
update = function('static int udpfsUpdateGameList(')
assert update.index('sbCreateFolders(') < update.index('udpfsDiscoverLanguages();')
assert 'udpfsLanguagesScanned = 0;' in function('void udpfsInit(')
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
typedef struct { int root; } DIR;
struct dirent { char d_name[32]; };
static DIR root_dir={1}, child_dir={0};
static struct dirent entry;
static const char *udpfsPrefix="udpfs:/";
static struct {int mode, updateDelay;} udpfsGameList={7,0};
static int udpfsLanguagesScanned, udpfsThemesScanned=1, udpfsWaitingForServer;
static int udpfsIomanModLoaded=1, online=1, root_ready=1, child_ready=1;
static int position, fault_at=-1, opens, adds;
static const char *names[8];
static char paths[8][128];
#define MENU_UPD_DELAY_GENREFRESH 2
#define UDPFS_MODE_UPDATE_DELAY 300
static int udpfsServerAnswers(void) {return online;}
static DIR *opendir(const char *path) {
    opens++;
    if(!strcmp(path,udpfsPrefix)) {position=0;return root_ready?&root_dir:NULL;}
    return child_ready?&child_dir:NULL;
}
static struct dirent *readdir(DIR *dir) {
    assert(dir==&root_dir);
    if(position==fault_at) {errno=EIO;return NULL;}
    if(!names[position]) return NULL;
    strcpy(entry.d_name,names[position++]);return &entry;
}
static int closedir(DIR *dir) {(void)dir;return 0;}
static int lngAddLanguages(char *path,const char *separator,int mode) {
    assert(!strcmp(separator,"/") && mode==7);
    strcpy(paths[adds++],path);return 0; // an empty readable LNG is a completed attempt too
}
@WAITER@
@DISCOVER@
static void reset(void) {
    udpfsLanguagesScanned=udpfsWaitingForServer=0;udpfsThemesScanned=1;
    udpfsIomanModLoaded=online=root_ready=child_ready=1;
    adds=opens=0;fault_at=-1;memset(names,0,sizeof(names));
    udpfsSetWaitingForServer(0);
    assert(udpfsGameList.updateDelay==MENU_UPD_DELAY_GENREFRESH);
}
int main(void) {
    reset();names[0]="CD";names[1]="lng";names[2]="LNG";names[3]="DVD";
    udpfsDiscoverLanguages();
    assert(udpfsLanguagesScanned && adds==2);
    assert(!strcmp(paths[0],"udpfs:/lng") && !strcmp(paths[1],"udpfs:/LNG"));
    assert(udpfsGameList.updateDelay==UDPFS_MODE_UPDATE_DELAY);
    int saved=opens;udpfsDiscoverLanguages();assert(opens==saved && adds==2);
    reset();names[0]="LnG";online=0;udpfsDiscoverLanguages();assert(!opens && !adds);
    online=1;root_ready=0;udpfsDiscoverLanguages();assert(!udpfsLanguagesScanned && !adds);
    root_ready=1;child_ready=0;udpfsDiscoverLanguages();assert(!udpfsLanguagesScanned && !adds);
    child_ready=1;udpfsDiscoverLanguages();assert(udpfsLanguagesScanned && adds==1);
    reset();names[0]="LNG";fault_at=1;udpfsDiscoverLanguages();
    assert(!udpfsLanguagesScanned && adds==1); // never publish partial root EOF as complete
    fault_at=-1;udpfsDiscoverLanguages();assert(udpfsLanguagesScanned && adds==2);
    reset();names[0]="CD";udpfsDiscoverLanguages();assert(!udpfsLanguagesScanned && !adds);
    names[1]="LNG";udpfsThemesScanned=0;udpfsDiscoverLanguages();
    assert(udpfsLanguagesScanned && udpfsGameList.updateDelay==MENU_UPD_DELAY_GENREFRESH);
    udpfsThemesScanned=1;udpfsSetWaitingForServer(1);
    assert(udpfsGameList.updateDelay==MENU_UPD_DELAY_GENREFRESH);
    reset();names[0]="LNG";udpfsIomanModLoaded=0;udpfsDiscoverLanguages();assert(!opens);
    puts("PASS: UDPFS LNG discovery, mixed case, late server, failed/partial directories and retry cadence");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    cfile = path / 'languages.c'
    binary = path / ('languages.exe' if sys.platform == 'win32' else 'languages')
    cfile.write_text(harness.replace('@DISCOVER@', discover).replace('@WAITER@', waiter))
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
