"""Compile the real cache constructor with failing allocations and check cleanup."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/texcache.c").read_text(encoding="utf-8")
start = source.index("image_cache_t *cacheInitCache(")
brace = source.index("{", start)
depth = 0
end = brace
while end < len(source):
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
    if depth == 0:
        break
assert depth == 0
function = source[start:end]
program = r'''
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef struct { int lastUsed, UID; } cache_entry_t;
typedef struct {
    int userId, count;
    char *prefix;
    int isPrefixRelative;
    char *suffix;
    int nextUID, activeRequests;
    cache_entry_t *content;
} image_cache_t;
static void cacheClearItem(cache_entry_t *entry, int freeTxt) {
    (void)freeTxt;
    memset(entry, 0, sizeof(*entry));
    entry->lastUsed = -1;
}
static int calls, failAt, live;
static void *test_malloc(size_t n) {
    ++calls;
    if (failAt == calls) return NULL;
    void *p = malloc(n);
    if (p) live++;
    return p;
}
static void test_free(void *p) {
    if (p) {
        live--;
        free(p);
    }
}
#define malloc test_malloc
#define free test_free
@FUNCTION@
int main(void) {
    for (int n = 1; n <= 4; n++) {
        calls = 0; failAt = n;
        assert(cacheInitCache(4, "mass0:", 1, "COV", 3) == NULL);
        assert(live == 0);
    }
    failAt = 0; calls = 0;
    assert(cacheInitCache(4, "mass0:", 1, NULL, 3) == NULL);
    assert(cacheInitCache(4, "mass0:", 1, "COV", 0) == NULL);
    assert(live == 0 && calls == 0);
    image_cache_t *cache = cacheInitCache(4, "mass0:", 1, "COV", 3);
    assert(cache && cache->count == 3 && cache->nextUID == 1);
    assert(!strcmp(cache->prefix, "mass0:") && !strcmp(cache->suffix, "COV"));
    for (int i = 0; i < 3; i++) assert(cache->content[i].lastUsed == -1);
    free(cache->content);
    free(cache->suffix);
    free(cache->prefix);
    free(cache);
    assert(live == 0);
    puts("PASS: image cache allocation failures preserve memory and permit recovery");
    return 0;
}
'''.replace("@FUNCTION@", function)
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "test.c"
    out = Path(d) / "test"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                    str(src), "-o", str(out)], check=True)
    subprocess.run([str(out)], check=True, timeout=10)
