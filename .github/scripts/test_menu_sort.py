"""The game-list sort must produce exactly the old order, in O(n log n) comparisons.

submenuSort (src/menusys.c) runs on every list rebuild while Sort Games Alphabetically is on (the
default), and the rows come off the scan in reverse directory order. It used to be a bubble sort:
O(n^2), and worst-case on a library copied in alphabetical order. It is now a stable bottom-up merge
sort with the same comparison, so every row must land exactly where the bubble sort put it.

This compiles submenuItemGetText, submenuSortCompare and submenuSort from src/menusys.c on the host,
next to the removed bubble sort (kept here only as the reference), and checks on random lists --
case-only ties, folders, localized rows and PS1 rows whose game-ID prefix is hidden -- that both give
the same row order with consistent prev links. It then counts comparisons on large lists.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
menusys = (root / 'src/menusys.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/menusys.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


functions = ''.join(function_text(menusys, sig) for sig in (
    'char *submenuItemGetText(',
    'static int submenuSortCompare(',
    'void submenuSort(',
))

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#define MODE_COUNT 4

typedef struct item_list { int mode; } item_list_t;
typedef struct { item_list_t *support; } opl_io_module_t;

typedef struct submenu_item
{
    int icon_id;
    char *text;
    int text_id;
    int id;
    int *cache_id;
    int *cache_uid;
    int favourited;
    int isFolder;
} submenu_item_t;

typedef struct submenu_list
{
    struct submenu_item item;
    struct submenu_list *prev, *next;
} submenu_list_t;

static long comparisons;
static int counting_strcasecmp(const char *a, const char *b)
{
    comparisons++;
    return strcasecmp(a, b);
}
#define strcasecmp counting_strcasecmp

static char *langTable[] = {"Zeta Localized", "alpha localized", "Mid Localized"};
static char *_l(int id) { return langTable[id]; }

static item_list_t lists[MODE_COUNT] = {{0}, {1}, {2}, {3}};
static opl_io_module_t modules[MODE_COUNT] = {{&lists[0]}, {&lists[1]}, {&lists[2]}, {&lists[3]}};
static opl_io_module_t *oplGetModule(int mode) { return &modules[mode]; }

/* PS1 rows are odd ids on mode 1; with the game id hidden they sort past "SLUS_123.45.". */
static int hideId = 1;
static const char *vcdDisplayNameForRow(item_list_t *itemList, int id, const char *text)
{
    if (!hideId || itemList == NULL || itemList->mode != 1 || !(id & 1))
        return text;
    return strlen(text) > 12 && text[4] == '_' && text[8] == '.' && text[11] == '.' ? text + 12 : text;
}

@FUNCTIONS@

/* ---- the removed bubble sort, verbatim apart from its name ---- */
static void swap(submenu_list_t *a, submenu_list_t *b)
{
    submenu_list_t *pa, *nb;
    pa = a->prev;
    nb = b->next;
    a->next = nb;
    b->prev = pa;
    b->next = a;
    a->prev = b;
    if (pa)
        pa->next = b;
    if (nb)
        nb->prev = a;
}

static void refSort(submenu_list_t **submenu, int mode)
{
    submenu_list_t *head;
    int sorted = 0;
    if ((submenu == NULL) || (*submenu == NULL) || ((*submenu)->next == NULL))
        return;
    head = *submenu;
    item_list_t *support = NULL;
    if (mode >= 0 && mode < MODE_COUNT) {
        opl_io_module_t *mod = oplGetModule(mode);
        if (mod != NULL)
            support = mod->support;
    }
    while (!sorted) {
        sorted = 1;
        submenu_list_t *tip = head;
        while (tip->next) {
            submenu_list_t *nxt = tip->next;
            const char *raw1 = submenuItemGetText(&tip->item);
            const char *raw2 = submenuItemGetText(&nxt->item);
            const char *txt1 = tip->item.isFolder ? raw1 : vcdDisplayNameForRow(support, tip->item.id, raw1);
            const char *txt2 = nxt->item.isFolder ? raw2 : vcdDisplayNameForRow(support, nxt->item.id, raw2);
            int cmp;
            if (tip->item.isFolder != nxt->item.isFolder)
                cmp = tip->item.isFolder ? -1 : 1;
            else
                cmp = strcasecmp(txt1, txt2);
            if (cmp > 0) {
                swap(tip, nxt);
                if (tip == head)
                    head = nxt;
                sorted = 0;
            } else {
                tip = tip->next;
            }
        }
    }
    *submenu = head;
}

/* ---- list building ---- */
static unsigned rng = 12345;
static unsigned next_rand(void) { rng = rng * 1103515245u + 12345u; return (rng >> 8) & 0xFFFFFF; }

static const char *words[] = {"abc", "ABC", "Abc", "abd", "zz", "Zz", "b", "B", "", "a b", "a  b",
                              "SLUS_123.45.Crash", "SLES_999.99.crash", "SCUS_000.01.Alpha", "Alpha", "crash"};

/* Build n nodes; node k carries tag k in cache_uid so the two sorts can be compared node for node. */
static submenu_list_t *build(int n, int *tags, int mode, int pattern)
{
    submenu_list_t *head = NULL, *tail = NULL;
    for (int k = 0; k < n; k++) {
        submenu_list_t *s = calloc(1, sizeof(*s));
        char buf[48];
        s->item.cache_uid = &tags[k];
        s->item.id = k;
        s->item.text_id = -1;
        if (pattern == 0) {
            unsigned r = next_rand();
            if (r % 11 == 0)
                s->item.text_id = r % 3;
            else
                s->item.text = strdup(words[r % (sizeof(words) / sizeof(words[0]))]);
            s->item.isFolder = (r >> 5) % 7 == 0;
        } else {
            /* pattern 1: reverse alphabetical (a library copied in order, then prepended by the scan);
               pattern 2: already sorted; pattern 3: random distinct titles */
            int key = pattern == 1 ? n - k : pattern == 2 ? k : (int)(next_rand() % 1000000);
            snprintf(buf, sizeof(buf), "Game %07d", key);
            s->item.text = strdup(buf);
        }
        (void)mode;
        s->prev = tail;
        if (tail)
            tail->next = s;
        else
            head = s;
        tail = s;
    }
    return head;
}

static void destroy(submenu_list_t *s)
{
    while (s) {
        submenu_list_t *n = s->next;
        if (s->item.text_id < 0)
            free(s->item.text);
        free(s);
        s = n;
    }
}

static int check_links(submenu_list_t *head, int n)
{
    int count = 0;
    submenu_list_t *prev = NULL;
    for (submenu_list_t *s = head; s; s = s->next) {
        if (s->prev != prev)
            return 0;
        prev = s;
        count++;
    }
    return count == n;
}

int main(void)
{
    static int tags[4096];
    int failures = 0;

    for (int k = 0; k < 4096; k++)
        tags[k] = k;

    for (int iter = 0; iter < 3000; iter++) {
        int n = iter % 64;
        int mode = iter % 5 - 1; /* -1 = no support resolved, as gui.c passes when userdata is unset */
        hideId = (iter / 5) % 2;
        unsigned seed = rng;
        submenu_list_t *a = build(n, tags, mode, 0);
        rng = seed;
        submenu_list_t *b = build(n, tags, mode, 0);

        refSort(&a, mode);
        submenuSort(&b, mode);

        submenu_list_t *x = a, *y = b;
        for (; x && y; x = x->next, y = y->next)
            if (x->item.cache_uid != y->item.cache_uid)
                break;
        if (x || y || (n > 0 && (!check_links(b, n) || b->prev != NULL))) {
            printf("iteration %d (n=%d mode=%d hideId=%d): order or links differ from the bubble sort\n", iter, n, mode, hideId);
            failures++;
        }
        destroy(a);
        destroy(b);
    }
    printf("3000 random lists (0-63 rows, ties, folders, localized, hidden PS1 ids): %s\n", failures ? "MISMATCH" : "same order as the bubble sort");

    static const char *names[] = {"", "reverse-sorted", "already sorted", "random"};
    for (int pattern = 1; pattern <= 3; pattern++) {
        for (int n = 250; n <= 2000; n *= 2) {
            long old, now;
            submenu_list_t *a = build(n, tags, 0, pattern);
            comparisons = 0;
            refSort(&a, 0);
            old = comparisons;
            destroy(a);
            submenu_list_t *b = build(n, tags, 0, pattern);
            comparisons = 0;
            submenuSort(&b, 0);
            now = comparisons;
            int ok = check_links(b, n);
            for (submenu_list_t *s = b; s && s->next; s = s->next)
                if (strcasecmp(s->item.text, s->next->item.text) > 0)
                    ok = 0;
            destroy(b);
            int lg = 0;
            while ((1 << lg) < n)
                lg++;
            printf("%-15s n=%4d: bubble %8ld comparisons, merge %6ld\n", names[pattern], n, old, now);
            if (!ok || now > (long)n * lg) {
                printf("  FAIL: not sorted, or more than n*ceil(log2 n) comparisons\n");
                failures++;
            }
        }
    }

    return failures ? 1 : 0;
}
'''

if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'menu_sort.c'
        exe = Path(tmp) / ('menu_sort.exe' if sys.platform == 'win32' else 'menu_sort')
        c_file.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        build = subprocess.run(['cc', '-std=gnu99', '-O1', '-Wall', '-Wextra', '-Werror',
                                '-Wno-unused-function', '-Wno-unused-parameter', str(c_file), '-o', str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('harness reported failures (see above)')

if failures:
    for failure in failures:
        print('FAIL:', failure)
    sys.exit(1)
print('menu sort: OK')
