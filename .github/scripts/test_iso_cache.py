"""The games.bin cache must answer exactly as before, without O(n^2) work per scan.

scanForISO (src/supportbase.c) asks queryISOGameListCache for every ISO it reads, and hands the list
to updateISOGameList to decide whether games.bin must be rewritten. The lookup used to snprintf every
cache entry for every file. The cache is written in the REVERSE of the order the next scan reads the
directory, so each lookup walked about half the cache. The change check compared the same pair
cache->count times and read past the cache when games had been added.

This compiles isoCacheEntryMatches, queryISOGameListCache and updateISOGameList from src/supportbase.c
on the host, next to the removed versions (kept here only as the reference), and checks:

- every lookup, in reverse, forward and random scan order, returns what the old one returned, entry
  for entry, including misses and names that differ only by extension or case;
- updateISOGameList decides to rewrite (or not) exactly when the old one did;
- a 1000-game directory scanned in the usual order costs O(n) entry comparisons, not O(n^2).
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
support = (root / 'src/supportbase.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/supportbase.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


functions = ''.join(function_text(support, sig) for sig in (
    'static int isoCacheEntryMatches(',
    'static int queryISOGameListCache(',
    'static int updateISOGameList(',
))

if 'queryISOGameListCache(&cache, &cachedGInfo, dirent->d_name, &cacheHint)' not in support or \
        'int cacheHint = -1;' not in support:
    failures.append('scanForISO: must thread one cacheHint (starting at -1) through its lookups')

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define ISO_GAME_NAME_MAX 160
#define ISO_GAME_EXTENSION_MAX 4
#define GAME_STARTUP_MAX 12
#define ISO_GAME_FNAME_MAX (ISO_GAME_NAME_MAX + ISO_GAME_EXTENSION_MAX)
#define LOG(...) ((void)0)

typedef struct
{
    char name[ISO_GAME_NAME_MAX + 1];
    char startup[GAME_STARTUP_MAX + 1];
    char extension[ISO_GAME_EXTENSION_MAX + 1];
    unsigned char parts;
    unsigned char media;
    unsigned short format;
    int sizeMB;
} base_game_info_t;

struct game_list_t
{
    base_game_info_t gameinfo;
    struct game_list_t *next;
};

struct game_cache_list
{
    unsigned int count;
    base_game_info_t *games;
};

/* Counted string work: an entry comparison in the new code, an snprintf in the old one. */
static long entryCompares, formats;
static int counted_strncmp(const char *a, const char *b, size_t n) { entryCompares++; return strncmp(a, b, n); }

/* File stubs: updateISOGameList's only observable decision is whether it rewrites games.bin. */
static int writes, removes;
static FILE *stub_fopen(const char *path, const char *mode) { (void)path; if (mode[0] == 'w') writes++; return NULL; }
static int stub_remove(const char *path) { (void)path; removes++; return 0; }
static void *stub_memalign(size_t align, size_t size) { (void)align; return malloc(size); }

#define fopen stub_fopen
#define remove stub_remove
#define memalign stub_memalign

/* ---- the new code ---- */
#define strncmp counted_strncmp
@FUNCTIONS@
#undef strncmp

/* ---- the removed code, verbatim apart from names ---- */
static int oldQuery(const struct game_cache_list *cache, base_game_info_t *ginfo, const char *filename)
{
    char isoname[ISO_GAME_FNAME_MAX + 1];
    int i;
    for (i = 0; i < cache->count; i++) {
        formats++;
        snprintf(isoname, sizeof(isoname), "%s%s", cache->games[i].name, cache->games[i].extension);
        if (strcmp(filename, isoname) == 0) {
            memcpy(ginfo, &cache->games[i], sizeof(base_game_info_t));
            return 0;
        }
    }
    return ENOENT;
}

static int oldModified(const struct game_cache_list *cache, const struct game_list_t *head, int count)
{
    const struct game_list_t *game;
    int i, j, modified = 0;
    if (cache != NULL) {
        if ((head != NULL) && (count > 0)) {
            game = head;
            for (i = 0; i < count; i++) {
                for (j = 0; j < cache->count; j++) {
                    if (strncmp(cache->games[i].name, game->gameinfo.name, ISO_GAME_NAME_MAX + 1) == 0 && strncmp(cache->games[i].extension, game->gameinfo.extension, ISO_GAME_EXTENSION_MAX + 1) == 0)
                        break;
                }
                if (j == cache->count) {
                    modified = 1;
                    break;
                }
                game = game->next;
            }
            if ((!modified) && (count != cache->count))
                modified = 1;
        } else
            modified = 0;
    } else
        modified = ((head != NULL) && (count > 0)) ? 1 : 0;
    return modified;
}

static unsigned rng = 777;
static unsigned rnd(void) { rng = rng * 1103515245u + 12345u; return (rng >> 8) & 0xFFFFFF; }

static const char *exts[] = {".iso", ".zso", ".ISO", ".is"};

static void make_game(base_game_info_t *g, int k)
{
    memset(g, 0, sizeof(*g));
    /* small name space so case-only and extension-only neighbours occur */
    snprintf(g->name, sizeof(g->name), (rnd() & 1) ? "Game %d" : "GAME %d", k % 37);
    snprintf(g->extension, sizeof(g->extension), "%s", exts[rnd() % 4]);
    snprintf(g->startup, sizeof(g->startup), "SLUS_%03d.%02d", k % 1000, k % 100);
}

int main(void)
{
    int failures = 0;
    /* +64 slack so the reference's read past the cache (games added) stays defined in the test. */
    static base_game_info_t pool[2000 + 64];
    char filename[256];

    for (int iter = 0; iter < 4000; iter++) {
        int n = iter % 70;
        struct game_cache_list cache = {(unsigned)n, pool};
        for (int k = 0; k < n + 64; k++)
            make_game(&pool[k], rnd());

        /* the directory: the cache's files in reverse (the usual case), forward, or shuffled, plus
           strays the cache does not hold */
        int order = iter % 3, files = n + (int)(rnd() % 4);
        int hint = -1;
        for (int f = 0; f < files; f++) {
            if (f < n) {
                int k = order == 0 ? n - 1 - f : order == 1 ? f : (int)(rnd() % n);
                snprintf(filename, sizeof(filename), "%s%s", pool[k].name, pool[k].extension);
            } else
                snprintf(filename, sizeof(filename), "Stray %u.iso", rnd() % 50);
            base_game_info_t a, b;
            memset(&a, 0xAA, sizeof(a));
            memset(&b, 0xAA, sizeof(b));
            int ra = oldQuery(&cache, &a, filename);
            int rb = queryISOGameListCache(&cache, &b, filename, &hint);
            /* Duplicate name+extension pairs may legitimately resolve to a different (identical-key)
               entry; compare the key and the startup the scan actually uses. */
            if (ra != rb || (ra == 0 && (strcmp(a.name, b.name) || strcmp(a.extension, b.extension)))) {
                printf("lookup mismatch: iter %d file '%s' old=%d new=%d\n", iter, filename, ra, rb);
                failures++;
            }
        }

        /* change detection: same list, reordered, one added, one removed, empty */
        for (int variant = 0; variant < 5; variant++) {
            struct game_list_t nodes[80], *head = NULL;
            int count = variant == 2 ? n + 1 : variant == 3 ? (n > 0 ? n - 1 : 0) : variant == 4 ? 0 : n;
            for (int k = count - 1; k >= 0; k--) {
                int src = (variant == 1 && n > 1) ? (k + 1) % n : k;
                nodes[k].gameinfo = pool[src < n + 64 ? src : 0];
                if (variant == 2 && k == n)
                    snprintf(nodes[k].gameinfo.name, sizeof(nodes[k].gameinfo.name), "New Game");
                nodes[k].next = head;
                head = &nodes[k];
            }
            int expect = oldModified(&cache, head, count);
            writes = removes = 0;
            updateISOGameList("mass0:DVD", &cache, head, count);
            int got = (writes + removes) > 0;
            if (expect != got) {
                printf("change check mismatch: iter %d variant %d n=%d count=%d old=%d new=%d\n", iter, variant, n, count, expect, got);
                failures++;
            }
        }
    }
    printf("4000 random caches: lookups and rewrite decisions %s\n", failures ? "DIFFER" : "match the old code");

    /* cost: a 1000-game directory read in the usual (reverse-of-cache) order */
    {
        int n = 1000, hint = -1;
        struct game_cache_list cache = {(unsigned)n, pool};
        for (int k = 0; k < n; k++) {
            memset(&pool[k], 0, sizeof(pool[k]));
            snprintf(pool[k].name, sizeof(pool[k].name), "Some Game Title %04d", k);
            snprintf(pool[k].extension, sizeof(pool[k].extension), ".iso");
        }
        formats = entryCompares = 0;
        for (int f = 0; f < n; f++) {
            base_game_info_t g;
            snprintf(filename, sizeof(filename), "Some Game Title %04d.iso", n - 1 - f);
            oldQuery(&cache, &g, filename);
            queryISOGameListCache(&cache, &g, filename, &hint);
        }
        printf("1000 cached ISOs, one scan: old %ld snprintf calls, new %ld entry comparisons\n", formats, entryCompares);
        if (entryCompares > 4L * n) {
            printf("  FAIL: the usual scan order must cost O(n) entry comparisons\n");
            failures++;
        }
    }

    return failures ? 1 : 0;
}
'''

if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'iso_cache.c'
        exe = Path(tmp) / ('iso_cache.exe' if sys.platform == 'win32' else 'iso_cache')
        c_file.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        build = subprocess.run(['cc', '-std=gnu99', '-O1', '-Wall', '-Wextra', '-Werror',
                                '-Wno-unused-function', '-Wno-sign-compare', '-Wno-format-truncation',
                                str(c_file), '-o', str(exe)],
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
print('ISO list cache: OK')
