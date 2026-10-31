"""Long text on the warning, text, video-mode and remove-settings screens wraps like the message box.

Those four screens drew their text as one unbounded line, so a long translation ran past the
message rules and off the screen (YAOPL 6a091fc, Roman Kelesidis). This compiles the real
guiDrawWrappedLines/guiDrawMsgText from src/gui.c with a fixed-width font stub and checks that
every line fits between the rules, that a one-line message stays at its old position, and that
each of the four screens draws through the wrapping helper.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/gui.c').read_text(encoding='utf-8')
failures = []


def function_text(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


def body_of(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if not match:
        failures.append('missing ' + signature)
        return ''
    return source[match.start():source.index('\n}', match.start())]


for signature in ('void guiRenderTextScreen(', 'void guiWarning(', 'int guiConfirmVideoMode(',
                  'int guiGameShowRemoveSettings('):
    body = body_of(signature)
    if body and 'guiDrawMsgText(' not in body:
        failures.append(signature + ' does not wrap its text through guiDrawMsgText')
    if re.search(r'fntRenderString\([^;]*usedHeight >> 1, ALIGN_CENTER[^;]*\);', body):
        failures.append(signature + ' still draws its text as one unbounded line')

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
enum { ALIGN_CENTER = 1, MENU_ITEM_HEIGHT = 20, CHAR_W = 8 };
static struct {int fonts[1], usedHeight, textColor;} theme = {{0}, 448, 1}, *gTheme = &theme;
static int screenWidth = 640;
static int drawn, firstY, lastY, widest;
/* Fixed-width greedy wrap on spaces, standing in for fntWrapText. */
static int fntWrapText(int font, const char *text, int innerW, char *out, int outSize)
{
    int lines = 1, col = 0, max = innerW / CHAR_W, o = 0;
    const char *p = text;
    (void)font;
    while (*p && o < outSize - 1) {
        const char *w = p;
        int n;
        while (*w && *w != ' ')
            w++;
        n = (int)(w - p);
        if (col && col + 1 + n > max) {
            out[o++] = '\n';
            lines++;
            col = 0;
        } else if (col && o < outSize - 1) {
            out[o++] = ' ';
            col++;
        }
        while (p < w && o < outSize - 1) {
            out[o++] = *p++;
            col++;
        }
        while (*p == ' ')
            p++;
    }
    out[o] = '\0';
    return lines;
}
static int guiWrapText(const char *text, int innerW, char *out, int outSize)
{
    return fntWrapText(gTheme->fonts[0], text, innerW, out, outSize);
}
static void fntRenderString(int font, int x, int y, int align, int w, int h, const char *s, int c)
{
    int width = (int)strlen(s) * CHAR_W;
    (void)font; (void)align; (void)w; (void)h; (void)c;
    assert(x == screenWidth / 2);
    assert(strchr(s, '\n') == NULL);
    if (!drawn)
        firstY = y;
    lastY = y;
    if (width > widest)
        widest = width;
    drawn++;
}
@FUNCTIONS@
static void reset(void) { drawn = firstY = lastY = widest = 0; }
int main(void)
{
    const char *longText = "The read-only UDPBD server keeps no VMC: saves made in this game stay "
                           "in memory and are lost when the console turns off. Copy the VMC to a "
                           "writable device first.";
    int y;
    reset();
    y = guiDrawMsgText("Please wait...");
    assert(drawn == 1 && firstY == 224 && y == 224);
    reset();
    y = guiDrawMsgText(longText);
    assert(drawn > 1);
    assert(widest <= screenWidth - 120);
    assert(y == lastY && lastY == firstY + (drawn - 1) * MENU_ITEM_HEIGHT);
    /* The block stays centred on the old single-line position. */
    assert(firstY + lastY == 2 * 224 || firstY + lastY == 2 * 224 - MENU_ITEM_HEIGHT);
    /* All lines between the rules at y 75 and 410. */
    assert(firstY > 75 && lastY < 410);
    printf("PASS: %d lines, widest %d px of %d\n", drawn, widest, screenWidth - 120);
    return 0;
}
'''

if not failures:
    functions = function_text('static int guiDrawWrappedLines(') + function_text('static int guiDrawMsgText(')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        cfile = path / 'wrap.c'
        binary = path / ('wrap.exe' if sys.platform == 'win32' else 'wrap')
        cfile.write_text(harness.replace('@FUNCTIONS@', functions), encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            if run.returncode != 0:
                failures.append('harness failed (%d):\n%s%s' % (run.returncode, run.stdout, run.stderr))
            else:
                print(run.stdout.strip())

if failures:
    print('Message wrap checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('message wrap: text screen, warning, video-mode confirm and remove-settings prompt wrap between the rules')
