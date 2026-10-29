"""Execute the PS1 RetroGEM metadata-id memo: kind separation, precedence, retries, deferral.

The memo behind PS1 art/CFG id lookups (vcdsupport.c) is extracted into a host harness with
mocked resolvers. Asserts: .VCD and .CUE rows of the same name never cross-serve; the
disc-verified id beats a filename-parsed one; the display request keeps its zero-IO contract
for well-named rows while the metadata request verifies them; art/BGM-busy deferral and
retry-to-absent behave; a re-pointed scan dir re-asks the disc; multi-disc CUE folders use
discs.txt order (disc 1's id) before the best-priority image fallback.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (ROOT / path).read_text(encoding='utf-8')
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


src = (ROOT / 'src/vcdsupport.c').read_text(encoding='utf-8')
vcdh = (ROOT / 'include/vcdsupport.h').read_text(encoding='utf-8')
retrh = (ROOT / 'include/retrogem.h').read_text(encoding='utf-8')
cueh = (ROOT / 'include/cuesupport.h').read_text(encoding='utf-8')

state_enum = re.search(r'typedef enum \{\s*VCD_ID_UNREQUESTED.*?\} vcd_id_state_t;', src, re.S).group()
memo_struct = re.search(r'typedef struct vcd_id_memo.*?\} vcd_id_memo_t;', src, re.S).group()
memo_globals = 'static vcd_id_memo_t *gVcdIdMemo = NULL;\nstatic int gVcdIdMemoCount = 0;'
kind_enum = re.search(r'typedef enum \{\s*PS1_ROW_VCD.*?\} ps1_row_kind_t;', vcdh, re.S).group()
queue_globals = re.search(
    r'static char gVcdIdReqName\[256\];\n'
    r'static volatile unsigned char gVcdIdReqKind = PS1_ROW_VCD;\n'
    r'static volatile int gVcdIdReqPending = 0;', src).group()
vcd_id_max = re.search(r'#define VCD_ID_MAX\s+(\d+)', vcdh).group(1)
retrogem_max = re.search(r'#define RETROGEM_GAMEID_MAX\s+(\d+)', retrh).group(1)
memo_max = re.search(r'#define VCD_ID_MEMO_MAX\s+(\d+)', src).group(1)
max_retries = re.search(r'#define VCD_ID_MAX_RETRIES\s+(\d+)', src).group(1)
cue_name_max = re.search(r'#define CUE_NAME_MAX\s+(\d+)', cueh).group(1)
cue_max_discs = re.search(r'#define CUE_MAX_DISCS\s+(\d+)', cueh).group(1)

functions = '\n\n'.join(function('src/vcdsupport.c', signature) for signature in (
    'static int vcdSkipPopstarterPrefix(',
    'int vcdExtractGameId(',
    'static vcd_id_memo_t *vcdIdMemoFind(',
    'void vcdNoteScanDirKind(',
    'void vcdNoteScanDir(',
    'void vcdInvalidateGameIds(',
    'static int vcdCanonDisplayId(',
    'static int vcdResolveMemoEntry(',
    'static int vcdResolveRowId(',
    'int vcdResolveDisplayId(',
    'static void vcdResolveQueuedDisplayId(',
    'static void vcdRequestRowIdInternal(',
    'void vcdRequestDisplayId(',
    'void ps1RowIdRequest(',
    'int ps1RowIdCached(',
))

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

#define DIntr() ((void)0)
#define EIntr() ((void)0)
#define IO_OK 0
#define IO_CUSTOM_SIMPLEACTION 1
static int guiFrameId = 0;

#define VCD_ID_MAX @VCD_ID_MAX@
#define RETROGEM_GAMEID_MAX @RETROGEM_MAX@
#define VCD_ID_MEMO_MAX @MEMO_MAX@
#define VCD_ID_MAX_RETRIES @MAX_RETRIES@
#define CUE_NAME_MAX @CUE_NAME_MAX@
#define CUE_MAX_DISCS @CUE_MAX_DISCS@

@KIND_ENUM@
@STATE_ENUM@
@MEMO_STRUCT@
@MEMO_GLOBALS@

/* ---- mocks: the world around the memo ------------------------------------ */
static int artPending;         /* cacheHasPendingArt() answer        */
static int bgmAllowed = 1;     /* bgmDiscretionaryIoAllowed() answer */
static int putCount;           /* ioPutRequest calls                 */
static void (*queuedFn)(void);
static int ioPutRequest(int type, void *data)
{
    assert(type == IO_CUSTOM_SIMPLEACTION);
    putCount++;
    queuedFn = (void (*)(void))data;
    return IO_OK;
}
static int cacheHasPendingArt(void) { return artPending; }
static int bgmDiscretionaryIoAllowed(void) { return bgmAllowed; }

/* retrogem resolvers: succeed only for the exact expected path */
static char expectedVcdPath[1024];
static const char *vcdIdToReturn; /* NULL = unreadable / no id */
static int vcdCalls;
static int retrogemGetVcdGameID(const char *path, char *out, size_t maxLen)
{
    vcdCalls++;
    if (vcdIdToReturn == NULL || strcmp(path, expectedVcdPath) != 0)
        return 0;
    snprintf(out, maxLen, "%s", vcdIdToReturn);
    return 1;
}
static char expectedCuePath[1024];
static const char *cueIdToReturn;
static int cueCalls;
static int retrogemGetPs1ImageGameID(const char *path, char *out, size_t maxLen)
{
    cueCalls++;
    if (cueIdToReturn == NULL || strcmp(path, expectedCuePath) != 0)
        return 0;
    snprintf(out, maxLen, "%s", cueIdToReturn);
    return 1;
}

/* cue support: discs.txt order when present, best-priority image otherwise */
typedef struct { int count; char names[CUE_MAX_DISCS][CUE_NAME_MAX]; } cue_disc_list_t;
static int cueListMode; /* 1 = one-entry discs.txt, 0 = none, -1 = unreadable */
static int cueListCalls;
static char lastCueListPrefix[256];
static int cueReadDiscList(const char *devPrefix, const char *folder, cue_disc_list_t **outList)
{
    cueListCalls++;
    snprintf(lastCueListPrefix, sizeof(lastCueListPrefix), "%s", devPrefix);
    (void)folder;
    *outList = NULL;
    if (cueListMode < 0)
        return -1;
    if (cueListMode == 0)
        return 0;
    *outList = calloc(1, sizeof(cue_disc_list_t));
    if (*outList == NULL)
        return -1;
    (*outList)->count = 1;
    snprintf((*outList)->names[0], CUE_NAME_MAX, "Disc 1.cue");
    return 1;
}
static int cueBuildDiscPath(const char *devPrefix, const char *folder, const char *disc, char *out, int outSize)
{
    snprintf(out, outSize, "%sEMBER/games/%s/%s", devPrefix, folder, disc);
    return 1;
}
static int cueResolveFail; /* 0 ok, 1 unreadable, 2 readable-but-empty */
static int cueResolveCalls;
static int cueResolveGameImage(const char *devPrefix, const char *name, char *out, int outSize)
{
    cueResolveCalls++;
    if (cueResolveFail == 1)
        return -1;
    if (cueResolveFail == 2)
        return 0;
    snprintf(out, outSize, "%sEMBER/games/%s/best.cue", devPrefix, name);
    return 1;
}

@QUEUE_GLOBALS@

@FUNCTIONS@

/* ---- test helpers --------------------------------------------------------- */
static void pump(void)
{
    assert(queuedFn != NULL);
    queuedFn();
    queuedFn = NULL;
}
static void reset(void)
{
    vcdInvalidateGameIds();
    guiFrameId = 0;
    artPending = 0;
    bgmAllowed = 1;
    putCount = vcdCalls = cueCalls = cueListCalls = cueResolveCalls = 0;
    queuedFn = NULL;
    expectedVcdPath[0] = expectedCuePath[0] = lastCueListPrefix[0] = 0;
    vcdIdToReturn = cueIdToReturn = NULL;
    cueListMode = 0;
    cueResolveFail = 0;
}
static void settleVcd(const char *name, const char *dir, const char *path, const char *id)
{
    char got[VCD_ID_MAX];
    vcdNoteScanDirKind(name, dir, PS1_ROW_VCD);
    snprintf(expectedVcdPath, sizeof(expectedVcdPath), "%s", path);
    vcdIdToReturn = id;
    ps1RowIdRequest(name, PS1_ROW_VCD);
    pump();
    assert(ps1RowIdCached(name, PS1_ROW_VCD, got, sizeof(got)));
    assert(!strcmp(got, id));
}

int main(void)
{
    char id[VCD_ID_MAX];

    /* 1. kind separation: same display name in both cores resolves independently */
    vcdNoteScanDirKind("Game", "mass0:/POPS/", PS1_ROW_VCD);
    vcdNoteScanDirKind("Game", "mass0:/", PS1_ROW_CUE);
    settleVcd("Game", "mass0:/POPS/", "mass0:/POPS/Game.VCD", "SLUS_111.11");
    assert(cueCalls == 0); /* the VCD resolve never touched the Ember path */
    assert(!ps1RowIdCached("Game", PS1_ROW_CUE, id, sizeof(id))); /* CUE row still unresolved */
    cueListMode = 1;
    cueIdToReturn = "SLUS_222.22";
    snprintf(expectedCuePath, sizeof(expectedCuePath), "%s", "mass0:/EMBER/games/Game/Disc 1.cue");
    ps1RowIdRequest("Game", PS1_ROW_CUE);
    pump();
    assert(!strcmp(lastCueListPrefix, "mass0:/"));
    assert(ps1RowIdCached("Game", PS1_ROW_CUE, id, sizeof(id)) && !strcmp(id, "SLUS_222.22"));
    assert(ps1RowIdCached("Game", PS1_ROW_VCD, id, sizeof(id)) && !strcmp(id, "SLUS_111.11"));
    /* the display resolver stays VCD-only: a CUE-only row is invisible to it */
    vcdNoteScanDirKind("EmuGame", "mass0:/", PS1_ROW_CUE);
    cueListMode = 0; /* no discs.txt: best-priority image */
    cueIdToReturn = "SLES_999.99";
    snprintf(expectedCuePath, sizeof(expectedCuePath), "%s", "mass0:/EMBER/games/EmuGame/best.cue");
    ps1RowIdRequest("EmuGame", PS1_ROW_CUE);
    pump();
    assert(ps1RowIdCached("EmuGame", PS1_ROW_CUE, id, sizeof(id)) && !strcmp(id, "SLES_999.99"));
    assert(!vcdResolveDisplayId("EmuGame", id, sizeof(id)));
    reset();

    /* 2. multi-disc CUE folder without discs.txt falls back to the best-priority image */
    vcdNoteScanDirKind("Game", "mmce0:/", PS1_ROW_CUE);
    cueIdToReturn = "SLES_033.44";
    snprintf(expectedCuePath, sizeof(expectedCuePath), "%s", "mmce0:/EMBER/games/Game/best.cue");
    ps1RowIdRequest("Game", PS1_ROW_CUE);
    pump();
    assert(ps1RowIdCached("Game", PS1_ROW_CUE, id, sizeof(id)) && !strcmp(id, "SLES_033.44"));
    assert(cueResolveCalls == 1);
    reset();

    /* 3. disc truth beats the filename: a misnamed file upgrades when verified */
    vcdNoteScanDirKind("SLUS_333.33.Bad Name", "mass0:/POPS/", PS1_ROW_VCD);
    assert(ps1RowIdCached("SLUS_333.33.Bad Name", PS1_ROW_VCD, id, sizeof(id)));
    assert(!strcmp(id, "SLUS_333.33")); /* provisional free parse, zero IO */
    assert(putCount == 0);
    /* the display request keeps that zero-IO contract for well-named rows */
    vcdRequestDisplayId("SLUS_333.33.Bad Name");
    assert(putCount == 0);
    /* the metadata request verifies it against the disc, which disagrees */
    snprintf(expectedVcdPath, sizeof(expectedVcdPath), "%s", "mass0:/POPS/SLUS_333.33.Bad Name.VCD");
    vcdIdToReturn = "SLUS_444.44";
    ps1RowIdRequest("SLUS_333.33.Bad Name", PS1_ROW_VCD);
    assert(putCount == 1);
    pump();
    assert(ps1RowIdCached("SLUS_333.33.Bad Name", PS1_ROW_VCD, id, sizeof(id)));
    assert(!strcmp(id, "SLUS_444.44"));
    reset();

    /* 4. one-slot queue: a second request while queued is a no-op */
    vcdNoteScanDirKind("Game2", "mass0:/POPS/", PS1_ROW_VCD);
    vcdIdToReturn = "SCUS_555.55";
    snprintf(expectedVcdPath, sizeof(expectedVcdPath), "%s", "mass0:/POPS/Game2.VCD");
    ps1RowIdRequest("Game2", PS1_ROW_VCD);
    ps1RowIdRequest("Game2", PS1_ROW_VCD);
    assert(putCount == 1);
    pump();
    assert(ps1RowIdCached("Game2", PS1_ROW_VCD, id, sizeof(id)) && !strcmp(id, "SCUS_555.55"));
    reset();

    /* 5. art/BGM-busy deferral: throttled retry until the pipelines go quiet */
    vcdNoteScanDirKind("Game3", "mass0:/POPS/", PS1_ROW_VCD);
    vcdIdToReturn = "SLPM_666.66";
    snprintf(expectedVcdPath, sizeof(expectedVcdPath), "%s", "mass0:/POPS/Game3.VCD");
    artPending = 1;
    ps1RowIdRequest("Game3", PS1_ROW_VCD);
    pump();
    assert(!ps1RowIdCached("Game3", PS1_ROW_VCD, id, sizeof(id)));
    ps1RowIdRequest("Game3", PS1_ROW_VCD); /* before the backoff frame: no new queue entry */
    assert(putCount == 1);
    guiFrameId += 200;
    artPending = 0;
    ps1RowIdRequest("Game3", PS1_ROW_VCD);
    assert(putCount == 2);
    pump();
    assert(ps1RowIdCached("Game3", PS1_ROW_VCD, id, sizeof(id)) && !strcmp(id, "SLPM_666.66"));
    reset();

    /* 6. unreadable disc: bounded retries, then ABSENT for the session */
    vcdNoteScanDirKind("Game4", "mass0:/POPS/", PS1_ROW_VCD);
    vcdIdToReturn = NULL; /* every probe fails */
    for (int attempt = 0; attempt <= VCD_ID_MAX_RETRIES; attempt++) {
        int before = putCount;
        ps1RowIdRequest("Game4", PS1_ROW_VCD);
        assert(putCount == before + 1);
        pump();
        guiFrameId += 200; /* pass the DEFERRED backoff */
    }
    assert(vcdCalls == VCD_ID_MAX_RETRIES + 1);
    assert(!ps1RowIdCached("Game4", PS1_ROW_VCD, id, sizeof(id)));
    int putsBefore = putCount;
    ps1RowIdRequest("Game4", PS1_ROW_VCD); /* ABSENT: never re-asked */
    assert(putCount == putsBefore && vcdCalls == VCD_ID_MAX_RETRIES + 1);
    reset();

    /* 7. a re-pointed scan dir (device swap / HDD layout) re-asks the disc */
    settleVcd("Game5", "mass0:/POPS/", "mass0:/POPS/Game5.VCD", "SLUS_777.77");
    vcdNoteScanDirKind("Game5", "pfs0:/", PS1_ROW_VCD); /* same row, new home */
    assert(!ps1RowIdCached("Game5", PS1_ROW_VCD, id, sizeof(id))); /* memo reset */
    settleVcd("Game5", "pfs0:/", "pfs0:/Game5.VCD", "SLUS_888.88");
    reset();

    /* 8. free-parse shapes */
    assert(ps1RowIdCached("XX.SLUS_005.51.Whatever", PS1_ROW_VCD, id, sizeof(id)));
    assert(!strcmp(id, "SLUS_005.51"));
    assert(!ps1RowIdCached("just a game name", PS1_ROW_CUE, id, sizeof(id)));

    puts("PASS: kind separation, discs.txt-first CUE ids, disc-beats-parse, queue dedup, "
         "busy deferral, retry-to-absent, dir re-point, free-parse shapes");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    source = HARNESS.replace('@VCD_ID_MAX@', vcd_id_max)
    source = source.replace('@RETROGEM_MAX@', retrogem_max)
    source = source.replace('@MEMO_MAX@', memo_max)
    source = source.replace('@MAX_RETRIES@', max_retries)
    source = source.replace('@CUE_NAME_MAX@', cue_name_max)
    source = source.replace('@CUE_MAX_DISCS@', cue_max_discs)
    source = source.replace('@KIND_ENUM@', kind_enum)
    source = source.replace('@STATE_ENUM@', state_enum)
    source = source.replace('@MEMO_STRUCT@', memo_struct)
    source = source.replace('@MEMO_GLOBALS@', memo_globals)
    source = source.replace('@QUEUE_GLOBALS@', queue_globals)
    source = source.replace('@FUNCTIONS@', functions)
    cfile = folder / 'ps1meta.c'
    binary = folder / ('ps1meta.exe' if sys.platform == 'win32' else 'ps1meta')
    cfile.write_text(source)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
                    '-Wno-missing-field-initializers', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)

# ---- source contracts for the art and CFG consumers (structure, not behavior) ----
themes = (ROOT / 'src/themes.c').read_text(encoding='utf-8')
art_fn = themes[themes.index('static GSTEXTURE *getGameImageTextureEx('):]
art_fn = art_fn[:art_fn.index('\n}')]
assert 'list->mode != FAV_MODE && list->mode != APP_MODE' in art_fn, \
    'PS1 id-art must stay off the FAV/APP pages (favGetArtMode matches the value)'
assert art_fn.index('ps1RowIdCached(startup, kind, id, sizeof(id))') < \
    art_fn.index('cacheGetTextureIdOrName(cache, list, cacheId, cacheUid, id, startup, isPriority)') < \
    art_fn.rindex('cacheGetTextureEx(cache, list, cacheId, cacheUid, startup, isPriority)'), \
    'id-keyed art must be probed (with its name fallback) before the plain name probe'
assert 'ps1RowIdRequest(startup, kind);' in art_fn, 'a cold memo must queue a background resolve'
texcache = (ROOT / 'src/texcache.c').read_text(encoding='utf-8')
probe_fn = texcache[texcache.index('GSTEXTURE *cacheGetTextureIdOrName('):]
probe_fn = probe_fn[:probe_fn.index('\n}')]
assert '*cacheId = parkId;' in probe_fn and 'parkUid' in probe_fn, \
    'the id-absence memo must be parked aside so the name fallback is not shadowed'
assert probe_fn.index('cacheHoldsFallback(') < probe_fn.index('cacheSlotKeyedOther('), \
    'a row settled on its name fallback must not re-probe the id every frame (cover flicker)'
assert probe_fn.index('cacheAdoptFallback(') < probe_fn.index('cacheSlotKeyedOther('), \
    'a row reseated by a list rebuild must take back its settled name fallback before re-probing the id'

support = (ROOT / 'src/supportbase.c').read_text(encoding='utf-8')
cfg_fn = support[support.index('PS1 metadata fallback (both cores)'):]
cfg_fn = cfg_fn[:cfg_fn.index('\n    }\n')]
assert 'if (isPs1) {' in cfg_fn, 'the id-keyed Title merge must run for every PS1 row lacking a Title'
assert 'haveMetaKey && isVcd && !configLoaded' in cfg_fn, \
    'skip only the parsed-ID CFG already handled by the absent-name VCD compatibility fallback'
assert 'configGetStr(meta, "Title", &metaTitle)' in cfg_fn, 'Title is the only merged key'
assert 'configMerge(config, meta)' not in cfg_fn, 'settings must never merge from the id-keyed cfg'
assert 'config->modified = wasModified;' in cfg_fn, 'metadata must not dirty the name cfg'
assert 'ps1RowIdCached(game->name, isVcd ? PS1_ROW_VCD : PS1_ROW_CUE,' in cfg_fn, \
    'the cfg path must use the memo-only accessor (zero disc IO)'

cues = (ROOT / 'src/cuesupport.c').read_text(encoding='utf-8')
assert 'vcdNoteScanDirKind(entries[i].name, devPrefix, PS1_ROW_CUE);' in cues, \
    'the CUE scan must notify the shared memo per row'

print('PASS: art probe order/park-restore, Title-only cfg merge, CUE scan notification')

# The actual renderer and metadata merge are compiled too: mocking only the memo
# misses caller-order bugs and UID slots shared between name and ID probes.
CONSUMERS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#define VCD_ID_MAX 16
#define RETROGEM_GAMEID_MAX 12
#define PS1_ROW_VCD 0
#define PS1_ROW_CUE 1
#define FAV_MODE 10
#define APP_MODE 11
#define CACHE_ID_PS1_BOTH_ABSENT -3
typedef struct { int marker; void *Mem; } GSTEXTURE;
typedef struct { GSTEXTURE texture; int UID; char key[128]; void *qr; int lastUsed; unsigned int failEpoch; unsigned char nameFallback; } cache_entry_t;
typedef struct { int userId, count; char *suffix; cache_entry_t *content; } image_cache_t;
typedef struct { char name[256], extension[8]; int cue; } base_game_info_t;
typedef struct item_list item_list_t;
struct item_list { int mode; char *(*itemGetStartup)(item_list_t *, int); void *(*itemGet)(item_list_t *, int); };
struct submenu_item { int isFolder, id; int *cache_id, *cache_uid; };
static struct { int gameCacheCount; } theme = {1}, *gTheme = &theme;
static int gEnableArt = 1, gEnableBGArt = 1;
static int isHiddenArtworkCache(image_cache_t *c) { (void)c; return 0; }
static int cueIsCueEntry(const base_game_info_t *r) { return r->cue; }
static base_game_info_t row;
static char *startup(item_list_t *l, int i) { (void)l; (void)i; return row.name; }
static void *getrow(item_list_t *l, int i) { (void)l; (void)i; return &row; }
static int requests, resolved, idPresent = 1, namePresent = 1, idLoading, guiFrameId = 1;
static unsigned int gArtFailEpoch = 9;
static int idAsks; /* id lookups that got past the UID fast path: each is a claim + device read on a miss */
static void ps1RowIdRequest(const char *n, int k) { (void)n; (void)k; requests++; }
static int ps1RowIdCached(const char *n, int k, char *out, int size)
{ (void)n; (void)k; snprintf(out, size, "%s", resolved ? "SLUS_222.22" : "SLUS_111.11"); return 1; }
/* Cache contract: UID fast path precedes value lookup, and -2 parks absence. */
static GSTEXTURE *cacheGetTextureEx(image_cache_t *c, item_list_t *l, int *slot, int *uid, char *v, int p)
{
    (void)l; (void)p;
    if (*slot == -2) return NULL;
    if (*slot >= 0 && *slot < c->count && c->content[*slot].UID == *uid)
        return &c->content[*slot].texture;
    *slot = -1;
    int isId = strcmp(v, row.name) != 0;
    idAsks += isId;
    if ((isId && !idPresent) || (!isId && !namePresent)) { *slot = -2; *uid = (int)gArtFailEpoch; return NULL; }
    if (isId && idLoading) return NULL;
    for (int i = 0; i < c->count; i++)
        if (!strcmp(c->content[i].key, v)) { *slot = i; *uid = c->content[i].UID; return &c->content[i].texture; }
    return NULL;
}
@PROBE@
@ART@
typedef struct { const char *title; int modified, setting; } config_set_t;
static config_set_t metadata = {"Disc title", 0, 999};
static int reads;
static int configGetStr(config_set_t *c, const char *k, const char **out)
{ assert(!strcmp(k, "Title")); *out = c->title; return *out != NULL; }
static config_set_t *configAlloc(int t, void *u, const char *p)
{ (void)t; (void)u; assert(strstr(p, resolved ? "CFG/SLUS_222.22.cfg" : "CFG/SLUS_111.11.cfg")); return &metadata; }
static int configRead(config_set_t *c) { assert(c == &metadata); reads++; return 1; }
static void configFree(config_set_t *c) { assert(c == &metadata); }
static void configSetStr(config_set_t *c, const char *k, const char *v)
{ assert(!strcmp(k, "Title")); c->title = v; c->modified = 1; }
static int vcdExtractGameId(const char *n, char *out, int size)
{ if (strncmp(n, "SLUS_", 5)) return 0; snprintf(out, size, "SLUS_111.11"); return 1; }
static void populate(base_game_info_t *game, config_set_t *config, int configLoaded)
{
    char path[256]; const char *prefix = "mass0:/", *sep = "/";
    int isVcd = !strcmp(game->extension, ".VCD"), isPs1 = isVcd || game->cue;
    @CFG@
}
@NORMALIZE@
@CLEAN@
static void normalized(const char *raw, const char *expected)
{
    char out[12]; assert(retrogemNormalizeGameID(raw, out, sizeof(out)));
    assert(!strcmp(out, expected));
}
int main(void)
{
    cache_entry_t entries[3] = {{{1, NULL}, 101, "SLUS_111.11.Name", NULL, 0, 0, 0}, {{2, NULL}, 102, "SLUS_111.11", NULL, 0, 0, 0},
                                {{3, NULL}, 103, "SLUS_222.22", NULL, 0, 0, 0}};
    image_cache_t cache = {0, 3, "COV", entries}; item_list_t list = {0, startup, getrow};
    int slot = 0, uid = 101; struct submenu_item item = {0, 0, &slot, &uid};
    strcpy(row.name, "SLUS_111.11.Name"); strcpy(row.extension, ".VCD");
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[1].texture);
    assert(requests == 1); /* parsed ID must still request disc verification */
    resolved = 1;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[2].texture);
    resolved = 0; idPresent = 0;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[0].texture);
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[0].texture);
    assert(entries[0].nameFallback); /* settled: the row stays on its name art, no id re-probe */
    /* a list rebuild reseats the row with no slot: it takes its settled (decoded) name fallback back */
    entries[0].texture.Mem = &entries[0], entries[0].lastUsed = 1, slot = -1, uid = -1;
    int asks = idAsks;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[0].texture && slot == 0 && uid == 101);
    assert(idAsks == asks); /* the id's absence memo is long evicted: asking again re-reads the device */
    entries[0].texture.Mem = NULL, entries[0].lastUsed = 0;
    namePresent = 0; slot = -1;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == NULL && slot == CACHE_ID_PS1_BOTH_ABSENT);
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == NULL && slot == CACHE_ID_PS1_BOTH_ABSENT);
    idPresent = 1; gArtFailEpoch++; /* new art may have appeared: the park re-opens */
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[1].texture);
    slot = 0; uid = 101; idLoading = 1; /* on its name fallback while id art loads: keeps the name art */
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[0].texture);
    entries[0].nameFallback = 0; /* not a settled fallback: the id is asked for */
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == NULL);
    row.cue = 1; idLoading = 0;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[1].texture);
    int before = requests; list.mode = FAV_MODE; slot = 0; uid = 101;
    assert(getGameImageTextureEx(&cache, &list, &item, 0) == &entries[0].texture && requests == before);
    row.cue = 0;
    config_set_t cfg = {NULL, 0, 42}; populate(&row, &cfg, 1);
    assert(!strcmp(cfg.title, "Disc title") && cfg.setting == 42 && cfg.modified == 0);
    cfg.title = ""; cfg.modified = 1; populate(&row, &cfg, 1);
    assert(!strcmp(cfg.title, "Disc title") && cfg.modified == 1);
    before = reads; cfg.title = "Name title"; populate(&row, &cfg, 1);
    assert(reads == before && !strcmp(cfg.title, "Name title"));
    cfg.title = NULL; populate(&row, &cfg, 0); assert(reads == before);
    /* A verified disc ID overrides the parsed ID for Title, just as for art. */
    resolved = 1; metadata.title = "Verified disc title";
    populate(&row, &cfg, 1);
    assert(reads == before + 1 && !strcmp(cfg.title, "Verified disc title"));
    cfg.title = NULL; populate(&row, &cfg, 0);
    assert(reads == before + 2 && !strcmp(cfg.title, "Verified disc title"));
    cfg.title = "Name title"; populate(&row, &cfg, 1);
    assert(reads == before + 2 && !strcmp(cfg.title, "Name title"));
    cfg.title = NULL; before = reads;
    row.cue = 1; strcpy(row.extension, ".CUE"); populate(&row, &cfg, 0);
    assert(reads == before + 1 && !strcmp(cfg.title, "Verified disc title"));
    normalized("slus_123.45", "SLUS_123.45"); normalized("SlUs-12345", "SLUS_123.45");
    normalized("SLUS12345", "SLUS_123.45"); normalized("SLUS.123_45", "SLUS_123.45");
    normalized("slusp_123.45", "SLUS_123.45"); normalized("lsp12345.67", "LSP12345.67");
    normalized("LSP-123456", "LSP12345.6");
    char out[12]; assert(!retrogemNormalizeGameID(NULL, out, sizeof(out)));
    assert(!retrogemNormalizeGameID("", out, sizeof(out)));
    assert(!retrogemNormalizeGameID("SLUS123456", out, sizeof(out)));
    assert(!retrogemNormalizeGameID("SLUS12X45", out, sizeof(out)));
    assert(!retrogemNormalizeGameID("LSP12345678", out, sizeof(out)));
    assert(!retrogemNormalizeGameID("Crash Bandicoot", out, sizeof(out)));
    assert(!retrogemNormalizeGameID("SLUS12345", out, 11));
    assert(retrogemCleanTitleID("cdrom:\\slusp_123.45;1", out, sizeof(out)));
    assert(!strcmp(out, "SLUS_123.45"));
    assert(retrogemCleanTitleID("cdrom0:\\lsp12345.67;1", out, sizeof(out)));
    assert(!strcmp(out, "LSP12345.67"));
    assert(retrogemCleanTitleID("cdrom:\\slus12345;1", out, sizeof(out)));
    assert(!strcmp(out, "SLUS_123.45"));
    assert(!retrogemCleanTitleID("cdrom:\\Crash.exe;1", out, sizeof(out)));
    puts("PASS: actual art/CFG consumers and CosmicScale serial normalization");
    return 0;
}
'''
cfg_block = cfg_fn[cfg_fn.index('    if (isPs1) {'):] + '\n    }'
probe = '\n'.join(function('src/texcache.c', signature) for signature in (
    'static int cacheSlotKeyedOther(', 'static int cacheHoldsFallback(', 'static GSTEXTURE *cacheResidentByValue(',
    'static int cacheAdoptFallback(', 'GSTEXTURE *cacheGetTextureIdOrName('))
consumer_source = CONSUMERS.replace('@PROBE@', probe).replace('@ART@', function('src/themes.c',
    'static GSTEXTURE *getGameImageTextureEx(')).replace('@CFG@', cfg_block)
normalizer = function('src/retrogem.c', 'static int retrogemTitlePrefixChar(')
normalizer += '\n' + function('src/retrogem.c', 'int retrogemNormalizeGameID(')
consumer_source = consumer_source.replace('@NORMALIZE@', normalizer)
consumer_source = consumer_source.replace('@CLEAN@', function('src/retrogem.c',
    'static int retrogemCleanTitleID('))
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    cfile = folder / 'consumers.c'
    binary = folder / ('consumers.exe' if sys.platform == 'win32' else 'consumers')
    cfile.write_text(consumer_source, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)
