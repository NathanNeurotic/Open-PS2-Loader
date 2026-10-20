"""The newest confirm / cancel / message / transition press cuts the one-shot still sounding (#504).

audsrv can neither replace nor stop an adpcm voice: ps2sdk's iop/sound/audsrv/src/adpcm.c
audsrv_ch_play_adpcm() returns -AUDSRV_ERR_NO_MORE_CHANNELS for a voice whose ENDX bit is clear (the
sample has not ended) and plays nothing, and there is no key-off RPC. With one voice per sound a
second confirm inside confirm's ~0.8 s was silent -- the "cooldown" in #504 -- and confirm then
cancel layered. The one-shots now play on a pool of voices and a press cuts the previous one by
muting its voice.

Part 1 pins the shape statically: the pool's voices belong to nobody else, sfxPlay sends the four
one-shots through the frame coalesce and then sfxPlayOneShot, sfxInit resets the pool after
audsrv_adpcm_init(), and audioSetVolume never sets a pool voice's volume behind the pool's back.

Part 2 compiles the pool functions from src/sound.c on the host and runs presses against a model of
the IOP voices. After every press the newest sound must be the only one-shot heard, a cut sound must
never be heard again, a press must cost one RPC when nothing is sounding, and length estimates that
are wrong either way (a theme's 22 or 48 kHz sound) must not change the outcome.
"""
from pathlib import Path
import os
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
header = (root / 'include/sound.h').read_text(encoding='utf-8').replace('\r\n', '\n')

# ---- Part 1: static shape ----

enum = re.search(r'enum SFX \{(.*?)\};', header, re.S)
names = [n.split('=')[0].strip() for n in re.sub(r'//[^\n]*', '', enum.group(1)).split(',') if n.strip()]
ids = {name: i for i, name in enumerate(names)}

voices_match = re.search(r'^static const u8 oneShotVoices\[\] = \{([^}]*)\};', sound, re.M)
cursor_count = re.search(r'^#define CURSOR_SFX_CHANNEL_COUNT\s+(\d+)', sound, re.M)
if voices_match is None or cursor_count is None:
    failures.append('src/sound.c: oneShotVoices[] or CURSOR_SFX_CHANNEL_COUNT not found')
    pool = []
else:
    pool = [int(v) for v in voices_match.group(1).split(',')]
    cursor = set(range(ids['SFX_COUNT'], ids['SFX_COUNT'] + int(cursor_count.group(1))))
    owned = {0: 'the boot sound', ids['SFX_BD_CONNECT']: 'SFX_BD_CONNECT', ids['SFX_BD_DISCONNECT']: 'SFX_BD_DISCONNECT'}
    owned.update({v: 'the cursor rotation' for v in cursor})
    for v in pool:
        if not 0 <= v < 24:
            failures.append('oneShotVoices: voice %d is not one of SPU2 core 1\'s 24' % v)
        elif v in owned:
            failures.append('oneShotVoices: voice %d belongs to %s' % (v, owned[v]))
    if len(set(pool)) != len(pool):
        failures.append('oneShotVoices: a voice is listed twice')
    if len(pool) > 32:
        failures.append('oneShotVoices: more voices than oneShotMuted has bits')
    # Fast presses must not run out of voices against the longest built-in one-shot (1.07 s
    # transition): presses 72 ms apart need every slot.
    if len(pool) * 72 < 1071:
        failures.append('oneShotVoices: %d voices cannot keep up with presses 72 ms apart' % len(pool))

play = function_text(sound, 'void sfxPlay(')
branch = re.search(r'else if \(sfxIsUiOneShot\(id\)\) \{(.*?)\n        \} else \{', play or '', re.S)
if branch is None:
    failures.append('sfxPlay: the four one-shots must have their own branch')
elif not re.search(r'SFX_ONESHOT_COALESCE_MS\)\s*return;.*sfxPlayOneShot\(id, sfxStartTicks\);', branch.group(1), re.S):
    failures.append('sfxPlay: a one-shot must pass the frame coalesce (#575) and then play through sfxPlayOneShot')

init = function_text(sound, 'int sfxInit(')
order = [init.find(token) if init else -1 for token in ('audsrv_adpcm_init()', 'sfxResetOneShots()', 'audioSetVolume()')]
if -1 in order or order != sorted(order):
    failures.append('sfxInit: must reset the one-shot pool after audsrv_adpcm_init() keys every voice off, '
                    'before audioSetVolume()')

volume = function_text(sound, 'void audioSetVolume(')
if volume is None or 'sfxSetOneShotVoicesVolume(gSFXVolume)' not in volume:
    failures.append('audioSetVolume: must set the pool through sfxSetOneShotVoicesVolume()')
else:
    for v in pool:
        if re.search(r'audsrv_adpcm_set_volume\(\s*%d\s*,' % v, volume) or re.search(r'for \(i = 1; i < SFX_COUNT', volume):
            failures.append('audioSetVolume: sets pool voice %d directly, which would un-mute a cut sound' % v)
            break

# ---- Part 2: the pool against a model of audsrv's voices ----

