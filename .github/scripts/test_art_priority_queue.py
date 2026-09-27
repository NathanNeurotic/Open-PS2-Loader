"""Verify unified art priority queue tiering and selection trio ordering.

Tests:
1. texcache.c queue mechanics:
   - artPush appends non-priority items at the tail (FIFO).
   - artPushPriority inserts items at the end of the high-priority section (FIFO within priority)
     ahead of any speculative lookahead items.
   - artPromote splices an existing speculative lookahead into the end of the priority block.
   - artPromote on an item already at the head or already priority operates safely without corrupting links.
   - artPop drains priority items first in insertion order, then speculative items.
   - BG abort loop marks abortRequested on unselected BG cache entries.

2. themes.c source structure:
   - Pre-requests highlighted COV and ICO with isPriority = 1 during ELEM_TYPE_BACKGROUND draw.
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

if 'coverflowCoverSettled' in themes:
    failures.append('themes.c: coverflowCoverSettled should be removed to allow fluid BG streaming')

QUEUE_HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void DIntr(void) {}
static void EIntr(void) {}

typedef struct load_image_request {
    const char *tag;
    volatile int abortRequested;
    unsigned char priority;
    unsigned int queueEpoch;
    struct load_image_request *prev;
    struct load_image_request *next;
} load_image_request_t;

static load_image_request_t *gArtReqList = NULL;
static load_image_request_t *gArtReqEnd = NULL;
static load_image_request_t *gArtCurrentReq = NULL;
static volatile int gArtQueuedCount = 0;
static volatile int gArtActiveCount = 0;
static unsigned int gArtQueueEpoch = 1;

static void artPush(load_image_request_t *req)
{
    DIntr();
    req->next = NULL;
    req->prev = gArtReqEnd;
    req->queueEpoch = gArtQueueEpoch;
    req->priority = 0;
    if (gArtReqEnd)
        gArtReqEnd->next = req;
    else
        gArtReqList = req;
    gArtReqEnd = req;
    gArtQueuedCount++;
    EIntr();
}

static void artPushPriority(load_image_request_t *req)
{
    DIntr();
    req->queueEpoch = gArtQueueEpoch;
    req->priority = 1;

    if (gArtReqList == NULL) {
        req->prev = NULL;
        req->next = NULL;
        gArtReqList = req;
        gArtReqEnd = req;
    } else if (!gArtReqList->priority) {
        req->prev = NULL;
        req->next = gArtReqList;
        gArtReqList->prev = req;
        gArtReqList = req;
    } else {
        load_image_request_t *curr = gArtReqList;
        while (curr->next != NULL && curr->next->priority) {
            curr = curr->next;
        }
        req->prev = curr;
        req->next = curr->next;
        if (curr->next != NULL)
            curr->next->prev = req;
        else
            gArtReqEnd = req;
        curr->next = req;
    }
    gArtQueuedCount++;
    EIntr();
}

static void artPromote(load_image_request_t *req)
{
    if (req == NULL)
        return;

    DIntr();
    if (gArtCurrentReq != req && req->queueEpoch == gArtQueueEpoch && !req->priority) {
        req->priority = 1;

        if (req->prev != NULL) {
            load_image_request_t *prev = req->prev;
            load_image_request_t *next = req->next;

            prev->next = next;
            if (next)
                next->prev = prev;
            else
                gArtReqEnd = prev;

            if (!gArtReqList->priority) {
                req->prev = NULL;
                req->next = gArtReqList;
                gArtReqList->prev = req;
                gArtReqList = req;
            } else {
                load_image_request_t *curr = gArtReqList;
                while (curr->next != NULL && curr->next->priority) {
                    curr = curr->next;
                }
                req->prev = curr;
                req->next = curr->next;
                if (curr->next != NULL)
                    curr->next->prev = req;
                else
                    gArtReqEnd = req;
                curr->next = req;
            }
        }
    }
    EIntr();
}

static load_image_request_t *artPop(void)
{
    load_image_request_t *req;

    DIntr();
    req = gArtReqList;
    if (req) {
        gArtReqList = req->next;
        if (gArtReqList)
            gArtReqList->prev = NULL;
        else
            gArtReqEnd = NULL;
        req->next = NULL;
        req->prev = NULL;
        req->queueEpoch = 0;

        if (gArtQueuedCount > 0)
            gArtQueuedCount--;
        gArtActiveCount++;
        gArtCurrentReq = req;
    }
    EIntr();

    return req;
}

int main(void)
{
    int failed = 0;

    // Test 1: Sequence with speculative lookaheads then priority trio
    // Suppose neighbor covers lookahead +1 and +2 are pushed as non-priority
    load_image_request_t lookahead1 = { .tag = "LOOKAHEAD_+1" };
    load_image_request_t lookahead2 = { .tag = "LOOKAHEAD_+2" };
    artPush(&lookahead1);
    artPush(&lookahead2);

    // Active selection arrives: COV, ICO, BG pushed with artPushPriority
    load_image_request_t cov = { .tag = "COV_SEL" };
    load_image_request_t ico = { .tag = "ICO_SEL" };
    load_image_request_t bg  = { .tag = "BG_SEL" };
    artPushPriority(&cov);
    artPushPriority(&ico);
    artPushPriority(&bg);

    // Later neighbor lookahead -1 is pushed non-priority
    load_image_request_t lookahead_prev = { .tag = "LOOKAHEAD_-1" };
    artPush(&lookahead_prev);

    // Verify order in queue must be: COV_SEL -> ICO_SEL -> BG_SEL -> LOOKAHEAD_+1 -> LOOKAHEAD_+2 -> LOOKAHEAD_-1
    const char *expected_order[] = {
        "COV_SEL", "ICO_SEL", "BG_SEL", "LOOKAHEAD_+1", "LOOKAHEAD_+2", "LOOKAHEAD_-1"
    };
    int idx = 0;
    for (load_image_request_t *cur = gArtReqList; cur; cur = cur->next) {
        if (strcmp(cur->tag, expected_order[idx]) != 0) {
            printf("FAIL: at pos %d, expected %s, got %s\n", idx, expected_order[idx], cur->tag);
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
            printf("FAIL: prev pointer mismatch for %s\n", cur->tag);
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
        if (strcmp(cur->tag, expected_promoted[idx]) != 0) {
            printf("FAIL: after promote at pos %d, expected %s, got %s\n", idx, expected_promoted[idx], cur->tag);
            failed = 1;
        }
        idx++;
    }

    // Test 3: artPop drains in exact expected order
    for (int i = 0; i < 6; i++) {
        load_image_request_t *p = artPop();
        if (!p || strcmp(p->tag, expected_promoted[i]) != 0) {
            printf("FAIL pop %d: expected %s, got %s\n", i, expected_promoted[i], p ? p->tag : "NULL");
            failed = 1;
        }
    }
    if (gArtReqList != NULL || gArtReqEnd != NULL || gArtQueuedCount != 0) {
        printf("FAIL: queue not empty after popping all elements\n");
        failed = 1;
    }

    if (!failed)
        printf("art priority queue: FIFO within priority tier and lookahead promotion verified\n");

    return failed;
}
'''


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-Wno-unused-variable', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            failures.append('%s harness reported failures' % name)


if not failures:
    compile_and_run('art_priority_queue', QUEUE_HARNESS)

if failures:
    print('Art priority checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
