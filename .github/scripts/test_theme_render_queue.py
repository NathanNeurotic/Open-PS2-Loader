"""Exercise the production theme publish tail against a retained HIRES upload queue.

gsKit HIRES replays its last queue until a flip replaces it. Inline upload tags
refer to EE texture pixels, so a CPU frame lock alone cannot make those freeable.
This models that ownership contract, not PS2 DMA execution or console acceptance.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
renderer = (root / 'src/renderman.c').read_text(encoding='utf-8').replace('\r\n', '\n')
themes = (root / 'src/themes.c').read_text(encoding='utf-8').replace('\r\n', '\n')
retire = re.search(r'^void rmDiscardFrame\(void\)\n\{.*?^\}', renderer, re.M | re.S).group(0)
load = themes[themes.index('static int thmLoad('):themes.index('static void thmRebuildGuiNames(')]
publish = load[load.rindex('    guiLock();'):load.rindex('    return 0;')]
assert publish.index('rmDiscardFrame();') < publish.index('thmFree(curT);') < publish.index('guiUnlock();')

fixture = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned char u8;
typedef struct { int pixels; } theme_t;
static theme_t *gTheme;
static theme_t *replayed;
static int locked;
static int syncs, flips, frees;
static int loadedFontSize, gFontSize, cfIsAnimating, psbbnFlowStartOffset;
static void *gsGlobal;
static u8 hires;
static jmp_buf failure;
static void guiLock(void) { assert(!locked); locked = 1; }
static void guiUnlock(void) { assert(locked); locked = 0; }
static void gsKit_hires_sync(void *g) { (void)g; assert(locked); ++syncs; }
static void gsKit_hires_flip(void *g) {
    (void)g;
    assert(locked && syncs == flips + 1);
    // The between-frame draw queue is empty. Flip waits for the previous DMA,
    // changes the queue the HIRES worker replays, and resets the old queue.
    replayed = NULL; ++flips;
}
@RETIRE@
static void thmFree(theme_t *old) {
    assert(locked);
    if (old && replayed == old)
        longjmp(failure, 1);
    if (old) ++frees;
}
static void publish(theme_t *curT, theme_t *newT) {
@PUBLISH@
}
static void run(int isHires, int first) {
    theme_t old = {0}, next = {0};
    hires = (u8)isHires; gTheme = first ? NULL : &old;
    replayed = isHires && !first ? &old : NULL;
    locked = 0; syncs = flips = frees = 0;
    publish(gTheme, &next);
    assert(gTheme == &next && !locked && frees == !first);
    assert(syncs == (isHires && !first) && flips == syncs);
}
int main(void) {
    if (setjmp(failure)) {
        fprintf(stderr, "retained HIRES upload references the freed theme\n");
        return 3;
    }
    run(0, 0); run(1, 1); run(1, 0);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='theme-render-queue-') as folder:
    folder = Path(folder)
    for name, tail, expected in [('fixed', publish, 0), ('before', publish.replace('rmDiscardFrame();', '(void)0;'), 3)]:
        # Before control retains the old publish/free sequence while omitting only the fix.
        source = fixture.replace('@RETIRE@', retire).replace('@PUBLISH@', tail)
        if name == 'before':
            source = source.replace('assert(syncs == (isHires && !first) && flips == syncs);', '')
        c = folder / (name + '.c')
        exe = folder / name
        c.write_text(source, encoding='utf-8')
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-variable', str(c), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        assert result.returncode == expected, (name, result.returncode, result.stderr)
print('PASS: old theme retained through HIRES queue retirement; baseline fails, fixed path passes; non-HIRES and first load do not flip')
