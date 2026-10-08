"""Create VMC on First Launch (fork-gaps OR2): what it creates, assigns, skips and reports.

Compiles the real guiGameAutoCreateVmc from src/guigame.c against stubs for genvmc's devctls, the
config accessors and the GUI, and checks every branch: the setting off, PS1/app rows, HTTP, APA under
Neutrino, a slot already set or switched off, create vs. reuse of the dialog's default name, a failed
or stuck genvmc job, a fragmented result, and Back during creation.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/guigame.c').read_text(encoding='utf-8').replace('\r\n', '\n')
opl = (root / 'src/opl.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []

match = re.search(r'^int guiGameAutoCreateVmc\([^;{]*\)\s*\{', source, re.M)
if match is None:
    sys.exit('src/guigame.c: guiGameAutoCreateVmc not found')
function = source[match.start():source.index('\n}', match.start()) + 3]
defines = '\n'.join(re.findall(r'^#define AUTO_VMC_\w+ .*$', source, re.M))
status = re.search(r'typedef struct\s*\{[^}]*VMC_status[^}]*\} statusVMCparam_t;', source)
if status is None or 'AUTO_VMC_SIZE_MB' not in defines:
    sys.exit('src/guigame.c: statusVMCparam_t or the AUTO_VMC_* defines not found')

# The launch must ask before the GameID flash and itemLaunch, and re-check the row afterwards.
select = opl[opl.index('static void itemExecSelect'):]
select = select[:select.index('\n}\n')]
call, flash, launch = (select.find('guiGameAutoCreateVmc(support, launchId, configSet)'),
                       select.find('guiShowGameID('), select.find('support->itemLaunch(support, launchId, configSet)'))
if not (0 <= call < flash < launch):
    failures.append('opl.c itemExecSelect: guiGameAutoCreateVmc must run before the GameID flash and itemLaunch')
# Row ids are list indices, so the re-check must compare the game's startup id (captured before the
# creation) and re-take launchId from the row the game sits on now -- never trust the old index.
capture = select.find('snprintf(gameIdStartup, sizeof(gameIdStartup), "%s", startup);')
gate = select.find("if (gameIdStartup[0] != '\\0') {")
retake = select.find('launchId = curMenu->current->item.id;', call)
compare = select.find('if (startup == NULL || strcmp(startup, gameIdStartup) != 0)', call)
if not (0 <= capture < gate < call < retake < compare < flash):
    failures.append('opl.c itemExecSelect: capture the startup id, then -- only for a row that has one -- create the '
                    'VMC, re-take launchId from the current row and require the same non-empty startup id')
if 'curMenu->current->item.id != launchId' in select:
    failures.append('opl.c itemExecSelect: a bare row-index re-check passes when another game lands on that row')

# A failed creation must not leave a half-written card behind: a later launch would reuse it.
genvmc = (root / 'modules/vmc/genvmc/genvmc.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failed = genvmc[genvmc.index('    if (r < 0) {', genvmc.index('vmc_mcformat(param->VMC_filename')):]
failed = failed[:failed.index('goto exit;')]
cleanup = failed.find('if (r != -98 && r != -99 && r != -100 && r != -101)\n            remove(param->VMC_filename);')
report = failed.find('genvmc_stats.VMC_status = GENVMC_STAT_AVAIL;')
if not (0 <= cleanup < report):
    failures.append('genvmc.c: every failure after the open -- never one before it (-98..-101) -- must remove the '
                    'partial file before reporting')

HARNESS = r'''
#include <stdio.h>
#include <string.h>

enum { BDM_MODE = 0, ETH_MODE, HDD_MODE, APP_MODE, FAV_MODE, HTTP_MODE, MMCE_MODE };
enum { LIB_VIEW_PS2 = 0, LIB_VIEW_PS1 };
enum { _STR_AUTO_VMC_CREATING = 1, _STR_AUTO_VMC_FAILED, _STR_VMC_FRAGMENTED_ON_CREATE };
#define CONFIG_ITEM_CORE_LOADER "$CoreLoader"
#define LOG(...) ((void)0)
struct UIItem;
typedef struct { int unused; } config_set_t;
typedef struct item_list item_list_t;
struct item_list {
    int mode;
    char *(*itemGetStartup)(item_list_t *, int);
    int (*itemCheckVMC)(item_list_t *, char *, int);
};

@STATUS@

static int gAutoCreateVmc = 1, gDefaultCoreLoader, guiActive = 1, rowView, favSource = BDM_MODE;
static int cfgCore = -1, cfgDisabled;
static char cfgVmc[32];
static int fileExists, checkCalls, createSize, renders, saves, lastMsg, msgs, cancelAtPoll = -1, fragmented;
static int jobPolls, jobDoneAfter = 3, jobError, jobNeverEnds, aborts, polls;
static char createdName[32];

static int guiIsActive(void) { return guiActive; }
static int libListRowView(item_list_t *l, int id) { (void)l; (void)id; return rowView; }
static int favGetItemSourceMode(int id) { (void)id; return favSource; }
static int configGetInt(config_set_t *c, const char *k, int *v) { (void)c; (void)k; if (cfgCore < 0) return 0; *v = cfgCore; return 1; }
static void configGetVMC(config_set_t *c, char *v, int n, int slot) { (void)c; (void)slot; snprintf(v, n, "%s", cfgVmc); }
static void configGetVMCDisable(config_set_t *c, int slot, int *d) { (void)c; (void)slot; *d = cfgDisabled; }
static void configSetVMC(config_set_t *c, const char *v, int slot) { (void)c; if (slot == 0) snprintf(cfgVmc, sizeof(cfgVmc), "%s", v); }
static const char *getGroupIdForTitleId(const char *t) { return strcmp(t, "SLUS_212.34") ? t : "SLUS_GROUP"; }
static int fileXioDevctl(const char *dev, int cmd, void *a, int al, void *b, int bl)
{
    (void)dev; (void)a; (void)al; (void)bl;
    if (cmd == 0xC0DE0002) { aborts++; jobNeverEnds = 0; jobDoneAfter = 0; return 0; }
    if (cmd == 0xC0DE0003) {
        statusVMCparam_t *s = (statusVMCparam_t *)b;
        polls++;
        jobPolls++;
        s->VMC_progress = jobPolls * 30 > 100 ? 100 : jobPolls * 30;
        s->VMC_status = (jobNeverEnds || jobPolls < jobDoneAfter) ? 1 : 0;
        s->VMC_error = s->VMC_status ? 0 : jobError;
        return 0;
    }
    return -1;
}
static int readPads(void) { return 0; }
static int guiCancelKey(void) { return 99; }
static int getKeyOn(int k) { return k == 99 && polls == cancelAtPoll; }
static char *_l(int id) { static char t[8]; snprintf(t, sizeof(t), "#%d", id); return t; }
static void guiRenderTextScreen(const char *t) { (void)t; renders++; }
static int guiMsgBox(const char *t, int accept, struct UIItem *ui) { (void)accept; (void)ui; msgs++; sscanf(t, "#%d", &lastMsg); return 0; }
static int sysVMCContiguity(void) { return fragmented ? 0 : 1; }
static int menuSaveConfig(void) { saves++; return 1; }

static char *getStartup(item_list_t *l, int id) { (void)l; (void)id; static char s[] = "SLUS_212.34"; return s; }
static int checkVMC(item_list_t *l, char *name, int size)
{
    (void)l;
    checkCalls++;
    if (size == 0)
        return fileExists ? 8 : -1;
    createSize = size;
    snprintf(createdName, sizeof(createdName), "%s", name);
    jobPolls = 0;
    return 0;
}

@DEFINES@
@FUNCTION@

static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL %s\n", m); fails++; } } while (0)
static item_list_t dev = {BDM_MODE, getStartup, checkVMC};
static config_set_t cfg;

static void reset(void)
{
    gAutoCreateVmc = 1; gDefaultCoreLoader = 0; guiActive = 1; rowView = LIB_VIEW_PS2; favSource = BDM_MODE;
    cfgCore = -1; cfgDisabled = 0; cfgVmc[0] = 0; fileExists = 0; checkCalls = 0; createSize = 0;
    renders = saves = lastMsg = msgs = aborts = polls = jobPolls = jobError = jobNeverEnds = fragmented = 0;
    jobDoneAfter = 3; cancelAtPoll = -1; createdName[0] = 0; dev.mode = BDM_MODE;
}

static void skipped(const char *why)
{
    char before[32];
    int r;
    snprintf(before, sizeof(before), "%s", cfgVmc);
    r = guiGameAutoCreateVmc(&dev, 0, &cfg);
    if (r != 1 || checkCalls || saves || msgs || strcmp(before, cfgVmc))
        printf("FAIL %s: r=%d checks=%d saves=%d msgs=%d slot1 %s -> %s\n", why, r, checkCalls, saves, msgs, before, cfgVmc), fails++;
}

int main(void)
{
    reset(); gAutoCreateVmc = 0; skipped("setting off");
    reset(); guiActive = 0; skipped("no menu (autolaunch)");
    reset(); rowView = LIB_VIEW_PS1; skipped("PS1 row");
    reset(); dev.mode = APP_MODE; skipped("app row");
    reset(); dev.mode = FAV_MODE; favSource = HTTP_MODE; skipped("HTTP favourite");
    reset(); dev.mode = HDD_MODE; cfgCore = 1; skipped("APA under per-game Neutrino");
    reset(); dev.mode = HDD_MODE; gDefaultCoreLoader = 1; skipped("APA under global Neutrino");
    reset(); snprintf(cfgVmc, sizeof(cfgVmc), "MyCard"); skipped("slot 1 already set");
    CHECK(!strcmp(cfgVmc, "MyCard"), "an assigned card is never replaced");
    reset(); cfgDisabled = 1; skipped("slot 1 switched off");

    reset(); dev.mode = HDD_MODE;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && createSize == AUTO_VMC_SIZE_MB, "APA under the OPL core still gets a card");

    reset();
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1, "creation goes on with the launch");
    CHECK(createSize == 8 && !strcmp(createdName, "SLUS_GROUP_0"), "8 MB, named like the VMC dialog (group id, slot 1)");
    CHECK(!strcmp(cfgVmc, "SLUS_GROUP_0") && saves == 1, "the new card is assigned to slot 1 and saved once");
    CHECK(renders >= 3 && msgs == 0, "progress is shown while genvmc works, no message on success");

    reset(); fileExists = 1;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && createSize == 0 && !strcmp(cfgVmc, "SLUS_GROUP_0") && saves == 1,
          "an existing file of that name is assigned, never recreated");

    reset(); dev.mode = FAV_MODE; favSource = MMCE_MODE;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && createSize == 8, "a favourite from a writable device gets a card");

    reset(); jobError = -5;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && lastMsg == _STR_AUTO_VMC_FAILED && !cfgVmc[0] && !saves,
          "a failed creation says so, assigns nothing and still launches");

    reset(); fragmented = 1;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && lastMsg == _STR_VMC_FRAGMENTED_ON_CREATE && !strcmp(cfgVmc, "SLUS_GROUP_0"),
          "a fragmented card gets the VMC dialog's warning and is still assigned, as the dialog does");

    reset(); fragmented = 1; cfgCore = 1;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && msgs == 0 && saves == 1,
          "Neutrino does not inherit the native single-fragment warning");
    reset(); fragmented = 1; cfgCore = 2; gDefaultCoreLoader = 1;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && msgs == 0 && saves == 1,
          "Default following Neutrino does not inherit the native warning");

    reset(); cancelAtPoll = 2;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 0 && aborts == 1 && !cfgVmc[0] && !saves,
          "Back aborts genvmc and stays in the menu");

    reset(); jobNeverEnds = 1;
    CHECK(guiGameAutoCreateVmc(&dev, 0, &cfg) == 1 && aborts == 1 && lastMsg == _STR_AUTO_VMC_FAILED && !cfgVmc[0],
          "a genvmc job that never finishes is aborted and reported, not waited on forever");
    return fails ? 1 : 0;
}
'''

if not failures:
    program = (HARNESS.replace('@STATUS@', status.group(0)).replace('@DEFINES@', defines)
               .replace('@FUNCTION@', function))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'autovmc.c'
        exe = Path(tmp) / ('autovmc' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            if run.returncode != 0:
                failures.extend(run.stdout.strip().splitlines() or ['harness exited %d' % run.returncode])

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('auto VMC: skips, create vs. reuse, failure, fragmentation, Back and a stuck job all behave')
