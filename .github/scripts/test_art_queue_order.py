"""Pin the art queue order that issue #772 depends on.

#770 replaced "the newest priority request goes to the FRONT" with a FIFO priority tier and stopped
promoting a request that was already priority. While scrolling Coverflow, every cover passed stays
on screen as a neighbour and keeps its priority request alive, so the cover actually SELECTED ended
up behind all of them -- zack's "covers pop in late while scrolling" (#772). #773 restored the old
order; this test keeps it restored.

Also pins the BG half of the same report. The "latest selection wins" abort for per-game
backgrounds used to be guarded by `cache->count == 1`, but initMutableImage floors EVERY per-game
art cache at 2 slots, so that guard made the abort dead code: an abandoned background's decode kept
running in front of the next cover. The abort now lives in cacheAbortOtherBackgrounds, which scans
every slot, and is tested here with a real 2-slot cache.

Everything below is compiled from the production source text of src/texcache.c, not a copy.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


texcache = read('src/texcache.c')
themes = read('src/themes.c')

# --- The cache floor that makes a `count == 1` guard dead code ---------------------------------
if not re.search(r'if \(cachePattern != NULL && cacheCount < 2\)\s*\n\s*cacheCount = 2;', themes):
    failures.append('themes.c: per-game art caches are no longer floored at 2 slots -- re-check '
                    'whether cacheAbortOtherBackgrounds still needs to scan every slot')

# --- The BG abort must be the tested helper, called for BG caches whatever their size ----------
if re.search(r'cache->count\s*==\s*1\s*&&\s*cache->suffix', texcache):
    failures.append('texcache.c: the BG abort is guarded by cache->count == 1 again -- BG caches '
                    'have at least 2 slots, so it would never fire')
if not re.search(r'strcmp\(cache->suffix, "BG"\) == 0\)\s*\n\s*cacheAbortOtherBackgrounds\(cache, value\);',
                 texcache):
    failures.append('texcache.c: cacheGetTextureEx no longer calls cacheAbortOtherBackgrounds for '
                    'BG caches')

# --- Coverflow still holds a new background until its cover has had its turn -----------------
if 'coverflowCoverSettled' not in themes or \
        'texture = getGameImageCached(gameImage->cache, &item->item);' not in themes:
    failures.append('themes.c: the Coverflow background gate (coverflowCoverSettled) is gone -- a '
                    'full-screen BG read would start ahead of the carousel covers again (#772)')
if re.search(r'texture = getGameImageTextureEx\(gameImage->cache, menu->item->userdata, &item->item, 1\);\s*\n\s*\} else \{',
             themes):
    failures.append('themes.c: the per-game background is requested as a PRIORITY image again (#772)')

functions = ''.join(function_text(texcache, 'src/texcache.c', sig) for sig in (
    'static void artPush(',
    'static void artPushFront(',
    'static void artPromote(',
    'static load_image_request_t *artPop(',
    'static void cacheAbortOtherBackgrounds(',
))

HARNESS = r'''
#include <stdio.h>
#include <string.h>

static void DIntr(void) {}
static void EIntr(void) {}

typedef struct load_image_request {
    struct load_image_request *next;
    struct load_image_request *prev;
    unsigned int queueEpoch;
    volatile int abortRequested;
    unsigned char sio2;
    char *value;
} load_image_request_t;

typedef struct {
    void *qr;
    char key[64];
} cache_entry_t;

typedef struct {
    int count;
    cache_entry_t *content;
} image_cache_t;

static load_image_request_t *gArtReqList = NULL;
static load_image_request_t *gArtReqEnd = NULL;
static load_image_request_t *volatile gArtCurrentReq = NULL;
static volatile int gArtQueuedCount = 0;
static volatile int gArtActiveCount = 0;
static unsigned int gArtQueueEpoch = 1;
static volatile int gArtNavActive = 0;

@FUNCTIONS@

static int failed = 0;

static void expectOrder(const char *what, const char **want, int n)
{
    int i = 0;
    load_image_request_t *prev = NULL, *cur;

    for (cur = gArtReqList; cur; cur = cur->next, i++) {
        if (i >= n || strcmp(cur->value, want[i]) != 0) {
            printf("FAIL %s: position %d is %s, expected %s\n", what, i, cur->value, i < n ? want[i] : "(end)");
            failed = 1;
            return;
        }
        if (cur->prev != prev) {
            printf("FAIL %s: prev link broken at %s\n", what, cur->value);
            failed = 1;
        }
        prev = cur;
    }
    if (i != n) {
        printf("FAIL %s: %d queued, expected %d\n", what, i, n);
        failed = 1;
    }
    if (gArtReqEnd != prev) {
        printf("FAIL %s: tail pointer does not match the last request\n", what);
        failed = 1;
    }
}

static void drain(void)
{
    while (artPop() != NULL)
        gArtCurrentReq = NULL;
    gArtActiveCount = 0;
}

int main(void)
{
    // 1. Scrolling Coverflow A -> B -> C -> D. Each newly selected cover is a priority request. The
    //    ones already passed stay queued (they are still on screen as neighbours). The cover the user
    //    is LOOKING AT must be read first -- under #770's FIFO tier it was read last.
    load_image_request_t a = {.value = "COV_A"}, b = {.value = "COV_B"};
    load_image_request_t c = {.value = "COV_C"}, d = {.value = "COV_D"};
    artPushFront(&a);
    artPushFront(&b);
    artPushFront(&c);
    artPushFront(&d);
    {
        const char *want[] = {"COV_D", "COV_C", "COV_B", "COV_A"};
        expectOrder("scroll A->D", want, 4);
    }
    load_image_request_t *first = artPop();
    if (first != &d) {
        printf("FAIL scroll A->D: the selected cover (COV_D) must be read first, got %s\n", first ? first->value : "NULL");
        failed = 1;
    }
    gArtCurrentReq = NULL;
    drain();

    // 2. A neighbour already warming at the back of the queue becomes the selection: promote moves
    //    it to the front in one splice, and the tail pointer follows when it was the tail.
    load_image_request_t n1 = {.value = "NEIGHBOUR_1"}, n2 = {.value = "NEIGHBOUR_2"};
    load_image_request_t n3 = {.value = "NEIGHBOUR_3"};
    artPush(&n1);
    artPush(&n2);
    artPush(&n3);
    artPromote(&n3);
    {
        const char *want[] = {"NEIGHBOUR_3", "NEIGHBOUR_1", "NEIGHBOUR_2"};
        expectOrder("promote the tail", want, 3);
    }
    artPromote(&n1); // from the middle
    {
        const char *want[] = {"NEIGHBOUR_1", "NEIGHBOUR_3", "NEIGHBOUR_2"};
        expectOrder("promote the middle", want, 3);
    }
    artPromote(&n1); // already at the head: no-op
    {
        const char *want[] = {"NEIGHBOUR_1", "NEIGHBOUR_3", "NEIGHBOUR_2"};
        expectOrder("promote the head", want, 3);
    }
    drain();

    // 3. The request the worker is executing is never spliced back into the queue.
    load_image_request_t run = {.value = "RUNNING"}, q1 = {.value = "QUEUED"};
    artPush(&run);
    artPush(&q1);
    if (artPop() != &run) {
        printf("FAIL running: expected RUNNING to pop first\n");
        failed = 1;
    }
    artPromote(&run);
    {
        const char *want[] = {"QUEUED"};
        expectOrder("promote the running request", want, 1);
    }
    gArtCurrentReq = NULL;
    drain();

    // 4. SIO2 defer (#340): an SIO2 head is not started while a direction is held.
    load_image_request_t sio2 = {.value = "SIO2_COVER", .sio2 = 1};
    artPushFront(&sio2);
    gArtNavActive = 1;
    if (artPop() != NULL) {
        printf("FAIL sio2: an SIO2 cover must not start while a direction is held\n");
        failed = 1;
    }
    gArtNavActive = 0;
    if (artPop() != &sio2) {
        printf("FAIL sio2: the deferred SIO2 cover must start once navigation stops\n");
        failed = 1;
    }
    gArtCurrentReq = NULL;
    drain();

    // 5. Latest background wins, in a real 2-slot cache (the floor initMutableImage applies). A
    //    background still pending for another game is aborted; the one for the game now selected, an
    //    idle slot, and a slot with no key are left alone.
    load_image_request_t oldBg = {.value = "OLD_GAME"}, newBg = {.value = "NEW_GAME"};
    cache_entry_t slots[2];
    image_cache_t bg = {2, slots};
    memset(slots, 0, sizeof(slots));
    slots[0].qr = &oldBg;
    strcpy(slots[0].key, "OLD_GAME");
    slots[1].qr = &newBg;
    strcpy(slots[1].key, "NEW_GAME");
    cacheAbortOtherBackgrounds(&bg, "NEW_GAME");
    if (!oldBg.abortRequested) {
        printf("FAIL bg: the abandoned background (slot 0 of 2) was not aborted\n");
        failed = 1;
    }
    if (newBg.abortRequested) {
        printf("FAIL bg: the selected game's own background was aborted\n");
        failed = 1;
    }
    oldBg.abortRequested = 0;
    slots[1].qr = NULL; // idle slot
    slots[0].key[0] = '\0'; // pending request with no reunion key: nothing to compare, leave it
    cacheAbortOtherBackgrounds(&bg, "NEW_GAME");
    if (oldBg.abortRequested) {
        printf("FAIL bg: a request without a key must not be aborted\n");
        failed = 1;
    }

    if (!failed)
        printf("art queue order: selected cover first, promote-to-front, SIO2 defer and latest-background-wins verified\n");
    return failed;
}
'''


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            failures.append('%s harness reported failures' % name)


if not failures:
    compile_and_run('art_queue_order', HARNESS.replace('@FUNCTIONS@', functions))

if failures:
    print('Art queue order checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
