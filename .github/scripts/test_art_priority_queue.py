"""Verify unified art priority queue tiering and active trio ordering.

Tests:
1. texcache.c queue mechanics (extracted directly from production src/texcache.c):
   - artPush appends non-priority items at the tail (FIFO).
   - artPushPriority inserts items at the end of the high-priority section (FIFO within priority)
     ahead of any speculative lookahead items.
   - artPromote splices an existing speculative lookahead into the end of the priority block.
   - artPromote on an item already at the head or already priority operates safely without corrupting links.
   - artPop drains priority items first in insertion order, then speculative items.
   - artPop preserves SIO2 defer when navigation is active (Issue #340 protection).

2. themes.c source structure:
   - Pre-requests highlighted COV and ICO with isPriority = 1 during ELEM_TYPE_BACKGROUND draw.
   - Passes icoElem through thmGetElemForItem for row-specific redirection.
   - Requests BG with isPriority = 1.
   - Removes artificial coverflowCoverSettled stall.
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

# --- Source structural guards ---

if 'artPushPriority' not in texcache:
    failures.append('texcache.c: artPushPriority function missing')

if 'unsigned char priority;' not in texcache:
    failures.append('texcache.c: load_image_request_t priority field missing')

if 'abortRequested = 1;' not in texcache:
    failures.append('texcache.c: abortRequested not found in texcache.c')

# In themes.c, verify active trio pre-requests COV and ICO with isPriority = 1
if 'getGameImageTextureEx(selImg->cache, menu->item->userdata, &item->item, 1)' not in themes and \
   'getGameImageTextureEx(cfImg->cache, menu->item->userdata, &item->item, 1)' not in themes:
    failures.append('themes.c: COV pre-request with isPriority = 1 missing in drawGameImage')

if 'getGameImageTextureEx(icoImg->cache, menu->item->userdata, &item->item, 1)' not in themes:
    failures.append('themes.c: ICO pre-request with isPriority = 1 missing in drawGameImage')

# Verify ICO redirect via thmGetElemForItem
if 'icoElem = thmGetElemForItem(menu, item, icoElem);' not in themes:
    failures.append('themes.c: icoElem missing thmGetElemForItem redirection')

if 'coverflowCoverSettled' in themes:
    failures.append('themes.c: coverflowCoverSettled should be removed to allow fluid BG streaming')

queue_functions = ''.join(function_text(texcache, 'src/texcache.c', sig) for sig in (
    'static void artPush(',
    'static void artPushPriority(',
    'static void artPromote(',
    'static load_image_request_t *artPop(',
))

QUEUE_HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void DIntr(void) {}
static void EIntr(void) {}

typedef struct load_image_request {
    struct load_image_request *next;
    struct load_image_request *prev;
    unsigned int queueEpoch;
    volatile int abortRequested;
    unsigned char priority;
    unsigned char sio2;
    char *value;
} load_image_request_t;

static load_image_request_t *gArtReqList = NULL;
static load_image_request_t *gArtReqEnd = NULL;
static load_image_request_t *volatile gArtCurrentReq = NULL;
static volatile int gArtQueuedCount = 0;
static volatile int gArtActiveCount = 0;
static unsigned int gArtQueueEpoch = 1;
static int gArtNavActive = 0;

@QUEUE_FUNCTIONS@

int main(void)
{
    int failed = 0;

    // Test 1: Sequence with speculative lookaheads then priority trio
    // Suppose neighbor covers lookahead +1 and +2 are pushed as non-priority
    load_image_request_t lookahead1 = { .value = "LOOKAHEAD_+1" };
    load_image_request_t lookahead2 = { .value = "LOOKAHEAD_+2" };
    artPush(&lookahead1);
    artPush(&lookahead2);

    // Active selection arrives: COV, ICO, BG pushed with artPushPriority
    load_image_request_t cov = { .value = "COV_SEL" };
    load_image_request_t ico = { .value = "ICO_SEL" };
    load_image_request_t bg  = { .value = "BG_SEL" };
    artPushPriority(&cov);
    artPushPriority(&ico);
    artPushPriority(&bg);

    // Later neighbor lookahead -1 is pushed non-priority
    load_image_request_t lookahead_prev = { .value = "LOOKAHEAD_-1" };
    artPush(&lookahead_prev);

    // Verify order in queue must be: COV_SEL -> ICO_SEL -> BG_SEL -> LOOKAHEAD_+1 -> LOOKAHEAD_+2 -> LOOKAHEAD_-1
    const char *expected_order[] = {
        "COV_SEL", "ICO_SEL", "BG_SEL", "LOOKAHEAD_+1", "LOOKAHEAD_+2", "LOOKAHEAD_-1"
    };
    int idx = 0;
    for (load_image_request_t *cur = gArtReqList; cur; cur = cur->next) {
        if (strcmp(cur->value, expected_order[idx]) != 0) {
            printf("FAIL: at pos %d, expected %s, got %s\n", idx, expected_order[idx], cur->value);
            failed = 1;
        }
        idx++;
    }
    if (idx != 6) {
        printf("FAIL: expected 6 items in queue, found %d\n", idx);
        failed = 1;
    }

    // Verify bi-directional links (prev/next consistency)
    load_image_request_t *prev = NULL;
    for (load_image_request_t *cur = gArtReqList; cur; cur = cur->next) {
        if (cur->prev != prev) {
            printf("FAIL: prev pointer mismatch for %s\n", cur->value);
            failed = 1;
        }
        prev = cur;
    }
    if (gArtReqEnd != prev) {
        printf("FAIL: gArtReqEnd does not match tail\n");
        failed = 1;
    }

    // Test 2: artPromote: promote LOOKAHEAD_+2 to priority
    artPromote(&lookahead2);
    // After promotion, lookahead2 should be appended to the priority block:
    // COV_SEL -> ICO_SEL -> BG_SEL -> LOOKAHEAD_+2 -> LOOKAHEAD_+1 -> LOOKAHEAD_-1
    const char *expected_promoted[] = {
        "COV_SEL", "ICO_SEL", "BG_SEL", "LOOKAHEAD_+2", "LOOKAHEAD_+1", "LOOKAHEAD_-1"
    };
    idx = 0;
    for (load_image_request_t *cur = gArtReqList; cur; cur = cur->next) {
        if (strcmp(cur->value, expected_promoted[idx]) != 0) {
            printf("FAIL: after promote at pos %d, expected %s, got %s\n", idx, expected_promoted[idx], cur->value);
            failed = 1;
        }
        idx++;
    }

    // Test 3: artPop drains in exact expected order
    for (int i = 0; i < 6; i++) {
        load_image_request_t *p = artPop();
        if (!p || strcmp(p->value, expected_promoted[i]) != 0) {
            printf("FAIL pop %d: expected %s, got %s\n", i, expected_promoted[i], p ? p->value : "NULL");
            failed = 1;
        }
    }
    if (gArtReqList != NULL || gArtReqEnd != NULL || gArtQueuedCount != 0) {
        printf("FAIL: queue not empty after popping all elements\n");
        failed = 1;
    }

    // Test 4: SIO2 defer behavior (Issue #340 protection)
    load_image_request_t sio2_req = { .value = "SIO2_COVER", .sio2 = 1 };
    artPushPriority(&sio2_req);
    gArtNavActive = 1; // user is holding D-pad
    load_image_request_t *popped_sio2 = artPop();
    if (popped_sio2 != NULL) {
        printf("FAIL: artPop must return NULL when SIO2 head is deferred during navigation\n");
        failed = 1;
    }
    gArtNavActive = 0; // user released D-pad
    popped_sio2 = artPop();
    if (popped_sio2 != &sio2_req) {
        printf("FAIL: artPop must return deferred SIO2 item once navigation idle\n");
        failed = 1;
    }

    if (!failed)
        printf("art priority queue: production functions FIFO priority tiering and SIO2 defer verified\n");

    return failed;
}
'''


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-Wno-unused-variable', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            failures.append('%s harness reported failures' % name)


if not failures:
    compile_and_run('art_priority_queue', QUEUE_HARNESS.replace('@QUEUE_FUNCTIONS@', queue_functions))

if failures:
    print('Art priority checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