pieces = []
for pattern in (r'^#define SFX_ONESHOT_VOICE_COUNT .*$', r'^static (?:int|unsigned int|u32) oneShot\w+ = 0;.*$'):
    pieces += re.findall(pattern, sound, re.M)
for signature in ('static void sfxResetOneShots(', 'static void sfxSetOneShotVoicesVolume(',
                  'static void sfxCutOneShot(', 'static void sfxPlayOneShot('):
    text = function_text(sound, signature)
    if text is None:
        failures.append('src/sound.c: %s) not found' % signature)
    pieces.append(text or '')

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>

typedef unsigned char u8;
typedef unsigned int u32;

#define AUDSRV_ERR_ARGS             0x0005
#define AUDSRV_ERR_NO_MORE_CHANNELS 0x0007
#define SFX_CLOCKS_PER_MS           147456

enum { SFX_BOOT, SFX_CANCEL, SFX_CONFIRM, SFX_CURSOR, SFX_MESSAGE, SFX_TRANSITION, SFX_BD_CONNECT, SFX_BD_DISCONNECT, SFX_COUNT };

typedef struct { int unused; } audsrv_adpcm_t;
static audsrv_adpcm_t sfx[SFX_COUNT];
static struct { int duration_ms; } sfx_files[SFX_COUNT];
static int gSFXVolume = 90;

/* ---- model: ps2sdk iop/sound/audsrv/src/adpcm.c, one SPU2 core 1 voice each ---- */
static const int builtinMs[SFX_COUNT] = {3671, 436, 834, 80, 848, 1071, 452, 903}; /* the built-in audio/ files */
static int realMs[SFX_COUNT], loaded[SFX_COUNT];
static long long nowUs;
static u32 tickBase;
static int press, rpcs, fails;
static const char *scenario;
static struct {
    long long endUs;
    int vol, press, cut;
} voice[24];

#define FAIL(...) do { printf("FAIL [%s] press %d: ", scenario, press); printf(__VA_ARGS__); printf("\n"); fails++; } while (0)

static int inPool(int ch);

static int audsrv_ch_play_adpcm(int ch, audsrv_adpcm_t *adpcm)
{
    int id = (int)(adpcm - sfx);

    rpcs++;
    if (!inPool(ch))
        FAIL("played on voice %d, outside the one-shot pool", ch);
    if (!loaded[id])
        return AUDSRV_ERR_ARGS; /* sic: positive */
    if (ch < 0 || ch >= 24)
        return -AUDSRV_ERR_ARGS;
    if (nowUs < voice[ch].endUs)
        return -AUDSRV_ERR_NO_MORE_CHANNELS; /* ENDX clear: the voice is still running its sample */
    voice[ch].endUs = nowUs + realMs[id] * 1000LL;
    voice[ch].press = press;
    voice[ch].cut = 0;
    return ch;
}

static void setVolume(int ch, int vol)
{
    rpcs++;
    if (!inPool(ch))
        FAIL("set the volume of voice %d, outside the one-shot pool", ch);
    if (nowUs < voice[ch].endUs) {
        if (vol == 0)
            voice[ch].cut = 1;
        else if (voice[ch].cut)
            FAIL("voice %d un-muted while its cut sound (press %d) is still running", ch, voice[ch].press);
    }
    voice[ch].vol = vol;
}
#define audsrv_adpcm_set_volume(ch, vol) setVolume(ch, vol)

@POOL@

static int inPool(int ch)
{
    for (int i = 0; i < SFX_ONESHOT_VOICE_COUNT; i++)
        if (oneShotVoices[i] == ch)
            return 1;
    return 0;
}

static void begin(const char *name, int scale100, u32 ticks)
{
    scenario = name;
    press = 0;
    nowUs = 0;
    tickBase = ticks;
    for (int i = 0; i < 24; i++) {
        voice[i].endUs = 0;
        voice[i].vol = 0x3fff; /* audsrv_adpcm_init() */
        voice[i].press = -1;
        voice[i].cut = 0;
    }
    for (int i = 0; i < SFX_COUNT; i++) {
        sfx_files[i].duration_ms = builtinMs[i]; /* what sfxLoad estimates at 44.1 kHz */
        realMs[i] = builtinMs[i] * scale100 / 100;
        loaded[i] = 1;
    }
    gSFXVolume = 90;
    sfxResetOneShots();
    sfxSetOneShotVoicesVolume(gSFXVolume); /* audioSetVolume() */
}

static int audibleCount(int *newest)
{
    int n = 0;
    *newest = 0;
    for (int i = 0; i < SFX_ONESHOT_VOICE_COUNT; i++) {
        int ch = oneShotVoices[i];
        if (nowUs < voice[ch].endUs && voice[ch].vol > 0) {
            n++;
            if (voice[ch].press == press)
                *newest = 1;
        }
    }
    return n;
}

