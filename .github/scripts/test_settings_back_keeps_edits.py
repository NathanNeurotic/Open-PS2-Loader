"""Back on a Settings page keeps what was changed (FifthFox, 09-27).

"If you leave a page without hitting OK, it gets reset, but if you go to another page it doesn't."
Circle on a page used to be Cancel -- that page's edits were dropped -- while L1/R1 applied them and
flipped. Now Circle behaves like L1/R1: the page's edits are kept and the user lands on the Settings
Index. Leaving Settings is where the decision is made (Save / Exit without saving / Continue).

Checked here, from the production source:
- dia.c: on a Settings PAGE (the shell UI), Circle returns DIA_RESULT_INDEX, before the generic
  Cancel; sub-dialogs opened from a page are not the shell UI and keep Circle = Cancel.
- gui.c: guiSettingsPageResult arms the save prompt for DIA_RESULT_INDEX (compiled and run).
- every page applies its rows for any result other than Cancel, so DIA_RESULT_INDEX applies them --
  except that Back/L1/R1 off a page whose rows were NOT changed applies nothing. The pages whose
  apply is a full device re-apply (General, Game Sources, Network, Launch, PS1) gate on
  guiSettingsLeftUntouched; diaHasChanges (compiled + run) compares every value row with the def
  the page set. Merely entering Game Sources and backing out re-applied every source and blanked
  the USB page (#806, zackcage6, Beta-3338).
- the Network page no longer reconnects SMB on an exit that changed nothing: it snapshots what a
  live SMB session depends on and reconnects only on OK/Reconnect or a real change (compiled + run).
- Exit without saving KEEPS every edit live for this session -- it only skips the disk write, as the
  prompt says ("Your changes are currently active") and as stock OPL does. A network setup can be
  tried without saving it (Vapor, 10-06). The old source-state revert (#807) is gone.
- both obsolete compatibility download paths are absent: the Start-menu bulk Network Update and the
  per-game Compatibility Settings -> Download Defaults action/backend.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            lines = [line for line in run.stdout.splitlines() if line.startswith('FAIL')]
            failures.extend(lines or ['%s harness exited %d' % (name, run.returncode)])


dia_c = read('src/dia.c')
gui_c = read('src/gui.c')
menusys_c = read('src/menusys.c')
dialogs_c = read('src/dialogs.c')
dialogs_h = read('include/dialogs.h')
gui_h = read('include/gui.h')
guigame_c = read('src/guigame.c')
opl_c = read('src/opl.c')
opl_h = read('include/opl.h')
config_h = read('include/config.h')
iosupport_h = read('include/iosupport.h')

# --- dia.c: Circle on a Settings page -> Index, ahead of the generic Cancel ----------------------

execute = function_text(dia_c, 'src/dia.c', 'int diaExecuteDialog(')
# "Back" is the user's cancel button -- Circle by default, Cross when Circle is chosen as confirm.
back = re.search(r'if \(settingsShell && getKeyOn\(guiCancelKey\(\)\)\) \{[^}]*return DIA_RESULT_INDEX;', execute)
cancel = execute.find('return UIID_BTN_CANCEL;')
if back is None:
    failures.append('diaExecuteDialog: the cancel button on a Settings page must return DIA_RESULT_INDEX (keep the edits)')
elif cancel < 0 or back.start() > cancel:
    failures.append('diaExecuteDialog: the Settings-page Circle branch must come before the generic Cancel')

# --- gui.c: the Index result arms the save prompt (compiled and run) --------------------------

PAGE_HARNESS = r'''
#include <stdio.h>
#define DIA_RESULT_PREV (-2)
#define DIA_RESULT_NEXT (-3)
#define DIA_RESULT_INDEX (-4)
#define UIID_BTN_CANCEL 0
#define UIID_BTN_OK 1
static int guiSettingsSavePending;

@FUNCTIONS@

static int fails;
static void expect(const char *what, int result, int wantReturn, int wantPending)
{
    int got;
    guiSettingsSavePending = 0;
    got = guiSettingsPageResult(result);
    if (got != wantReturn || guiSettingsSavePending != wantPending) {
        printf("FAIL %s: returned %d, pending %d (want %d, %d)\n", what, got, guiSettingsSavePending, wantReturn, wantPending);
        fails++;
    }
}

int main(void)
{
    expect("Back from a page (Index)", DIA_RESULT_INDEX, DIA_RESULT_INDEX, 1);
    expect("L1 from a page", DIA_RESULT_PREV, DIA_RESULT_PREV, 1);
    expect("R1 from a page", DIA_RESULT_NEXT, DIA_RESULT_NEXT, 1);
    expect("OK from a page", UIID_BTN_OK, DIA_RESULT_INDEX, 1);
    expect("a Cancel that still reaches here", UIID_BTN_CANCEL, DIA_RESULT_INDEX, 0);
    if (!fails)
        printf("settings back: Back, L1/R1 and OK all keep a page's edits and arm the save prompt\n")
            ;
    return fails ? 1 : 0;
}
'''

page_functions = ''.join(function_text(gui_c, 'src/gui.c', sig) for sig in (
    'static int guiSettingsIsPeerResult(',
    'static int guiSettingsIsShellResult(',
    'static int guiSettingsPageResult(',
))
if page_functions.count('{') >= 3:
    compile_and_run('settings_page_result', PAGE_HARNESS.replace('@FUNCTIONS@', page_functions))

# --- every page applies its rows for DIA_RESULT_INDEX ------------------------------------------

PAGES = ('static int guiSettingsShowGeneral(', 'static int guiSettingsShowSources(', 'int guiShowNetConfig(',
         'static int guiSettingsShowInterface(', 'static int guiSettingsShowLaunch(',
         'static int guiSettingsShowPopstarter(', 'int guiShowControllerConfig(')
# Pages whose apply block is a full device re-apply: an untouched Back/L1/R1 must skip it (#806).
DEVICE_PAGES = {
    'static int guiSettingsShowGeneral(': 'if (result != UIID_BTN_CANCEL && result != -1 && !guiSettingsLeftUntouched(ui, result, exitPathEdit, gExitPath))',
    'static int guiSettingsShowSources(': 'if (result != UIID_BTN_CANCEL && result != -1 && !guiSettingsLeftUntouched(ui, result, NULL, NULL))',
    'int guiShowNetConfig(': 'if (result && !guiSettingsLeftUntouched(diaNetConfig, result, NULL, NULL))',
    'static int guiSettingsShowLaunch(': 'if (result != UIID_BTN_CANCEL && result != -1 && !guiSettingsLeftUntouched(ui, result, neutrinoPathEdit, gNeutrinoPath))',
    'static int guiSettingsShowPopstarter(': 'if (result != UIID_BTN_CANCEL && result != -1 && !guiSettingsLeftUntouched(ui, result, popstarterPathEdit, gPopstarterPath))',
}
for sig in PAGES:
    body = function_text(gui_c, 'src/gui.c', sig)
    if not body:
        continue
    if sig in DEVICE_PAGES:
        if DEVICE_PAGES[sig] not in body:
            failures.append('%s...): its full re-apply must be skipped when Back/L1/R1 left it untouched (#806)' % sig)
    elif 'if (result != UIID_BTN_CANCEL && result != -1)' not in body and 'if (result) {' not in body:
        failures.append('%s...): its rows must apply for every result except Cancel' % sig)
    if 'guiSettingsPageResult(result)' not in body:
        failures.append('%s...): must return through guiSettingsPageResult(result)' % sig)
audio = function_text(gui_c, 'src/gui.c', 'int guiShowAudioConfig(')
if audio and 'guiSettingsPageResult(result)' not in audio:
    failures.append('guiShowAudioConfig: must return through guiSettingsPageResult(result)')

# --- an untouched page: which exits count, and the long-path edit buffers -----------------------

untouched = function_text(gui_c, 'src/gui.c', 'static int guiSettingsLeftUntouched(')
if untouched:
    if 'if (!guiSettingsIsShellResult(result) || diaHasChanges(ui))' not in untouched:
        failures.append('guiSettingsLeftUntouched: only an unchanged Back/L1/R1 counts as untouched')
    # Each page passes ITS OWN long-path buffer (CodeRabbit #807): another page's buffer is still
    # empty until that page opens, so comparing it would make every page look edited.
    if 'return pathEdit == NULL || strcmp(pathEdit, pathValue) == 0;' not in untouched:
        failures.append('guiSettingsLeftUntouched: must compare only the page\'s own long-path buffer')
    for buffer in ('exitPathEdit', 'neutrinoPathEdit', 'popstarterPathEdit'):
        if buffer in untouched:
            failures.append('guiSettingsLeftUntouched: must not read %s itself; the page passes its own' % buffer)

CHANGES_HARNESS = r'''
#include <stdio.h>
#include <string.h>

@TYPES@
@FUNCTIONS@

static int fails;
static struct UIItem ui[5];
static void reset(void)
{
    memset(ui, 0, sizeof(ui));
    ui[0].type = UI_LABEL;
    ui[1].type = UI_BOOL;
    ui[1].intvalue.def = ui[1].intvalue.current = 1;
    ui[2].type = UI_ENUM;
    ui[2].intvalue.def = ui[2].intvalue.current = 3;
    ui[3].type = UI_STRING;
    strcpy(ui[3].stringvalue.def, "mass:/");
    strcpy(ui[3].stringvalue.text, "mass:/");
    ui[4].type = UI_TERMINATOR;
}
static void expect(const char *what, int want)
{
    if (diaHasChanges(ui) != want) {
        printf("FAIL %s: diaHasChanges=%d, want %d\n", what, !want, want);
        fails++;
    }
}

int main(void)
{
    reset();
    expect("a page opened and left alone", 0);
    reset();
    ui[1].intvalue.current = 0;
    expect("a toggled row", 1);
    reset();
    ui[2].intvalue.current = 1;
    expect("a changed choice", 1);
    reset();
    strcpy(ui[3].stringvalue.text, "mmce:/");
    expect("an edited string", 1);
    reset();
    ui[2].intvalue.current = 1;
    ui[2].intvalue.current = 3;
    expect("a row changed and changed back", 0);
    reset();
    ui[0].label.stringId = 99;
    expect("a label row", 0);
    if (!fails)
        printf("settings back: an untouched page is recognised, any edited value row is not\n");
    return fails ? 1 : 0;
}
'''

dia_h = read('include/dia.h')
item_enum = re.search(r'^typedef enum \{.*?\} UIItemType;', dia_h, re.M | re.S)
item_struct = re.search(r'^struct UIItem\s*\{.*?^\};', dia_h, re.M | re.S)
has_changes = function_text(dia_c, 'src/dia.c', 'int diaHasChanges(')
if item_enum is None or item_struct is None:
    failures.append('include/dia.h: UIItemType / struct UIItem not found')
elif has_changes:
    types = 'typedef unsigned long long u64;\n' + item_enum.group(0) + '\n' + item_struct.group(0)
    compile_and_run('dia_has_changes', CHANGES_HARNESS.replace('@TYPES@', types).replace('@FUNCTIONS@', has_changes))

# --- Exit without saving: the session keeps the edits -------------------------------------------

index = function_text(gui_c, 'src/gui.c', 'static int guiSettingsShowIndex(')

# No snapshot/revert machinery may come back: "without saving" is not "undo".
for name in ('guiSettingsCaptureSourceState', 'guiSettingsRestoreSourceState',
             'guiSettingsSourceStateChanged', 'guiSettingsReadSourceState', 'gui_settings_source_state_t'):
    if name in gui_c:
        failures.append('src/gui.c: %s is back -- Exit without saving must keep the session edits live' % name)
if index:
    exit_pos = index.find('promptResult == SETTINGS_PROMPT_EXIT')
    return_pos = index.find('return 0;', exit_pos)
    if exit_pos < 0 or return_pos < 0:
        failures.append('guiSettingsShowIndex: Exit without saving branch not found')
    else:
        branch = index[exit_pos:return_pos]
        for forbidden in ('applyConfig(', 'bdmForceDeviceRefresh(', 'menuReinitMainMenu('):
            if forbidden in branch:
                failures.append('Exit without saving must not re-apply/revert settings (%s found)' % forbidden)
        if 'guiSettingsSavePending = 0;' not in branch:
            failures.append('Exit without saving must clear the pending-save flag')
        if 'hddDiscardOplHomeSelection();' not in branch:
            failures.append('Exit without saving must discard the pending HDD OPL-home selection')

# --- Obsolete compatibility download feature is gone end-to-end -------------------------------

for where, source, needle in (
    ('src/menusys.c', menusys_c, 'MENU_NETWORK_UPDATE'),
    ('src/menusys.c', menusys_c, 'guiShowNetCompatUpdate'),
    ('src/dialogs.c', dialogs_c, 'diaNetCompatUpdate'),
    ('src/dialogs.c', dialogs_c, 'COMPAT_DL_DEFAULTS'),
    ('include/dialogs.h', dialogs_h, 'NETUPD_OPT_UPD_ALL'),
    ('include/dialogs.h', dialogs_h, 'diaNetCompatUpdate'),
    ('include/dialogs.h', dialogs_h, 'COMPAT_DL_DEFAULTS'),
    ('src/gui.c', gui_c, 'guiShowNetCompatUpdate'),
    ('include/gui.h', gui_h, 'guiShowNetCompatUpdate'),
    ('src/guigame.c', guigame_c, 'COMPAT_DL_DEFAULTS'),
    ('src/opl.c', opl_c, 'oplUpdateGameCompat'),
    ('src/opl.c', opl_c, 'CompatUpdateStatus'),
    ('src/opl.c', opl_c, 'IO_COMPAT_UPDATE_DEFFERED'),
    ('include/opl.h', opl_h, 'IO_COMPAT_UPDATE_DEFFERED'),
    ('include/opl.h', opl_h, 'OPL_COMPAT_UPDATE_STAT_'),
):
    if needle in source:
        failures.append('%s: obsolete compatibility downloader still contains %s' % (where, needle))

if (root / 'include/compatupd.h').exists():
    failures.append('include/compatupd.h: obsolete compatibility updater API should be removed')

# Preserve numeric/UI identity around removed rows so deleting the feature cannot silently retag
# surviving menu/dialog controls. The retired constants must never be rendered or handled.
if 'MENU_RETIRED_NETWORK_UPDATE' not in menusys_c:
    failures.append('src/menusys.c: retired Network Update slot must remain reserved')
if 'COMPAT_RETIRED_DOWNLOAD_DEFAULTS' not in dialogs_h:
    failures.append('include/dialogs.h: retired Download Defaults slot must remain reserved')
if 'if (it->item.id == MENU_NBD)' not in menusys_c:
    failures.append('src/menusys.c: main-menu spacing must key off the live NBD row, not enum arithmetic')

# Removal of the fetcher must not rewrite the per-game compatibility/config ABI. Old downloaded
# configs still need to load as such, and the actual compatibility mode/core keys remain untouched.
for where, source, needle in (
    ('include/config.h', config_h, '#define CONFIG_SOURCE_DLOAD   2'),
    ('include/config.h', config_h, 'CONFIG_ITEM_COMPAT'),
    ('include/config.h', config_h, 'CONFIG_ITEM_DMA'),
    ('include/config.h', config_h, 'CONFIG_ITEM_CORE_LOADER'),
    ('include/config.h', config_h, 'CONFIG_ITEM_NEUTRINO_ARGS'),
    ('include/iosupport.h', iosupport_h, '#define COMPAT_MODE_1 0x01'),
    ('include/iosupport.h', iosupport_h, '#define COMPAT_MODE_6 0x20'),
    ('include/dialogs.h', dialogs_h, 'COMPAT_MODE_BASE = 250'),
    ('include/dialogs.h', dialogs_h, 'COMPAT_MODE_BASE = 200'),
):
    if needle not in source:
        failures.append('%s: updater removal must preserve %s' % (where, needle))

# --- Network page: reconnect only on OK/Reconnect or a real change (compiled and run) -----------

net = function_text(gui_c, 'src/gui.c', 'int guiShowNetConfig(')
if net:
    if not re.search(r'gui_smb_link_t smbBefore;\s*\n\s*guiSmbLinkCapture\(&smbBefore\);', net):
        failures.append('guiShowNetConfig: must snapshot the SMB link (guiSmbLinkCapture) before the dialog')
    if not re.search(r'\(result == NETCFG_OK \|\| result == NETCFG_RECONNECT \|\| guiSmbLinkChanged\(&smbBefore\)\)\)\s*\n\s*ethRequestReconnect\(\);', net):
        failures.append('guiShowNetConfig: ethRequestReconnect must be gated on OK/Reconnect or guiSmbLinkChanged')

LINK_HARNESS = r'''
#include <stdio.h>
#include <string.h>

int ps2_ip_use_dhcp, ps2_ip[4], ps2_netmask[4], ps2_gateway[4], ps2_dns[4], pc_ip[4];
int gPCPort, gPCShareAddressIsNetBIOS, gETHOpMode, gNetworkProtocol;
char gPCShareNBAddress[17], gPCShareName[32], gPCUserName[32], gPCPassword[32];

@TYPES@
@FUNCTIONS@

static int fails;
static void seed(void)
{
    int i;
    ps2_ip_use_dhcp = 0;
    for (i = 0; i < 4; i++) {
        ps2_ip[i] = 192 - i;
        ps2_netmask[i] = 255;
        ps2_gateway[i] = 1 + i;
        ps2_dns[i] = 8;
        pc_ip[i] = 10 + i;
    }
    gPCPort = 445;
    gPCShareAddressIsNetBIOS = 0;
    gETHOpMode = 0;
    gNetworkProtocol = 0;
    strcpy(gPCShareNBAddress, "PC");
    strcpy(gPCShareName, "PS2SMB");
    strcpy(gPCUserName, "GUEST");
    strcpy(gPCPassword, "");
}
static void expect(const char *what, void (*change)(void), int want)
{
    gui_smb_link_t before;
    seed();
    guiSmbLinkCapture(&before);
    if (change)
        change();
    if (guiSmbLinkChanged(&before) != want) {
        printf("FAIL %s: changed=%d, want %d\n", what, !want, want);
        fails++;
    }
}
static void ip(void) { pc_ip[3] = 99; }
static void port(void) { gPCPort = 1111; }
static void share(void) { strcpy(gPCShareName, "GAMES"); }
static void password(void) { strcpy(gPCPassword, "x"); }
static void dhcp(void) { ps2_ip_use_dhcp = 1; }
static void protocol(void) { gNetworkProtocol = 1; }
static void sameString(void) { strcpy(gPCUserName, "GUEST"); }

int main(void)
{
    expect("nothing changed", NULL, 0);
    expect("the same string written back", sameString, 0);
    expect("server IP", ip, 1);
    expect("SMB port", port, 1);
    expect("share name", share, 1);
    expect("password", password, 1);
    expect("DHCP", dhcp, 1);
    expect("protocol", protocol, 1);
    if (!fails)
        printf("settings back: the Network page reconnects only when the SMB link changed\n");
    return fails ? 1 : 0;
}
'''

link_type = re.search(r'^typedef struct\s*\{[^}]*\} gui_smb_link_t;', gui_c, re.M)
if link_type is None:
    failures.append('src/gui.c: typedef gui_smb_link_t not found')
link_functions = ''.join(function_text(gui_c, 'src/gui.c', sig) for sig in (
    'static void guiSmbLinkCapture(',
    'static int guiSmbLinkChanged(',
))
if link_type is not None and link_functions.count('{') >= 2:
    compile_and_run('smb_link', LINK_HARNESS.replace('@TYPES@', link_type.group(0)).replace('@FUNCTIONS@', link_functions))

if failures:
    print('Settings back checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
