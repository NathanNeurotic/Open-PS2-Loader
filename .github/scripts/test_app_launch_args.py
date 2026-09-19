"""Compile the real Apps launch function with host stubs and inspect its handoff.

Guards the APA argv[0] regression from #688 and checks the kernel argument-pool
boundary before teardown. --baseline accepts an older appsupport.c to reproduce
the missing partition. This does not emulate IOP or console behavior.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = root / "src/appsupport.c"
if len(sys.argv) == 3 and sys.argv[1] == "--baseline":
    source = Path(sys.argv[2])
text = source.read_text()


def function(name):
    """Extract a complete top-level static C function for the host harness."""
    start = text.index("static ", text.index(name) - 25)
    end = text.index("\n}", start) + 2
    return text[start:end]


STUBS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stddef.h>
#define O_RDONLY 0
#define MAX_BDM_DEVICES 10
#define HDD_MODE 1
#define APP_MODE 2
#define ETH_MODE 3
#define UNMOUNT_EXCEPTION 1
#define KEEPIOP_EXCEPTION 2
#define IO_MODE_SELECTED_ALL_SPARE 99
#define CONFIG_ITEM_STARTUP 1
#define CONFIG_ITEM_ALTSTARTUP 2
#define _STR_ERR_FILE_INVALID 1
#define _STR_POPSTARTER_SMB_MISSING 2
#define _STR_POPSTARTER_NET_ERR 3
#define _STR_POPSTARTER_NET_INVALID 4
#define _STR_POPSTARTER_SMB_NEEDS_STATIC 5
typedef int item_list_t;
typedef struct { const char *path; const char *arg; } config_set_t;
typedef int vcd_popsnet_ensure_t;
enum { VCD_POPSNET_SMB_MISSING, VCD_POPSNET_NEED_STATIC,
       VCD_POPSNET_IO_ERROR, VCD_POPSNET_INVALID };
static struct { const char *title; } appsList[] = {{"launcHER"}};
static char gOPLPart[128];
static int is_pops, reset_iop, errors, torn_down, launched, sdk_launch;
static int got_argc, got_reset, got_cleanup;
static char got_path[512], got_partition[256], got_argv[2][512];
static int appVisibleToMaster(item_list_t *items, int id) { return id; }
static void configGetStrCopy(config_set_t *c, int key, char *out, size_t size)
{ snprintf(out, size, "%s", c->path); }
static int configGetStr(config_set_t *c, int key, const char **out)
{ *out = c->arg; return c->arg != NULL; }
static int mock_open(const char *path, int flags) { return 1; }
static int mock_close(int fd) { return 0; }
#define open mock_open
#define close mock_close
static int oplPath2Mode(const char *path)
{ return !strncmp(path, "pfs", 3) ? HDD_MODE : APP_MODE; }
static int appIsPopstarterSmb(const char *path) { return 0; }
static const char *ethGetSMBPrefix(void) { return "smb0:"; }
static int vcdPreparePopstarterSmbLaunch(const char *path) { return -1; }
static int appIsPopstarterElf(const char *path, const char *title) { return is_pops; }
static int appGetRebootIopConfig(config_set_t *c) { return reset_iop; }
static int guiPromptRebootIop(void) { return 0; }
static void mmceReset(void) {}
static const char *_l(int id) { return "error"; }
static void guiMsgBox(const char *text, int mode, void *data)
{ assert(!torn_down); errors++; }
static void deinit(int exception, int mode) { torn_down++; }
static int captureLoad(const char *path, const char *partition, int argc, char **argv, int reset, int cleanup)
{
    assert(torn_down == 1);
    launched++;
    got_argc = argc;
    got_reset = reset;
    got_cleanup = cleanup;
    snprintf(got_path, sizeof(got_path), "%s", path);
    snprintf(got_partition, sizeof(got_partition), "%s", partition);
    for (int i = 0; i < argc; i++)
        snprintf(got_argv[i], sizeof(got_argv[i]), "%s", argv[i]);
    return 0;
}
static int sysLoadELF(const char *path, const char *partition, int argc, char **argv, int reset)
{
    return captureLoad(path, partition, argc, argv, reset, 0);
}
int sysLoadELFApp(const char *path, const char *partition, int argc, char **argv, int reset, int cleanup)
{
    return captureLoad(path, partition, argc, argv, reset, cleanup);
}
static void LoadELFFromFileWithPartition(const char *path, const char *partition, int argc, char **argv)
{
    sdk_launch++;
    sysLoadELF(path, partition, argc, argv, 1);
}
'''

TESTS = r'''
static void run(const char *path, const char *arg, int reset, int pops)
{
    config_set_t config = {path, arg};
    reset_iop = reset;
    is_pops = pops;
    errors = torn_down = launched = sdk_launch = got_argc = got_cleanup = 0;
    memset(got_argv, 0, sizeof(got_argv));
    appLaunchItem(NULL, 0, &config);
}
int main(void)
{
    const char *apa = "pfs0:/APPS/Ember/launcHER.elf";
    const char *qualified = "hdd0:+OPL:pfs:/APPS/Ember/launcHER.elf";
    strcpy(gOPLPart, "hdd0:+OPL");
    for (int reset = 0; reset <= 1; reset++) {
        run(apa, NULL, reset, 0);
        assert(launched == 1 && !errors && !sdk_launch && got_argc == 1);
        assert(!strcmp(got_path, apa) && !strcmp(got_argv[0], qualified));
        assert(got_reset == reset && got_cleanup == 1);
        run(apa, "hdd0:__.EMBER/EMBER/launcHER.CNF", reset, 0);
        assert(got_argc == 2 && !strcmp(got_argv[0], qualified));
        assert(!strcmp(got_argv[1], "hdd0:__.EMBER/EMBER/launcHER.CNF"));
        run(apa, "", reset, 0);
        assert(got_argc == 2 && got_argv[1][0] == 0);

        const char *paths[] = {"mass0:/APPS/launcHER.elf", "mc0:/BOOT/launcHER.elf",
                               "mmce0:/APPS/launcHER.elf"};
        for (unsigned i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
            run(paths[i], NULL, reset, 0);
            assert(launched == 1 && !errors);
            assert(!strcmp(got_path, paths[i]) && !strcmp(got_argv[0], paths[i]));
            assert(got_partition[0] == 0 && got_cleanup == 0);
        }

        // NULs, duplicate load path and reset flag all count toward the first hop.
        size_t fixed = strlen(apa) + 1 + strlen(qualified) + 1;
        fixed += reset ? sizeof("-la=RH") : sizeof("-la=H");
        char arg[256];
        memset(arg, 'a', sizeof(arg));
        arg[256 - fixed - 1] = 0;
        run(apa, arg, reset, 0);
        assert(launched == 1 && !errors);
        arg[256 - fixed - 1] = 'a';
        arg[256 - fixed] = 0;
        run(apa, arg, reset, 0);
        assert(errors == 1 && !torn_down && !launched);

        gOPLPart[0] = 0;
        run(apa, NULL, reset, 0);
        assert(errors == 1 && !torn_down && !launched && !sdk_launch);
        run(apa, "hdd0:__.EMBER/EMBER/launcHER.CNF", reset, 0);
        assert(errors == 1 && !torn_down && !launched && !sdk_launch);
        for (unsigned i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
            run(paths[i], NULL, reset, 0);
            assert(launched == 1 && !errors && !sdk_launch);
            assert(!strcmp(got_path, paths[i]) && !strcmp(got_argv[0], paths[i]));
        }
        strcpy(gOPLPart, "hdd0:+OPL");
    }
    strcpy(gOPLPart, "hdd0:__common");
    run("pfs0:OPL/APPS/launcHER.elf", NULL, 0, 0);
    assert(!strcmp(got_path, "pfs0:/OPL/APPS/launcHER.elf"));
    assert(!strcmp(got_argv[0], "hdd0:__common:pfs:/OPL/APPS/launcHER.elf"));
    strcpy(gOPLPart, "hdd0:CustomApps");
    run(apa, NULL, 1, 0);
    assert(!strcmp(got_argv[0], "hdd0:CustomApps:pfs:/APPS/Ember/launcHER.elf"));
    run(apa, "game", 0, 1);
    assert(sdk_launch == 1 && got_argc == 1);
    assert(!strcmp(got_path, apa) && !strcmp(got_partition, "hdd0:CustomApps:"));
    assert(!strcmp(got_argv[0], "game"));
    puts("PASS: APA pfs handoff, HDD cleanup, reset choices, optional argv[1], other devices, POPSTARTER, 256/257-byte boundary");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="opl-app-args-") as temp:
    path = Path(temp)
    harness = path / "launch.c"
    helpers = function("appNormalizeLaunchPath(") + "\n"
    if "appBuildHddHandoffPath(" in text:
        helpers += function("appBuildHddHandoffPath(") + "\n"
    harness.write_text(STUBS + helpers + function("appLaunchItem(") + TESTS)
    executable = path / ("launch.exe" if os.name == "nt" else "launch")
    flags = ["-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter"]
    if source != root / "src/appsupport.c":
        flags.append("-Wno-error=format-truncation")
    subprocess.run([os.environ.get("CC", "gcc"), *flags, str(harness), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
