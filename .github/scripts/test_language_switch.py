"""Exercise the actual language switch function with host runtime stubs."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/lang.c').read_text(encoding='utf-8')


def extract(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


# The real lock helpers, the switch and its locking wrapper.
function = '\n'.join(extract(s) for s in ('static void lngSwitchLock(void)\n{', 'static void lngSwitchUnlock(void)\n{',
                                          'static int lngSetGuiValueLocked(int langID)\n{',
                                          'int lngSetGuiValue(int langID)\n{'))
harness = r'''
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
typedef struct { char *filePath; char *name; } language_t;
static language_t languages[1] = {{"lang_test.lng", "test"}};
static int guiLangID, nLanguages = 1, nValidEntries, frees, themes, muted, loads, fail, guiLockDepth;
static char *internalEnglish[1], *foreign[1], **lang_strs = internalEnglish;
#define LANG_STR_COUNT 1
/* The language switch lock (lngSwitchSema): one switch at a time, held from the old table to the id commit and
   across the theme reload (lock order: language, theme, GUI). It is not recursive. */
static int lngSwitchSema = 5, switchDepth;
void WaitSema(int id) { assert(id == lngSwitchSema && switchDepth == 0); switchDepth++; }
void SignalSema(int id) { assert(id == lngSwitchSema && switchDepth == 1); switchDepth--; }
/* The IO worker may replace the registry's path meanwhile: it is copied under the GUI lock, and the
   file is read with the lock released (the lock is not recursive). */
void guiLock(void) { assert(guiLockDepth == 0); guiLockDepth++; }
void guiUnlock(void) { assert(guiLockDepth == 1); guiLockDepth--; }
void bgmMute(void) { muted++; }
void bgmUnMute(void) { muted--; }
int lngLoadFromFile(char *path, char *name)
{
    assert(guiLockDepth == 0 && switchDepth == 1);
    assert(path != languages[0].filePath && strcmp(path, languages[0].filePath) == 0);
    assert(name == languages[0].name);
    loads++;
    if (fail)
        return 0;
    lang_strs = foreign;
    return 1;
}
void lngFreeFromFile(char **strings) { if (guiLangID) { assert(strings == foreign); frees++; } }
/* The theme reload reads the selected theme id under the theme switch lock itself. */
int thmReload(void) { assert(switchDepth == 1 && guiLockDepth == 0); themes++; return 1; }
void fntLoadDefault(void *path) {}
'''
harness += function + r'''
int main(void) {
    assert(lngSetGuiValue(0) == 0);
    assert(lngSetGuiValue(1) == 1 && guiLangID == 1);
    assert(lngSetGuiValue(1) == 0 && loads == 1);
    assert(lngSetGuiValue(0) == 1 && guiLangID == 0);
    assert(frees == 1 && lang_strs == internalEnglish && themes == 2);
    assert(lngSetGuiValue(-1) == 0 && lngSetGuiValue(2) == 0);
    fail = 1;
    assert(lngSetGuiValue(1) == 1 && guiLangID == 0 && muted == 0);
    assert(switchDepth == 0 && guiLockDepth == 0);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'language.c').write_text(harness, encoding='utf-8')
    subprocess.run(['cc', str(path / 'language.c'), '-o', str(path / 'language.exe')], check=True)
    subprocess.run([str(path / 'language.exe')], check=True)
print('Language switch controls passed')
