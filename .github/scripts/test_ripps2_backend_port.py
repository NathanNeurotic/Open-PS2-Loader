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
defines = ''.join(line + '\n' for line in mmce.splitlines() if line.startswith(('#define MMCE_GAMEID_START', '#define MMCE_GAMEID_QUERY', '#define MMCE_CARD_READY')))
loop = send[send.index('    int queryFailures = 0;'):]
mmce_program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define LOG(...) ((void)0)
#define diagLog(...) ((void)0)
#define KEY_START 1
#define _STR_MMCE_GAMEID_CARD_WAIT 0
''' + defines + r'''
static int script[512], scriptLen, calls, startPressed, slept;
static int fileXioDevctl(const char *d, int cmd, void *a, unsigned al, void *b, unsigned bl)
{
    (void)d; (void)a; (void)al; (void)b; (void)bl;
    assert(cmd == 0x2);
    int i = calls++;
    return i < scriptLen ? script[i] : script[scriptLen - 1];
}
static void readPads(void) {}
static int getKeyOn(int key) { (void)key; return startPressed; }
static const char *_l(int id) { (void)id; return "%d"; }
static void guiRenderTextScreen(const char *s) { (void)s; }
static void DelayThread(int us) { slept += us; }
''' + wait + r'''
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
    assert(run(noQuery, 1) == -1 && calls == MMCE_GAMEID_QUERY_FAILURES); /* no busy query: unconfirmed, quickly */
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
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ripps2-mmce-') as temp:
    src = Path(temp) / 'mmce.c'
    src.write_text(mmce_program)
    exe = Path(temp) / 'mmce.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   MMCE Game ID: failed busy queries are retried and never read as ready')

new_library = fnt[fnt.index('static FT_Error fntNewLibrary('):]
new_library = new_library[:new_library.index('\n}\n')]
add_fail = new_library[new_library.index('FT_Add_Module('):]
assert add_fail.index('FT_Done_Library(*library);') < add_fail.index('*library = NULL;') < add_fail.index('return error;'), \
    'a failed FT_Add_Module must not leave a freed library for fntEnd'
print('ok   FreeType: a failed module add leaves no library for fntEnd to free again')
