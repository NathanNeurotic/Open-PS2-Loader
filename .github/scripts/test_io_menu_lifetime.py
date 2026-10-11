"""Compile real queue-count and submenu-removal routines; check GUI append OOM guard."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
io = (root / "src/ioman.c").read_text(encoding="utf-8")
menu = (root / "src/menusys.c").read_text(encoding="utf-8")
gui = (root / "src/gui.c").read_text(encoding="utf-8")

def body(src, signature):
    pos = src.index(signature)
    brace = src.index("{", pos)
    balance = 0
    for end in range(brace, len(src)):
        balance += (src[end] == "{") - (src[end] == "}")
        if balance == 0:
            return src[pos:end + 1]
    raise AssertionError("unterminated function: " + signature)

queue_fn = body(io, "int ioGetPendingRequestCount(void)")
remove_fn = body(menu, "void submenuRemoveItem(")
destroy_fn = body(menu, "static void submenuDestroyItem(")

assert queue_fn.index("WaitSema(gProcSemaId)") < queue_fn.index("= gReqList;")
append_start = gui.index("case GUI_OP_APPEND_MENU:")
append_end = gui.index("case GUI_OP_SELECT_MENU:", append_start)
append = gui[append_start:append_end]
assert "if (result == NULL)\n                break;" in append
assert append.index("if (result == NULL)") < append.index("->last = result")
assert append.index("if (result == NULL)") < append.index("->current = result")

program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct io_request_t {
    int type;
    void *data;
    struct io_request_t *next;
} io_request_t;
static io_request_t old = {0}, head = {0}, tail = {0};
static io_request_t *gReqList;
static int gProcSemaId = 5, lockHeld = 0, mutateOnLock = 0;
static int WaitSema(int id) {
    assert(id == gProcSemaId && !lockHeld);
    if (mutateOnLock) {
        gReqList = &head;
        head.next = &tail;
        tail.next = NULL;
    }
    lockHeld = 1;
    return 0;
}
static int SignalSema(int id) {
    assert(id == gProcSemaId && lockHeld);
    lockHeld = 0;
    return 0;
}
@QUEUE_FN@
typedef struct submenu_item {
    int id;
    int *cache_id, *cache_uid;
} submenu_item_t;
typedef struct submenu_list {
    struct submenu_list *prev, *next;
    submenu_item_t item;
} submenu_list_t;
@DESTROY_FN@
@REMOVE_FN@
static submenu_list_t *node(int id) {
    submenu_list_t *n = calloc(1, sizeof(*n));
    assert(n);
    n->item.id = id;
    return n;
}
int main(void) {
    gReqList = &old;
    old.next = NULL;
    mutateOnLock = 1;
    assert(ioGetPendingRequestCount() == 2);
    assert(lockHeld == 0);
    mutateOnLock = 0;
    assert(ioGetPendingRequestCount() == 2);
    gReqList = NULL;
    assert(ioGetPendingRequestCount() == 0);

    submenu_list_t *first = node(1), *middle = node(2), *last = node(3);
    first->next = middle; middle->prev = first;
    middle->next = last; last->prev = middle;
    submenu_list_t *list = first;
    submenuRemoveItem(&list, 2);
    assert(list == first && first->next == last && last->prev == first);
    submenuRemoveItem(&list, 1);
    assert(list == last && list->prev == NULL);
    submenuRemoveItem(&list, 3);
    assert(list == NULL);

    first = node(2); middle = node(2); last = node(3);
    first->next = middle; middle->prev = first;
    middle->next = last; last->prev = middle;
    list = first;
    submenuRemoveItem(&list, 2);
    assert(list == last && list->prev == NULL && list->next == NULL);
    submenuRemoveItem(&list, 3);
    assert(list == NULL);
    puts("PASS: queue snapshot is locked; removals preserve backward and forward links");
    return 0;
}
'''.replace("@QUEUE_FN@", queue_fn).replace("@DESTROY_FN@", destroy_fn).replace("@REMOVE_FN@", remove_fn)

with tempfile.TemporaryDirectory() as temp:
    f = Path(temp) / "regression.c"
    exe = Path(temp) / "regression"
    f.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", str(f), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
