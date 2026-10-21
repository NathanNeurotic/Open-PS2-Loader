"""Exercise PSBBN geometry, native row rendering and built-in theme lifecycle."""
from pathlib import Path
import os
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'src/themes.c').read_text(encoding='utf-8')


def function(signature):
    start = SOURCE.index(signature)
    return SOURCE[start:SOURCE.index('\n}', start) + 2]


def span(first, last):
    """Source from `first` through the end of the function that starts with `last`."""
    start = SOURCE.index(first)
    end = SOURCE.index('\n}', SOURCE.index(last, start))
    return SOURCE[start:end + 2]


def run(name, program):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        source = folder / (name + '.c')
        binary = folder / (name + ('.exe' if os.name == 'nt' else ''))
        source.write_text(program, encoding='utf-8')
        subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-I', str(ROOT), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)


geometry = r'''
#include <assert.h>
#include <stdio.h>
#include "include/psbbnflow.h"
int main(void) {
 assert(psbbnFlowSize(640,480)==204 && psbbnFlowSize(200,480)==80 && psbbnFlowSize(640,576)>0);
 psbbn_flow_card_t focal=psbbnFlowCard(0,204,204,454,240);
 assert(focal.xl==352 && focal.xr==556 && focal.hl==204 && focal.hr==204 && focal.yc==240);
 assert(focal.shade==128 && focal.alpha==128);
 // The first tail card tucks behind the focal cover's left edge, turned away (left edge shorter).
 psbbn_flow_card_t first=psbbnFlowCard(1000,204,204,454,240);
 assert(first.xr==360 && first.xl==322 && first.hr==106 && first.hl==86 && first.alpha==128);
 // The tail recedes: every card is smaller, further left and no brighter than the one before it.
 psbbn_flow_card_t prev=first;
 for(int slot=2;slot<=PSBBN_FLOW_TAIL;slot++) {
  psbbn_flow_card_t c=psbbnFlowCard(slot*1000,204,204,454,240);
  assert(c.xr<prev.xr && c.xl<prev.xl && c.hr<prev.hr && c.hl<c.hr && c.shade<prev.shade && c.alpha<=prev.alpha);
  assert(c.alpha>0 && c.xl>0 && c.yc==240);
  prev=c;
 }
 // Beyond the visible tail the card has faded out completely; halfway it is half faded in.
 assert(psbbnFlowCard((PSBBN_FLOW_TAIL+1)*1000,204,204,454,240).alpha==0);
 assert(psbbnFlowCard(99000,204,204,454,240).alpha==0);
 psbbn_flow_card_t edge=psbbnFlowCard(PSBBN_FLOW_TAIL*1000+500,204,204,454,240);
 assert(edge.alpha==26);
 // Turning toward the viewer interpolates every edge.
 psbbn_flow_card_t turning=psbbnFlowCard(500,204,204,454,240);
 assert(turning.xr<focal.xr && turning.xr>first.xr && turning.hl<turning.hr && turning.hr<204);
 // Outgoing: swells to the upper right and fades out.
 psbbn_flow_card_t out=psbbnFlowCard(-500,204,204,454,240);
 assert(out.alpha==32 && out.hr==357 && out.hl==out.hr && out.xl==362 && out.xr==718 && out.yc==220);
 assert(psbbnFlowCard(-1000,204,204,454,240).alpha==0 && psbbnFlowCard(-5000,204,204,454,240).alpha==0);
 // Widescreen squeezes widths only.
 psbbn_flow_card_t wide=psbbnFlowCard(0,153,204,454,240);
 assert(wide.xr-wide.xl==153 && wide.hr==204);
 assert(psbbnFlowOffset(1000,0)==1000 && psbbnFlowOffset(1000,25)==0);
 assert(psbbnFlowOffset(-3000,12)<0 && psbbnFlowOffset(3000,12)>0);
 assert(psbbnFlowOffset(3000,~0u)==0);
 float uv[4];
 psbbnFlowCrop(140,200,uv);assert(uv[0]==0 && uv[2]==140 && uv[1]==30 && uv[3]==170);
 psbbnFlowCrop(256,128,uv);assert(uv[0]==64 && uv[2]==192 && uv[1]==0 && uv[3]==128);
 psbbnFlowCrop(256,256,uv);assert(uv[0]==0 && uv[1]==0 && uv[2]==256 && uv[3]==256);
 float pts[PSBBN_FLOW_ROUND_POINTS*2];
 psbbnFlowRoundRect(10,20,110,220,8,8,pts);
 assert(pts[0]==10 && pts[1]==28 && pts[8]==18 && pts[9]==20);
 for(int i=0;i<PSBBN_FLOW_ROUND_POINTS;i++)
  assert(pts[i*2]>=10 && pts[i*2]<=110 && pts[i*2+1]>=20 && pts[i*2+1]<=220);
 // Clockwise outline: the top edge comes before the right one, which comes before the bottom.
 assert(pts[10]==102 && pts[19]==28 && pts[20]==110 && pts[28]==102 && pts[29]==220 && pts[30]==18);
 puts("PSBBN: focal, tail, fade-in, turn, outgoing, widescreen, crop and rounded outline geometry passed");
}
'''
run('psbbn_geometry', geometry)


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
static int guiFrameId = 100, cfIsAnimating;
static int psbbnFlowStartOffset;
static unsigned int psbbnFlowStartFrame = 100, psbbnFlowMovingFrame = ~0u;
static struct { u64 textColor; void *psbbnFlow; } theme, *gTheme = &theme;
static int gCoverflowAnimSpeed, cfAnimDirection, cfAnimFrameCount;
static clock_t cfAnimStartTime;
static int drawn[9], positions[9], rims[9], nDrawn, priorities, frames;
static char counter[32];
#define ALIGN_LEFT 0
static int fntCalcDimensions(int f,const char *s) {(void)f;return strlen(s)*8;}
static int rmUnScaleX(int x) {return x;}
static int rmWideScale(int x) {return x;}
static int psbbnFlowFocalSize(const theme_element_t *e) {(void)e;return 204;}
static void drawPsbbnFrame(struct menu_list *m,theme_element_t *e) {(void)m;(void)e;frames++;}
static void fntRenderString(int f,int x,int y,int a,int w,int h,const char *s,u64 c) {
 (void)f;(void)x;(void)y;(void)a;(void)w;(void)h;(void)c;snprintf(counter,sizeof(counter),"%s",s);
}
static theme_element_t *thmGetElemForItem(struct menu_list *m,struct submenu_list *i,theme_element_t *e)
{(void)m;(void)i;return e;}
static void *thmGetItemSource(struct menu_list *m,struct submenu_list *i) {(void)m;(void)i;return NULL;}
static void getGameImageTextureEx(int *c,void *s,void *i,int priority)
{(void)c;(void)s;(void)i;priorities+=priority;}
static void drawPsbbnCover(struct menu_list *m,struct submenu_list *i,theme_element_t *e,int p,int rim) {
 (void)m;(void)e;assert(nDrawn<9);drawn[nDrawn]=i->item.id;rims[nDrawn]=rim;positions[nDrawn++]=p;
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
 theme_element_t elem={.extended=&image,.width=204,.posX=454,.posY=240};
 nDrawn=priorities=frames=0;counter[0]=0;guiFrameId++;
 psbbnFlowStartOffset=flow;psbbnFlowStartFrame=guiFrameId;
 drawPsbbnFlow(&menu,count?&rows[selected]:NULL,NULL,&elem);
 assert(frames==1);
 assert(priorities==(count?1:0));
 assert(nDrawn<=count && nDrawn<=9);
 int selectedDraws=0,rimDraws=0;
 for(int i=0;i<nDrawn;i++) {
  assert(drawn[i]>=0 && drawn[i]<count);
  selectedDraws+=drawn[i]==selected;
  rimDraws+=rims[i];
  if(rims[i]) assert(drawn[i]==selected && positions[i]==0);
  for(int j=0;j<i;j++) assert(drawn[i]!=drawn[j]);
 }
 assert(selectedDraws==(count?1:0));
 int moving=count>=2 && flow!=0;
 assert(rimDraws==(count && !moving ? 1 : 0));
 assert((psbbnFlowMovingFrame==(unsigned int)guiFrameId)==moving);
 if(count<2) {assert(!cfIsAnimating);if(count)assert(positions[0]==0);}
 if(count && !moving) {
  char expected[32];snprintf(expected,sizeof(expected),"%d/%d",selected+1,count);
  assert(!strcmp(counter,expected));
 } else
  assert(!counter[0]);
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
 for(int n=0;n<=10;n++)for(int s=0;s<(n?n:1);s++)for(int f=-3000;f<=3000;f+=1000)
  checkRows(n,s,f);
 puts("PSBBN: both glide directions, empty/single/short lists, wrap deduplication, rim and resting count passed");
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
static int screenWidth=640,screenHeight=480,hidden,overlays,batches,tris,textured,wDraw,hDraw;
static float uMin,uMax,vMin,vMax;
static GSTEXTURE *loaded,*drawn;
static theme_element_t *redirect;
#define GS_SETREG_RGBA(r,g,b,a) ((u64)(r)|((u64)(g)<<8)|((u64)(b)<<16)|((u64)(a)<<24))
#define ALIGN_CENTER 3
#define SCALING_RATIO 1
#define COVER_DEFAULT 0
static GSTEXTURE fallback={128,256,(void *)1};
static GSTEXTURE *thmGetTexture(int id) {(void)id;return &fallback;}
static int rmWideScale(int x) {return x;}
static int isHiddenArtworkCache(int *c) {(void)c;return hidden;}
static theme_element_t *thmGetElemForItem(struct menu_list *m,struct submenu_list *i,theme_element_t *e) {(void)m;(void)i;return redirect?redirect:e;}
static void *thmGetItemSource(struct menu_list *m,struct submenu_list *i) {(void)m;(void)i;return NULL;}
static GSTEXTURE *getGameImageTexture(int *c,void *s,int *i) {(void)c;(void)s;(void)i;return loaded;}
static void rmDrawBlendedTriangles(GSTEXTURE *t,int count,const float *xy,const float *uv,const u64 *col) {
 (void)xy;(void)col;batches++;tris+=count;
 if(!t) {assert(uv==NULL);return;}
 textured++;drawn=t;
 for(int i=0;i<count*3;i++) {
  uMin=uv[i*2]<uMin?uv[i*2]:uMin;uMax=uv[i*2]>uMax?uv[i*2]:uMax;
  vMin=uv[i*2+1]<vMin?uv[i*2+1]:vMin;vMax=uv[i*2+1]>vMax?uv[i*2+1]:vMax;
 }
}
static void rmDrawPixmap(GSTEXTURE *t,int x,int y,int a,int w,int h,int s,u64 color,int r) {
 (void)t;(void)x;(void)y;(void)a;(void)s;(void)color;(void)r;wDraw=w;hDraw=h;
}
static void rmDrawOverlayPixmap(GSTEXTURE *t,int x,int y,int a,int w,int h,int s,u64 color,GSTEXTURE *cover,
 int ulx,int uly,int urx,int ury,int llx,int lly,int lrx,int lry,int r) {
 (void)t;(void)x;(void)y;(void)a;(void)s;(void)color;(void)cover;(void)ulx;(void)uly;(void)ury;(void)llx;(void)r;
 assert(urx==w && lly==h && lrx==w && lry==h);overlays++;wDraw=w;hDraw=h;
}
@COVER@
static void reset(void) {batches=tris=textured=0;drawn=NULL;uMin=vMin=1e9f;uMax=vMax=-1e9f;}
int main(void) {
 struct menu_list menu={0};struct submenu_list row={0};int cache=0;
 mutable_image_t image={.cache=&cache};theme_element_t elem={204,204,454,240,&image};
 GSTEXTURE portrait={128,256,(void *)1},square={256,256,(void *)1},empty={256,256,NULL};
 // Settled selection: rim ring, rounded fan cropped to the centre square, inner rim.
 reset();loaded=&portrait;drawPsbbnCover(&menu,&row,&elem,0,1);
 assert(batches==3 && textured==1 && drawn==&portrait && tris==PSBBN_FLOW_ROUND_POINTS*5);
 assert(uMin==0 && uMax==128 && vMin==64 && vMax==192);
 reset();drawPsbbnCover(&menu,&row,&elem,0,0);assert(batches==1 && tris==PSBBN_FLOW_ROUND_POINTS);
 // Turned tail card: perspective strips spanning the whole crop.
 reset();loaded=&square;drawPsbbnCover(&menu,&row,&elem,1000,0);
 assert(batches==1 && tris==2*PSBBN_FLOW_STRIPS && uMin==0 && uMax==256 && vMin==0 && vMax==256);
 // Outgoing covers stay flat; fully faded or off-tail cards draw nothing.
 reset();drawPsbbnCover(&menu,&row,&elem,-400,0);assert(batches==1 && tris==PSBBN_FLOW_ROUND_POINTS);
 reset();drawPsbbnCover(&menu,&row,&elem,-1000,0);assert(batches==0);
 reset();drawPsbbnCover(&menu,&row,&elem,(PSBBN_FLOW_TAIL+1)*1000,0);assert(batches==0);
 reset();loaded=&empty;drawPsbbnCover(&menu,&row,&elem,0,0);assert(drawn==&fallback);
 image_texture_t app={.source={256,256,(void *)1}};
 mutable_image_t appImage={.cache=&cache,.defaultTexture=&app};theme_element_t appElem={204,204,454,240,&appImage};
 reset();redirect=&appElem;loaded=NULL;drawPsbbnCover(&menu,&row,&elem,0,0);assert(drawn==&app.source);
 redirect=NULL;
 image_texture_t overlay={.source={256,256,(void *)1},.upperRight_x=204,.lowerLeft_y=204,.lowerRight_x=204,.lowerRight_y=204};
 reset();image.overlayTexture=&overlay;loaded=&portrait;drawPsbbnCover(&menu,&row,&elem,0,1);
 assert(overlays==1 && batches==0 && wDraw==204 && hDraw==204);
 reset();hidden=1;drawPsbbnCover(&menu,&row,&elem,0,0);assert(batches==0 && overlays==1);
 hidden=0;image.overlayTexture=NULL;square.Width=0;loaded=&square;
 reset();drawPsbbnCover(&menu,&row,&elem,0,0);assert(batches==0);
 puts("PSBBN: rounded square crop, rim, turned card, fades, missing art, family fallback, overlays and hidden art passed");
}
'''.replace('@COVER@', span('#define PSBBN_FLOW_STRIPS', 'static void drawPsbbnCover('))
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
assert cfg.count('default=psbbn_bg') == 2
makefile = (ROOT / 'Makefile').read_text(encoding='utf-8')
assert 'theme_psbbn_flow.o' in makefile and re.search(r'\bpsbbn_bg\b', makefile)
assert '{PSBBN_BACKGROUND, "psbbn_bg", &psbbn_bg_png}' in (ROOT / 'src/textures.c').read_text(encoding='utf-8')
for name in ('src/menusys.c', 'src/gui.c', 'src/opl.c'):
    text = (ROOT / name).read_text(encoding='utf-8')
    assert 'GUI_SCREEN_COLLECTION' not in text and 'OPLUNA_UI' not in text
assert not re.search(r'^(?:bg|text|ui|sel)_color=', cfg, re.M)
# Theme graphics stay 8-bit PNGs.
png = (ROOT / 'gfx/psbbn_bg.png').read_bytes()
assert png[:8] == b'\x89PNG\r\n\x1a\n' and png[24] == 8, 'psbbn_bg.png must be an 8-bit PNG'
width, height = struct.unpack('>II', png[16:24])
assert (width, height) == (160, 120)
print('PSBBN: built-in config, embedded nebula asset and native screen/shortcut wiring passed')
