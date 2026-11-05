"""Execute the theme's GameCountText: the number follows the list, not only the selected game.

The element used to rewrite its text only when the selected game's config changed (its uid). A count
that changed under the same selection stayed stale on screen: a cold boot's USB scan landing after the
first frame, the PS1 half of a Mixed view, a rescan adding rows (zackcage6, 2026-11-01). The real
drawGameCountText is compiled here against stubs and driven through those cases.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ("src/gfx/themeelems.cpp" if (ROOT / "src/gfx/themeelems.cpp").exists() else "src/themes.c")
CPP = SOURCE.suffix == ".cpp"
text = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")

match = re.search(r"^static void drawGameCountText\(.*?\n\}\n", text, re.S | re.M)
assert match, "drawGameCountText not found in %s" % SOURCE
draw = match.group(0)
assert "currentCount" in draw, "drawGameCountText no longer compares the count itself"
# The harness starts currentCount at -1 by hand; production gets it from initMutableText. Without that
# the first 0-game frame matches the zeroed field and the element draws an empty string (CodeRabbit).
init = re.search(r"^static mutable_text_t \*initMutableText\(.*?\n\}\n", text, re.S | re.M)
assert init and "currentCount = -1;" in init.group(0), "initMutableText must start currentCount at -1"

if CPP:
    CONFIG = "struct config_set_t { u32 uid_; u32 uid() const { return uid_; } };"
    LIST = "struct item_list_t { int n; };\nstruct GameSource { int count(item_list_t *l) { return l->n; } };\nstatic GameSource gs;\nstatic GameSource *gsOf(item_list_t *) { return &gs; }"
else:
    CONFIG = "typedef struct { u32 uid; } config_set_t;"
    LIST = ("typedef struct item_list_t item_list_t;\nstruct item_list_t { int n; int (*itemGetCount)(item_list_t *); };\n"
            "static int listCount(item_list_t *l) { return l->n; }")

HARNESS = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef unsigned int u32;
@CONFIG@
@LIST@
struct menu_item { void *userdata; };
struct menu_list { struct menu_item *item; };
struct submenu_list { int id; };
struct theme_element {
 void *extended;
 void (*endElem)(struct theme_element *);
 void (*drawElem)(struct menu_list *, struct submenu_list *, config_set_t *, struct theme_element *);
};
typedef struct theme_element theme_element_t;
typedef struct {} theme_t;
typedef struct { char *value; u32 currentConfigId; int currentCount; } mutable_text_t;
#define SIZING_NONE 0
#define _STR_FILE_COUNT 0
static const char *_l(int) { return "Files found: %i"; }
static char drawn[64];
static void endMutableText(struct theme_element *e) { (void)e; }
static int alloc_call, fail_alloc, live_allocs;
static size_t value_alloc_size;
static void *test_malloc(size_t n) { value_alloc_size=n; if (++alloc_call == fail_alloc) return NULL; void *p=malloc(n); if(p)live_allocs++; return p; }
static void *test_calloc(size_t n,size_t size) { if (++alloc_call == fail_alloc) return NULL; void *p=calloc(n,size); if(p)live_allocs++; return p; }
static void test_free(void *p) { if(p){live_allocs--;free(p);} }
#define malloc test_malloc
#define calloc test_calloc
#define free test_free
static void thmDrawElemText(struct theme_element *, int, const char *s, int) { snprintf(drawn, sizeof(drawn), "%s", s); }
@GETCOUNT@
@DRAW@
@INITCOUNT@
int main(void)
{
    char value[60] = "";
    mutable_text_t mt = { value, 0, -1 };
    struct theme_element elem = { &mt, NULL, NULL };
    item_list_t list = @LISTINIT@;
    struct menu_item mi = { &list };
    struct menu_list menu = { &mi };
    config_set_t cfgA = { 1 }, cfgB = { 2 };

    /* cold boot: the first frame draws before the scan has landed */
    list.n = 0;
    drawGameCountText(&menu, NULL, NULL, &elem);
    assert(!strcmp(drawn, "Files found: 0"));
    /* the scan lands, the selection has not moved yet: the number must follow */
    list.n = 37;
    drawGameCountText(&menu, NULL, NULL, &elem);
    assert(!strcmp(drawn, "Files found: 37"));
    /* a config arrives for the same list: unchanged number, nothing breaks */
    drawGameCountText(&menu, NULL, &cfgA, &elem);
    assert(!strcmp(drawn, "Files found: 37"));
    /* the PS1 half of a Mixed view lands under the same selected game */
    list.n = 41;
    drawGameCountText(&menu, NULL, &cfgA, &elem);
    assert(!strcmp(drawn, "Files found: 41"));
    /* a new selection with the same count still refreshes, as before */
    drawGameCountText(&menu, NULL, &cfgB, &elem);
    assert(!strcmp(drawn, "Files found: 41") && mt.currentConfigId == 2);
    /* a rescan drops rows while the config pointer is gone */
    list.n = 40;
    drawGameCountText(&menu, NULL, NULL, &elem);
    assert(!strcmp(drawn, "Files found: 40") && mt.currentConfigId == 2);
    /* Simulate a rescan/return count change; this does not execute the game-return lifecycle. */
    list.n = 0;
    drawGameCountText(&menu, NULL, &cfgB, &elem);
    assert(!strcmp(drawn, "Files found: 0"));
    list.n = 40;
    drawGameCountText(&menu, NULL, &cfgB, &elem);
    assert(!strcmp(drawn, "Files found: 40"));
    /* Exercise the actual initializer, including BOTH allocation failures. */
    for (int failure=1; failure<=3; failure++) {
        struct theme_element fresh = { NULL, NULL, NULL };
        alloc_call=0;fail_alloc=failure;
        initGameCountText(NULL, NULL, NULL, &fresh, NULL);
        if (failure<=2) {
            assert(fresh.extended==NULL && live_allocs==0);
            strcpy(drawn,"unchanged");
            drawGameCountText(&menu,NULL,NULL,&fresh);
            assert(!strcmp(drawn,"unchanged"));
        } else {
            mutable_text_t *m=(mutable_text_t *)fresh.extended;
            assert(m && m->currentCount==-1 && !m->value[0] && live_allocs==2 && value_alloc_size>=60);
            list.n=123456;
            drawGameCountText(&menu,NULL,NULL,&fresh);
            assert(!strcmp(drawn,"Files found: 123456"));
            test_free(m->value);test_free(m);
            assert(!live_allocs);
        }
    }
    puts("PASS: GameCountText follows the list's count, not only the selected game");
    return 0;
}
"""

