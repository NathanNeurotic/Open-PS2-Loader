"""Back on a Settings page keeps what was changed (FifthFox, 09-27).

"If you leave a page without hitting OK, it gets reset, but if you go to another page it doesn't."
Circle on a page used to be Cancel -- that page's edits were dropped -- while L1/R1 applied them and
flipped. Now Circle behaves like L1/R1: the page's edits are kept and the user lands on the Settings
Index. Leaving Settings is where the decision is made (Save / Exit without saving / Continue).

Checked here, from the production source:
- dia.c: on a Settings PAGE (the shell UI), Circle returns DIA_RESULT_INDEX, before the generic
  Cancel; sub-dialogs opened from a page are not the shell UI and keep Circle = Cancel.
- gui.c: guiSettingsPageResult arms the save prompt for DIA_RESULT_INDEX (compiled and run).
- every page applies its rows for any result other than Cancel, so DIA_RESULT_INDEX applies them.
- the Network page no longer reconnects SMB on an exit that changed nothing: it snapshots what a
  live SMB session depends on and reconnects only on OK/Reconnect or a real change (compiled + run).
- Exit without saving restores the source activation/routing snapshot captured when Settings opened,
  so an applied-but-unsaved source change cannot leave the game page empty/off (#806, zackcage6).
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

# --- dia.c: Circle on a Settings page -> Index, ahead of the generic Cancel ----------------------

execute = function_text(dia_c, 'src/dia.c', 'int diaExecuteDialog(')
back = re.search(r'if \(settingsShell && getKeyOn\(KEY_CIRCLE\)\) \{[^}]*return DIA_RESULT_INDEX;', execute)
cancel = execute.find('return UIID_BTN_CANCEL;')
if back is None:
    failures.append('diaExecuteDialog: Circle on a Settings page must return DIA_RESULT_INDEX (keep the edits)')
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
for sig in PAGES:
    body = function_text(gui_c, 'src/gui.c', sig)
    if not body:
        continue
    if 'if (result != UIID_BTN_CANCEL && result != -1)' not in body and 'if (result) {' not in body:
        failures.append('%s...): its rows must apply for every result except Cancel' % sig)
    if 'guiSettingsPageResult(result)' not in body:
        failures.append('%s...): must return through guiSettingsPageResult(result)' % sig)
audio = function_text(gui_c, 'src/gui.c', 'int guiShowAudioConfig(')
if audio and 'guiSettingsPageResult(result)' not in audio:
    failures.append('guiShowAudioConfig: must return through guiSettingsPageResult(result)')

# --- Exit without saving: restore the source state captured at Settings entry --------------------

read_source = function_text(gui_c, 'src/gui.c', 'static void guiSettingsReadSourceState(')
capture = function_text(gui_c, 'src/gui.c', 'static void guiSettingsCaptureSourceState(')
changed = function_text(gui_c, 'src/gui.c', 'static int guiSettingsSourceStateChanged(')
restore = function_text(gui_c, 'src/gui.c', 'static void guiSettingsRestoreSourceState(')
shell = function_text(gui_c, 'src/gui.c', 'static void guiShowSettingsFromPage(')
index = function_text(gui_c, 'src/gui.c', 'static int guiSettingsShowIndex(')

SOURCE_FIELDS = (
    'gDefaultDevice', 'gBDMStartMode', 'gHDDStartMode', 'gAPPStartMode', 'gMMCEStartMode',
    'gFAVStartMode', 'gEnableUSB', 'gEnableILK', 'gEnableMX4SIO', 'gEnableBdmHDD',
    'gNetworkProtocol', 'gNetStartMode', 'gNetProtocolPick', 'gETHStartMode',
    'gEnableUDPBD', 'gNetBootProtocol', 'gMMCESlot', 'gMMCEIGRSlot',
    'gMMCEEnableGameID', 'gMMCEAckWaitCycles', 'gMMCEUseAlarms', 'gMMCEPrefix',
)
for field in SOURCE_FIELDS:
    if read_source and field not in read_source:
        failures.append('guiSettingsReadSourceState: missing %s' % field)
    if restore and field not in restore:
        failures.append('guiSettingsRestoreSourceState: missing %s' % field)

if capture and 'guiSettingsReadSourceState(&guiSettingsSourceState);' not in capture:
    failures.append('guiSettingsCaptureSourceState: must snapshot through the complete source-state reader')
if changed and 'memcmp(&current, &guiSettingsSourceState, sizeof(current)) != 0' not in changed:
    failures.append('guiSettingsSourceStateChanged: must compare the complete captured source state')
if shell and 'guiSettingsCaptureSourceState();' not in shell:
    failures.append('guiShowSettingsFromPage: must capture source state before any Settings page can apply edits')
if restore:
    if 'if (!guiSettingsSourceStateChanged())' not in restore:
        failures.append('guiSettingsRestoreSourceState: must avoid a device refresh when no source state changed')
    for needle in ('bdmForceDeviceRefresh();', 'applyConfig(-1, -1, 0);', 'menuReinitMainMenu();'):
        if needle not in restore:
            failures.append('guiSettingsRestoreSourceState: missing %s' % needle)
if index:
    exit_pos = index.find('promptResult == SETTINGS_PROMPT_EXIT')
    restore_pos = index.find('guiSettingsRestoreSourceState();', exit_pos)
    return_pos = index.find('return 0;', exit_pos)
    if exit_pos < 0 or restore_pos < 0 or return_pos < 0 or restore_pos > return_pos:
        failures.append('Exit without saving must restore source state before leaving Settings')

    save_pos = index.find('if (menuSaveSettings() > 0)')
    recapture_pos = index.find('guiSettingsCaptureSourceState();', save_pos)
    pending_clear = index.find('guiSettingsSavePending = 0;', save_pos)
    if save_pos < 0 or recapture_pos < 0 or pending_clear < 0 or not (save_pos < recapture_pos < pending_clear):
        failures.append('a successful in-shell Save Changes must become the new discard baseline')

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
