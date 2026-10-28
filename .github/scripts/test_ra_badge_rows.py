"""Exercise production badge-row ownership across refreshes and allocation failures."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
menu = (root / "src/menusys.c").read_text()
gui = (root / "src/gui.c").read_text()
opl = (root / "src/opl.c").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("\n}", start) + 2
    return source[start:end]


append = gui[gui.index("        case GUI_OP_APPEND_MENU:"):gui.index("        case GUI_OP_SELECT_MENU:")]
program = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define RETROACHIEVEMENTS 1
enum { GUI_OP_APPEND_MENU = 1 };
typedef struct submenu_item {
    int icon_id, text_id, id, isFolder, lastPlayed, favourited, raBadged;
    char *text, *raText;
    int *cache_id, *cache_uid;
} submenu_item_t;
typedef struct submenu_list {
    submenu_item_t item;
    struct submenu_list *prev, *next;
} submenu_list_t;
typedef struct menu_item {
    submenu_list_t *last, *submenu, *current, *pagestart;
    int remindLast;
} menu_item_t;
struct gui_update_t {
    int type;
    struct { menu_item_t *menu; submenu_list_t **subMenu; } menu;
    struct { int icon_id, id, text_id, isFolder, lastPlayed, favourited, raBadged, selected, autoStart; char *text, *raText; } submenu;
};
struct gui_update_list_t {
    struct gui_update_t *item;
    struct gui_update_list_t *next;
};
static int live, fail, appendFail, gSemaId, depth, gScheduledOps;
static int gRememberLastPlayed, gAutoStartLastPlayed, KeyPressedOnce, DisableCron;
static struct gui_update_list_t *gUpdateList, *gUpdateEnd;
static void *take(size_t n) {
    if (fail) { fail = 0; return NULL; }
    void *p = malloc(n); assert(p); live++; return p;
}
static void drop(void *p) { if (p) { assert(live > 0); live--; free(p); } }
static char *copy(const char *s) { char *p = take(strlen(s)+1); assert(p); strcpy(p,s); return p; }
#define malloc take
#define free drop
static void WaitSema(int s) { (void)s; assert(depth++ == 0); }
static void SignalSema(int s) { (void)s; assert(--depth == 0); }
static char *_l(int id) { (void)id; return "localized"; }
static submenu_list_t *submenuAppendItem(submenu_list_t **head, int icon, char *text, int id, int textid) {
    (void)icon;
    if (appendFail) return NULL;
    submenu_list_t *n = malloc(sizeof(*n)); memset(n,0,sizeof(*n));
    n->item.text = text; n->item.id = id; n->item.text_id = textid;
    *head = n; return n;
}
@DEFER@
@DESTROY@
@GETTEXT@
static void appendOp(struct gui_update_t *item) {
    submenu_list_t *result = NULL;
    switch (item->type) {
@APPEND@
    }
}
static struct gui_update_t *op(menu_item_t *m, submenu_list_t **head) {
    struct gui_update_t *p = malloc(sizeof(*p)); memset(p,0,sizeof(*p));
    p->type = GUI_OP_APPEND_MENU; p->menu.menu = m; p->menu.subMenu = head;
    p->submenu.text = "Crash"; p->submenu.text_id = -1;
    p->submenu.raText = copy("Crash [RA]"); p->submenu.raBadged = 1;
    return p;
}
int main(void) {
    menu_item_t m = {0}; submenu_list_t *head = NULL;
    struct gui_update_t *p = op(&m,&head);
    fail = 1;
    assert(guiDeferUpdate(p) == -1 && depth == 0 && live == 0);
    p = op(&m,&head); appendFail = 1;
    appendOp(p); free(p); assert(head == NULL && live == 0);
    appendFail = 0; p = op(&m,&head);
    appendOp(p); free(p);
    assert(head && !strcmp(head->item.text,"Crash"));
    assert(!strcmp(submenuItemGetText(&head->item),"Crash [RA]"));
    /* Freeing the producer's operation/cache cannot invalidate the row snapshot. */
    assert(live == 2);
    submenuDestroyItem(head); assert(live == 0);
    /* Failure to copy decoration leaves a usable, unmodified identity. */
    p = op(&m,&head); free(p->submenu.raText); p->submenu.raText = NULL;
    appendOp(p); free(p);
    assert(!strcmp(submenuItemGetText(&head->item),"Crash"));
    submenuDestroyItem(head); assert(live == 0);
    puts("PASS: badge snapshots preserve identity and survive producer cleanup; allocation failures release ownership");
}
'''
program = program.replace("@DEFER@", function(gui, "int guiDeferUpdate("))
program = program.replace("@DESTROY@", function(menu, "static void submenuDestroyItem("))
program = program.replace("@GETTEXT@", function(menu, "char *submenuItemGetText("))
program = program.replace("@APPEND@", append)

# The producer must copy only the cosmetic label; source identity stays unchanged.
assert "gup->submenu.raText = badge != NULL ? strdup(badge) : NULL;" in opl
assert "gup->submenu.text = (char *)(badge" not in opl
assert "gRATelemetry != previousRATelemetry || gRABadges != previousRABadges" in gui
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "rows.c"
    exe = Path(tmp) / "rows"
    c.write_text(program)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
