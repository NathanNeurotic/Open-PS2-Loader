"""Auto Loading settings discovery (#545): exercise the production helpers and pin the fixes.

Part 1 compiles hddIsApaMbrHybrid (with hddApaHeaderValid) from src/hddsupport.c on the host and
drives it with synthetic sector-0 images: PSBBN's APA-Jail layout must classify as a hybrid, and a
plain APA disk -- including one with a residual 0x55AA -- must not.

Part 2 compiles the config sibling-path helpers from src/config.c. A device-root home such as
"mass0:" has no '/', and splitting on '/' alone turned the official/legacy fallback into a bare
relative name resolved against the process CWD.

Part 3 statically pins the other fixes, so a later edit cannot quietly reintroduce them: the NULL
item list in the BDM autolaunch, the pre-GUI message box, the cheats prompt comparison, the
miniDeinit(NULL) crash, one shared discovery path, and the network re-probe.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def text(path):
    # Windows checkouts carry CRLF; the checks below match on LF.
    return (root / path).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        return None
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / name
        src.write_text(program)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(src)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('%s did not compile:\n%s' % (name, result.stderr))
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('%s failed:\n%s%s' % (name, result.stdout, result.stderr))


HYBRID_HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define LOG(...) ((void)0)
#define ATA_DEVCTL_READ_PARTITION_SECTOR 0

static unsigned char disk[1024];
static int devctlResult;

static int fileXioDevctl(const char *name, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen)
{
    (void)name;
    (void)cmd;
    (void)arg;
    (void)arglen;
    memcpy(buf, disk, buflen < sizeof(disk) ? buflen : sizeof(disk));
    return devctlResult;
}

%(defines)s
%(header_valid)s
%(hybrid)s

static void put32(unsigned int ofs, u32 v)
{
    disk[ofs] = v & 0xff;
    disk[ofs + 1] = (v >> 8) & 0xff;
    disk[ofs + 2] = (v >> 16) & 0xff;
    disk[ofs + 3] = (v >> 24) & 0xff;
}

static void apa(void)
{
    memset(disk, 0, sizeof(disk));
    put32(0x04, 0x00415041); /* "APA\0" */
    memcpy(disk + 0x10, "__mbr", 5);
    memcpy(disk + 0x100, "Sony Computer Entertainment Inc.", 32);
}

static void entry(int i, u8 type, u32 start, u32 count)
{
    disk[0x1BE + i * 16 + 4] = type;
    put32(0x1BE + i * 16 + 8, start);
    put32(0x1BE + i * 16 + 12, count);
}

static void signature(void)
{
    disk[0x1FE] = 0x55;
    disk[0x1FF] = 0xAA;
}

static void seal(void)
{
    u32 sum = 0;
    for (int i = 1; i < 256; i++)
        sum += disk[i * 4] | (disk[i * 4 + 1] << 8) | (disk[i * 4 + 2] << 16) | ((u32)disk[i * 4 + 3] << 24);
    put32(0, sum);
}

static int fails;

static void expect(const char *what, int want)
{
    int got = hddIsApaMbrHybrid();
    if (got != want) {
        printf("FAIL %%s: hddIsApaMbrHybrid() = %%d, want %%d\n", what, got, want);
        fails++;
    }
}

int main(void)
{
    /* PSBBN Definitive: sfdisk ",APA,17 / ,32MiB,17 / ,,07", then the APA checksum re-fixed. */
    apa();
    entry(0, 0x17, 2048, 0x00C00000);
    entry(1, 0x17, 0x00C00800, 0x00010000);
    entry(2, 0x07, 0x00C10800, 0x20000000);
    signature();
    seal();
    expect("APA-Jail (exFAT partition 3)", 1);

    apa();
    entry(0, 0x0C, 0x00100000, 0x01000000);
    signature();
    seal();
    expect("APA + FAT32 LBA partition", 1);

    apa();
    seal();
    expect("plain APA disk", 0);

    apa();
    signature();
    seal();
    expect("APA with a residual 0x55AA and an empty table", 0);

    apa();
    entry(0, 0x17, 2048, 0x00C00000);
    signature();
    seal();
    expect("APA + MBR with no FAT/exFAT entry", 0);

    apa();
    entry(0, 0x07, 0x0003FFFF, 0x01000000);
    signature();
    seal();
    expect("exFAT entry inside the APA reserved area", 0);

    apa();
    entry(0, 0x07, 0x01000000, 0);
    signature();
    seal();
    expect("zero-length exFAT entry", 0);

    apa();
    entry(2, 0x07, 0x00C10800, 0x20000000);
    signature();
    seal();
    put32(0, 0x12345678);
    expect("bad APA checksum", 0);

    memset(disk, 0, sizeof(disk));
    entry(0, 0x07, 2048, 0x20000000);
    signature();
    expect("plain MBR/exFAT disk", 0);

    apa();
    entry(2, 0x07, 0x00C10800, 0x20000000);
    signature();
    seal();
    devctlResult = -5;
    expect("sector read failure", 0);

    if (fails == 0)
        printf("hybrid classifier: 10 cases OK\n");
    return fails != 0;
}
'''

PATH_HARNESS = r'''
#include <stdio.h>
#include <string.h>

%(dir_end)s
%(sibling)s

static int fails;

static void expect(const char *path, const char *want)
{
    char out[256];
    configBuildSiblingPath(path, "conf_opl.cfg", out, sizeof(out));
    if (strcmp(out, want) != 0) {
        printf("FAIL sibling of %%s = %%s, want %%s\n", path, out, want);
        fails++;
    }
}

int main(void)
{
    expect("mass0:settings_riptopl.cfg", "mass0:conf_opl.cfg");
    expect("mass0:/settings_riptopl.cfg", "mass0:/conf_opl.cfg");
    expect("pfs0:settings_riptopl.cfg", "pfs0:conf_opl.cfg");
    expect("pfs0:OPL/settings_riptopl.cfg", "pfs0:OPL/conf_opl.cfg");
    expect("mc0:/APPS/RIPTOPL/settings_riptopl.cfg", "mc0:/APPS/RIPTOPL/conf_opl.cfg");
    expect("settings_riptopl.cfg", "conf_opl.cfg");
    if (fails == 0)
        printf("config sibling paths: 6 cases OK\n");
    return fails != 0;
}
'''


def run_hybrid_harness():
    source = text('src/hddsupport.c')
    header_valid = function_text(source, 'static int hddApaHeaderValid(')
    hybrid = function_text(source, 'int hddIsApaMbrHybrid(')
    reserved = re.search(r'^#define HDD_APA_RESERVED_SECTORS .*$', source, re.M)
    if header_valid is None or hybrid is None or reserved is None:
        failures.append('src/hddsupport.c: hddApaHeaderValid/hddIsApaMbrHybrid/HDD_APA_RESERVED_SECTORS not found')
        return
    compile_and_run('hybrid', HYBRID_HARNESS % {'defines': reserved.group(0), 'header_valid': header_valid,
                                                'hybrid': hybrid})


def run_path_harness():
    source = text('src/config.c')
    dir_end = function_text(source, 'static const char *configPathDirEnd(')
    sibling = function_text(source, 'static void configBuildSiblingPath(')
    if dir_end is None or sibling is None:
        failures.append('src/config.c: configPathDirEnd/configBuildSiblingPath not found')
        return
    compile_and_run('sibling', PATH_HARNESS % {'dir_end': dir_end, 'sibling': sibling})


def check_pins():
    bdm = text('src/bdmsupport.c')
    launch = function_text(bdm, 'void bdmLaunchGame(')
    check(launch is not None and 'itemList != NULL ? folderGetSub(itemList->mode) : ""' in launch and
          not re.search(r'sbSetBrowseSub\(folderGetSub\(itemList->mode\)\)', launch),
          'bdmLaunchGame: autolaunch (itemList == NULL) must not read itemList->mode')

    gui = text('src/gui.c')
    msgbox = function_text(gui, 'int guiMsgBox(')
    check(msgbox is not None and re.search(r'if \(gTheme == NULL\) \{[^}]*return 0;', msgbox) and
          msgbox.find('gTheme == NULL') < msgbox.find('guiWrapText('),
          'guiMsgBox: must answer "back" (0) before the GUI exists')

    support = text('src/supportbase.c')
    cheats = function_text(support, 'int sbCheatsMissingContinue(')
    # The accept branch itself, not just the call: a negated test (!guiMsgBox) or a comparison against
    # anything other than truthiness would make "continue without cheats" cancel the launch again.
    check(cheats is not None and
          re.search(r'if \(guiMsgBox\(text, 1, NULL\)\)\s*return 1;', cheats) and
          not re.search(r'!\s*guiMsgBox\(|guiMsgBox\([^;]*\)\s*[=!<>]=', cheats),
          'sbCheatsMissingContinue: guiMsgBox returns 1 for accept -- continue the launch on a true result')
    # Cheats on for ALL games + a title with no .cht: continue with no prompt. Must sit BEFORE the
    # prompt, must be keyed on -ENOENT (a file that exists but will not load still asks), and the flag
    # must only ever be raised on the global branch of InitCheatsConfig.
    silent = re.search(r'if \(cheatResult == -ENOENT && GetCheatsFromGlobalDefault\(\)\) \{[^}]*return 1;', cheats or '')
    check(silent is not None and silent.start() < cheats.find('guiMsgBox('),
          'sbCheatsMissingContinue: a missing .cht with cheats on for all games must continue without a prompt')
    init = function_text(text('src/cheatman.c'), 'void InitCheatsConfig(')
    per_game, _, global_branch = (init or '').partition('} else {')
    check(init is not None and 'gCheatFromGlobal = 0;' in per_game and 'gCheatFromGlobal = 1;' not in per_game and
          'gCheatFromGlobal = 1;' in global_branch,
          'InitCheatsConfig: gCheatFromGlobal is reset each launch and set only by the all-games default')

    ioman = text('src/ioman.c')
    io_init = function_text(ioman, 'void ioInit(')
    # The wait must be uncapped (loop condition is ONLY the worker flag) and must finish before anything
    # the old worker shares -- gIOTerminate, the queue, the static stack -- is reset or reused.
    wait = re.search(r'for \([^;]*;\s*\*\(volatile int \*\)&isIORunning\s*;', io_init or '')
    check(io_init is not None and wait is not None and 'isIOBlocked = 0;' in io_init and
          wait.start() < io_init.find('gIOTerminate = 0;') < io_init.find('CreateThread('),
          'ioInit: after a refused autolaunch, wait (uncapped) for the old worker before reusing its stack')

    config = text('src/config.c')
    free_body = function_text(config, 'void configFree(')
    check(free_body is not None and re.search(r'if \(configSet == NULL\)\s*return;', free_body),
          'configFree: miniDeinit(NULL) needs a NULL-safe configFree')
    read = function_text(config, 'int configRead(')
    official = read[read.find('CONFIG_OPL_FILENAME_OFFICIAL'):] if read else ''
    check(read is not None and 'CONFIG_OPL_FILENAME_OFFICIAL' in read and
          'configMove(' not in official[:official.find('if (!fileBuffer)')],
          'configRead: the official conf_opl.cfg seed must never re-home the set onto official\'s file')
    translate = function_text(config, 'static void configTranslateOfficialOpl(')
    check(translate is not None and 'ETH_MODE + (device - 5)' in translate and 'modified = 0' in translate,
          'configTranslateOfficialOpl: official default_device 5/6/7 must map to ETH/HDD/APP')
    # RiptOPL settings carried over from the APA home outrank official's seed, and neither re-homes the
    # set: the first save must land in the current (exFAT) home, not back on APA.
    carry = read.find('configOpenCarryOver(CONFIG_OPL_FILENAME)') if read else -1
    check(read is not None and 0 <= carry < read.find('CONFIG_OPL_FILENAME_OFFICIAL') and
          'configMove(' not in read[carry:read.find('if (!fileBuffer)')],
          'configRead: the APA carry-over must come before the official seed and never re-home the set')

    # Retest of #545: a hybrid is homed on exFAT like official OPL. Only an explicit Custom Settings Path
    # in the APA home keeps APA; RiptOPL settings found there are carried over instead of winning.
    apa_home = function_text(text('src/opl.c'), 'static int resolveApaBootHome(')
    check(apa_home is not None and
          'haveExfatHome && !bootHomeHasFile(gHDDPrefix, configPathRedirectFile)' in apa_home and
          apa_home.find('configSetCarryOverDir(gHDDPrefix);') <
          apa_home.find('adoptHybridExfatHome(before, exfatHome, "hybrid: exFAT, APA settings carried over")') and
          'haveExfatHome && !bootHomeHasRiptoplSettings(gHDDPrefix)' not in apa_home,
          'resolveApaBootHome: a hybrid must stay on exFAT when only RiptOPL settings sit on APA')
    # APA-Jail first run (CosmicScale, 2026-09-25): with the exFAT home in hand the APA home is only
    # looked at, so the look must not create __common/OPL/, and a home that supplies nothing is let go
    # (no "__common partition mounted" toast). Settings carried over still need it mounted.
    carried = apa_home.find('"hybrid: exFAT, APA settings carried over"') if apa_home else -1
    first_run = apa_home.find('"hybrid: exFAT (official seed or first run)"') if apa_home else -1
    unusable = apa_home.find('"hybrid: exFAT (APA data home unusable)"') if apa_home else -1
    check(apa_home is not None and
          re.search(r'if \(haveExfatHome\)\s*hddInspectSupportHome\(\);\s*else\s*hddLoadSupportModules\(\);', apa_home) and
          0 < carried < first_run < unusable and
          'hddReleaseSupportHome' not in apa_home[apa_home.rfind('configSetCarryOverDir(gHDDPrefix);'):carried] and
          'hddReleaseSupportHome();' in apa_home[carried:first_run] and
          'hddReleaseSupportHome();' in apa_home[apa_home.rfind('if (haveExfatHome) {'):unusable],
          'resolveApaBootHome: a hybrid must inspect the APA home without creating __common/OPL/ and '
          'release it unless settings are carried over from it')
    hdd = text('src/hddsupport.c')
    mount = function_text(hdd, 'static void hddMountSupportHome(')
    check(mount is not None and
          re.search(r'if \(createCommonHome\)\s*\(void\)hddCheckOPLFolder\(hddPrefix\);', mount) and
          mount.count('hddCheckOPLFolder(') == 1 and
          re.search(r'void hddLoadSupportModules\(void\)\s*\{\s*hddMountSupportHome\(1\);', hdd) and
          re.search(r'void hddInspectSupportHome\(void\)\s*\{\s*hddMountSupportHome\(0\);', hdd),
          'hddsupport: only hddLoadSupportModules may create __common/OPL/; hddInspectSupportHome never does')
    release = function_text(hdd, 'void hddReleaseSupportHome(')
    check(release is not None and 'fileXioUmount(hddPrefix);' in release and 'gHDDPrefix = NULL;' in release and
          "gOPLPart[0] = '\\0';" in release,
          'hddReleaseSupportHome: must unmount pfs0: and forget the data partition')
    multi = function_text(config, 'int configReadMulti(')
    check(multi is not None and
          'configPrepareLoadNotification(configOplCarryOver ? configCarryOverDir : configSet->filename);' in multi,
          'configReadMulti: the load toast must name the carry-over home when settings came from there')
    toast = function_text(text('src/gui.c'), 'static void guiShowNotifications(')
    check(toast is not None and
          'configOplIsOfficialSeed() ? _STR_OFFICIAL_CFG_NOTIFICATION : _STR_CFG_NOTIFICATION' in toast,
          'guiShowNotifications: official OPL\'s seed must not be announced as RiptOPL settings')
    # One decision for an on-time drive and a late one. A failed ATA load is retryable, so the drive can
    # first come up in tryAlternateDevice's retry; a bare PFS mount there skipped the hybrid check and homed
    # the hybrid on __common/OPL (CodeRabbit on #725).
    to_mass = function_text(text('src/opl.c'), 'static void resolveBootDirToMass(')
    check(to_mass is not None and 'hddLoadModulesReady() && resolveApaBootHome()' in to_mass and
          'hddIsApaMbrHybrid(' not in to_mass,
          'resolveBootDirToMass: the APA home must come from resolveApaBootHome')
    retry = function_text(text('src/opl.c'), 'static int tryAlternateDevice(')
    retry_head = retry[:retry.find('readConfigPathRedirect(')] if retry else ''
    check(retry is not None and
          re.search(r'hddLoadModulesReady\(\) && resolveApaBootHome\(\) && gBootHomeHybridExfat\)\s*\{\s*'
                    r'value = configReadMulti\(types\);', retry_head) and
          'hddLoadSupportModules();' not in retry_head,
          'tryAlternateDevice: a drive that comes up on the retry must get the boot-time hybrid decision')
    load = function_text(text('src/opl.c'), 'static void _loadConfig(')
    check(load is not None and
          re.search(r'gBootHomeHybridExfat && gBDMStartMode == START_MODE_DISABLED &&\s*'
                    r'\(!\(result & CONFIG_OPL\) \|\| configOplIsOfficialSeed\(\) \|\| configOplIsCarryOver\(\)\)', load) and
          'CONFIG_OPL_BDM_MODE, gBDMStartMode' in load,
          '_loadConfig: a hybrid exFAT home without its own RiptOPL settings must start the BDM page Auto')

    iosupport = text('include/iosupport.h')
    check(re.search(r'BDM_MODE7,\s*ETH_MODE,\s*HDD_MODE,\s*APP_MODE,', iosupport),
          'iosupport.h: the official default_device mapping assumes ETH/HDD/APP follow BDM_MODE7')

    opl = text('src/opl.c')
    check(re.search(r'^static int tryAlternateDevice\(int types\)$', opl, re.M),
          'tryAlternateDevice: autolaunch must not get its own discovery branch again')
    mini = function_text(opl, 'static void miniInit(')
    check(mini is not None and 'resolveBootDirToMass();' in mini and 'gBootHomeApa' not in mini,
          'miniInit: autolaunch must run exactly the menu discovery')
    check(re.search(r'!\(result & CONFIG_NETWORK\) && !\(lscstatus & CONFIG_OPL\)', opl),
          '_loadConfig: a missing conf_network.cfg must not re-run discovery after the master load')
    restore = function_text(opl, 'static void restoreRecoverySaveHome(')
    check(restore is not None and 'sameConcreteMcSlot(gBootDir, recoveredHome) && !configOplIsOfficialSeed()' in restore,
          'restoreRecoverySaveHome: an official seed must not pick the save home')
    resolve = function_text(opl, 'static int resolveHybridExfatHome(')
    check(resolve is not None and 'bdmResolveBootDirBootstrap(home, homeLen, "", &bdmType)' in resolve,
          'resolveHybridExfatHome: pass no ELF name (the launcher ELF is on APA, not exFAT)')


run_hybrid_harness()
run_path_harness()
check_pins()

if failures:
    print('\nAuto Loading settings checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('Auto Loading settings: hybrid detection, sibling paths and pinned fixes OK')
