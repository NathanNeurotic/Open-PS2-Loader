"""Exercise PSBBN geometry, native row rendering and built-in theme lifecycle."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'src/themes.c').read_text(encoding='utf-8')


def function(signature):
    start = SOURCE.index(signature)
    return SOURCE[start:SOURCE.index('\n}', start) + 2]


def run(name, program):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        source = folder / (name + '.c')
        binary = folder / (name + ('.exe' if os.name == 'nt' else ''))
        source.write_text(program, encoding='utf-8')
        subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-I', str(ROOT), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)


render = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include "include/psbbnflow.h"
typedef unsigned long long u64;
typedef int config_set_t;
typedef struct { int *cache; } mutable_image_t;
typedef struct theme_element { void *extended; int width, posX, posY, font; } theme_element_t;
struct submenu_list { struct { int id; } item; struct submenu_list *prev, *next; };
struct menu_item { struct submenu_list *submenu, *last; };
struct menu_list { struct menu_item *item; };
static int screenWidth = 640, screenHeight = 480, guiFrameId = 100, cfIsAnimating;
static int psbbnFlowStartOffset;
static unsigned int psbbnFlowStartFrame = 100;
static struct { u64 textColor; void *psbbnFlow; } theme, *gTheme = &theme;
static int gCoverflowAnimSpeed, cfAnimDirection, cfAnimFrameCount;
static clock_t cfAnimStartTime;
static int drawn[8], positions[8], nDrawn, priorities;
static char counter[32];
#define GS_SETREG_RGBA(...) ((u64)0)
#define ALIGN_LEFT 0
static void rmDrawRect(int x,int y,int w,int h,u64 c) {(void)x;(void)y;(void)w;(void)h;(void)c;}
static int fntCalcDimensions(int f,const char *s) {(void)f;return strlen(s)*8;}
static int rmUnScaleX(int x) {return x;}
static void fntRenderString(int f,int x,int y,int a,int w,int h,const char *s,u64 c) {
 (void)f;(void)x;(void)y;(void)a;(void)w;(void)h;(void)c;snprintf(counter,sizeof(counter),"%s",s);
}
static theme_element_t *thmGetElemForItem(struct menu_list *m,struct submenu_list *i,theme_element_t *e)
{(void)m;(void)i;return e;}
static void *thmGetItemSource(struct menu_list *m,struct submenu_list *i) {(void)m;(void)i;return NULL;}
static void getGameImageTextureEx(int *c,void *s,void *i,int priority)
{(void)c;(void)s;(void)i;priorities+=priority;}
static void drawPsbbnCover(struct menu_list *m,struct submenu_list *i,theme_element_t *e,int p) {
 (void)m;(void)e;assert(nDrawn<8);drawn[nDrawn]=i->item.id;positions[nDrawn++]=p;
}
@TRIGGER@
@RENDER@
static void checkRows(int count,int selected,int flow) {
 struct submenu_list rows[10]={0};
 for(int i=0;i<count;i++) {
  rows[i].item.id=i;rows[i].prev=i?&rows[i-1]:NULL;rows[i].next=i+1<count?&rows[i+1]:NULL;
 }
 struct menu_item page={count?rows:NULL,count?&rows[count-1]:NULL};
 struct menu_list menu={&page}; int cache=1;mutable_image_t image={&cache};
 theme_element_t elem={.extended=&image,.width=279,.posX=603,.posY=75};
 nDrawn=priorities=0;psbbnFlowStartOffset=flow;psbbnFlowStartFrame=guiFrameId;
 drawPsbbnFlow(&menu,count?&rows[selected]:NULL,NULL,&elem);
 assert(priorities==(count?1:0));
 assert(nDrawn<=count && nDrawn<=8);
 int selectedDraws=0;
 for(int i=0;i<nDrawn;i++) {
  assert(drawn[i]>=0 && drawn[i]<count);
  selectedDraws+=drawn[i]==selected;
  for(int j=0;j<i;j++) assert(drawn[i]!=drawn[j]);
 }
 assert(selectedDraws==(count?1:0));
 if(count<2) {assert(!cfIsAnimating);if(count)assert(positions[0]==0);}
 char expected[32];snprintf(expected,sizeof(expected),"%d/%d",count?selected+1:0,count);
 assert(!strcmp(counter,expected));
}
int main(void) {
 gTheme->psbbnFlow=&theme;gCoverflowAnimSpeed=0;
 thmTriggerCoverflowAnim(1);assert(psbbnFlowStartOffset==1000 && cfIsAnimating);
 thmTriggerCoverflowAnim(-1);assert(psbbnFlowStartOffset==0 && !cfIsAnimating);
 gCoverflowAnimSpeed=220;cfAnimFrameCount=99;
 thmTriggerCoverflowAnim(-1);
 assert(psbbnFlowStartOffset==-1000 && cfAnimDirection==-1 && cfAnimFrameCount==0 && cfIsAnimating);
 for(int i=0;i<5;i++)thmTriggerCoverflowAnim(-1);
 assert(psbbnFlowStartOffset==-3000);
 guiFrameId+=25;thmTriggerCoverflowAnim(1);assert(psbbnFlowStartOffset==1000);
 gTheme->psbbnFlow=NULL;thmTriggerCoverflowAnim(-1);
 assert(psbbnFlowStartOffset==1000 && cfAnimDirection==-1);
 psbbn_flow_rect_t focal=psbbnFlowRect(0,316,446,233);
 assert(focal.size==316 && focal.x==288 && focal.y==75 && focal.shade==128);
 psbbn_flow_rect_t tail=psbbnFlowRect(1000,316,446,233);
 assert(tail.size==139 && tail.x==219 && tail.shade==88);
 psbbn_flow_rect_t outgoing=psbbnFlowRect(-1000,316,446,233);
 assert(outgoing.size==553 && outgoing.x==675);
 assert(psbbnFlowOffset(1000,0)==1000 && psbbnFlowOffset(1000,25)==0);
 assert(psbbnFlowOffset(-3000,12)<0 && psbbnFlowOffset(3000,12)>0);
 assert(psbbnFlowOffset(3000,~0u)==0);
 assert(psbbnFlowSize(640,480)>0 && psbbnFlowSize(640,576)>0);
 for(int n=0;n<=10;n++)for(int s=0;s<(n?n:1);s++)for(int f=-3000;f<=3000;f+=1000)
  checkRows(n,s,f);
 puts("PSBBN: original geometry, both glide directions, empty/single/short lists and wrap deduplication passed");
}
'''.replace('@RENDER@', function('static void drawPsbbnFlow(')).replace('@TRIGGER@', function('void thmTriggerCoverflowAnim('))
run('psbbn_render', render)


covers = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include "include/psbbnflow.h"
typedef unsigned long long u64;
typedef struct {int Width,Height;void *Mem;} GSTEXTURE;
typedef struct {GSTEXTURE source;int upperLeft_x,upperLeft_y,upperRight_x,upperRight_y,lowerLeft_x,lowerLeft_y,lowerRight_x,lowerRight_y;} image_texture_t;
typedef struct {int *cache;image_texture_t *defaultTexture,*overlayTexture,*overlayTexture2;} mutable_image_t;
typedef struct theme_element {int width,height,posX,posY;void *extended;} theme_element_t;
struct menu_list {int id;};struct submenu_list {int item;};
static int screenWidth=640,screenHeight=480,hidden,draws,overlays,wDraw,hDraw;
static GSTEXTURE *loaded,*drawn;
static theme_element_t *redirect;
#define GS_SETREG_RGBA(...) ((u64)0)
#define ALIGN_CENTER 3
#define SCALING_RATIO 1
#define COVER_DEFAULT 0
static GSTEXTURE fallback={128,256,(void *)1};
static GSTEXTURE *thmGetTexture(int id) {(void)id;return &fallback;}
static int isHiddenArtworkCache(int *c) {(void)c;return hidden;}
static theme_element_t *thmGetElemForItem(struct menu_list *m,struct submenu_list *i,theme_element_t *e) {(void)m;(void)i;return redirect?redirect:e;}
static void *thmGetItemSource(struct menu_list *m,struct submenu_list *i) {(void)m;(void)i;return NULL;}
static GSTEXTURE *getGameImageTexture(int *c,void *s,int *i) {(void)c;(void)s;(void)i;return loaded;}
static void rmDrawPixmap(GSTEXTURE *t,int x,int y,int a,int w,int h,int s,u64 color,int r) {
 (void)x;(void)y;(void)a;(void)s;(void)color;(void)r;draws++;drawn=t;wDraw=w;hDraw=h;
}
static void rmDrawOverlayPixmap(GSTEXTURE *t,int x,int y,int a,int w,int h,int s,u64 color,GSTEXTURE *cover,
 int ulx,int uly,int urx,int ury,int llx,int lly,int lrx,int lry,int r) {
 (void)cover;(void)ulx;(void)uly;(void)ury;(void)llx;(void)r;
 assert(urx==w && lly==h && lrx==w && lry==h);overlays++;
 rmDrawPixmap(t,x,y,a,w,h,s,color,0);
}
@COVER@
int main(void) {
 struct menu_list menu={0};struct submenu_list row={0};int cache=0;
 mutable_image_t image={.cache=&cache};theme_element_t elem={279,279,603,75,&image};
 GSTEXTURE portrait={128,256,(void *)1},square={256,256,(void *)1},empty={256,256,NULL};
 loaded=&portrait;drawPsbbnCover(&menu,&row,&elem,0);
 assert(drawn==&portrait && wDraw==139 && hDraw==279);
 loaded=&square;drawPsbbnCover(&menu,&row,&elem,0);assert(wDraw==279 && hDraw==279);
 loaded=&empty;drawPsbbnCover(&menu,&row,&elem,0);assert(drawn==&fallback);
 image_texture_t app={.source={256,256,(void *)1}};
 mutable_image_t appImage={.cache=&cache,.defaultTexture=&app};theme_element_t appElem={279,279,603,75,&appImage};
 redirect=&appElem;loaded=NULL;drawPsbbnCover(&menu,&row,&elem,0);assert(drawn==&app.source && wDraw==279);
 redirect=NULL;
 image_texture_t overlay={.source={256,256,(void *)1},.upperRight_x=279,.lowerLeft_y=279,.lowerRight_x=279,.lowerRight_y=279};
 image.overlayTexture=&overlay;loaded=&portrait;drawPsbbnCover(&menu,&row,&elem,0);assert(overlays==1);
 int oldDraws=draws;hidden=1;drawPsbbnCover(&menu,&row,&elem,0);assert(draws==oldDraws);
 hidden=0;image.overlayTexture=NULL;square.Width=0;loaded=&square;
 drawPsbbnCover(&menu,&row,&elem,0);assert(draws==oldDraws);
 puts("PSBBN: portrait/square proportions, missing art, family fallback, overlays and hidden art passed");
}
'''.replace('@COVER@', function('static void drawPsbbnCover('))
run('psbbn_covers', covers)

registry = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#define LOG(...) ((void)0)
static int nThemes=2,guiThemeID,gLoadCoverflowBuiltin,gLoadPsbbnFlowBuiltin;
static const char **guiThemesNames;
typedef struct {char *name,*filePath;} theme_file_t;
static theme_file_t themes[8];
static int loads,loaded,colors,failLoad,locks;
static int gTheme;
#define THM_MAX_FILES 16
#define CONFIG_OPL 0
#define MODE_COUNT 0
static int configGetByType(int t) {return t;}
static int configGetStr(int c,const char *key,const char **value) {(void)c;(void)key;(void)value;return 0;}
static void moduleUpdateMenu(int i,int a,int b) {(void)i;(void)a;(void)b;}
static int thmReadEntry;
static int listDir(char *path,const char *sep,int max,int *cb) {
 (void)path;(void)sep;(void)max;(void)cb;
 themes[nThemes].name=strdup("C");themes[nThemes].filePath=strdup("mass1:/THM/C/");return 1;
}
static void guiLock(void) {assert(!locks);locks++;}
static void guiUnlock(void) {assert(locks);locks--;}
static int thmLoad(const char *path) {
 loads++;loaded=path?3:gLoadPsbbnFlowBuiltin?2:gLoadCoverflowBuiltin?1:0;
 return failLoad?-1:0;
}
static void thmSetColors(int t) {(void)t;colors++;}
int thmFindGuiID(const char *theme);
@FUNCTIONS@
int main(void) {
 themes[0].name=strdup("A");themes[0].filePath=strdup("mass0:/THM/A/");
 themes[1].name=strdup("B");themes[1].filePath=strdup("mc0:/THM/B/");
 thmRebuildGuiNames();
 assert(!strcmp(guiThemesNames[3],"<Coverflow>"));
 assert(!strcmp(guiThemesNames[4],"<PSBBN Flow>") && !guiThemesNames[5]);
 assert(thmFindGuiID("<psbbn flow>")==4);
 assert(thmSetGuiValue(4,0) && loaded==2 && guiThemeID==4);
 assert(!gLoadCoverflowBuiltin && !gLoadPsbbnFlowBuiltin && !thmGetFilePath(4));
 thmSetGuiValue(4,0);assert(colors==1);
 failLoad=1;assert(!thmSetGuiValue(1,0) && guiThemeID==4);failLoad=0;
 int oldLoads=loads;
 thmReinit("mass0:");assert(nThemes==1 && guiThemeID==3 && loads==oldLoads);
 assert(!strcmp(guiThemesNames[guiThemeID],"<PSBBN Flow>"));
 thmReinit("mc0:");assert(nThemes==0 && guiThemeID==2 && loads==oldLoads);
 assert(thmAddElements("mass1:","/",0)==1 && guiThemeID==3 && loads==oldLoads);
 assert(!strcmp(guiThemesNames[guiThemeID],"<PSBBN Flow>"));
 thmReinit("mass1:");assert(guiThemeID==2 && loads==oldLoads);
 assert(thmSetGuiValue(1,0) && loaded==1 && !thmGetFilePath(1));
 oldLoads=loads;
 assert(thmAddElements("mass1:","/",0)==1 && guiThemeID==2 && loads==oldLoads);
 assert(!strcmp(guiThemesNames[guiThemeID],"<Coverflow>"));
 thmReinit("mass1:");assert(guiThemeID==1 && loads==oldLoads);
 assert(!thmSetGuiValue(99,0) && guiThemeID==1);
 assert(thmSetGuiValue(0,0) && loaded==0);
 free(guiThemesNames);
 puts("PSBBN: picker, persistence lookup, palette, failed-load rollback and disk-theme discovery/removal passed");
}
'''
functions = '\n'.join(function(s) for s in (
    'static void thmRebuildGuiNames(', 'int thmFindGuiID(', 'int thmSetGuiValue(',
    'int thmAddElements(',
    'char *thmGetFilePath(', 'void thmReinit(',
))
run('psbbn_registry', registry.replace('@FUNCTIONS@', functions))

# Native integration must not import Collection's screen, source snapshots or R3 remapping.
cfg = (ROOT / 'misc/theme_psbbn_flow.cfg').read_text(encoding='utf-8')
assert cfg.count('type=PSBBNFlow') == 3
assert 'theme_psbbn_flow.o' in (ROOT / 'Makefile').read_text(encoding='utf-8')
for name in ('src/menusys.c', 'src/gui.c', 'src/opl.c'):
    text = (ROOT / name).read_text(encoding='utf-8')
    assert 'GUI_SCREEN_COLLECTION' not in text and 'OPLUNA_UI' not in text
assert not re.search(r'^(?:bg|text|ui|sel)_color=', cfg, re.M)
print('PSBBN: built-in config, embedded asset and native screen/shortcut wiring passed')
