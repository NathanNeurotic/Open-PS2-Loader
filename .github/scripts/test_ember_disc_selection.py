"""Execute the production manifest parser, picker and all five Ember launch legs.

Only the final argument changes. Missing manifests preserve folder launches; cancellation
must precede settings writes/teardown and restore APA mounts. No console behavior is modeled.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (ROOT / path).read_text(encoding='utf-8')
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


header = (ROOT / 'include/cuesupport.h').read_text()
constants = '\n'.join(re.findall(r'^#define CUE_(?:NAME_MAX|NAME_LAUNCH_MAX|MAX_DISCS)\s+\d+', header, re.M))
disc_type = re.search(r'typedef struct\s*\{\s*int count;.*?\} cue_disc_list_t;', header, re.S).group()
dia = (ROOT / 'include/dia.h').read_text()
enum = dia[dia.index('typedef enum {'):dia.index('} UIItemType;') + len('} UIItemType;')]
start = dia.index('struct UIItem\n')
ui_type = dia[start:dia.index('\n};', start) + 3]
functions = '\n\n'.join(function('src/cuesupport.c', signature) for signature in (
    'static char cueSep(', 'const char *cueEmberFolder(', 'void cueBuildGamesDir(',
    'int cueNameLaunchable(', 'int cueBuildDiscArgument(', 'int cueBuildDiscPath(',
    'static int cueAppendDiscLine(', 'static int cueConfirmDiscListAbsent(', 'int cueReadDiscList(',
))
gui = '\n\n'.join(function('src/gui.c', signature) for signature in (
    'static int guiShowEmberDiscList(', 'int guiPrepareEmberLaunch(',
))
legs = '\n\n'.join(function('src/' + name, signature) for name, signature in (
    ('bdmsupport.c', 'static void bdmLaunchCue('),
    ('mmcesupport.c', 'static void mmceLaunchCue('),
    ('ethsupport.c', 'static void ethLaunchCue('),
    ('udpfssupport.c', 'static void udpfsLaunchCue('),
    ('hddsupport.c', 'static void hddDoLaunchEmber('),
))
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <dirent.h>
#define LOG(...) ((void)0)
#define EMBER_FOLDER_DEFAULT "EMBER"
#define EMBER_GAMES_FOLDER "games"
@CONSTANTS@
@DISC_TYPE@
@UI_TYPES@
enum { _STR_EMBER_SELECT_DISC=1, _STR_EMBER_DISC_ENTRY, _STR_EMBER_DISCS_INVALID,
       _STR_EMBER_DISC_ARGS_TOO_LONG, _STR_ERR_FILE_INVALID, _STR_EMBER_BAD_NAME,
       _STR_PLEASE_WAIT, _STR_EMBER_NOT_FOUND, _STR_EMBER_BIOS_MISSING, _STR_EMBER_NO_DISC };
static const char *_l(int id) { return id == _STR_EMBER_DISC_ENTRY ? "Disc %d: %s" : "message"; }
static char root[1024], sourceName[CUE_NAME_MAX], captured[CUE_NAME_MAX], settingsName[CUE_NAME_MAX];
static int picker, dialogs, errors, settings, deinitializations, restored, blocked;
static int fail_alloc, fail_open, fail_read, read_count, read_error;
static void *tracked_calloc(size_t n,size_t s) {
    if (fail_alloc) { fail_alloc=0;return NULL; } return calloc(n,s);
}
static const char *mapped(const char *path) {
    static char result[2048];
    if (!strncmp(path,"pfs0:/",6) || !strncmp(path,"mass0:/",7) ||
        !strncmp(path,"mmce0:/",7) || !strncmp(path,"smb:\\",5) || !strncmp(path,"udpfs:/",7))
        snprintf(result,sizeof(result),"%s/%s",root,strchr(path,':')+2);
    else snprintf(result,sizeof(result),"%s",path);
    for(char *p=result;*p;p++) if(*p=='\\') *p='/';
    return result;
}
static FILE *mapped_fopen(const char *path,const char *mode) {
    if(fail_open && mode[0]=='r') {errno=EIO;return NULL;}
    read_count=read_error=0;return fopen(mapped(path),mode);
}
static int mapped_open(const char *path,int flags) { return open(mapped(path),flags); }
static DIR *mapped_opendir(const char *path) { return opendir(mapped(path)); }
static int injected_getc(FILE *f) {
    if(fail_read && ++read_count>5) {read_error=1;return EOF;} return fgetc(f);
}
static int injected_ferror(FILE *f) {return read_error || ferror(f);}
#define calloc tracked_calloc
#define fopen mapped_fopen
#define open mapped_open
#define opendir mapped_opendir
#define fgetc injected_getc
#define ferror injected_ferror
@FUNCTIONS@
static void guiMsgBox(const char *s,int n,void *p) {(void)s;(void)n;(void)p;errors++;}
static void guiMsgBoxMissing(const char *s,const char *p) {(void)s;(void)p;errors++;}
static int diaExecuteDialog(struct UIItem *ui,int focus,short menu,int (*update)(int)) {
    (void)menu;(void)update;dialogs++;assert(focus==1);
    int buttons=0;
    for(int i=0;ui[i].type!=UI_TERMINATOR;i++) if(ui[i].type==UI_BUTTON) {
        buttons++;assert(ui[i].id==buttons);assert(strstr(ui[i].label.text,".cue"));
    }
    assert(buttons>=2 && buttons<=CUE_MAX_DISCS);return picker;
}
@GUI@
typedef struct {int unused;} config_set_t;
typedef struct {int bdmDeviceType;} bdm_device_data_t;
typedef struct {void *priv;int mode;} item_list_t;
#define BDM_TYPE_SDC 5
#define MMCE_ART_ABORT_WAIT_TICKS 500
#define HDD_ART_QUIESCE_MS 500
#define APA_IDMAX 32
#define FIO_MT_RDWR 1
#define HDD_PFS_MT_WRITETHROUGH 2
#define UNMOUNT_EXCEPTION 1
#define KEEPIOP_EXCEPTION 2
static char mmcePrefix[1100], ethPrefix[1100], udpfsPrefix[1100], hddPrefix[]="pfs0:/";
static char gPCShareName[]="share";
static void bdmBuildPs1Prefix(char *s,int n,int mode) {(void)mode;snprintf(s,n,"mass0:/");}
static void mmceGetDeviceRoot(char *s,int n) {snprintf(s,n,"mmce0:/");}
static int cueResolveEmber(const char *p,char *s,int n) {(void)p;snprintf(s,n,"mass0:/EMBER/ember.elf");return 1;}
static int cueResolveEmberBios(const char *p,char *s,int n) {(void)p;snprintf(s,n,"bios.bin");return 1;}
static int cueGameHasImage(const char *p,const char *s) {(void)p;(void)s;return 1;}
static void cueApplySettings(const char *p,const char *s,config_set_t *c) {
    (void)p;(void)c;settings++;snprintf(settingsName,sizeof(settingsName),"%s",s);
}
static void cuePrepareRetroGemBarcode(const char *p,const char *s) {(void)p;assert(!strcmp(s,"Game"));}
static int cacheAbortMmceImageLoadsTimed(int n) {(void)n;return 1;}
static int cacheCancelPendingImageLoadsTimed(int n) {(void)n;return 1;}
static void guiWarning(const char *s,int n) {(void)s;(void)n;errors++;}
static void guiRenderTextScreen(const char *s) {(void)s;}
static void ioBlockOps(int n) {blocked=n;}
static void hddRestoreDataHome(void) {restored++;}
static int fileXioUmount(const char *p) {(void)p;return 0;}
static int fileXioMount(const char *p,const char *s,int f) {(void)p;(void)s;(void)f;return 0;}
static void hddShowEmberMissing(int n,const char *p,const char *s) {(void)n;(void)p;(void)s;errors++;}
static void deinit(int flags,int mode) {
    (void)flags;(void)mode;deinitializations++;memset(sourceName,'x',sizeof(sourceName)-1);
    sourceName[sizeof(sourceName)-1]=0;
}
static void sysLaunchEmber(const char *e,const char *a) {(void)e;snprintf(captured,sizeof(captured),"%s",a);}
@LEGS@
#undef fopen
#undef open
#undef opendir
#undef calloc
#undef fgetc
#undef ferror
static void reset(void) {
    strcpy(sourceName,"Game");captured[0]=settingsName[0]=0;
    picker=2;dialogs=errors=settings=deinitializations=restored=blocked=0;
    fail_alloc=fail_open=fail_read=read_error=0;
}
static void manifest(const char *text) {
    char path[1400];snprintf(path,sizeof(path),"%s/EMBER/games/Game/discs.txt",root);
    if(!text) {remove(path);return;}
    FILE *f=fopen(path,"wb");assert(f);assert(fwrite(text,1,strlen(text),f)==strlen(text));fclose(f);
}
static void call_leg(int leg) {
    bdm_device_data_t device={0};item_list_t item={&device,1};config_set_t config={0};
    switch(leg) {
      case 0:bdmLaunchCue(&item,sourceName,&config);break;
      case 1:mmceLaunchCue(&item,sourceName,&config);break;
      case 2:ethLaunchCue(&item,sourceName,&config);break;
      case 3:udpfsLaunchCue(&item,sourceName,&config);break;
      case 4:hddDoLaunchEmber(&item,sourceName,"__.EMBER",&config);break;
    }
}
int main(int argc,char **argv) {
    assert(argc==2);snprintf(root,sizeof(root),"%s",argv[1]);
    snprintf(ethPrefix,sizeof(ethPrefix),"smb:\\");
    snprintf(udpfsPrefix,sizeof(udpfsPrefix),"udpfs:/");
    cue_disc_list_t *list=NULL;char argument[192],path[640],prefix[1100];
    snprintf(prefix,sizeof(prefix),"%s/",root);
    manifest(NULL);assert(cueReadDiscList(prefix,"Game",&list)==0 && !list);
    fail_open=1;assert(cueReadDiscList("mmce0:/","Game",&list)==0 && !list);fail_open=0;
    manifest("\xef\xbb\xbf" "Disc 2.cue\r\n\r\nDisc 1.cue");
    assert(cueReadDiscList(prefix,"Game",&list)==2);
    assert(!strcmp(list->names[0],"Disc 2.cue") && !strcmp(list->names[1],"Disc 1.cue"));free(list);
    const char *invalid[]={"", "\n\r\n", "../disc.cue\n", "mass:/disc.cue\n", "sub/disc.cue\n",
        "sub\\disc.cue\n", "image.bin\n", "Disc\t1.cue\n", "Disc 1.cue\n/escape.cue\n"};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        manifest(invalid[i]);assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);
    }
    char oversized[9000];memset(oversized,'\n',sizeof(oversized)-1);oversized[sizeof(oversized)-1]=0;
    manifest(oversized);assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);
    oversized[0]=0;for(int i=0;i<CUE_MAX_DISCS+1;i++) strcat(oversized,"Disc 1.cue\n");
    manifest(oversized);assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);
    manifest("Disc 1.cue\nDisc 2.cue\n");fail_alloc=1;
    assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);
    fail_open=1;assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);fail_open=0;
    fail_read=1;assert(cueReadDiscList(prefix,"Game",&list)==-1 && !list);fail_read=0;
    assert(cueBuildDiscArgument("Game","Disc 2.cue",argument,sizeof(argument)));
    assert(!strcmp(argument,"Game/Disc 2.cue"));
    assert(!cueBuildDiscArgument("Game","Disc 2.cue",argument,8));
    assert(cueBuildDiscPath("smb:\\","Game","Disc 2.cue",path,sizeof(path)));
    assert(!strcmp(path,"smb:\\EMBER\\games\\Game\\Disc 2.cue"));
    reset();manifest("Disc 1.cue\nMissing.cue\n");
    assert(!guiPrepareEmberLaunch(prefix,"Game","mass:/EMBER/ember.elf",argument,sizeof(argument)));
    assert(errors==1);
    reset();manifest("Disc 1.cue\n");
    assert(guiPrepareEmberLaunch(prefix,"Game","mass:/EMBER/ember.elf",argument,sizeof(argument)));
    assert(!dialogs && !strcmp(argument,"Game/Disc 1.cue"));
    reset();char elf[200];memset(elf,'e',sizeof(elf)-1);elf[sizeof(elf)-1]=0;
    assert(!guiPrepareEmberLaunch(prefix,"Game",elf,argument,sizeof(argument)) && errors==1);
    for(int leg=0;leg<5;leg++) {
        reset();manifest(NULL);call_leg(leg);
        assert(deinitializations==1 && !strcmp(captured,"Game"));
        assert(settings==1 && !strcmp(settingsName,"Game") && !dialogs);
        reset();manifest("Disc 1.cue\nDisc 2.cue\n");call_leg(leg);
        assert(deinitializations==1 && !strcmp(captured,"Game/Disc 2.cue"));
        assert(settings==1 && !strcmp(settingsName,"Game") && dialogs==1);
        reset();picker=0;call_leg(leg);
        assert(!deinitializations && !settings && !captured[0]);
        if(leg==4) assert(restored==1 && blocked==0);
    }
    puts("PASS: manifests, ordered picker, faults, argument bounds, five launch legs and APA cancellation");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    game = folder / 'EMBER/games/Game'
    game.mkdir(parents=True)
    for name in ('Disc 1.cue', 'Disc 2.cue'):
        (game / name).write_text('FILE "game.bin" BINARY\n')
    source = HARNESS.replace('@CONSTANTS@', constants).replace('@DISC_TYPE@', disc_type)
    source = source.replace('@UI_TYPES@', enum + '\n' + ui_type)
    source = source.replace('@FUNCTIONS@', functions).replace('@GUI@', gui).replace('@LEGS@', legs)
    cfile = folder / 'discs.c'
    binary = folder / ('discs.exe' if sys.platform == 'win32' else 'discs')
    cfile.write_text(source)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
                    '-Wno-missing-field-initializers', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(folder)], check=True, timeout=15)
