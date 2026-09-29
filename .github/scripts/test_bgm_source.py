"""Background music must survive a card that loses the music file's descriptor mid-stream.

SD2PSX (sd2psxtd firmware, 1.4.0 and develop) keeps the descriptor of the command in progress in
one int, op_data->fd, in src/ps2/mmceman/. An open stores it whole -- and -1 when the open fails --
but the close, read, write and lseek handlers receive their descriptor into that int's LOW BYTE
only. After any failed open or stat on the card (the ul.cfg probe of every MMCE refresh, a cover
that does not exist), the next read or lseek of any file that is still open goes to a negative
descriptor and fails, until some open succeeds and writes the whole int again. The decoder took
the empty read for the end of the stream, the rewind failed the same way, and theme music stopped
for good a few seconds into the menu.

src/sound.c feeds vorbisfile through bgmSource* callbacks that keep their own position and reopen
the file when a read comes back empty before the end, or a seek fails.

Part 1 pins the load path to those callbacks. Part 2 compiles bgmSourceReopen, bgmSourceRead,
bgmSourceSeek, bgmSourceTell and bgmSourceClose on the host against a model of that firmware and
checks that the music arrives whole and in order wherever the descriptor dies, that the real end of
the file is still the end of the stream, that no descriptor is left open on the card, and that a
file that is gone for good gives up in bounded time.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def function_text(source, signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        return None
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


sound = (root / 'src/sound.c').read_text(encoding='utf-8').replace('\r\n', '\n')

load = function_text(sound, 'static int bgmTryLoadPath(')
if load is None:
    failures.append('src/sound.c: bgmTryLoadPath() not found')
else:
    if not re.search(r'ov_open_callbacks\(\s*src\s*,[^;]*bgmSourceCallbacks\s*\)', load):
        failures.append('bgmTryLoadPath: the decoder must read through bgmSourceCallbacks, not a bare FILE*')
    if 'SEEK_END' not in load or 'ftell(' not in load:
        failures.append('bgmTryLoadPath: must measure the file size, or an empty read cannot be told from the end')
    if 'bgmSourceClose(src)' not in load:
        failures.append('bgmTryLoadPath: a failed ov_open_callbacks leaves the source to the caller to close')

names = ('static int bgmSourceReopen(', 'static size_t bgmSourceRead(', 'static int bgmSourceSeek(',
         'static long bgmSourceTell(', 'static int bgmSourceClose(')
functions = []
for name in names:
    text = function_text(sound, name)
    if text is None:
        failures.append('src/sound.c: %s) not found' % name[:-1])
    functions.append(text)

reopen = functions[0]
if reopen is not None:
    opened = reopen.find('fopen(')
    closed = reopen.find('fclose(src->f)')
    if opened < 0 or closed < 0 or closed < opened:
        failures.append('bgmSourceReopen: must open the new handle BEFORE closing the dead one '
                        '(only a successful open makes the card\'s descriptor whole again)')

source_type = re.search(r'^typedef struct\n\{\n[ \t]*FILE \*f;.*?^\} bgm_source_t;\n', sound, re.M | re.S)
if source_type is None:
    failures.append('src/sound.c: bgm_source_t not found')
defines = '\n'.join(re.findall(r'^#define BGM_REOPEN_[A-Z_]+\b.*$', sound, re.M))

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int logs;
#define LOG(...) (logs++)
typedef long long ogg_int64_t;

/* ---- sd2psxtd MMCE file service (src/ps2/mmceman/, firmware 1.4.0), reduced to the descriptor ---- */
#define CARD_FILES 16
#define MUSIC_SIZE (300 * 1024 + 123)
static unsigned char music[MUSIC_SIZE];
static int cardOpen[CARD_FILES];
static long cardPos[CARD_FILES];
static int opFd;             /* op_data->fd */
static int musicExists = 1;
static long long delayedUs;
static int opens;

typedef struct
{
    int handle;
} FAKEFILE;

/* Somebody else's open or stat of a missing file: the card stores -1. */
static void failedLookup(void)
{
    opFd = -1;
}

/* close/read/lseek: receiveOrNextCmd((uint8_t*)&op_data->fd) writes the low byte, and the handler
   refuses a descriptor that is not open (sd_fd_is_open / CHECK_FD). */
static int cardSelect(int handle)
{
    opFd = (int)(((unsigned)opFd & ~0xffu) | ((unsigned)handle & 0xffu));
    return (opFd >= 0 && opFd < CARD_FILES && cardOpen[opFd]) ? opFd : -1;
}

static FAKEFILE *fake_fopen(const char *path, const char *mode)
{
    FAKEFILE *f;
    int i;

    (void)path;
    (void)mode;
    opens++;
    if (!musicExists) {
        opFd = -1;
        return NULL;
    }
    for (i = 0; i < CARD_FILES && cardOpen[i]; i++)
        ;
    if (i == CARD_FILES) {
        opFd = -1;
        return NULL;
    }
    cardOpen[i] = 1;
    cardPos[i] = 0;
    opFd = i; /* sd_open's result, the whole int */
    f = malloc(sizeof(*f));
    f->handle = i;
    return f;
}

static size_t fake_fread(void *ptr, size_t size, size_t nmemb, FAKEFILE *f)
{
    int h = cardSelect(f->handle);
    long want = (long)(size * nmemb);

    if (h < 0)
        return 0; /* the IOP read comes back with 0 bytes and no error */
    if (want > MUSIC_SIZE - cardPos[h])
        want = MUSIC_SIZE - cardPos[h];
    if (want < 0)
        want = 0;
    memcpy(ptr, music + cardPos[h], (size_t)want);
    cardPos[h] += want;
    return (size_t)want / size;
}

static int fake_fseek(FAKEFILE *f, long offset, int whence)
{
    int h = cardSelect(f->handle);
    long target;

    if (h < 0)
        return -1;
    target = whence == SEEK_SET ? offset : (whence == SEEK_CUR ? cardPos[h] + offset : MUSIC_SIZE + offset);
    if (target < 0)
        return -1;
    cardPos[h] = target;
    return 0;
}

static int fake_fclose(FAKEFILE *f)
{
    int h = cardSelect(f->handle);

    free(f);
    if (h < 0)
        return -1; /* the card never closes it: that handle stays taken for the session */
    cardOpen[h] = 0;
    return 0;
}

static int DelayThread(int us)
{
    delayedUs += us;
    return 0;
}

#define FILE   FAKEFILE
#define fopen  fake_fopen
#define fread  fake_fread
#define fseek  fake_fseek
#define fclose fake_fclose

@DEFINES@
@TYPE@
@FUNCTIONS@

static int fails;

static void expectThat(int ok, const char *test, const char *what, long long got)
{
    if (!ok) {
        printf("FAIL %s: %s (got %lld)\n", test, what, got);
        fails++;
    }
}

static int cardHandlesOpen(void)
{
    int i, n = 0;

    for (i = 0; i < CARD_FILES; i++)
        n += cardOpen[i];
    return n;
}

static bgm_source_t *openMusic(void)
{
    bgm_source_t *src = malloc(sizeof(*src));

    memset(cardOpen, 0, sizeof(cardOpen));
    musicExists = 1;
    opens = 0;
    delayedUs = 0;
    src->f = fopen("mmce0:/THM/theme/sound/bgm.ogg", "rb");
    src->pos = 0;
    src->size = MUSIC_SIZE;
    snprintf(src->path, sizeof(src->path), "%s", "mmce0:/THM/theme/sound/bgm.ogg");
    return src;
}

static unsigned char got[MUSIC_SIZE];

/* vorbisfile reads 2048 bytes at a time (READSIZE) until a read returns 0. The card loses the
   descriptor before every `every`-th read, starting at read `first`. */
static void wholeFile(const char *test, int every, int first)
{
    bgm_source_t *src = openMusic();
    long total = 0;
    int reads = 0, losses = 0, opensAtEnd, endReopens;
    size_t r;

    for (;;) {
        if (every > 0 && reads >= first && (reads - first) % every == 0) {
            failedLookup();
            losses++;
        }
        r = bgmSourceRead(got + total, 1, 2048, src);
        reads++;
        if (r == 0)
            break;
        total += (long)r;
        if (reads > 100000)
            break;
    }
    opensAtEnd = opens;
    /* Two more reads at the end, one of them on a lost descriptor: still the end, no reopen. */
    r = bgmSourceRead(got, 1, 2048, src);
    failedLookup();
    r += bgmSourceRead(got, 1, 2048, src);
    endReopens = opens - opensAtEnd;
    /* A close right after a failed lookup goes to a negative descriptor as well, and the card keeps
       the file open until its next MMCE_CMD_RESET (mmceman sends one when it loads, RiptOPL before
       a launch). Not this code's to fix: let another client's open succeed first, as covers do. */
    fclose(fopen("mmce0:/ART/cover.png", "rb"));

    expectThat(total == MUSIC_SIZE, test, "bytes delivered", total);
    expectThat(memcmp(got, music, MUSIC_SIZE) == 0 || total != MUSIC_SIZE, test, "the music reached the decoder out of order", 0);
    expectThat(bgmSourceTell(src) == MUSIC_SIZE, test, "position at the end", bgmSourceTell(src));
    expectThat(r == 0 && endReopens == 0, test, "the real end of the file reopened it", endReopens);
    expectThat(cardHandlesOpen() == 1, test, "descriptors left open on the card while playing", cardHandlesOpen());
    bgmSourceClose(src);
    expectThat(cardHandlesOpen() == 0, test, "descriptors left open on the card after closing", cardHandlesOpen());
    printf("%-34s %6d reads, %5d lost descriptors, %5d opens, %lld us waited: OK\n", test, reads, losses, opens, delayedUs);
}

static void seeks(void)
{
    bgm_source_t *src = openMusic();
    size_t r;

    failedLookup();
    expectThat(bgmSourceSeek(src, 1000, SEEK_SET) == 0, "seeks", "SEEK_SET on a lost descriptor", -1);
    r = bgmSourceRead(got, 1, 16, src);
    expectThat(r == 16 && memcmp(got, music + 1000, 16) == 0, "seeks", "data after SEEK_SET", (long long)r);

    failedLookup();
    expectThat(bgmSourceSeek(src, 100, SEEK_CUR) == 0 && bgmSourceTell(src) == 1116, "seeks", "SEEK_CUR on a lost descriptor",
               bgmSourceTell(src));
    r = bgmSourceRead(got, 1, 16, src);
    expectThat(r == 16 && memcmp(got, music + 1116, 16) == 0, "seeks", "data after SEEK_CUR", (long long)r);

    failedLookup();
    expectThat(bgmSourceSeek(src, -64, SEEK_END) == 0 && bgmSourceTell(src) == MUSIC_SIZE - 64, "seeks",
               "SEEK_END on a lost descriptor", bgmSourceTell(src));
    r = bgmSourceRead(got, 1, 2048, src);
    expectThat(r == 64 && memcmp(got, music + MUSIC_SIZE - 64, 64) == 0, "seeks", "data after SEEK_END", (long long)r);

    expectThat(bgmSourceSeek(src, -1, SEEK_SET) != 0 && bgmSourceTell(src) == MUSIC_SIZE, "seeks", "a negative target",
               bgmSourceTell(src));
    expectThat(cardHandlesOpen() == 1, "seeks", "descriptors left open on the card", cardHandlesOpen());
    bgmSourceClose(src);
    printf("%-34s OK\n", "seeks");
}

static void gone(void)
{
    bgm_source_t *src = openMusic();
    size_t r;
    long before;

    r = bgmSourceRead(got, 1, 2048, src);
    before = bgmSourceTell(src);
    musicExists = 0; /* card pulled, file deleted */
    failedLookup();
    r = bgmSourceRead(got, 1, 2048, src);
    expectThat(r == 0, "gone", "a read of a file that is gone", (long long)r);
    expectThat(bgmSourceTell(src) == before, "gone", "position after giving up", bgmSourceTell(src));
    expectThat(delayedUs <= 2000000, "gone", "microseconds spent before giving up", delayedUs);
    expectThat(bgmSourceSeek(src, 0, SEEK_SET) != 0 && bgmSourceTell(src) == before, "gone", "a failed seek moved the position",
               bgmSourceTell(src));
    printf("%-34s gave up after %d opens and %lld us: OK\n", "gone", opens, delayedUs);
    bgmSourceClose(src);
}

int main(void)
{
    long i;

    setvbuf(stdout, NULL, _IONBF, 0);
    for (i = 0; i < MUSIC_SIZE; i++)
        music[i] = (unsigned char)((i * 131u) ^ (i >> 7));

    wholeFile("clean card", 0, 0);
    wholeFile("lost before the first read", 1000000, 0);
    wholeFile("lost once mid-stream", 1000000, 37);
    wholeFile("lost before the last read", 1000000, MUSIC_SIZE / 2048);
    wholeFile("lost every 7th read", 7, 3);
    wholeFile("lost before every read", 1, 0);
    seeks();
    gone();
    return fails != 0;
}
'''


def run_source_harness():
    if source_type is None or None in functions:
        return
    program = (HARNESS.replace('@DEFINES@', defines).replace('@TYPE@', source_type.group(0))
               .replace('@FUNCTIONS@', '\n'.join(functions)))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'bgm_source.c'
        exe = Path(tmp) / 'bgm_source'
        src.write_text(program)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(src)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('bgm source harness did not compile:\n%s' % result.stderr)
            return
        try:
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            failures.append('bgm source harness did not finish in 60 s')
            return
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('bgm source harness failed:\n%s%s' % (result.stdout, result.stderr))


run_source_harness()

if failures:
    print('BGM source checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('bgm source: the music survives a lost descriptor and still ends where the file ends')
