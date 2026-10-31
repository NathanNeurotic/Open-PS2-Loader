"""A context-free error must not render the active library or queue its artwork."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/gui.c').read_text(encoding='utf-8')
# guiMsgBox draws its lines through the shared guiDrawWrappedLines helper; compile both.
function = ''
for signature in ('static int guiDrawWrappedLines(', 'int guiMsgBox('):
    start = source.index(signature)
    function += source[start:source.index('\n}', start) + 2] + '\n'
harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define LOG(...) ((void)0)
enum { KEY_CIRCLE=1, KEY_CROSS, SFX_MESSAGE, SFX_CANCEL, SFX_CONFIRM,
       CROSS_ICON, CIRCLE_ICON, _STR_BACK, _STR_ACCEPT, ALIGN_CENTER, MENU_ITEM_HEIGHT=20 };
struct UIItem {int unused;};
static struct {int fonts[1],usedHeight,textColor;} theme={{0},448,1}, *gTheme=&theme;
static struct {int inMenu;} handler={0}, *screenHandler=&handler;
static int screenWidth=640,screenHeight=448,gSelectButton=KEY_CROSS;
static int gColDarker=1,gColBlack=2,gColWhite=3;
static int activeRenders, contextRenders, shade, key=KEY_CIRCLE;
void guiShow(void) {activeRenders++;}
static int guiWrapText(const char *s,int width,char *out,int size) {
    (void)width;snprintf(out,size,"%s",s);return 1;
}
static void sfxPlay(int sound) {(void)sound;}
static void guiStartFrame(void) {}
static void guiEndFrame(void) {}
static void readPads(void) {}
static int getKeyOn(int button) {return button==key;}
static void diaRenderUI(struct UIItem *ui,int menu,void *p,int n) {
    (void)menu;(void)p;(void)n;assert(ui);contextRenders++;
}
static void rmDrawRect(int x,int y,int w,int h,int color) {
    (void)x;(void)y;(void)w;(void)h;shade=color;
}
static void rmDrawLine(int x,...) {(void)x;}
static void fntRenderString(int font,...) {(void)font;}
static void guiDrawIconAndText(int icon,...) {(void)icon;}
@FUNCTION@
int main(void) {
    assert(guiMsgBox("Missing CUE",0,NULL)==0);
    assert(!activeRenders && !contextRenders && shade==gColBlack);
    struct UIItem context={0};key=KEY_CROSS;
    assert(guiMsgBox("Confirm",1,&context)==1);
    assert(!activeRenders && contextRenders==1 && shade==gColDarker);
    gTheme=NULL;assert(guiMsgBox("Early error",0,NULL)==0);
    assert(!activeRenders && contextRenders==1);
    puts("PASS: error dialogs avoid active-menu rendering; supplied UI and pre-GUI refusal preserved");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    cfile = path / 'dialog.c'
    binary = path / ('dialog.exe' if sys.platform == 'win32' else 'dialog')
    cfile.write_text(harness.replace('@FUNCTION@', function))
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
