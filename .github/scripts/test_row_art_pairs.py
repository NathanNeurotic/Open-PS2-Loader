"""Compile the real cacheRowPairsReady and drive it through theme view switches (RiptOPL #211)."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/texcache.c").read_text(encoding="utf-8")

def function(signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError(signature)

program = r"""
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int allocCount, failAt, live;
static void *trackedMalloc(size_t n) {
    ++allocCount;
    if (failAt && allocCount == failAt) return NULL;
    void *ptr = malloc(n);
    if (ptr) live++;
    return ptr;
}
static void trackedFree(void *ptr) {
    if (ptr) {
        assert(live > 0);
        live--;
        free(ptr);
    }
}
#define malloc trackedMalloc
#define free trackedFree
@FUNCTION@
static void startFail(int at) { allocCount = 0; failAt = at; }
static void allIs(const int *a, int n, int v) { for (int i = 0; i < n; i++) assert(a[i] == v); }
int main(void) {
    int *ids = NULL, *uids = NULL, capacity = 0;
    unsigned int gen = 0;

    // First draw in List (3 caches, load 1) allocates and resets both arrays.
    startFail(0);
    assert(cacheRowPairsReady(&ids, &uids, &capacity, &gen, 3, 1));
    assert(ids && uids && capacity == 3 && gen == 1 && live == 2);
    allIs(ids, 3, -1);
    allIs(uids, 3, -1);

    // Same load: pairs the cache filled in are kept, nothing is allocated.
    ids[1] = 4;
    uids[1] = 9;
    startFail(1);
    assert(cacheRowPairsReady(&ids, &uids, &capacity, &gen, 3, 1));
    assert(allocCount == 0 && ids[1] == 4 && uids[1] == 9);

    // Switch to Grid (6 caches, load 2) while out of memory: both allocation points fail,
    // the row keeps its old pairs and stays stamped stale, so callers never index past 3.
    for (int n = 1; n <= 2; n++) {
        int *oldIds = ids, *oldUids = uids;
        startFail(n);
        assert(!cacheRowPairsReady(&ids, &uids, &capacity, &gen, 6, 2));
        assert(ids == oldIds && uids == oldUids && capacity == 3 && gen == 1 && live == 2);
        assert(ids[1] == 4 && uids[1] == 9);
    }

    // Grid with memory: grows to 6 and drops every pair of the old load.
    startFail(0);
    assert(cacheRowPairsReady(&ids, &uids, &capacity, &gen, 6, 2));
    assert(capacity == 6 && gen == 2 && live == 2);
    allIs(ids, 6, -1);
    allIs(uids, 6, -1);

    // Back to List (3 caches, load 3): no allocation, the bigger arrays are reused and reset.
    ids[5] = 2;
    uids[0] = 7;
    startFail(1);
    assert(cacheRowPairsReady(&ids, &uids, &capacity, &gen, 3, 3));
    assert(allocCount == 0 && capacity == 6 && gen == 3);
    allIs(ids, 6, -1);
    allIs(uids, 6, -1);

    // A theme with no cover caches has nothing to hand out.
    startFail(0);
    assert(!cacheRowPairsReady(&ids, &uids, &capacity, &gen, 0, 4));

    // A row whose arrays were dropped earlier (NULL) is rebuilt even in the same load.
    free(ids);
    free(uids);
    ids = uids = NULL;
    capacity = 0;
    assert(cacheRowPairsReady(&ids, &uids, &capacity, &gen, 3, 3));
    assert(ids && uids && capacity == 3 && live == 2);

    free(ids);
    free(uids);
    assert(live == 0);
    puts("PASS: row art pairs reset per theme load, grow, survive OOM and are reused in one load");
    return 0;
}
""".replace("@FUNCTION@", function("int cacheRowPairsReady("))
with tempfile.TemporaryDirectory() as tmp:
    source_file = Path(tmp) / "test.c"
    exe = Path(tmp) / "test"
    source_file.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-parameter", str(source_file), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)