initcount = re.search(r"^(?:static )?void initGameCountText\(.*?\n\}\n", text, re.S | re.M).group(0)
getcount = re.search(r"^static int getGameCount\(.*?\n\}\n", text, re.S | re.M).group(0)
harness = (HARNESS.replace("@CONFIG@", CONFIG).replace("@LIST@", LIST).replace("@GETCOUNT@", getcount)
           .replace("@DRAW@", draw).replace("@INITCOUNT@", initcount).replace("@LISTINIT@", "{ 0 }" if CPP else "{ 0, listCount }"))
if not CPP:
    harness = harness.replace("static const char *_l(int) {", "static const char *_l(int i) { (void)i;")
    harness = harness.replace("static void thmDrawElemText(struct theme_element *, int, const char *s, int) {",
                              "static void thmDrawElemText(struct theme_element *e, int m, const char *s, int a) { (void)e; (void)m; (void)a;")

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / ("t.cpp" if CPP else "t.c")
    src.write_text(harness, encoding="utf-8")
    exe = Path(tmp) / "t"
    cc = ["g++", "-std=c++17"] if CPP else ["gcc", "-std=c11"]
    subprocess.check_call(cc + ["-Wall", "-Wextra", "-Wno-unused-parameter", "-Werror", "-o", str(exe), str(src)])
    out = subprocess.check_output([str(exe)], text=True)
    sys.stdout.write(out)
