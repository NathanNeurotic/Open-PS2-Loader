#!/usr/bin/env python3
"""Compile the production DVR scanner and cleanup against a synthetic filesystem."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/hddsupport.c').read_text(encoding='utf-8')


def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


types = source[source.index('#define HDD_DVR_MAX_ISOS'):source.index('/* Read the hardware capability')]
functions = '\n'.join(function(signature) for signature in (
    'static int hddDvrEnsureDrivers(', 'static void hddDvrPublish(', 'static int hddDvrIsIsoName(',
    'static void hddDvrNameToStartup(', 'static int hddDvrCollectDir(',
    'static void hddDvrScan(', 'static void hddDvrCleanUp(',
))
harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { char name[64], startup[12]; int disctype; u32 total_size_in_kb; } hdl_game_info_t;
typedef struct { char name[256]; struct {u32 hisize, size;} stat; } iox_dirent_t;
#define SCECdPS2CD 1
#define SCECdPS2DVD 2
#define FIO_MT_RDONLY 1
#define LOG(...) ((void)0)
static void guiLock(void) {}
static void guiUnlock(void) {}
static int drivers = 1, failedOpen = -1, failedRead = -1, oversized, entryCount = 1;
static int positions[6], unmounts, failedUnmount = -1;
static int gEnableDVR = 1;
static int ataReady = 1, failDrv, failFile, drvCalls, fileCalls, notices;
static int dvrdrv_irx, dvrfile_irx, size_dvrdrv_irx, size_dvrfile_irx;
static int hddDvrHardwarePresent(void) {return drivers;}
static int hddLoadModulesReady(void) {return ataReady;}
static int sysLoadModuleBuffer(void *module, int size, int argc, char *argv) {
    (void)size;(void)argc;(void)argv;
    if (module == &dvrdrv_irx) {drvCalls++;return failDrv ? -2 : 0;}
    assert(module == &dvrfile_irx);fileCalls++;return failFile ? -2 : 0;
}
static void sceCdNoticeGameStart(int mode, void *arg) {(void)mode;(void)arg;notices++;}
static int fileXioDopen(const char *path) {
    const char *colon;
    int part, sub;
    if (!strcmp(path, "dvr_hdd0:")) return 20;
    part = !strncmp(path, "dvr_pfs1:", 9);
    colon = strchr(path, ':');
    if (!colon[1]) return 21;
    sub = !strcmp(colon + 1, "/CD") ? 2 : !strcmp(colon + 1, "/DVD") ? 1 : 0;
    int dir = part * 3 + sub;
    if (dir == failedOpen) return -5;
    positions[dir] = 0;
    return dir;
}
static int fileXioDread(int fd, iox_dirent_t *entry) {
    if (fd == failedRead) return -5;
    if (fd != 1 || positions[fd]++ >= entryCount) return 0;
    memset(entry, 0, sizeof(*entry));
    if (oversized) {memset(entry->name, 'a', 240); strcpy(entry->name + 240, ".iso");}
    else strcpy(entry->name, "SLUS_211.34.RE4.iso");
    entry->stat.size = 4096;
    return 1;
}
static int fileXioDclose(int fd) {(void)fd;return 0;}
static int fileXioMount(const char *dst, const char *src, int mode) {
    (void)dst;(void)src;assert(mode == FIO_MT_RDONLY);return 0;
}
static int fileXioUmount(const char *path) {
    unmounts++;
    return ((strncmp(path, "dvr_pfs1:", 9) == 0) == failedUnmount) ? -5 : 0;
}
@TYPES@
@FUNCTIONS@
int main(void) {
    gEnableDVR = 0;hddDvrScan();assert(!drvCalls && !fileCalls);gEnableDVR = 1;
    drivers = 0;hddDvrScan();assert(!hddDvrGames && !hddDvrGameCount && !drvCalls && !fileCalls);
    drivers = 1;ataReady = 0;hddDvrScan();assert(!drvCalls && !fileCalls);
    ataReady = 1;failDrv = 1;hddDvrScan();hddDvrScan();
    assert(drvCalls == 1 && !fileCalls && !hddDvrDriverReady);
    /* Simulate a fresh GUI process after a failed base-driver start. */
    hddDvrDriverTried = 0;drvCalls = 0;failDrv = 0;failFile = 1;
    hddDvrScan();assert(drvCalls == 1 && fileCalls == 1 && !hddDvrDriverReady);
    failFile = 0;hddDvrScan();
    assert(drvCalls == 1 && fileCalls == 2 && hddDvrDriverReady && notices == 1);
    hddDvrScan();assert(drvCalls == 1 && fileCalls == 2 && notices == 1);
    assert(hddDvrGameCount == 1);
    assert(!strcmp(hddDvrGames[0].path, "dvr_pfs0:/DVD/SLUS_211.34.RE4.iso"));
    assert(!strcmp(hddDvrGames[0].game.startup, "SLUS_211.34"));
    hdd_dvr_iso_t *lastGood = hddDvrGames;
    failedOpen = 1;hddDvrScan();assert(hddDvrGames == lastGood && hddDvrGameCount == 1);
    failedOpen = -1;failedRead = 1;hddDvrScan();assert(hddDvrGames == lastGood);
    failedRead = -1;oversized = 1;hddDvrScan();assert(hddDvrGames == lastGood);
    oversized = 0;entryCount = HDD_DVR_MAX_ISOS + 1;hddDvrScan();assert(hddDvrGames == lastGood);
    entryCount = 0;hddDvrScan();assert(hddDvrGameCount == 0); /* proven empty may replace old list */
    hddDvrMounted[0] = hddDvrMounted[1] = 1;
    hddDvrCleanUp(1);
    assert(!hddDvrGames && !hddDvrGameCount && !unmounts);
    assert(hddDvrMounted[0] && hddDvrMounted[1]);
    failedUnmount = 1;
    hddDvrCleanUp(0);assert(unmounts == 2 && !hddDvrMounted[0] && hddDvrMounted[1]);
    failedUnmount = -1;
    hddDvrCleanUp(0);assert(unmounts == 3 && !hddDvrMounted[1]);
    hddDvrCleanUp(0);assert(unmounts == 3);
    puts("PASS: DVR scan publication, partial-open/read failures, overflow and mount handoff");
}
'''.replace('@TYPES@', types).replace('@FUNCTIONS@', functions)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    c = path / 'dvr.c'
    exe = path / 'dvr.exe'
    c.write_text(harness, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-variable', '-Wno-unused-but-set-variable', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
