"""Font loads that flush the glyph atlases must do so as GUI-frame work (RiptOPL #297 port).

The glyph atlases are GS textures. gsKit's texture manager keeps every texture in one unlocked
global list that the GUI thread walks on each draw, and a frame's inline uploads reference the
atlas pixels until that frame (and, under HIRES, its replay) is retired. thmLoad honours that:
guiLock, rmDiscardFrame(), then free. The font loaders did not: fntLoadFile, fntLoadDefault,
fntSetWeight and fntUpdateAspectRatio flushed EVERY font's atlases (fntUpdateAspectRatioLocked ->
fntCacheFlush -> atlasFree -> rmUnloadTexture + free) under the font lock alone. A saved disk theme
found by the IO worker while the boot splash is drawing is exactly that path. That is a plausible,
not console-confirmed, mechanism for a saved-theme boot freeze; this test verifies the lock
contract, not the cause of any report.

Compile the production loaders against a stub GUI/renderer that models the contract:
 - a texture may leave the texture manager only under the GUI lock, after the in-flight frame was
   retired with rmDiscardFrame();
 - the slow file read stays OUTSIDE the GUI lock (the splash keeps drawing while a font is read);
 - fntRelease takes no GUI lock of its own: thmFree calls it already holding the lock.
The "before" control swaps the frame lock back to the bare font lock in the same production code
and must fail.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/fntsys.c').read_text(encoding='utf-8').replace('\r\n', '\n')

functions = ['fntLock', 'fntUnlock', 'fntFrameLock', 'fntFrameUnlock', 'fntCacheFlush', 'fntInitSlot',
             'fntDeleteSlot', 'fntRelease', 'fntLoadSlotLocked', 'fntLoadFile', 'fntSetWeight',
             'fntLoadDefault', 'fntUpdateAspectRatio', 'fntUpdateAspectRatioLocked']
bodies = []
for name in functions:
    match = re.search(r'^(?:static )?[\w \*]*?\b' + name + r'\([^)]*\)\n\{.*?^\}\n', source, re.M | re.S)
    if match is None:
        print(f'FAIL: src/fntsys.c: {name}() not found')
        sys.exit(1)
    bodies.append(match.group(0))
production = '\n'.join(bodies)

fixture = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LOG(...) ((void)0)
#define FNT_ERROR (-1)
#define FNT_DEFAULT 0
#define FNT_MAX_COUNT 4
#define FNTSYS_DEFAULT_SIZE 17
#define ATLAS_MAX 2
#define GLYPH_CACHE_PAGE_SIZE 1

typedef struct { void *Mem; int Vram; } GSTEXTURE;
typedef struct { GSTEXTURE surface; } atlas_t;
typedef struct FT_FaceRec_ { int size; } *FT_Face;
typedef struct FT_LibraryRec_ { int dummy; } *FT_Library;
typedef unsigned char FT_Byte;
typedef int s32;
static const float fDPI = 72.0f;

typedef struct { int isValid; void *allocation; atlas_t *atlas; } fnt_glyph_cache_entry_t;
typedef struct {
    fnt_glyph_cache_entry_t **glyphCache;
    int cacheMaxPageID;
    FT_Face face;
    int isValid;
    int fontSize;
    int weight, embolden;
    atlas_t *atlases[ATLAS_MAX];
    void *dataPtr;
} font_t;

static font_t fonts[FNT_MAX_COUNT];
static FT_Library font_library;
static s32 gFontSemaId;

// --- the GUI thread, as the stubs see it -------------------------------------------------
static jmp_buf failure;
static const char *failureText;
#define FAIL(text) do { failureText = text; longjmp(failure, 1); } while (0)
static int guiReady = 1;      // 0 before guiInit: single-threaded, the GUI lock is a no-op
static int guiLocked = 0;     // the frame lock (non-recursive)
static int frameRetired = 0;  // rmDiscardFrame() ran since the lock was taken
static int fontLocked = 0;
static int discards = 0, unloads = 0;
static void guiLock(void) { if (!guiReady) return; if (guiLocked) FAIL("GUI lock taken twice (deadlock)"); guiLocked = 1; }
static void guiUnlock(void) { if (!guiReady) return; assert(guiLocked); guiLocked = 0; frameRetired = 0; }
static void rmDiscardFrame(void) { if (guiReady) assert(guiLocked); frameRetired = 1; ++discards; }
static void rmUnloadTexture(GSTEXTURE *txt) {
    (void)txt; ++unloads;
    if (!guiReady) return;
    if (!guiLocked) FAIL("glyph atlas left the texture manager outside the GUI lock");
    if (!frameRetired) FAIL("glyph atlas freed while the last frame's uploads can still reference it");
}
static void rmGetScreenExtents(int *w, int *h) { *w = 640; *h = 480; }
static void rmGetScreenExtentsNative(int *w, int *h) { *w = 640; *h = 448; }
static float rmGetPAR(void) { return 1.0f; }
static int fntScaleFontSize(int size) { return size; }
static int fntFaceSetWeight(FT_Library l, FT_Face f, int weight) { (void)l; (void)f; return weight; }
static int fntEmboldenFor(int a, int b) { (void)a; (void)b; return 0; }
static void WaitSema(s32 id) { (void)id; assert(!fontLocked); fontLocked = 1; }
static void SignalSema(s32 id) { (void)id; assert(fontLocked); fontLocked = 0; }
static int FT_New_Memory_Face(FT_Library l, const FT_Byte *b, int n, int i, FT_Face *face) {
    (void)l; (void)b; (void)n; (void)i; *face = calloc(1, sizeof(**face)); return 0; }
static void FT_Done_Face(FT_Face face) { free(face); }
static void FT_Set_Char_Size(FT_Face face, int a, int b, float c, float d) { (void)a; (void)b; (void)c; (void)d; face->size++; }
static atlas_t *atlasCreate(void) { atlas_t *a = calloc(1, sizeof(*a)); a->surface.Mem = malloc(64); a->surface.Vram = 1; return a; }
static void atlasFree(atlas_t *a) { if (a == NULL) return; rmUnloadTexture(&a->surface); free(a->surface.Mem); free(a); }
static void fntCacheFlushPage(fnt_glyph_cache_entry_t *page) { (void)page; }
static unsigned char builtin[8];
// Stands in for fntReadData: the slow read must happen while the GUI thread can still draw.
static void *fntReadData(char *path, int *bufferSize, int *owned) {
    if (guiReady && guiLocked) FAIL("font file read under the GUI lock");
    *owned = 0;
    if (path == NULL) { *bufferSize = sizeof(builtin); return builtin; }
    *owned = 1; *bufferSize = 32; return malloc(32);
}

static void fntUpdateAspectRatioLocked(void);

@PRODUCTION@

// The splash (GUI thread) has drawn text: the font owns live atlases and a glyph cache page.
static void cacheDrawn(int id) {
    font_t *f = &fonts[id];
    f->atlases[0] = atlasCreate();
    f->glyphCache = calloc(1, sizeof(*f->glyphCache));
    f->glyphCache[0] = calloc(1, sizeof(fnt_glyph_cache_entry_t));
    f->cacheMaxPageID = 0;
}
static void idle(void) { assert(!guiLocked && !fontLocked); }

int main(void) {
    int i, id;
    char themeFont[] = "mass0:/THM/thm_test/font.ttf";
    if (setjmp(failure)) {
        fprintf(stderr, "%s\n", failureText);
        return 3;
    }
    for (i = 0; i < FNT_MAX_COUNT; ++i) // fntInit
        fntInitSlot(&fonts[i]);

    // Pre-GUI: fntInit/lngInit load the default font before guiInit; nothing may wait or assert.
    guiReady = 0;
    assert(fntLoadDefault(NULL) == 0);
    guiReady = 1;

    // Boot: the splash is drawing with font 0 while the IO worker finds the saved theme's fonts.
    cacheDrawn(FNT_DEFAULT);
    id = fntLoadFile(themeFont, 17);
    assert(id != FNT_ERROR); idle();
    assert(fonts[FNT_DEFAULT].atlases[0] == NULL); // the flush really ran
    cacheDrawn(FNT_DEFAULT); cacheDrawn(id);
    fntSetWeight(id, 700); idle();
    cacheDrawn(FNT_DEFAULT);
    fntUpdateAspectRatio(); idle();
    cacheDrawn(FNT_DEFAULT);
    assert(fntLoadDefault(themeFont) == 0); idle();

    // thmFree: fntRelease runs under the caller's GUI lock, after its own rmDiscardFrame.
    cacheDrawn(id);
    guiLock(); rmDiscardFrame();
    fntRelease(id);
    guiUnlock(); idle();
    assert(!fonts[id].isValid);
    assert(unloads > 0 && discards > 0);
    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='font-flush-frame-lock-') as folder:
    folder = Path(folder)
    # The control turns the frame lock back into the bare font lock in the production loaders. Run it
    # first: a fixture that cannot catch the unguarded flush proves nothing about the fixed one.
    before = production.replace('    fntFrameLock();\n', '    fntLock();\n').replace('    fntFrameUnlock();\n', '    fntUnlock();\n')
    before = re.sub(r'^static void fntFrameLock\(void\)\n\{.*?^\}\n', 'static void fntFrameLock(void)\n{\n    fntLock();\n}\n', before, flags=re.M | re.S)
    before = re.sub(r'^static void fntFrameUnlock\(void\)\n\{.*?^\}\n', 'static void fntFrameUnlock(void)\n{\n    fntUnlock();\n}\n', before, flags=re.M | re.S)
    for name, code, expected in [('before', before, 3), ('fixed', production, 0)]:
        c = folder / (name + '.c')
        exe = folder / name
        c.write_text(fixture.replace('@PRODUCTION@', code), encoding='utf-8')
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(c), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        if name == 'before' and 'outside the GUI lock' not in result.stderr:
            print(f'FAIL: the control did not trip on the unguarded flush (exit {result.returncode}):\n{result.stderr}')
            sys.exit(1)
        if result.returncode != expected:
            print(f'FAIL: {name}: exit {result.returncode}, expected {expected}\n{result.stderr}')
            sys.exit(1)
        if name == 'before' and before == production:
            print('FAIL: the font loaders take no fntFrameLock (guiLock + rmDiscardFrame) around their atlas flush')
            sys.exit(1)
print('PASS: font loads flush glyph atlases under the GUI lock after retiring the frame; the file read stays outside it; fntRelease does not re-lock; the before-control is caught')
