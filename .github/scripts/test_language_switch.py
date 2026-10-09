"""Exercise the actual language switch function with host runtime stubs."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/lang.c').read_text(encoding='utf-8')
start = source.index('int lngSetGuiValue(int langID)\n{')
function = source[start:source.index('\n}', start) + 2]
harness = r'''
#include <assert.h>
#include <stddef.h>
typedef struct { char *filePath; char *name; } language_t;
static language_t languages[1] = {{"lang_test.lng", "test"}};
static int guiLangID, nLanguages = 1, nValidEntries, frees, themes, muted, loads, fail;
static char *internalEnglish[1], *foreign[1], **lang_strs = internalEnglish;
#define LANG_STR_COUNT 1
void bgmMute(void) { muted++; }
void bgmUnMute(void) { muted--; }
int lngLoadFromFile(char *path, char *name) { loads++; if (fail) return 0; lang_strs = foreign; return 1; }
void lngFreeFromFile(char **strings) { if (guiLangID) { assert(strings == foreign); frees++; } }
int thmGetGuiValue(void) { return 0; }
void thmSetGuiValue(int id, int force) { themes++; }
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
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'language.c').write_text(harness, encoding='utf-8')
    subprocess.run(['cc', str(path / 'language.c'), '-o', str(path / 'language.exe')], check=True)
    subprocess.run([str(path / 'language.exe')], check=True)
print('Language switch controls passed')