/* One press at `ms`. mustSound: the newest sound has to be the one heard. */
static void hit(int id, long long ms, int mustSound)
{
    int newest, n;

    press++;
    nowUs = ms * 1000;
    rpcs = 0;
    sfxPlayOneShot(id, tickBase + (u32)(nowUs * SFX_CLOCKS_PER_MS / 1000));
    n = audibleCount(&newest);
    if (n > 1)
        FAIL("%d one-shots heard at once; the newest press must cut the rest", n);
    if (mustSound && (n != 1 || !newest))
        FAIL("the newest press is not the sound heard (heard %d, newest %s)", n, newest ? "yes" : "no");
    if (rpcs > 2 * SFX_ONESHOT_VOICE_COUNT + 1)
        FAIL("%d audsrv RPCs for one press", rpcs);
}

int main(void)
{
    static const int cycle[] = {SFX_CONFIRM, SFX_TRANSITION, SFX_CANCEL, SFX_MESSAGE, SFX_CONFIRM, SFX_CONFIRM};
    long long t;
    int i;

    setvbuf(stdout, NULL, _IONBF, 0);

    begin("idle press", 100, 0);
    hit(SFX_CONFIRM, 1000, 1);
    if (rpcs != 1)
        FAIL("a press with nothing sounding took %d RPCs, not 1", rpcs);
    hit(SFX_CANCEL, 5000, 1);
    if (rpcs != 1)
        FAIL("a press after the last sound ended took %d RPCs, not 1", rpcs);

    begin("confirm twice inside confirm", 100, 0);
    hit(SFX_CONFIRM, 1000, 1);
    hit(SFX_CONFIRM, 1300, 1); /* #504: this one used to be silent */
    hit(SFX_CONFIRM, 1600, 1);

    begin("confirm then cancel", 100, 0);
    hit(SFX_CONFIRM, 1000, 1);
    hit(SFX_CANCEL, 1200, 1);
    hit(SFX_TRANSITION, 1400, 1);
    hit(SFX_MESSAGE, 1500, 1);

    for (int step = 72; step <= 400; step += 41) {
        char name[48];
        snprintf(name, sizeof(name), "mash every %d ms", step);
        begin(name, 100, 0);
        for (i = 0, t = 1000; i < 80; i++, t += step)
            hit(cycle[i % 6], t, 1);
        hit(SFX_CONFIRM, t + 3000, 1);
        if (rpcs != 1)
            FAIL("the first press after a burst took %d RPCs, not 1", rpcs);
    }

    /* A theme's 22.05 kHz sound plays twice as long as the 44.1 kHz estimate; a 48 kHz one shorter. */
    begin("sounds longer than estimated", 200, 0);
    for (i = 0, t = 1000; i < 60; i++, t += 150)
        hit(cycle[i % 6], t, 1);
    begin("sounds shorter than estimated", 50, 0);
    for (i = 0, t = 1000; i < 60; i++, t += 150 + (i % 3) * 200)
        hit(cycle[i % 6], t, 1);

    begin("cpu_ticks wraps mid-burst", 100, 0xFFFFFFFFu - 147456u * 1500u);
    for (i = 0, t = 1000; i < 40; i++, t += 110)
        hit(cycle[i % 6], t, 1);

    /* A volume change while cut sounds are still running must not bring them back. */
    begin("volume change mid-burst", 100, 0);
    for (i = 0, t = 1000; i < 8; i++, t += 120)
        hit(cycle[i % 6], t, 1);
    gSFXVolume = 50;
    sfxSetOneShotVoicesVolume(gSFXVolume);
    for (; i < 30; i++, t += 120) {
        hit(cycle[i % 6], t, 1);
        for (int v = 0; v < SFX_ONESHOT_VOICE_COUNT; v++)
            if (voice[oneShotVoices[v]].press == press && voice[oneShotVoices[v]].vol != 50)
                FAIL("the newest sound plays at volume %d, not the new 50", voice[oneShotVoices[v]].vol);
    }

    /* Every voice busy with a long theme sound: a press may be silent, but never two heard at once. */
    begin("every voice busy", 500, 0);
    for (i = 0, t = 1000; i < 60; i++, t += 60)
        hit(cycle[i % 6], t, 0);

    begin("sample not loaded", 100, 0);
    hit(SFX_CONFIRM, 1000, 1);
    loaded[SFX_CANCEL] = 0;
    hit(SFX_CANCEL, 1200, 0);
    if (rpcs > 2)
        FAIL("an unloaded sample took %d RPCs; it must not walk the pool", rpcs);

    return fails != 0;
}
'''


def run_pool_harness():
    if any(not piece for piece in pieces):
        return
    program = HARNESS.replace('@POOL@', 'static const u8 oneShotVoices[] = {%s};\n' % voices_match.group(1)
                              + '\n'.join(pieces))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'sfx_pool.c'
        exe = Path(tmp) / ('sfx_pool.exe' if os.name == 'nt' else 'sfx_pool')
        src.write_text(program)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(src)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('one-shot pool harness did not compile:\n%s' % result.stderr)
            return
        try:
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            failures.append('one-shot pool harness did not finish in 60 s')
            return
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('one-shot pool harness failed:\n%s%s' % (result.stdout, result.stderr))


if voices_match is not None:
    run_pool_harness()

if failures:
    print('One-shot sound checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('sfx one-shots: the newest press cuts the sound still playing; a cut sound stays silent')
