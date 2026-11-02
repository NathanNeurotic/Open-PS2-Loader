"""Backend fixes ported from RIPPS2 (akilluminati47/RIPPS2, builds 114-115).

1. POPS files: vcdConfirmPopsFiles lets a launch through only when POPS_IOX.PAK and POPS.PAK, or POPS.ELF
   with IOPRP252.IMG, are beside the game, and otherwise asks, naming what is missing. When another started
   drive has a complete set, it first offers to copy over only the files this drive lacks (RIPPOPS, builds
   89 and 115); a declined or failed copy falls back to the ask.
2. IOP reset: reset() makes every source forget its "module loaded" latches, so the next initAllSupport
   loads iLink, MX4SIO, ATA, PCCF, UDPBD, HDD, MMCE and UDPFS again (they stayed dead after the NBD server).
3. FreeType: neither FT_Init_FreeType nor FT_Done_FreeType is called; both live in ftinit.c with every
   module's table and would link them all back in.
4. MMCE Game ID: the send waits to SEE the card go busy before it trusts "not busy"; a failed busy query
   is retried and never reads as "ready" (CodeRabbit on OPL #1084).
5. FreeType: a failed module add leaves no library handle behind for fntEnd to free twice.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
vcd = (root / 'src/vcdsupport.c').read_text()
start = vcd.index('static const char *const vcdPopsFiles[]')
block = vcd[start:vcd.index('static int vcdRaModuleStatus(')]
block = block[:block.rindex('/*')]  # drop vcdRaModuleStatus's own comment

program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#define POPS_FOLDER "POPS"
#define LOG(...) ((void)0)
#define _STR_POPS_FILES_MISSING 0
#define _STR_POPS_COPY_OFFER 1
#define _STR_POPS_COPYING 2
#define _STR_POPS_COPY_FAILED 3
#define MAX_BDM_DEVICES 2
#define BDM_MODE 0
static const char *_l(int id)
{
    static const char *const text[] = {"missing=[%s] in %s%s", "offer from %s: [%s] to %s%s", "copying %s", "failed %s to %s%s"};
    return text[id];
}
static int offered, copied, failCopy, rendered;
static const char *hddFolder = "SRC/POPS/";
static int bdmSlotEverConnected(int mode) { (void)mode; return 0; } /* mass%d:/ is no host path */
static int mmceModulesLoaded(void) { return 0; }
static int hddVisitCommonPops(int (*visit)(const char *folder, void *arg), void *arg) { return visit(hddFolder, arg); }
static int vcdSafeCopyFile(const char *src, const char *dst)
{
    char buf[16];
    size_t n;
    FILE *in, *out;
    if (failCopy)
        return -3;
    in = fopen(src, "rb");
    out = fopen(dst, "wb");
    assert(in && out);
    n = fread(buf, 1, sizeof(buf), in);
    fwrite(buf, 1, n, out);
    fclose(in);
    fclose(out);
    copied++;
    return 0;
}
static char vcdSep(const char *p) { (void)p; return '/'; }
static char last[512];
static int answer, asked;
static int guiMsgBox(const char *s, int confirm, void *unused)
{
    (void)unused;
    asked++;
    if (!strncmp(s, "offer", 5))
        offered++;
    snprintf(last, sizeof(last), "%s", s);
    return confirm ? answer : 0;
}
static void guiRenderTextScreen(const char *s) { (void)s; rendered++; }
int vcdConfirmPopsFiles(const char *root);
''' + block + r'''
static void put(const char *name) { char p[64]; snprintf(p, sizeof(p), "POPS/%s", name); FILE *f = fopen(p, "wb"); fputs("x", f); fclose(f); }
static void putIn(const char *dir, const char *name, const char *text) { char p[64]; snprintf(p, sizeof(p), "%s%s", dir, name); FILE *f = fopen(p, "wb"); fputs(text, f); fclose(f); }
static int has(const char *name, const char *text) { char p[64], got[8] = ""; snprintf(p, sizeof(p), "POPS/%s", name); FILE *f = fopen(p, "rb"); if (!f) return 0; if (!fgets(got, sizeof(got), f)) got[0] = 0; fclose(f); return !strcmp(got, text); }
static void clearIn(const char *dir) { const char *n[] = {"POPS_IOX.PAK", "POPS.ELF", "POPS.PAK", "IOPRP252.IMG"}; char p[64]; for (int i = 0; i < 4; i++) { snprintf(p, sizeof(p), "%s%s", dir, n[i]); unlink(p); } }
static void clear(void) { const char *n[] = {"POPS_IOX.PAK", "POPS.ELF", "POPS.PAK", "IOPRP252.IMG"}; char p[64]; for (int i = 0; i < 4; i++) { snprintf(p, sizeof(p), "POPS/%s", n[i]); unlink(p); } }
int main(void) {
    mkdir("POPS", 0777);
    mkdir("SRC", 0777);
    mkdir("SRC/POPS", 0777);
    answer = 0;
    asked = 0; assert(vcdConfirmPopsFiles("") == 1 && asked == 0);             /* no root: nothing to check */
    asked = 0; assert(vcdConfirmPopsFiles("./") == 0 && asked == 1);           /* nothing there: asked, declined */
    assert(strstr(last, "POPS_IOX.PAK") && strstr(last, "POPS.PAK / POPS.ELF + IOPRP252.IMG"));
    answer = 1; assert(vcdConfirmPopsFiles("./") == 1); answer = 0;            /* launch anyway */
    put("POPS_IOX.PAK");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 0 && !strstr(last, "POPS_IOX.PAK"));
    put("POPS.PAK");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 1 && asked == 0);           /* set 1: IOX + PAK */
    clear(); put("POPS_IOX.PAK"); put("POPS.ELF"); put("IOPRP252.IMG");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 1 && asked == 0);           /* set 2: IOX + ELF + IMG */
    clear(); put("POPS_IOX.PAK"); put("POPS.ELF");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 0 && asked == 1);           /* ELF needs its IOPRP252.IMG */
    assert(strstr(last, "[IOPRP252.IMG]"));
    clear(); put("POPS.PAK");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 0 && strstr(last, "[POPS_IOX.PAK]"));
    assert(offered == 0 && copied == 0);                                        /* no source anywhere: no offer */

    /* RIPPOPS: another drive has a set. Only what this drive lacks is offered and copied; nothing is overwritten */
    clear(); put("POPS.PAK");
    putIn("SRC/POPS/", "POPS_IOX.PAK", "y"); putIn("SRC/POPS/", "POPS.PAK", "y"); putIn("SRC/POPS/", "POPS.ELF", "y");
    putIn("SRC/POPS/", "IOPRP252.IMG", "y");
    answer = 1; asked = 0;
    assert(vcdConfirmPopsFiles("./") == 1 && asked == 1 && offered == 1 && copied == 3 && rendered == 3);
    assert(strstr(last, "offer from SRC/POPS/: [POPS_IOX.PAK, POPS.ELF, IOPRP252.IMG] to ./POPS"));
    assert(has("POPS_IOX.PAK", "y") && has("POPS.ELF", "y") && has("IOPRP252.IMG", "y") && has("POPS.PAK", "x"));

    /* declined: nothing copied, then the usual ask */
    clear(); offered = copied = 0; answer = 0; asked = 0;
    assert(vcdConfirmPopsFiles("./") == 0 && asked == 2 && offered == 1 && copied == 0 && strstr(last, "missing=["));
    assert(!has("POPS_IOX.PAK", "y"));

    /* a copy that fails: told, then the usual ask names what is still missing */
    clear(); offered = 0; answer = 1; failCopy = 1; asked = 0;
    assert(vcdConfirmPopsFiles("./") == 1 && asked == 3 && offered == 1); /* offer, failure, ask (answered launch) */
    failCopy = 0;

    /* an incomplete set elsewhere (no POPS_IOX.PAK) is no source */
    clear(); clearIn("SRC/POPS/"); putIn("SRC/POPS/", "POPS.PAK", "y"); offered = 0; answer = 0; asked = 0;
    assert(vcdConfirmPopsFiles("./") == 0 && asked == 1 && offered == 0);

    /* this drive is never its own source */
    clear(); put("POPS.PAK"); hddFolder = "./POPS/"; putIn("SRC/POPS/", "POPS_IOX.PAK", "y"); offered = 0; asked = 0;
    assert(vcdConfirmPopsFiles("./") == 0 && offered == 0);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ripps2-port-') as temp:
    src = Path(temp) / 'pops.c'
    src.write_text(program)
    exe = Path(temp) / 'pops.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=temp, check=True)
print('ok   POPS files: both sets pass, another drive\'s set is offered and copied, a missing set asks')

opl = (root / 'src/opl.c').read_text()
body = opl[opl.index('static void reset(void)\n{'):]
body = body[:body.index('\n}\n')]
for hook in ('bdmIopWasReset', 'hddIopWasReset', 'mmceIopWasReset', 'udpfsIopWasReset'):
    assert hook + '();' in body, hook + ' is not called from reset()'
bdm = (root / 'src/bdmsupport.c').read_text()
bdmReset = bdm[bdm.index('void bdmIopWasReset(void)'):]
bdmReset = bdmReset[:bdmReset.index('\n}\n')]
for latch in ('iUSBModLoaded', 'iLinkModLoaded', 'iLinkManModLoaded', 'ieee1394ModLoaded', 'mx4sioModLoaded',
              'pccfModLoaded', 'hddModLoaded', 'udpbdModLoaded', 'udpbdNicClaimed'):
    assert latch in bdmReset, latch + ' survives an IOP reset'
print('ok   reset() clears every source module latch')

fnt = (root / 'src/fntsys.c').read_text()
code = re.sub(r'//[^\n]*', '', fnt)
assert 'FT_Init_FreeType(' not in code and 'FT_Done_FreeType(' not in code, 'ftinit.c would link every FreeType module'
for module in ('tt_driver_class', 'cff_driver_class', 'sfnt_module_class', 'ft_smooth_renderer_class'):
    assert '&' + module in code, module + ' is not registered'
print('ok   FreeType registers only the TrueType/CFF modules')

mmce = (root / 'src/mmcesupport.c').read_text()
send = mmce[mmce.index('int mmceSendGameID('):]
send = send[:send.index('\n}\n')]
assert 'MMCE_GAMEID_START_MS' in send and 'mmceWaitCardReady(' in send, 'Game ID send no longer waits to see the switch start'
print('ok   MMCE Game ID waits for the switch to start, then for the card')

# The latches are cleared, not just named: run bdmIopWasReset with every latch set.
latches = ('iUSBModLoaded', 'iLinkModLoaded', 'iLinkManModLoaded', 'ieee1394ModLoaded', 'mx4sioModLoaded',
           'pccfModLoaded', 'hddModLoaded', 'udpbdModLoaded', 'udpbdNicClaimed')
reset_program = '#include <assert.h>\nstatic int ' + ', '.join(l + ' = 1' for l in latches) + \
    ', pccfProbeGeneration, udpbdLoadedProtocol = 1;\n' + bdmReset + '\n}\nint main(void)\n{\n    bdmIopWasReset();\n' + \
    ''.join('    assert(%s == 0);\n' % l for l in latches) + \
    '    assert(udpbdLoadedProtocol == -1 && pccfProbeGeneration == 1);\n    bdmIopWasReset();\n' + \
    '    assert(pccfProbeGeneration == 1); /* CF probes again only when the reset unloaded it */\n    return 0;\n}\n'
with tempfile.TemporaryDirectory(prefix='ripps2-reset-') as temp:
    src = Path(temp) / 'reset.c'
    src.write_text(reset_program)
    exe = Path(temp) / 'reset.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   bdmIopWasReset clears every latch and asks CF to probe again')

# MMCE Game ID, run against scripted busy-query answers (-1 = the devctl failed).
wait = mmce[mmce.index('static int mmceWaitCardReady('):]
wait = wait[:wait.index('\n}\n') + 3]
swapOn = mmce[mmce.index('static int mmceWaitSwapDoneOn('):]
swapOn = swapOn[:swapOn.index('\n}\n') + 3]
swap = mmce[mmce.index('void mmceWaitSwapDone('):]
swap = swap[:swap.index('\n}\n') + 3]
hist = mmce[mmce.index('int mmceWaitHistorySwitch('):]
hist = hist[:hist.index('\n}\n') + 3]
handoff = mmce[mmce.index('static int mmceWaitBeforeHandoff('):]
handoff = handoff[:handoff.index('\n}\n') + 3]
settle = mmce[mmce.index('int mmceGameIdSettle('):]
settle = settle[:settle.index('\n}\n') + 3]
slotOf = mmce[mmce.index('static int mmceSlotOf('):]
slotOf = slotOf[:slotOf.index('\n}\n') + 3]
lacks = mmce[mmce.index('static int mmceLacksBusyQuery('):]
lacks = lacks[:lacks.index('\n}\n') + 3]
startKey = mmce[mmce.index('static int mmceStartPressed('):]
startKey = startKey[:startKey.index('\n}\n') + 3]
sleepKey = mmce[mmce.index('static void mmceSleepReadingStart('):]
sleepKey = sleepKey[:sleepKey.index('\n}\n') + 3]
defines = ''.join(line + '\n' for line in mmce.splitlines() if line.startswith(('#define MMCE_GAMEID_START', '#define MMCE_GAMEID_QUERY', '#define MMCE_CARD_READY', '#define MMCE_HISTORY_SWITCH', '#define MMCE_START_SAMPLE')))
loop = send[send.index('    int queryFailures = 0;'):]
mmce_program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define LOG(...) ((void)(0 && printf(__VA_ARGS__)))     /* arguments stay referenced */
#define diagLog(...) ((void)(0 && printf(__VA_ARGS__)))
#define KEY_START 1
#define _STR_MMCE_GAMEID_CARD_WAIT 0
#define _STR_PLEASE_WAIT 1
''' + defines + r'''
static int script[512], scriptLen, calls, startPressed, slept, rendered, acked, noBusyQuery, asked[2], lastAsked = -1;
/* The script is the card's state over time, read by the busy query (0x2). The presence probe (0x1) reads the
   same state: a card whose next busy answer is -1 is silent for everything, so presence fails too and uses
   up that slot -- unless noBusyQuery, a firmware that answers presence but has no busy query at all. -2 is a
   card that answers the presence probe and falls silent before the busy query (the start of a swap, between
   the two commands): presence answers, the busy query fails. Every query is also counted for the slot asked. */
static int fileXioDevctl(const char *d, int cmd, void *a, unsigned al, void *b, unsigned bl)
{
    (void)a; (void)al; (void)b; (void)bl;
    assert(cmd == 0x1 || cmd == 0x2);
    assert(strncmp(d, "mmce", 4) == 0 && (d[4] == '0' || d[4] == '1'));
    asked[d[4] - '0']++;
    lastAsked = d[4] - '0';
    int answer = calls < scriptLen ? script[calls] : script[scriptLen - 1];
    if (cmd == 0x1) {
        if (noBusyQuery || answer != -1)
            return 0;
        calls++;
        return -1;
    }
    calls++;
    return answer < 0 ? -1 : answer;
}
/* START: presses still to come, each read at once (startPressed), or a tap held from tapFrom until tapUntil, in us
   of sleep (slept). readPads samples the pad as pad.c does (the last sample becomes the old one) and getKeyOn is an
   edge between the two: each press is seen once, and a tap that begins and ends between two reads is never seen. */
static int tapFrom = -1, tapUntil = -1, padDown, padWasDown;
static void tap(int from, int until) { tapFrom = from; tapUntil = until; padDown = padWasDown = 0; }
static void readPads(void) { padWasDown = padDown; padDown = tapFrom >= 0 && slept >= tapFrom && slept < tapUntil; }
static int getKeyOn(int key) { (void)key; if (startPressed > 0) { startPressed--; return 1; } return padDown && !padWasDown; }
static const char *_l(int id) { return id == _STR_PLEASE_WAIT ? "Please wait." : "%d"; }
static char lastLine[64]; /* the last frame drawn */
static void guiRenderTextScreen(const char *s) { rendered++; acked += !strcmp(s, "Please wait."); snprintf(lastLine, sizeof(lastLine), "%s", s); }
static void DelayThread(int us) { slept += us; }
''' + r'''
static char mmceGameIdTarget[8] = "mmce0:/";
static int mmceGameIdSwitchSeen;
static char gameRoot[8] = "mmce0:/"; /* the slot the game is on */
static void mmceGetDeviceRoot(char *root, size_t size) { snprintf(root, size, "%s", gameRoot); }
''' + slotOf + lacks + startKey + sleepKey + wait + swapOn + swap + handoff + hist + settle + r'''
static int sendWait(const char *mmceDevice, const char *startup)
{
    (void)startup; /* LOG discards it here */
''' + loop + r'''
}
static int run(const int *answers, int n)
{
    memcpy(script, answers, n * sizeof(int));
    scriptLen = n;
    calls = slept = 0;
    return sendWait("mmce0:/", "SLUS_000.01");
}
int main(void)
{
    const int startsThenReady[] = {0, 1, 1, 0};
    assert(run(startsThenReady, 4) == 1);                  /* seen busy, then ready: confirmed */
    const int neverBusy[] = {0};
    assert(run(neverBusy, 1) == 1);                        /* idle throughout: already this game's card */
    const int noQuery[] = {-1};
    noBusyQuery = 1;
    mmceGameIdSwitchSeen = 0;
    assert(run(noQuery, 1) == -1 && calls == MMCE_GAMEID_QUERY_FAILURES + 1); /* no busy query (asked once more): unconfirmed, quickly */
    assert(mmceGameIdSwitchSeen == 0);
    noBusyQuery = 0;
    /* The same three failures from a card that answers NOTHING are the swap already under way (sd2psXtd
       starts it in the main-loop pass right after the 0x8): waited out, not read as "no busy query". */
    assert(run(noQuery, 1) == -1 && calls > MMCE_GAMEID_QUERY_FAILURES + MMCE_CARD_READY_SILENT_MS / (MMCE_CARD_READY_POLL_US / 1000));
    /* A short silence: the card is back, loading its new card, by the time the presence probe goes out after
       the third failure. Its busy query answers again, so it is the swap, seen and waited out: not "no busy
       query" (which left the switch unseen and the history write's window to be paid on top). */
    const int backAtPresence[] = {-1, -1, -1, 1, 1, 0};
    mmceGameIdSwitchSeen = 0;
    assert(run(backAtPresence, 6) == 1 && calls == 6 && mmceGameIdSwitchSeen == 1);
    mmceGameIdSwitchSeen = 0;
    const int swapBeforeFirstPoll[] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 1, 1, 1, 0};
    assert(run(swapBeforeFirstPoll, 14) == 1 && calls == 14);  /* silent, then loading, then ready: confirmed */
    const int blipThenBusy[] = {-1, 0, -1, 1, 0};
    assert(run(blipThenBusy, 5) == 1);                     /* a failed query is retried, not trusted */
    const int failThenIdle[] = {-1, -1, 0};
    assert(run(failThenIdle, 3) == 1 && calls > 3);        /* failures reset; idle read only after the full budget */
    const int failsMidWait[] = {1, 1, -1};
    assert(run(failsMidWait, 3) == -1);                    /* the query died while busy: not "ready" */
    const int stuckBusy[] = {1};
    assert(run(stuckBusy, 1) == -1);                       /* still busy at the cap: launched unconfirmed */
    startPressed = 1;
    assert(run(stuckBusy, 1) == 1);                        /* START launches at once */
    startPressed = 0;
    /* sd2psXtd 8a20bd9 after a Game ID: idle until its next main-loop pass, then no answer at all while it
       exits, closes, sleeps 500 ms and reopens the card, then busy while the new card loads, then idle. */
    static int sd2psx[64];
    int n = 0;
    sd2psx[n++] = 0;
    for (int i = 0; i < 14; i++)
        sd2psx[n++] = -1; /* 700 ms of silence at the 50 ms start poll */
    for (int i = 0; i < 8; i++)
        sd2psx[n++] = 1;
    sd2psx[n++] = 0;
    assert(run(sd2psx, n) == 1 && calls == n);             /* waits out the swap and the load: confirmed */
    const int silentThenIdle[] = {0, -1, -1, -1, -1, 0};   /* a small card loads between two polls */
    assert(run(silentThenIdle, 6) == 1 && calls == 6);
    const int blipNoSwitch[] = {0, -1, 0};                 /* one failed query after an answer is not a switch */
    assert(run(blipNoSwitch, 3) == 1 && calls > 3);
    const int neverAgain[] = {0, -1};                      /* answered once, then gone for good: bounded */
    assert(run(neverAgain, 2) == -1);
    assert(calls - 1 - MMCE_GAMEID_QUERY_SILENT == MMCE_CARD_READY_SILENT_MS / (MMCE_CARD_READY_POLL_US / 1000));
    const int busySilentBusy[] = {1, -1, -1, -1, 1, 1, 0}; /* silence in the middle of the load */
    assert(run(busySilentBusy, 7) == 1);

    /* The MMCE-hosted legs' pre-handoff wait: presence, then busy, bounded; 1 when a swap was waited out
       (the caller then settles the card's file system), 0 when there was nothing to wait out. */
    const int idleCard[] = {0};
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1; calls = 0;
    mmceWaitSwapDone("test"); assert(calls == 1);                  /* answers and idle: ~0 ms */
    calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == 1); /* nothing waited out: no settle */
    const int stillLoading[] = {1, 1, 0};
    memcpy(script, stillLoading, sizeof(stillLoading)); scriptLen = 3; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 3); /* busy: waited out */
    const int silentThenLoading[] = {-1, -1, 1, 0};
    memcpy(script, silentThenLoading, sizeof(silentThenLoading)); scriptLen = 4; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 4); /* silent, then loading: waited out */
    const int silentThenIdleCard[] = {-1, -1, 0};
    memcpy(script, silentThenIdleCard, sizeof(silentThenIdleCard)); scriptLen = 3; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 3); /* silent, then idle: a swap ended between polls */
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == (MMCE_CARD_READY_SILENT_MS + 199) / 200); /* never answers: bounded */
    noBusyQuery = 1;
    calls = slept = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == 2 && slept == 0); /* presence but no busy query (asked twice): ~0 ms */
    noBusyQuery = 0;
    /* The card answers the presence probe and falls silent before the busy query: the start of its swap, not a
       firmware without the busy query. Waited out like any silence, then reported, so the caller settles. */
    const int fellSilentBetween[] = {-2, -1, 0};
    memcpy(script, fellSilentBetween, sizeof(fellSilentBetween)); scriptLen = 3; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 3);
    const int fellSilentThenLoading[] = {-2, -1, -1, 1, 0};
    memcpy(script, fellSilentThenLoading, sizeof(fellSilentThenLoading)); scriptLen = 5; calls = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 5);
    /* The card's silence is on screen like the rest of its wait (a frame for every look that found it silent),
       and START launches now: 0, so the caller does not settle a card that answers nothing. The press is answered
       at once with one "Please wait." frame. An idle card draws nothing. */
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1; calls = rendered = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == 1 && rendered == 0);
    memcpy(script, silentThenIdleCard, sizeof(silentThenIdleCard)); scriptLen = 3; calls = rendered = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 1 && calls == 3 && rendered == 2);
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1; calls = slept = rendered = acked = 0;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && rendered == (MMCE_CARD_READY_SILENT_MS + 199) / 200);
    calls = slept = rendered = acked = 0;
    startPressed = 1;
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == 1 && slept == 0 && rendered == 1 && acked == 1);
    startPressed = 0;

    /* The last look before the handoff always ends on the game's own slot (its ISO is there). A Game ID send to
       the other slot (two cards, the game's slot covered by its VMC) adds that slot first; it does not replace
       the game's. */
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1;
    strcpy(gameRoot, "mmce0:/");
    strcpy(mmceGameIdTarget, "mmce1:/");
    calls = 0; asked[0] = asked[1] = 0;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 2 && asked[1] == 2 && asked[0] == 2 && lastAsked == 0);
    const int gameSlotSwapping[] = {0, 1, 0}; /* the other slot idle, then the game's slot loading */
    memcpy(script, gameSlotSwapping, sizeof(gameSlotSwapping)); scriptLen = 3; calls = 0;
    assert(mmceWaitBeforeHandoff() == 1 && calls == 3 && lastAsked == 0);
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1;
    strcpy(mmceGameIdTarget, "mmce0:/"); /* the send went to the game's slot: one look */
    calls = 0; asked[0] = asked[1] = 0;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 1 && asked[1] == 0);
    mmceGameIdTarget[0] = '\0'; /* no send this launch (Game ID off): the game's slot */
    calls = 0; asked[0] = asked[1] = 0;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 1 && asked[0] == 2 && asked[1] == 0);
    strcpy(gameRoot, "mmce1:/");
    calls = 0; asked[0] = asked[1] = 0;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 1 && asked[1] == 2 && asked[0] == 0);
    strcpy(gameRoot, "mmce0:/");
    strcpy(mmceGameIdTarget, "mmce0:/");
    /* On screen the two looks are one wait, so one START press ends both (getKeyOn is an edge: read once).
       Pressed during the other slot's look, silent or loading, the game's own slot is still asked, but nothing
       more is waited out: an idle card is nothing to wait for, a silent one launches now (0: no settle), and one
       still loading returns at once, as after START in its own wait (1: the caller settles its file system). The
       press is answered once ("Please wait."), not once per look. */
    strcpy(mmceGameIdTarget, "mmce1:/");
    const int otherSilentGameIdle[] = {-1, 0};
    memcpy(script, otherSilentGameIdle, sizeof(otherSilentGameIdle)); scriptLen = 2;
    calls = rendered = acked = 0; asked[0] = asked[1] = 0;
    startPressed = 1;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 2 && asked[1] == 1 && asked[0] == 2 && lastAsked == 0 && rendered == 1 && acked == 1);
    const int bothSilent[] = {-1, -1};
    memcpy(script, bothSilent, sizeof(bothSilent)); scriptLen = 2;
    calls = slept = rendered = acked = 0; asked[0] = asked[1] = 0;
    startPressed = 1;
    assert(mmceWaitBeforeHandoff() == 0 && calls == 2 && asked[1] == 1 && asked[0] == 1 && lastAsked == 0 && slept == 0 && rendered == 1 && acked == 1);
    const int otherLoadingGameSilent[] = {1, 1, -1};
    memcpy(script, otherLoadingGameSilent, sizeof(otherLoadingGameSilent)); scriptLen = 3;
    calls = slept = rendered = acked = 0; asked[0] = asked[1] = 0;
    startPressed = 1;
    assert(mmceWaitBeforeHandoff() == 1 && calls == 3 && asked[1] == 3 && asked[0] == 1 && lastAsked == 0 && slept == 0 && rendered == 1 && acked == 1);
    const int otherSilentGameLoading[] = {-1, 1};
    memcpy(script, otherSilentGameLoading, sizeof(otherSilentGameLoading)); scriptLen = 2;
    calls = slept = rendered = acked = 0; asked[0] = asked[1] = 0;
    startPressed = 1;
    assert(mmceWaitBeforeHandoff() == 1 && calls == 3 && asked[1] == 1 && asked[0] == 3 && lastAsked == 0 && slept == 0 && rendered == 1 && acked == 1);
    /* The press holds for that one handoff only: the next one waits a silence out again. */
    memcpy(script, bothSilent, sizeof(bothSilent)); scriptLen = 2; calls = rendered = acked = 0;
    assert(startPressed == 0 && mmceWaitBeforeHandoff() == 0 && calls == 2 * ((MMCE_CARD_READY_SILENT_MS + 199) / 200) && acked == 0 &&
           rendered == 2 * ((MMCE_CARD_READY_SILENT_MS + 199) / 200));
    strcpy(mmceGameIdTarget, "mmce0:/");

    /* The history-write wait: idle for the whole window, a switch that begins (busy, or silence), skipped. */
    mmceGameIdSwitchSeen = 0;
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1; calls = 0;
    mmceWaitHistorySwitch("mmce0:/", "test"); assert(calls == MMCE_HISTORY_SWITCH_WINDOW_MS / MMCE_HISTORY_SWITCH_POLL_MS); /* no switch: the window */
    const int idleThenBusy[] = {0, 0, 1, 1, 0};
    memcpy(script, idleThenBusy, sizeof(idleThenBusy)); scriptLen = 5; calls = 0;
    mmceWaitHistorySwitch("mmce0:/", "test"); assert(calls == 5);           /* the switch began (busy): waited out */
    const int idleThenSilent[] = {0, -1, -1, -1, -1, 1, 0}; /* the presence probe reads the 4th silent slot */
    memcpy(script, idleThenSilent, sizeof(idleThenSilent)); scriptLen = 7; calls = 0;
    mmceWaitHistorySwitch("mmce0:/", "test"); assert(calls == 7);           /* the switch began (silence), then loading: waited out */
    noBusyQuery = 1;
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1; calls = 0;
    mmceWaitHistorySwitch("mmce0:/", "test"); assert(calls == MMCE_GAMEID_QUERY_FAILURES + 1); /* no busy query (asked once more): not held for the window */
    noBusyQuery = 0;
    /* Three failed queries in the switch's silence, and the card is back (loading) when the presence probe goes
       out: its busy query answers again, so the switch began; it is not "no busy query". */
    const int backBeforePresence[] = {0, -1, -1, -1, 1, 1, 0};
    memcpy(script, backBeforePresence, sizeof(backBeforePresence)); scriptLen = 7; calls = 0;
    assert(mmceWaitHistorySwitch("mmce0:/", "test") == 1 && calls == 7);
    mmceGameIdSwitchSeen = 1;
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1; calls = 0;
    mmceWaitHistorySwitch("mmce0:/", "test"); assert(calls == 0);           /* the Game ID send already switched the card: skipped */
    strcpy(mmceGameIdTarget, "mmce1:/"); /* the send switched the OTHER slot: this card was not switched, watch it */
    calls = 0;
    assert(mmceWaitHistorySwitch("mmce0:/", "test") == 0 && calls == MMCE_HISTORY_SWITCH_WINDOW_MS / MMCE_HISTORY_SWITCH_POLL_MS);
    strcpy(mmceGameIdTarget, "mmce0:/");
    mmceGameIdSwitchSeen = 0;

    /* The MX4SIO leg's settle: settled on an idle card or one without the busy query, not on one that fell silent
       between the presence and busy queries (the swap starting): that one is looked at again. */
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1; calls = slept = 0;
    assert(mmceGameIdSettle(1000) == 0 && calls == 1 && slept == 0);
    memcpy(script, fellSilentBetween, sizeof(fellSilentBetween)); scriptLen = 3; calls = slept = 0;
    assert(mmceGameIdSettle(1000) == 0 && calls == 3 && slept == 200 * 1000);
    noBusyQuery = 1;
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1; calls = slept = 0;
    assert(mmceGameIdSettle(1000) == 0 && calls == 2 && slept == 0);
    noBusyQuery = 0;
    calls = slept = 0;
    assert(mmceGameIdSettle(1000) == -1 && calls == 1000 / 200 + 1); /* never answers: expired, bounded */
    mmceGameIdTarget[0] = '\0';
    calls = 0;
    assert(mmceGameIdSettle(1000) == 0 && calls == 0); /* no send this launch: nothing to settle */
    strcpy(mmceGameIdTarget, "mmce0:/");

    /* START is read about once a frame while a wait sleeps between its looks at the card (getKeyOn is an edge
       between two reads), so a quick tap between two looks still launches, at the next look; the card is still
       asked once per interval. Each press is answered once with "Please wait.". */
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1;
    calls = slept = rendered = acked = 0;
    tap(250 * 1000, 350 * 1000); /* the silent phase looks at 200 and 400 ms */
    assert(mmceWaitSwapDoneOn("mmce0:/", "test", NULL) == 0 && calls == 3 && slept == 260 * 1000 && acked == 1 && !strcmp(lastLine, "Please wait."));
    rendered = acked = 0;
    tap(300 * 1000, 400 * 1000); /* the card wait looks at 250 and 500 ms */
    assert(run(stuckBusy, 1) == 1 && calls == 4 && slept == 310 * 1000 && acked == 1 && !strcmp(lastLine, "Please wait."));
    memcpy(script, idleCard, sizeof(idleCard)); scriptLen = 1;
    calls = slept = rendered = acked = 0;
    mmceGameIdSwitchSeen = 0;
    tap(600 * 1000, 700 * 1000); /* the history window looks at 500 and 750 ms */
    assert(mmceWaitHistorySwitch("mmce0:/", "test") == 0 && calls == 4 && slept == 600 * 1000 && acked == 1);
    /* A tap the history window catches while the card starts its switch: the switch is still reported (1), so
       the caller settles its file system, and its wait launches at once on the held press. */
    const int idleThenBusyAtTap[] = {0, 0, 0, 1};
    memcpy(script, idleThenBusyAtTap, sizeof(idleThenBusyAtTap)); scriptLen = 4;
    calls = slept = rendered = acked = 0;
    tap(600 * 1000, 700 * 1000);
    assert(mmceWaitHistorySwitch("mmce0:/", "test") == 1 && calls == 5 && slept == 600 * 1000 && acked == 1);
    /* The card wait reads START before either bound: a press caught in its last sleep launches (1), even on the
       look that would have ended the wait unconfirmed (-1) or at the cap (0). */
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1;
    calls = slept = rendered = acked = 0;
    tap(7100 * 1000, 7200 * 1000); /* the 30th silent look, at 7250 ms, ends the wait unconfirmed */
    assert(mmceWaitCardReady("mmce0:/", NULL) == 1 && calls == 30 && slept == 7100 * 1000 && acked == 1);
    tap(-1, -1);
    calls = slept = 0;
    assert(mmceWaitCardReady("mmce0:/", NULL) == -1 && calls == 30 && slept == 29 * 250 * 1000);
    memcpy(script, stuckBusy, sizeof(stuckBusy)); scriptLen = 1;
    calls = slept = rendered = acked = 0;
    tap(179900 * 1000, 179950 * 1000); /* the look at 180 s ends the wait at the cap */
    assert(mmceWaitCardReady("mmce0:/", NULL) == 1 && calls == 721 && slept == 179910 * 1000 && acked == 1);
    tap(-1, -1);
    calls = slept = rendered = acked = 0;
    assert(mmceWaitCardReady("mmce0:/", NULL) == 0 && calls == 721 && acked == 0);
    mmceGameIdSwitchSeen = 0;

    /* No slot resolved (Auto mode after the card was taken out): neither wait asks anything or waits. */
    memcpy(script, noQuery, sizeof(noQuery)); scriptLen = 1; calls = slept = 0;
    assert(mmceWaitSwapDoneOn("", "test", NULL) == 0 && calls == 0 && slept == 0);
    assert(mmceWaitHistorySwitch("", "test") == 0 && calls == 0 && slept == 0);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ripps2-mmce-') as temp:
    src = Path(temp) / 'mmce.c'
    src.write_text(mmce_program)
    exe = Path(temp) / 'mmce.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   MMCE Game ID: failed busy queries are retried and never read as ready; a silent card is a swap, waited out on screen before the handoff (START, read about once a frame and before the wait\'s bounds, launches now: one press for both slots, answered at once with "Please wait."); the card\'s own switch after the history write is waited out too')
print('ok   MMCE: "no busy query" only when the card answers presence and fails the busy query again; the handoff look always ends on the game\'s slot; a send to the other slot does not skip the history watch')

# The launch resolves its core, the Neutrino-to-OPL-core fallback included, before the OPL core's preparation:
# a launch that falls back gets the early history write and the card's switch waited out, before any card-side
# file is opened (it used to skip them, and sysLaunchLoaderElf wrote the record right before the IOP reset).
launch = mmce[mmce.index('void mmceLaunchGame('):]
assert launch.count('sbResolveNeutrinoPath(') == 1, 'the MMCE launch resolves neutrino.elf once, before the OPL core preparation'
assert launch.index('sbResolveNeutrinoPath(') < launch.index('_STR_NEUTRINO_NOT_FOUND') < launch.index('if (!coreLoader) {') \
    < launch.index('sbEnsureIgrUsbDrivers(compatmask);') < launch.index('sysAddHistoryRecord(') < launch.index('vmc_fd = fileXioOpen('), \
    'a Neutrino setting that falls back to the OPL core must get the OPL core preparation, history write first'
assert launch.count('sbEnsureIgrUsbDrivers(') == 1, 'one IGR driver check per MMCE launch, before any card switch'
print('ok   MMCE: the core (and its OPL-core fallback) is resolved before the OPL core preparation, so a fallback writes history early too')

new_library = fnt[fnt.index('static FT_Error fntNewLibrary('):]
new_library = new_library[:new_library.index('\n}\n')]
add_fail = new_library[new_library.index('FT_Add_Module('):]
assert add_fail.index('FT_Done_Library(*library);') < add_fail.index('*library = NULL;') < add_fail.index('return error;'), \
    'a failed FT_Add_Module must not leave a freed library for fntEnd'
print('ok   FreeType: a failed module add leaves no library for fntEnd to free again')
