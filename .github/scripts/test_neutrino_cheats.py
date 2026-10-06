"""Cheats on both cores: remembered Select-mode picks (upstream OPL #1748) and the Neutrino hand-over.

Compiles the real src/cheatconfig.c (name-matched picks, master codes always on, stale picks cleared)
and the real hand-over from src/system.c (the codes written as a TOML where Neutrino resolves -cfg=,
config/ or flat layout, a forwarded -cwd= and -cfg= honoured, nothing written for no codes, a raw
hddN: path refused, a failed write asked about -- never on an autolaunch), parses every file it writes
as TOML, then checks the wiring: all four Neutrino legs, the picker, the loader and the settings menu.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

try:
    import tomllib
except ImportError:  # Python < 3.11: the TOML parse is skipped, every other check still runs
    tomllib = None

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        sys.exit('missing ' + signature)
    return source[match.start():source.index('\n}', match.start()) + 2]


system = text('src/system.c')
cheatconfig = text('src/cheatconfig.c')

CONFIG_HARNESS = r'''
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define NUL 0x00
#define SPACE 0x20
#define CHEAT_NAME_MAX 128
#define MAX_CODES 250
#define CONFIG_KEY_NAME_LEN 32
#define CONFIG_KEY_VALUE_LEN 256
#define CONFIG_ITEM_CHEAT_SELECTION_PREFIX "$CheatSel"
typedef struct { char name[CHEAT_NAME_MAX + 1]; int enabled; } cheat_entry_t;
static cheat_entry_t table[MAX_CODES], *gCheats = table;
typedef struct { int n; char key[600][CONFIG_KEY_NAME_LEN]; char val[600][CONFIG_KEY_VALUE_LEN]; } config_set_t;
static int find(config_set_t *c, const char *k) { for (int i = 0; i < c->n; i++) if (!strcmp(c->key[i], k)) return i; return -1; }
static int configGetStrCopy(config_set_t *c, const char *k, char *out, int size) { int i = find(c, k); if (i < 0) return 0; snprintf(out, size, "%s", c->val[i]); return 1; }
static int configRemoveKey(config_set_t *c, const char *k) { int i = find(c, k); if (i < 0) return 0; c->n--; memmove(c->key[i], c->key[i + 1], (c->n - i) * sizeof(c->key[0])); memmove(c->val[i], c->val[i + 1], (c->n - i) * sizeof(c->val[0])); return 1; }
static int configSetStr(config_set_t *c, const char *k, const char *v) { int i = find(c, k); if (i < 0) i = c->n++; snprintf(c->key[i], sizeof(c->key[i]), "%s", k); snprintf(c->val[i], sizeof(c->val[i]), "%s", v); return 1; }

@FUNCTIONS@

static void fill(const char *const *names) { memset(table, 0, sizeof(table)); for (int i = 0; names[i]; i++) snprintf(table[i].name, sizeof(table[i].name), "%s", names[i]); }
static void show(const char *label) { printf("%s:", label); for (int i = 0; table[i].name[0]; i++) printf(" %d", table[i].enabled); printf("\n"); }
static void keys(config_set_t *c) { printf("keys:"); for (int i = 0; i < c->n; i++) printf(" %s=%s", c->key[i], c->val[i]); printf("\n"); }

int main(void)
{
    static config_set_t cfg;
    const char *masters[] = {"Mastercode", "  MASTER   code ", "Enable Code (Must Be On)", "enable code (must be on) ", "Master Code 2", "Infinite Health", "", NULL};
    printf("master:");
    for (int i = 0; masters[i]; i++) printf(" %d", cheatConfigIsMasterCode(masters[i]));
    printf("\n");

    const char *first[] = {"Mastercode", "Infinite Health", "Max Money", "Moon Jump", NULL};
    fill(first);
    for (int i = 0; i < 4; i++) table[i].enabled = 1;
    cheatConfigLoadSelections(NULL);
    show("fresh");                                  /* master on, the rest off */

    table[1].enabled = table[3].enabled = 1;
    cheatConfigSaveSelections(&cfg);
    keys(&cfg);                                     /* names, master never saved */

    const char *reordered[] = {"moon   jump", "Max Money", "MASTER CODE", "Infinite  Health", "New Cheat", NULL};
    fill(reordered);
    cheatConfigLoadSelections(&cfg);
    show("reordered");                              /* matched by name, master forced on */

    for (int i = 0; table[i].name[0]; i++) table[i].enabled = 0;
    table[1].enabled = 1;
    cheatConfigSaveSelections(&cfg);
    keys(&cfg);                                     /* the two older picks are gone */

    configSetStr(&cfg, "$CheatSel001", "Not In This File");
    cheatConfigLoadSelections(&cfg);
    show("unknown");                                /* a saved name no longer present is ignored */

    const char *twice[] = {"Mastercode", "Infinite Ammo", "Infinite Ammo", "Max Money", NULL};
    fill(twice);
    table[1].enabled = table[2].enabled = 1;
    cheatConfigSaveSelections(&cfg);
    cheatConfigLoadSelections(&cfg);
    show("twice");                                  /* a repeated name: each saved copy restores its own */
    return 0;
}
'''

HAND_HARNESS = r'''
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define LOG(...) ((void)0)
#define MAX_CHEATLIST 510
#define _STR_NEUTRINO_CHEATS_WRITE_FAILED 42
typedef unsigned int u32;
struct UIItem;
static char gNeutrinoArgs[256];
static void *gAutoLaunchGame, *gAutoLaunchBDMGame;
static int cheatsEnabled, setCalls, msgCalls, msgAnswer;
static u32 cheatList[MAX_CHEATLIST + 2];
static int GetCheatsEnabled(void) { return cheatsEnabled; }
static void set_cheats_list(void) { setCalls++; }
static const u32 *GetCheatsList(void) { return cheatList; }
static int guiMsgBox(const char *t, int accept, struct UIItem *ui) { (void)t; (void)accept; (void)ui; msgCalls++; return msgAnswer; }
static const char *_l(int id) { (void)id; return ""; }

@FUNCTIONS@

/* neutrinoPath globalArgs extraArgs startup enabled pairs autolaunch answer */
int main(int argc, char **argv)
{
    static int dummy;
    if (argc != 9)
        return 2;
    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "%s", argv[2]);
    cheatsEnabled = atoi(argv[5]);
    int pairs = atoi(argv[6]);
    for (int i = 0; i < pairs; i++) {
        cheatList[i * 2] = 0x20100000u + (u32)i * 4u;
        cheatList[i * 2 + 1] = 0x80000000u | (u32)i;
    }
    gAutoLaunchBDMGame = atoi(argv[7]) ? &dummy : NULL;
    msgAnswer = atoi(argv[8]);
    int r = sysNeutrinoHandCheats(argv[4], argv[1], argv[3]);
    printf("result=%d arg=[%s] for=[%s] msgs=%d set=%d\n", r, sysNeutrinoCheatArg, sysNeutrinoCheatStartup, msgCalls, setCalls);
    return 0;
}
'''

defines = '\n'.join(re.findall(r'^#define NEUTRINO_CHEAT_CFG .*$', system, re.M))
buffers = '\n'.join(re.findall(r'^static char sysNeutrinoCheat(?:Arg|Startup)\[\d+\];.*$', system, re.M))
if 'NEUTRINO_CHEAT_CFG' not in defines or buffers.count('static char') != 2:
    sys.exit('src/system.c: NEUTRINO_CHEAT_CFG or the hand-over buffers not found')
hand = '\n\n'.join([defines, buffers] + [function(system, sig) for sig in (
    'static const char *sysLastPathSeparator(',
    'static int neutrinoArgActiveValue(',
    'static int sysNeutrinoCheatPath(',
    'static int sysNeutrinoCfgNameSafe(',
    'static int sysWriteNeutrinoCheats(',
    'int sysNeutrinoHandCheats(',
)])
picks = '\n\n'.join(function(cheatconfig, sig) for sig in (
    'static void cheatConfigNormalize(',
    'int cheatConfigIsMasterCode(',
    'static int cheatConfigNamesMatch(',
    'void cheatConfigLoadSelections(',
    'void cheatConfigSaveSelections(',
))

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    def build(name, harness, functions):
        src, exe = tmp / (name + '.c'), tmp / name
        src.write_text(harness.replace('@FUNCTIONS@', functions), encoding='utf-8')
        result = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            sys.exit(name + ' did not compile:\n' + result.stderr)
        return exe

    # ---- remembered picks ----------------------------------------------------------------------
    out = subprocess.run([str(build('picks', CONFIG_HARNESS, picks))], capture_output=True, text=True, check=False).stdout.splitlines()
    want = ['master: 1 1 1 1 0 0 0',
            'fresh: 1 0 0 0',
            'keys: $CheatSel000=Infinite Health $CheatSel001=Moon Jump',
            'reordered: 1 0 1 1 0',
            'keys: $CheatSel000=Max Money',
            'unknown: 0 1 1 0 0',
            'twice: 1 1 1 0']
    if out != want:
        failures.append('remembered picks:\n  got  %r\n  want %r' % (out, want))

    # ---- the Neutrino hand-over ----------------------------------------------------------------
    hand_exe = build('hand', HAND_HARNESS, hand)

    def run(neutrino, global_args='', extra='', startup='SLUS_200.62', enabled=1, pairs=3, auto=0, answer=1):
        args = [str(hand_exe), neutrino, global_args, extra, startup, str(enabled), str(pairs), str(auto), str(answer)]
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=60).stdout.strip()

    def toml_of(path):
        body = path.read_text(encoding='utf-8')
        if tomllib is None:
            return body, None
        return body, tomllib.loads(body)

    codes = [v for i in range(3) for v in (0x20100000 + i * 4, 0x80000000 | i)]

    nested = tmp / 'neutrino'
    (nested / 'config').mkdir(parents=True)
    (nested / 'config' / 'system.toml').write_text('# stock\n', encoding='utf-8')
    target = nested / 'config' / 'riptopl-cheats.toml'
    got = run((nested / 'neutrino.elf').as_posix())
    if got != 'result=0 arg=[-cfg=riptopl-cheats] for=[SLUS_200.62] msgs=0 set=1' or not target.exists():
        failures.append('config/ layout: %r, file written: %s' % (got, target.exists()))
    else:
        body, data = toml_of(target)
        if data is not None and (data.get('eecore', {}).get('cheats') != codes or 'SLUS_200.62' not in data.get('name', '') or
                                 'depends' in data):
            failures.append('config/ layout: the TOML does not hold the codes (%r)' % data)
        if '    0x20100004, 0x80000001,\n' not in body:
            failures.append('codes must be written as 8-digit hex pairs, one pair per line:\n' + body)

    flat = tmp / 'flat'
    flat.mkdir()
    got = run((flat / 'neutrino.elf').as_posix())
    if 'arg=[-cfg=riptopl-cheats]' not in got or not (flat / 'riptopl-cheats.toml').exists():
        failures.append('flat layout (no config/system.toml): %r' % got)

    other = tmp / 'other'
    (other / 'config').mkdir(parents=True)
    (other / 'config' / 'system.toml').write_text('# stock\n', encoding='utf-8')
    target.unlink()
    got = run((nested / 'neutrino.elf').as_posix(), global_args='-cwd=' + other.as_posix())
    if 'result=0' not in got or not (other / 'config' / 'riptopl-cheats.toml').exists() or target.exists():
        failures.append('a forwarded -cwd= must decide the folder: %r' % got)
    got = run((nested / 'neutrino.elf').as_posix(), global_args='$-cwd=' + other.as_posix())
    if not target.exists():
        failures.append('a $-disabled -cwd= must be ignored: %r' % got)

    for extra, depends in (('-cfg=mine', ['mine']), ('-cfg=riptopl-cheats', None), ('-cfg=bad"name', None), ('$-cfg=mine', None)):
        target.unlink()
        got = run((nested / 'neutrino.elf').as_posix(), extra=extra)
        if not target.exists():
            failures.append('user %s: nothing written (%r)' % (extra, got))
            continue
        body, data = toml_of(target)
        if data is not None and data.get('depends') != depends:
            failures.append('user %s: depends should be %r, the file says %r' % (extra, depends, data.get('depends')))

    target.unlink()
    got = run((nested / 'neutrino.elf').as_posix(), pairs=0)
    if got != 'result=0 arg=[] for=[] msgs=0 set=1' or target.exists():
        failures.append('every cheat off: nothing to write or name (%r)' % got)
    got = run((nested / 'neutrino.elf').as_posix(), enabled=0)
    if got != 'result=0 arg=[] for=[] msgs=0 set=0' or target.exists():
        failures.append('cheats off: nothing at all (%r)' % got)

    missing = (tmp / 'missing' / 'neutrino.elf').as_posix()
    for answer, auto, want in ((1, 0, 'result=0 arg=[] for=[] msgs=1'), (0, 0, 'result=-1 arg=[] for=[] msgs=1'),
                               (0, 1, 'result=0 arg=[] for=[] msgs=0')):
        got = run(missing, answer=answer, auto=auto)
        if not got.startswith(want):
            failures.append('unwritable folder (answer %d, autolaunch %d): %r, want %r' % (answer, auto, got, want))
    got = run('hdd0:+OPL/neutrino/neutrino.elf')
    if not got.startswith('result=0 arg=[] for=[] msgs=1'):
        failures.append('a raw hddN: path must never be written to: %r' % got)
    if (Path.cwd() / 'hdd0:+OPL').exists():
        failures.append('a raw hddN: path created something on the host')

# ---- the wiring --------------------------------------------------------------------------------

# A host cannot tell the raw-APA refusal from any other failed open, so hold its place: the hddN: test
# comes before the first open() of anything in Neutrino's folder.
path_fn = function(system, 'static int sysNeutrinoCheatPath(')
guard = path_fn.find("!strncmp(dir, \"hdd\", 3) && dir[3] >= '0' && dir[3] <= '9' && dir[4] == ':'")
if guard < 0 or guard > path_fn.find('open('):
    failures.append('system.c: sysNeutrinoCheatPath must refuse a raw hddN: folder before opening anything')

for leg, call in (('src/bdmsupport.c', 'sbNeutrinoLoadCheats('), ('src/hddsupport.c', 'sbNeutrinoLoadCheats('),
                  ('src/mmcesupport.c', 'sysNeutrinoHandCheats('), ('src/udpfssupport.c', 'sysNeutrinoHandCheats(')):
    body = text(leg)
    pre, cheat, args = body.find('sysNeutrinoPreflight('), body.find(call), body.find('sysNeutrinoArgsPreflight(')
    if not (0 <= pre < cheat < args):
        failures.append('%s: the cheats step must run after sysNeutrinoPreflight and before the argv check' % leg)
bdm = text('src/bdmsupport.c')
if not re.search(r'if \(sbNeutrinoLoadCheats\([^;]+\) < 0\) \{\s*failResult = 1;\s*goto fail;', bdm):
    failures.append('bdmsupport.c: backing out of the cheats must return to the menu, never to the other core')
if not re.search(r'if \(sbNeutrinoLoadCheats\([^;]+\) < 0\)\s*return gAutoLaunchGame == NULL \? 1 : 0;', text('src/hddsupport.c')):
    failures.append('hddsupport.c: backing out of the cheats must stay in the menu')
# A way back to the menu after sbPrepare must restore the IRX patch zone: sbPrepare finds it by the
# pristine sample, so a zone left patched fails the next launch. MMCE launches that IRX natively, so each
# Neutrino abort undoes it; UDPFS only borrows the SMB IRX as scratch and restores it right after the
# cheats step, before any later return.
mmce = text('src/mmcesupport.c')
for call in ('sysNeutrinoPreflight(', 'sysNeutrinoHandCheats(', 'sysNeutrinoArgsPreflight('):
    if not re.search(r'if \(' + re.escape(call) + r'[^;]+\) < 0\) \{(?: //[^\n]*)?\s*sbUnprepare\(&settings->common\);\s*return;', mmce):
        failures.append('mmcesupport.c: %s failing must undo the native preparation and stay in the menu' % call[:-1])
udpfs = text('src/udpfssupport.c')
restore = udpfs.find('sbUnprepare((u8 *)(&smb_cdvdman_irx) + index);\n    sbLoadImage(')
if not (0 <= udpfs.find('sbCheatsMissingContinue((u8 *)(&smb_cdvdman_irx) + index, result)') < restore <
        udpfs.find('_STR_NET_NEEDS_NEUTRINO')):
    failures.append('udpfssupport.c: restore the scratch zone right after the cheats step, before any later return')
if not re.search(r'if \(sysNeutrinoHandCheats\([^;]+\) < 0\)\s*return;', udpfs):
    failures.append('udpfssupport.c: backing out of the cheats hand-off must stay in the menu')

support = text('src/supportbase.c')
calls = re.findall(r'sbLoadCheats\(([^;]*?)\)\) < 0', '\n'.join(text('src/' + f) for f in (
    'bdmsupport.c', 'ethsupport.c', 'hddsupport.c', 'httpsupport.c', 'mmcesupport.c', 'udpfssupport.c')))
if len(calls) != 6 or any(not c.rstrip().endswith('configSet') for c in calls):
    failures.append('every sbLoadCheats caller must pass the game config (found %r)' % calls)
select = function(support, 'static void sbCheatsSelect(')
if (select.find('cheatConfigLoadSelections(configSet);') < 0 or select.find('guiManageCheats(configSet);') <
        select.find('cheatConfigLoadSelections(configSet);') or 'gAutoLaunchBDMGame == NULL' not in select):
    failures.append('supportbase.c: Select mode must restore the picks, then show the picker -- never on an autolaunch')
if support.count('sbCheatsSelect(cheatMode, configSet);') != 2:
    failures.append('supportbase.c: both the cht.tar and the loose-file loads must go through sbCheatsSelect')
if 'if (pCommon != NULL)\n        sbUnprepare(pCommon);' not in support:
    failures.append('supportbase.c: sbCheatsMissingContinue must accept NULL from the lean Neutrino legs')
lean = function(support, 'int sbNeutrinoLoadCheats(')
if not (lean.find('InitCheatsConfig(configSet);') < lean.find('sbLoadCheats(prefix, startup, configSet)') <
        lean.find('sbCheatsMissingContinue(NULL, result)') < lean.find('sysNeutrinoHandCheats(')):
    failures.append('supportbase.c: sbNeutrinoLoadCheats must read the settings, load, ask, then hand over')

if 'gCheats[cheat_index].enabled = (gCheatMode == 0) || cheatConfigIsMasterCode(gCheats[cheat_index].name);' not in text('src/cheatman.c'):
    failures.append('cheatman.c: Select mode must start from the master codes alone')
picker = function(text('src/gui.c'), 'void guiManageCheats(')
if picker.count('cheatConfigIsMasterCode(') != 2 or 'strncasecmp' in picker:
    failures.append('gui.c: the picker must lock every master-code heading, through cheatConfigIsMasterCode')
if not (0 <= picker.rfind('cheatConfigSaveSelections(configSet);') < picker.rfind('configWrite(configSet)')):
    failures.append('gui.c: Start must save the picks for the next launch')

menu = text('src/menusys.c')
block = menu[menu.index('menuID == GAME_CHEAT_SETTINGS'):][:300]
if 'NEUTRINO_SETTING_NA' in block or 'guiGameShowCheatConfig(gameMenuCoreIsNeutrino());' not in block:
    failures.append('menusys.c: Cheat Settings must open for Neutrino games too')
if 'diaSetEnabled(diaCheatConfig, CHTCFG_ENABLEIMAGE, !neutrinoCore);' not in text('src/guigame.c'):
    failures.append('guigame.c: the PS2RD image row must be off for a Neutrino game')

base = text('lng_tmpl/_base.yml')
older, ours = base.find('- label: GAME_TYPE_LABELS\n'), base.find('- label: NEUTRINO_CHEATS_WRITE_FAILED\n')
if older < 0 or ours < older:
    failures.append('lng_tmpl/_base.yml: NEUTRINO_CHEATS_WRITE_FAILED must be appended after the existing labels')
if 'cheatconfig.o' not in text('Makefile'):
    failures.append('Makefile: cheatconfig.o is not built')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('cheats on both cores: remembered picks, Neutrino hand-over, layouts, refusals and wiring OK')
