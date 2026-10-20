#!/usr/bin/env python3
"""The HDD "mini" argv autolaunch boots the HDL game it names, and refuses anything else.

External launchers (OPL-Launcher / HDD-OSD / PSBBN) start RiptOPL with argv startup, start_sector,
partition hint, "mini". That carries no partition name, and since 9cf34fdd hddLaunchGame refuses an
autolaunch without one, so every such launch fell back to the menu. Before that, a global Neutrino
core sent an empty -dvd=hdl: that Neutrino could not open.

Compiles the real hddResolveAutoLaunchGame and hddLaunchGame's autolaunch guard from
src/hddsupport.c, the partition copy from hddTryNeutrinoLaunch and the -dvd=hdl: composition from
src/system.c, against a fake APA HDL list. Checks: a mini launch takes its partition name and size
from the matching row, the Neutrino leg gets -dvd=hdl:<partition>, and an unmatched sector, a zero
sector or an unreadable list refuses. Not a hardware test.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
hdd = (root / 'src/hddsupport.c').read_text(encoding='utf-8').replace('\r\n', '\n')
system = (root / 'src/system.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function(src, signature, name):
    match = re.search(signature, src, re.M)
    if match is None:
        sys.exit('%s: %s not found' % (name, signature))
    return src[match.start():src.index('\n}', match.start()) + 3]


def snippet(src, pattern, name, what):
    match = re.search(pattern, src, re.S)
    if match is None:
        sys.exit('%s: %s not found' % (name, what))
    return match.group(0)


resolver = function(hdd, r'^static int hddResolveAutoLaunchGame\(hdl_game_info_t \*game\)\s*\{', 'src/hddsupport.c')
launch = function(hdd, r'^void hddLaunchGame\(item_list_t \*itemList, int id, config_set_t \*configSet\)\s*\{',
                  'src/hddsupport.c')
guard = snippet(launch, r"if \(game->partition_name\[0\] == '\\0' && hddResolveAutoLaunchGame\(game\) < 0\) \{.*?\n\s+\}",
                'hddLaunchGame', 'the autolaunch resolve-or-refuse guard')
neutrino = function(hdd, r'^static int hddTryNeutrinoLaunch\(hdl_game_info_t \*game, config_set_t \*configSet\)\s*\{',
                    'src/hddsupport.c')
apaPart = snippet(neutrino, r'snprintf\(apaPart, sizeof\(apaPart\), "%s", game->partition_name\);',
                  'hddTryNeutrinoLaunch', 'the apaPart copy of game->partition_name')
if 'sysNeutrinoArgsPreflight("apa", apaPart,' not in neutrino:
    failures.append('hddTryNeutrinoLaunch: the apa preflight/launch must be handed apaPart (the partition name)')
dvd = snippet(system, r'snprintf\(filePath, sizeof\(filePath\), "-dvd=hdl:%s", path\);', 'src/system.c',
              'the apa -dvd=hdl: composition')

# The guard must run before either core sees the game.
guardAt = launch.find('hddResolveAutoLaunchGame(game)')
if guardAt < 0 or guardAt > launch.find('hddTryNeutrinoLaunch(game, configSet)'):
    failures.append('hddLaunchGame: resolve the mini launch before hddTryNeutrinoLaunch')
if guardAt > launch.find('settings->lba_start = game->start_sector;'):
    failures.append('hddLaunchGame: resolve the mini launch before the native core reads the row')
if 'hddGetHDLGamelist(&list)' not in resolver:
    failures.append('hddResolveAutoLaunchGame: reuse the HDD tab enumeration (hddGetHDLGamelist), read-only')
for forbidden in ('fileXioOpen', 'fileXioWrite', 'fileXioRemove', 'hddWrite', 'fileXioFormat', 'fileXioDevctl'):
    if forbidden in resolver:
        failures.append('hddResolveAutoLaunchGame: must stay read-only on APA (found %s)' % forbidden)

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned char u8;
typedef unsigned int u32;
#define APA_IDMAX 32
#define HDL_GAME_NAME_MAX 64
#define LOG(...) ((void)0)

typedef struct
{
    char partition_name[APA_IDMAX + 1];
    char name[HDL_GAME_NAME_MAX + 1];
    char startup[8 + 1 + 3 + 1];
    u8 hdl_compat_flags;
    u8 ops2l_compat_flags;
    u8 dma_type;
    u8 dma_mode;
    u8 disctype;
    u32 layer_break;
    u32 start_sector;
    u32 total_size_in_kb;
} hdl_game_info_t;

typedef struct
{
    u32 count;
    hdl_game_info_t *games;
} hdl_games_list_t;

/* The fake APA table: the HDD tab's rows. */
static const hdl_game_info_t table[] = {
    {"PP.SLUS_203.12.GAME_ONE", "Game One", "SLUS_203.12", 0, 0, 0, 0, 0x14, 0, 0x00104A00, 2097152},
    {"PP.SLES_535.05.BEAT_DOWN", "Beat Down", "SLES_535.05", 1, 2, 0x40, 4, 0x14, 1234, 0x0020C800, 4194304},
    {"PP.SLPM_661.81.THIRD", "Third", "SLPM_661.81", 0, 0, 0, 0, 0x12, 0, 0x00418000, 655360},
};
static int listFails, listCalls, liveLists;

static int hddGetHDLGamelist(hdl_games_list_t *game_list)
{
    listCalls++;
    if (listFails)
        return -5;
    game_list->games = malloc(sizeof(table));
    memcpy(game_list->games, table, sizeof(table));
    game_list->count = sizeof(table) / sizeof(table[0]);
    liveLists++;
    return 0;
}

static void hddFreeHDLGamelist(hdl_games_list_t *game_list)
{
    if (game_list->games != NULL) {
        free(game_list->games);
        game_list->games = NULL;
        game_list->count = 0;
        liveLists--;
    }
}

@RESOLVER@

/* hddLaunchGame's autolaunch branch, then the Neutrino leg's -dvd composition. 1 = launched. */
static int autoLaunch(hdl_game_info_t *game, char *dvdArg, int dvdSize)
{
    dvdArg[0] = '\0';
    @GUARD@
    char apaPart[APA_IDMAX + 1];
    @APAPART@
    char filePath[288];
    const char *path = apaPart;
    @DVD@
    snprintf(dvdArg, dvdSize, "%s", filePath);
    return 1;
}

/* What autoLaunchHDDGame builds from the launcher's argv. */
static void mini(hdl_game_info_t *game, const char *startup, const char *sector)
{
    memset(game, 0, sizeof(*game));
    snprintf(game->startup, sizeof(game->startup), "%s", startup);
    game->start_sector = strtoul(sector, NULL, 0);
}

static int fails;
#define CHECK(cond, what) do { if (!(cond)) { printf("FAIL: %s\n", what); fails++; } } while (0)

int main(void)
{
    hdl_game_info_t game;
    char dvd[300];

    mini(&game, "SLES_535.05", "2148352"); /* 0x0020C800, as OPL-Launcher passes it */
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 1, "a mini launch of an installed HDL game is not refused");
    CHECK(strcmp(game.partition_name, "PP.SLES_535.05.BEAT_DOWN") == 0, "a mini launch resolves its partition name");
    CHECK(strcmp(dvd, "-dvd=hdl:PP.SLES_535.05.BEAT_DOWN") == 0, "the Neutrino leg gets -dvd=hdl:<partition>");
    CHECK(strcmp(dvd, "-dvd=hdl:") != 0, "the Neutrino leg never gets an empty -dvd=hdl:");
    CHECK(game.total_size_in_kb == 4194304, "the native core gets the media size (mediaLsnCount)");
    CHECK(game.start_sector == 0x0020C800, "the data LBA is the launcher's");
    CHECK(game.layer_break == 1234 && game.dma_type == 0x40 && game.dma_mode == 4 && game.disctype == 0x14,
          "the rest of the HDL row comes along");
    CHECK(strcmp(game.name, "Beat Down") == 0 && strcmp(game.startup, "SLES_535.05") == 0, "name and startup filled");

    mini(&game, "SLUS_999.99", "0x00104A00");
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 1, "a hex start_sector resolves too");
    CHECK(strcmp(game.partition_name, "PP.SLUS_203.12.GAME_ONE") == 0, "hex sector -> its partition");
    CHECK(strcmp(game.startup, "SLUS_999.99") == 0, "the launcher's startup is kept: its CFG was already read under it");

    mini(&game, "", "4292608");
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 1 && strcmp(game.startup, "SLPM_661.81") == 0,
          "an empty launcher startup takes the HDL header's");

    mini(&game, "SLES_535.05", "2148353");
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 0, "an unmatched start_sector refuses");
    CHECK(game.partition_name[0] == '\0' && dvd[0] == '\0', "a refused launch builds no -dvd and names no partition");

    mini(&game, "SLES_535.05", "0");
    listCalls = 0;
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 0 && listCalls == 0, "a zero/garbage start_sector refuses without a scan");

    mini(&game, "SLES_535.05", "2148352");
    listFails = 1;
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 0, "an unreadable APA table refuses");
    listFails = 0;

    /* A row that already names its partition (a menu-style game) is never re-resolved. */
    mini(&game, "SLES_535.05", "2148352");
    snprintf(game.partition_name, sizeof(game.partition_name), "%s", "PP.KNOWN");
    listCalls = 0;
    CHECK(autoLaunch(&game, dvd, sizeof(dvd)) == 1 && listCalls == 0 && strcmp(dvd, "-dvd=hdl:PP.KNOWN") == 0,
          "a named partition skips the scan");

    CHECK(liveLists == 0, "every scanned list is freed");
    return fails ? 1 : 0;
}
'''

if not failures:
    # The guard's bare `return;` is "refused" here.
    program = (HARNESS.replace('@RESOLVER@', resolver).replace('@GUARD@', guard.replace('return;', 'return 0;'))
               .replace('@APAPART@', apaPart).replace('@DVD@', dvd))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'hddmini.c'
        exe = Path(tmp) / ('hddmini' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=10)
            if run.returncode != 0:
                failures.extend(run.stdout.strip().splitlines() or ['harness exited %d' % run.returncode])

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('HDD mini autolaunch: resolves its HDL partition, feeds -dvd=hdl:<part>, refuses unmatched sectors')
