"""Backend fixes ported from RIPPS2 (akilluminati47/RIPPS2, builds 114-115).

1. POPS files: vcdConfirmPopsFiles lets a launch through only when POPS_IOX.PAK and POPS.PAK or POPS.ELF
   are beside the game, and otherwise asks, naming what is missing.
2. IOP reset: reset() makes every source forget its "module loaded" latches, so the next initAllSupport
   loads iLink, MX4SIO, ATA, PCCF, UDPBD, HDD, MMCE and UDPFS again (they stayed dead after the NBD server).
3. FreeType: neither FT_Init_FreeType nor FT_Done_FreeType is called; both live in ftinit.c with every
   module's table and would link them all back in.
4. MMCE Game ID: the send waits to SEE the card go busy before it trusts "not busy".
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
#define _l(x) "missing=[%s] in %s%s"
#define _STR_POPS_FILES_MISSING 0
static char vcdSep(const char *p) { (void)p; return '/'; }
static char last[512];
static int answer, asked;
static int guiMsgBox(const char *s, int confirm, void *unused) { (void)unused; asked++; snprintf(last, sizeof(last), "%s", s); return confirm ? answer : 0; }
int vcdConfirmPopsFiles(const char *root);
''' + block + r'''
static void put(const char *name) { char p[64]; snprintf(p, sizeof(p), "POPS/%s", name); FILE *f = fopen(p, "wb"); fputs("x", f); fclose(f); }
static void clear(void) { const char *n[] = {"POPS_IOX.PAK", "POPS.ELF", "POPS.PAK", "IOPRP252.IMG"}; char p[64]; for (int i = 0; i < 4; i++) { snprintf(p, sizeof(p), "POPS/%s", n[i]); unlink(p); } }
int main(void) {
    mkdir("POPS", 0777);
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
    clear(); put("POPS.PAK");
    asked = 0; assert(vcdConfirmPopsFiles("./") == 0 && strstr(last, "[POPS_IOX.PAK]"));
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ripps2-port-') as temp:
    src = Path(temp) / 'pops.c'
    src.write_text(program)
    exe = Path(temp) / 'pops.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=temp, check=True)
print('ok   POPS files: both sets pass, a missing set asks and names what is missing')

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
