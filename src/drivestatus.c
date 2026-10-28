/*
  Drive Status, ported from RIPPS2 build 114 (akilluminati47/RIPPS2, ripps2status.c: DRIVES and SAVE DIAGNOSTICS).

  Every drive OPL sees, with the space it says it has: each started BDM drive by its driver (format, free space,
  cluster size), the APA HDD, MMCE cards and memory cards, then where the settings live. Save Diagnostics writes the
  hardware log to DIAG.TXT (diaglog.c). RIPPS2's launcher, boot loader and sounds sections are its own and stay there.
*/

#define NEWLIB_PORT_AWARE // fileXioDopen and fileXioDevctl: the driver name and the devctls have no POSIX call

#include <stdio.h>
#include <string.h>
#include <dirent.h>
#include <libmc.h>
#include <fileXio_rpc.h>

#include "include/opl.h"
#include "include/gui.h"
#include "include/lang.h"
#include "include/dialogs.h"
#include "include/config.h"
#include "include/sound.h"
#include "include/bdmsupport.h"
#include "include/hddsupport.h"
#include "include/diaglog.h"
#include "include/drivestatus.h"
#include "include/vmc_alloc.h"

#define DS_LINE_SIZE 160

static char dsLines[DSTAT_LINES][DS_LINE_SIZE];
static int dsCount;

// "12.3 GB" from KB
void dsSizeText(unsigned long long kb, char *out, int size)
{
    if (kb >= 1024ULL * 1024 * 1024)
        snprintf(out, size, "%u.%u TB", (unsigned)(kb >> 30), (unsigned)((kb & ((1ULL << 30) - 1)) * 10 >> 30));
    else if (kb >= 1024 * 1024)
        snprintf(out, size, "%u.%u GB", (unsigned)(kb >> 20), (unsigned)((kb & ((1 << 20) - 1)) * 10 >> 20));
    else if (kb >= 1024)
        snprintf(out, size, "%u MB", (unsigned)(kb >> 10));
    else
        snprintf(out, size, "%u KB", (unsigned)kb);
}

// A BDM driver by what it is; NULL for the exFAT HDD, which the caller names in the chosen language
const char *dsDriverLabel(const char *driver)
{
    if (!strcmp(driver, "usb"))
        return "USB";
    if (!strcmp(driver, "sd") || !strcmp(driver, "ilink"))
        return "iLink";
    if (!strcmp(driver, "sdc") || !strcmp(driver, "mx4sio"))
        return "MX4SIO";
    if (!strcmp(driver, "udp"))
        return "UDPBD";
    if (!strcmp(driver, "ata"))
        return NULL;
    return driver;
}

const char *dsFsName(unsigned int fsType)
{
    return fsType == 4 ? "exFAT" : fsType == 3 ? "FAT32" :
                               fsType == 2     ? "FAT16" :
                                                 "FAT12";
}

static char *dsAdd(void)
{
    if (dsCount >= DSTAT_LINES)
        return NULL;
    return dsLines[dsCount++];
}

static void dsScan(void)
{
    char *line, root[16], driver[32], a[24], b[24], c[24];
    unsigned int o[4];
    int i;

    guiRenderTextScreen(_l(_STR_DRIVE_STATUS_SCANNING));
    dsCount = 0;

    for (i = 0; i < MAX_BDM_DEVICES; i++) {
        const char *label;
        int n, dir;
        snprintf(root, sizeof(root), "mass%d:/", i);
        driver[0] = '\0';
        if ((dir = fileXioDopen(root)) < 0)
            continue; // nothing mounted in this slot
        bdmReadDriverName(dir, driver, sizeof(driver));
        fileXioDclose(dir);
        if ((line = dsAdd()) == NULL)
            break;
        label = driver[0] ? dsDriverLabel(driver) : _l(_STR_DRIVE_STATUS_UNKNOWN);
        n = snprintf(line, DS_LINE_SIZE, "mass%d:/  %s", i, label != NULL ? label : _l(_STR_DRIVE_STATUS_EXFAT_HDD));
        root[strlen(root) - 1] = '\0'; // the devctl goes to "massN:"
        memset(o, 0, sizeof(o));
        if (n < DS_LINE_SIZE && fileXioDevctl(root, BDM_DEVCTL_VOLINFO, NULL, 0, o, sizeof(o)) == 0 && o[2] != 0 && o[3] >= 1 && o[3] <= 4) {
            dsSizeText(o[0], a, sizeof(a));
            dsSizeText(o[1], b, sizeof(b));
            char space[DS_LINE_SIZE];
            if (o[2] >= 1024)
                dsSizeText(o[2] / 1024, c, sizeof(c));
            else
                snprintf(c, sizeof(c), "%u B", o[2]);
            snprintf(space, sizeof(space), _l(_STR_DRIVE_STATUS_SPACE), a, b, dsFsName(o[3]), c);
            snprintf(line + n, DS_LINE_SIZE - n, "   %s", space);
        }
    }

    {
        u32 total = 0, freeS = 0;
        if (hddModulesAreLoaded() && hddGetSpace(&total, &freeS) && (line = dsAdd()) != NULL) {
            dsSizeText(freeS / 2, a, sizeof(a));
            dsSizeText(total / 2, b, sizeof(b));
            snprintf(line, DS_LINE_SIZE, _l(_STR_DRIVE_STATUS_HDD), a, b);
        }
    }

    for (i = 0; i < 2; i++) {
        DIR *d;
        snprintf(root, sizeof(root), "mmce%d:/", i);
        if ((d = opendir(root)) == NULL)
            continue;
        closedir(d);
        if ((line = dsAdd()) != NULL)
            snprintf(line, DS_LINE_SIZE, "%s  MMCE", root);
    }

    for (i = 0; i < 2; i++) {
        int type = 0, freeClusters = -1, format = 0, result = -1;
        mcGetInfo(i, 0, &type, &freeClusters, &format);
        mcSync(0, NULL, &result); // mcGetInfo is async; the values are good after the sync
        if (type != sceMcTypePS2 || format != MC_FORMATTED || freeClusters < 0 || (line = dsAdd()) == NULL)
            continue;
        snprintf(line, DS_LINE_SIZE, _l(_STR_DRIVE_STATUS_MC), i + 1, freeClusters); // a card's cluster is 1 KB
    }

    if (dsCount == 0 && (line = dsAdd()) != NULL)
        snprintf(line, DS_LINE_SIZE, "%s", _l(_STR_DRIVE_STATUS_NONE));
    if ((line = dsAdd()) != NULL)
        snprintf(line, DS_LINE_SIZE, _l(_STR_DRIVE_STATUS_SETTINGS), configGetHomePath());

    for (i = 0; i < DSTAT_LINES; i++) {
        diaSetLabel(diaDriveStatus, DSTAT_LINE_FIRST + i, i < dsCount ? dsLines[i] : "");
        diaSetVisible(diaDriveStatus, DSTAT_LINE_FIRST + i, i < dsCount);
    }
}

void guiShowDriveStatus(void)
{
    int ret;

    dsScan();
    diagLog("drive status: %d lines", dsCount);
    while ((ret = diaExecuteDialog(diaDriveStatus, -1, 1, NULL)) == DSTAT_SAVE_DIAG) {
        char where[300], msg[400];
        int ok = diagSave(NULL, where, sizeof(where));
        snprintf(msg, sizeof(msg), _l(ok ? _STR_DIAG_SAVED : _STR_DIAG_SAVE_FAILED), where);
        guiMsgBox(msg, 0, NULL);
    }
}
