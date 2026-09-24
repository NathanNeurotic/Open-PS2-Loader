"""Background music must never hold audsrv across an open-ended wait, and must feed every format.

audsrv_wait_audio() parks audsrv's only IOP RPC thread -- and the EE library's call mutex -- until
the IOP play thread frees ring space, which it does only while SPU2 keeps completing block
transfers. The BGM playback thread lives in that wait, so whenever the stream stalled, every other
audsrv call waited with it for good: the menu thread's per-press sound effect froze the GUI with the
rumble motor left running, and bgmMute() hung the way into a launch. The playback thread polls
audsrv_available() instead, sleeping between polls.

Part 1 statically forbids audsrv_wait_audio() in src/ and pins that shape.

Part 2 compiles bgmWaitForRoom, bgmQueueChunk and bgmStart's ring sizing from src/sound.c on the host
and runs them against a model of ps2sdk's IOP audsrv ring (iop/sound/audsrv/src/audsrv.c): ten SPU2
feeds of the stream format, play_audio keeping only what fits. audsrv's ring for 16-bit mono under
19.2 kHz is SMALLER than one 4096-byte chunk (11025 Hz: 2340 bytes), so waiting for a whole chunk's
room never ends there. Every 16-bit format audsrv accepts must stream without drops, overruns or
underruns, and a stalled SPU2 must cost only slow polls until termination.
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


for path in sorted((root / 'src').rglob('*.c')):
    source = path.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    for number, line in enumerate(source.split('\n'), 1):
        code = line.split('//')[0]
        if re.search(r'\baudsrv_wait_audio\s*\(', code):
            failures.append('%s:%d calls audsrv_wait_audio(); poll audsrv_available() instead'
                            % (path.relative_to(root).as_posix(), number))

sound = (root / 'src/sound.c').read_text(encoding='utf-8').replace('\r\n', '\n')

wait = function_text(sound, 'static int bgmWaitForRoom(')
if wait is None:
    failures.append('src/sound.c: bgmWaitForRoom() not found')
elif not all(token in wait for token in ('audsrv_available()', 'DelayThread(', 'terminateFlag')):
    failures.append('bgmWaitForRoom: must poll audsrv_available(), sleep between polls and honour terminateFlag')

queue = function_text(sound, 'static int bgmQueueChunk(')
if queue is None:
    failures.append('src/sound.c: bgmQueueChunk() not found')
elif 'bgmWaitForRoom(' not in queue or 'done += sent' not in queue:
    failures.append('bgmQueueChunk: must wait through bgmWaitForRoom() and advance by what audsrv queued')

thread = function_text(sound, 'static void bgmThread(')
if thread is None or 'bgmQueueChunk(' not in thread or 'audsrv_play_audio(' in thread:
    failures.append('bgmThread: must queue chunks through bgmQueueChunk(), never audsrv_play_audio() directly')

start = function_text(sound, 'void bgmStart(')
sizing = re.search(r'^[ \t]*int room = audsrv_available\(\);\n[ \t]*int ring = room \+ audsrv_queued\(\);\n.*?'
                   r'^[ \t]*if \(bgmRoomTarget < BGM_ROOM_TARGET_MIN\)\n[^\n]*\n', start or '', re.M | re.S)
if sizing is None or start.find('audsrv_set_format(') > sizing.start():
    failures.append('bgmStart: must size bgmRoomTarget from the room and ring right after audsrv_set_format()')
# An unsupported rate leaves a ring that never drains; the stream must not start on it.
if start is None or not re.search(r'if \(audsrv_set_format\(&audsrvFmt\) != AUDSRV_ERR_NOERROR\) \{[^}]*bgmDeinit\(\);\s*return;',
                                  start):
    failures.append('bgmStart: a format audsrv refuses must stop BGM before any thread starts')

defines = '\n'.join(re.findall(r'^#define (?:BGM_RING_BUFFER_SIZE|BGM_ROOM_[A-Z_]+)\b.*$', sound, re.M))

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int stallLogs;
#define LOG(...) (stallLogs++)

@DEFINES@

static volatile unsigned char terminateFlag;
static int bgmBytesPerMs;
static int bgmRoomTarget = BGM_RING_BUFFER_SIZE;

/* ---- ps2sdk iop/sound/audsrv/src/audsrv.c, reduced to the ring ---- */
static char ringbuf[20480];
static int ringbufSize, readpos, writepos, playing, feedSize;
static long long nowUs, nextBlockUs; /* SPU2 finishes a 512-sample, 48 kHz block every 10667 us */
static int spuStalled;
static long long terminateAtUs = -1;
static long long rpcs, underruns, overAsks, overfills, badDelays, written;
/* Bytes queued and not yet played, counted here: audsrv's own arithmetic reads a FULL ring
   (writepos caught up with readpos) as empty. */
static int fill;
static unsigned char expect;
static int orderBroken;

static void iopSetFormat(int freq, int channels)
{
    feedSize = ((512 * freq) / 48000) << (1 + (channels == 2)); /* 16-bit */
    ringbufSize = feedSize * 10;
    writepos = 0;
    readpos = (feedSize * 5) & ~3;
    playing = 0;
    fill = ringbufSize - readpos; /* the stale half the reader plays before the first chunk */
}

static int iopAvailable(void)
{
    if (writepos <= readpos)
        return readpos - writepos;
    return ringbufSize - (writepos - readpos);
}

static int iopQueued(void)
{
    if (writepos < readpos)
        return ringbufSize - (readpos - writepos);
    return writepos - readpos;
}

static void runSpu(void)
{
    while (nextBlockUs <= nowUs) {
        if (playing && !spuStalled) {
            if (fill < feedSize) {
                underruns++;
                fill = 0;
            } else {
                fill -= feedSize;
            }
            readpos += feedSize;
            if (readpos >= ringbufSize)
                readpos = 0;
        }
        nextBlockUs += 10667;
    }
}

/* ---- EE side ---- */
static int DelayThread(int us)
{
    if (us <= 0)
        badDelays++;
    nowUs += us;
    if (nowUs > 600LL * 1000000) {
        printf("FAIL: ten simulated minutes without finishing -- a wait that can never be satisfied\n");
        exit(1);
    }
    runSpu();
    if (terminateAtUs >= 0 && nowUs >= terminateAtUs)
        terminateFlag = 1;
    return 0;
}

static int audsrv_available(void)
{
    rpcs++;
    return iopAvailable();
}

static int audsrv_queued(void)
{
    rpcs++;
    return iopQueued();
}

static int audsrv_play_audio(const char *buf, int buflen)
{
    int sent = 0;

    rpcs++;
    playing = 1;
    if (buflen > iopAvailable())
        overAsks++; /* audsrv keeps what fits and drops the rest */
    if (buflen > iopAvailable())
        buflen = iopAvailable();
    while (buflen > 0) {
        int copy = buflen, i;
        if (writepos >= readpos && ringbufSize - writepos < buflen)
            copy = ringbufSize - writepos;
        memcpy(ringbuf + writepos, buf, copy);
        for (i = 0; i < copy; i++)
            if ((unsigned char)buf[i] != expect++)
                orderBroken = 1;
        buf += copy;
        buflen -= copy;
        sent += copy;
        writepos += copy;
        if (writepos >= ringbufSize)
            writepos = 0;
    }
    written += sent;
    fill += sent;
    if (fill > ringbufSize)
        overfills++;
    return sent;
}

@WAIT@
@QUEUE@

static void startStream(int freq, int channels)
{
    iopSetFormat(freq, channels);
    bgmBytesPerMs = (freq * channels * 2) / 1000;
    {
@SIZING@
    }
    terminateFlag = 0;
    terminateAtUs = -1;
    spuStalled = 0;
    nowUs = nextBlockUs = 0;
    rpcs = underruns = overAsks = overfills = badDelays = written = 0;
    stallLogs = orderBroken = 0;
    expect = 0;
}

static char chunk[BGM_RING_BUFFER_SIZE];
static unsigned char seq;

static int queueNext(void)
{
    int i;
    for (i = 0; i < BGM_RING_BUFFER_SIZE; i++)
        chunk[i] = (char)seq++;
    return bgmQueueChunk(chunk);
}

static int fails;

static void expectThat(int ok, const char *what, int freq, int channels, long long got)
{
    if (!ok) {
        printf("FAIL %d Hz %d ch: %s (got %lld)\n", freq, channels, what, got);
        fails++;
    }
}

static void steady(int freq, int channels)
{
    int chunks, i, done = 1;
    long long audioMs;

    seq = 0;
    startStream(freq, channels);
    chunks = (2500 * bgmBytesPerMs) / BGM_RING_BUFFER_SIZE + 1; /* 2.5 s of music */
    for (i = 0; i < chunks && done; i++)
        done = queueNext();
    audioMs = ((long long)chunks * BGM_RING_BUFFER_SIZE) / bgmBytesPerMs;

    expectThat(done, "a chunk was never queued", freq, channels, i);
    expectThat(written == (long long)chunks * BGM_RING_BUFFER_SIZE, "bytes queued", freq, channels, written);
    expectThat(!orderBroken, "the stream reached audsrv out of order", freq, channels, 0);
    expectThat(overAsks == 0, "asked audsrv to queue more than its room (it drops the excess)", freq, channels, overAsks);
    expectThat(underruns == 0, "the ring ran dry while the decoder kept up", freq, channels, underruns);
    expectThat(overfills == 0, "overwrote music that had not played yet", freq, channels, overfills);
    expectThat(stallLogs == 0, "reported a stall on a healthy stream", freq, channels, stallLogs);
    expectThat(badDelays == 0, "slept for zero or less", freq, channels, badDelays);
    expectThat(rpcs * 1000 <= audioMs * 400, "audsrv RPCs per second of music", freq, channels, rpcs * 1000 / audioMs);
    printf("%5d Hz %d ch: ring %5d, target %4d, %lld RPC/s, %d chunks OK\n", freq, channels, ringbufSize,
           bgmRoomTarget, rpcs * 1000 / audioMs, chunks);
}

static void stalled(int freq, int channels)
{
    long long before, rpcsBefore;
    int i, done = 1;

    seq = 0;
    startStream(freq, channels);
    for (i = 0; i < 8 && done; i++)
        done = queueNext();
    spuStalled = 1; /* SPU2 stops completing transfers: the ring never drains again */
    before = nowUs;
    rpcsBefore = rpcs;
    terminateAtUs = nowUs + 3000000;
    while (done)
        done = queueNext();

    expectThat(nowUs - terminateAtUs <= BGM_ROOM_STALL_US, "microseconds past termination", freq, channels,
               nowUs - terminateAtUs);
    expectThat(stallLogs == 1, "stall reports", freq, channels, stallLogs);
    expectThat(rpcs - rpcsBefore <= BGM_ROOM_STALL_POLLS + 3000000 / BGM_ROOM_STALL_US + 16,
               "audsrv RPCs during a 3 s stall", freq, channels, rpcs - rpcsBefore);
    expectThat(overAsks == 0, "asked audsrv to queue more than its room", freq, channels, overAsks);
    printf("%5d Hz %d ch: 3 s SPU2 stall -> %lld RPCs, stopped %lld us after termination\n", freq, channels,
           rpcs - rpcsBefore, nowUs - terminateAtUs);
    (void)before;
}

int main(void)
{
    /* Every 16-bit format ps2sdk's audsrv upsamplers accept; BGM always decodes 16-bit. */
    static const int formats[][2] = {{11025, 1}, {11025, 2}, {12000, 2}, {22050, 1}, {22050, 2}, {24000, 2},
                                     {32000, 1}, {32000, 2}, {44100, 1}, {44100, 2}, {48000, 1}, {48000, 2}};
    unsigned i;

    setvbuf(stdout, NULL, _IONBF, 0);
    for (i = 0; i < sizeof(formats) / sizeof(formats[0]); i++)
        steady(formats[i][0], formats[i][1]);
    stalled(44100, 2);
    stalled(11025, 1);
    return fails != 0;
}
'''


def run_ring_harness():
    if wait is None or queue is None or sizing is None:
        return
    program = (HARNESS.replace('@DEFINES@', defines).replace('@WAIT@', wait).replace('@QUEUE@', queue)
               .replace('@SIZING@', sizing.group(0)))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'bgm_ring.c'
        exe = Path(tmp) / 'bgm_ring'
        src.write_text(program)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(src)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('bgm ring harness did not compile:\n%s' % result.stderr)
            return
        try:
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            failures.append('bgm ring harness did not finish in 60 s')
            return
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('bgm ring harness failed:\n%s%s' % (result.stdout, result.stderr))


run_ring_harness()

if failures:
    print('Audio thread checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('audio threads: no open-ended audsrv wait; every audsrv format streams')
