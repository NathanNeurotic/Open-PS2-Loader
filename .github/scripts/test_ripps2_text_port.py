"""Right-to-left and CJK text ported from RIPPS2 (akilluminati47/RIPPS2, build 104).

1. txtShape joins Arabic and Persian letters (presentation forms, lam-alef as one) and lays each line out right to
   left; Latin words and numbers keep their order, brackets turn round, text without right-to-left letters is left
   alone. txtBreakAt allows a line break only between CJK, Thai or Lao letters, never before closing punctuation or a
   vowel that belongs to the letter before.
2. fntWrapText (the message box) breaks CJK text between letters and an over-wide word anywhere,
   and never cuts a character when the buffer fills.
3. The font system draws and measures the shaped text, and skips zero-width marks. The settings hint box breaks
   CJK, Thai and Lao text the same way in its own loop.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
scripts = Path(__file__).resolve().parent
fnt = (root / 'src/fntsys.c').read_text()


def function(source, signature):
    pos = source.index(signature)
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1]
    raise AssertionError('unterminated ' + signature)


def run(name, code):
    with tempfile.TemporaryDirectory(prefix='ripps2-text-') as temp:
        src = Path(temp) / (name + '.c')
        exe = Path(temp) / (name + '.exe')
        src.write_text(code)
        # utf8.h spells its static after the type, which -Wextra calls old-style
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-old-style-declaration', '-I', str(root), str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


shape_main = (scripts / 'ripps2_text_cases.inc').read_text()
run('shape', '#include "src/textshape.c"\n' + shape_main.split('/* ---- wrap ---- */')[0])
print('ok   Arabic and Persian joined and laid out right to left; CJK, Thai and Lao line breaks')

wrap = function(fnt, 'static int fntWrapPut(') + '\n\n' + function(fnt, 'int fntWrapText(')
mocks = '''#include <string.h>
#include "src/textshape.c"
static int rmUnScaleX(int x) { return x; }
static int fntCalcDimensions(int id, const char *s) /* 10 a Latin character, 20 any other */
{
    int w = 0;
    (void)id;
    while (*s) {
        uint32_t c;
        int n = txtNext(s, &c);
        w += c < 0x80 ? 10 : 20;
        s += n;
    }
    return w;
}
'''
run('wrap', mocks + wrap + '\n' + shape_main.split('/* ---- wrap ---- */')[1])
print('ok   fntWrapText: words, hard breaks, over-wide words, CJK breaks, full buffer')

render = function(fnt, '#ifndef __RTL\nint fntRenderString(')
assert render.index('fntCalcDimensionsLocked(font, string)') < render.index('txtShape(string, shaped, sizeof(shaped), 1)'), 'measure, then shape for drawing'
assert 'txtZeroWidth(codepoint)' in render
calc = function(fnt, 'static int fntCalcDimensionsLocked(font_t *font, const char *str)\n{')
assert 'txtShape(str, joined, sizeof(joined), 0)' in calc and 'txtZeroWidth(codepoint)' in calc, 'measure the joined letters, skip zero-width marks'
assert '#ifndef __RTL' in calc, 'the old __RTL build keeps its own drawing'
gui = (root / 'src/gui.c').read_text()
assert 'return fntWrapText(gTheme->fonts[0], text, innerW, out, outSize);' in function(gui, 'static int guiWrapText(')
dia = function((root / 'src/dia.c').read_text(), 'static void diaDrawHint(')
assert 'noSpaces = txtNoSpaceScript(wordStart, wordLen);' in dia and 'if (wordLen < 256 && !noSpaces)' in dia
assert '(!noSpaces || txtBreakAt(wordStart, q))' in dia, 'the hint box breaks CJK only where the script allows'
assert 'textshape.o' in (root / 'Makefile').read_text()
print('ok   the font system shapes and measures right-to-left text; the hint and message boxes break CJK text')
