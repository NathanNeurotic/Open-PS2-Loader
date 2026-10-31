/*
  Licenced under Academic Free License version 3.0
  Review Open PS2 Loader README & LICENSE files for further details.
*/

// File Manager (main menu), after RIPPS2's Memory Files browser (akilluminati47/RIPPS2, ripps2files.c). RIPPS2
// draws its own glass screen; here it is an OPL dialog, one button per entry, on the drivers OPL already runs:
//
// - Drives: every started BDM drive, MMCE and memory card, the OPL partition on the internal HDD (pfs0:, never
//   an APA partition itself), a UDPFS server and the SMB share.
// - A folder lists ".." first, then its folders, then its files with their sizes; a memory card save shows the
//   title from its icon.sys. Pages of FM_ROWS: L1/R1 turn them.
// - Cross opens a folder, or shows what can be done with a file; Square marks; Triangle shows what can be done
//   with any entry; Circle goes up a folder (out of the drive list, it closes).
// - Copy, Cut, Paste here, Delete (asked first), Rename and New folder; Copy as PSU on a save folder, Unpack PSU
//   on a .psu (onto a memory card the save lands in the card's root); Run on an ELF, the way an app starts.
// - Everything that changes a drive needs Write Operations on.
//
// The file work is in filemgr.c (host tested); PSU through vmcsaves.c, the same code as VMC Saves.

#define NEWLIB_PORT_AWARE // fileXioDopen: a BDM drive's driver name

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <libmc.h>
#include <fileXio_rpc.h>

#include "include/opl.h"
#include "include/gui.h"
#include "include/dia.h"
#include "include/lang.h"
#include "include/dialogs.h"
#include "include/pad.h"
#include "include/bdmsupport.h"
#include "include/hddsupport.h"
#include "include/ethsupport.h"
#include "include/udpfssupport.h"
#include "include/drivestatus.h"
#include "include/appsupport.h"
#include "include/guigame.h"
#include "include/vmcsaves.h"
#include "include/filemgr.h"
#include "include/guifilemgr.h"

#define FM_MAX      512 // entries read from one folder
#define FM_CLIP_MAX 128
#define FM_PATH     320
#define FM_ROW_TEXT 160
#define FM_TITLE    48

static char fmDir[FM_PATH];          // "" is the drive list
static fm_entry_t *fmList_;          // the folder's entries (or the drives, by their roots)
static char (*fmLabel)[FM_ROW_TEXT]; // a drive's words, or a card save's title ("" for none)
static unsigned char *fmMarked;
static int fmCount, fmPage, fmOpenFailed;

static char (*fmClip)[FM_PATH];
static unsigned char fmClipIsDir[FM_CLIP_MAX];
static int fmClipCount, fmClipCut;

static char fmRowText[FM_ROWS][FM_ROW_TEXT];
static char fmStatusText[200];

static int fmIsMcPath(const char *path)
{
    return !strncmp(path, "mc", 2) && (path[2] == '0' || path[2] == '1') && path[3] == ':';
}

static int fmHasSuffix(const char *name, const char *suffix)
{
    int n = strlen(name), s = strlen(suffix);
    return n >= s && !strcasecmp(name + n - s, suffix);
}

static int fmInFolder(void)
{
    return fmDir[0] != '\0';
}

// Rows: in a folder ".." is row 0 and entry i is row i + 1; the drive list has no ".."
static int fmRows(void)
{
    return fmCount + (fmInFolder() ? 1 : 0);
}

static int fmPages(void)
{
    int pages = (fmRows() + FM_ROWS - 1) / FM_ROWS;
    return pages > 0 ? pages : 1;
}

// The entry a row shows: -1 for "..", -2 for none
static int fmEntryAt(int row)
{
    int v = fmPage * FM_ROWS + row;
    if (v >= fmRows())
        return -2;
    if (fmInFolder())
        return v - 1;
    return v;
}

static void fmPath(char *out, int size, int i)
{
    if (!fmJoin(out, size, fmDir, fmList_[i].name))
        out[0] = '\0';
}

static const char *fmErrText(int err)
{
    switch (err) {
        case FM_ERR_EXISTS:
            return _l(_STR_FM_ERR_EXISTS);
        case FM_ERR_INSIDE:
            return _l(_STR_FM_ERR_INSIDE);
        case FM_ERR_NAME:
            return _l(_STR_FM_ERR_NAME);
        case FM_ERR_READ:
            return _l(_STR_FM_ERR_READ);
        case FM_ERR_DELETE:
            return _l(_STR_FM_ERR_DELETE);
        case FM_ERR_DEEP:
            return _l(_STR_FM_ERR_DEEP);
        case FM_ERR_MEMORY:
            return _l(_STR_FM_ERR_MEMORY);
        default:
            return _l(_STR_FM_ERR_WRITE);
    }
}

static void fmShowFailure(const char *name, const char *why)
{
    char msg[FM_PATH + 200];
    snprintf(msg, sizeof(msg), _l(_STR_FM_FAILED), name, why);
    guiMsgBox(msg, 0, NULL);
}

static int fmCanWrite(void)
{
    if (gEnableWrite)
        return 1;
    guiMsgBox(_l(_STR_FM_READ_ONLY), 0, NULL);
    return 0;
}

// ---- reading ----

static int fmAddDrive(const char *root, const char *label)
{
    if (fmCount >= FM_MAX)
        return 0;
    snprintf(fmList_[fmCount].name, FM_NAME, "%s", root);
    fmList_[fmCount].isDir = 1;
    fmList_[fmCount].size = 0;
    snprintf(fmLabel[fmCount], FM_ROW_TEXT, "%s  %s", root, label);
    fmCount++;
    return 1;
}

static int fmDirOpens(const char *root)
{
    DIR *d = opendir(root);
    if (d == NULL)
        return 0;
    closedir(d);
    return 1;
}

static void fmScanDrives(void)
{
    char root[16], driver[32], words[FM_ROW_TEXT], a[24], b[24];
    int i;

    guiRenderTextScreen(_l(_STR_DRIVE_STATUS_SCANNING));
    fmCount = 0;
    for (i = 0; i < MAX_BDM_DEVICES; i++) {
        const char *label;
        int dir;
        snprintf(root, sizeof(root), "mass%d:/", i);
        if ((dir = fileXioDopen(root)) < 0)
            continue; // nothing mounted in this slot
        driver[0] = '\0';
        bdmReadDriverName(dir, driver, sizeof(driver));
        fileXioDclose(dir);
        label = driver[0] ? dsDriverLabel(driver) : _l(_STR_DRIVE_STATUS_UNKNOWN);
        fmAddDrive(root, label != NULL ? label : _l(_STR_DRIVE_STATUS_EXFAT_HDD));
    }
    for (i = 0; i < 2; i++) {
        snprintf(root, sizeof(root), "mmce%d:/", i);
        if (fmDirOpens(root))
            fmAddDrive(root, "MMCE");
    }
    for (i = 0; i < 2; i++) {
        int type = 0, freeClusters = -1, format = 0, result = -1;
        mcGetInfo(i, 0, &type, &freeClusters, &format);
        mcSync(0, NULL, &result); // mcGetInfo is async; the values are good after the sync
        if (type != sceMcTypePS2 || format != MC_FORMATTED)
            continue;
        snprintf(root, sizeof(root), "mc%d:/", i);
        snprintf(words, sizeof(words), _l(_STR_DRIVE_STATUS_MC), i + 1, freeClusters < 0 ? 0 : freeClusters);
        fmAddDrive(root, words);
    }
    if (hddModulesAreLoaded() && fmDirOpens("pfs0:/")) { // the OPL partition, mounted; APA itself is never listed
        u32 total = 0, freeS = 0;
        if (hddGetSpace(&total, &freeS)) {
            dsSizeText(freeS / 2, a, sizeof(a));
            dsSizeText(total / 2, b, sizeof(b));
            snprintf(words, sizeof(words), _l(_STR_DRIVE_STATUS_HDD), a, b);
        } else
            snprintf(words, sizeof(words), "HDD");
        fmAddDrive("pfs0:/", words);
    }
    if (udpfsGetModulesLoaded() && fmDirOpens("udpfs:/"))
        fmAddDrive("udpfs:/", "UDPFS");
    if (ethIsSMBShareConnected() && fmDirOpens("smb0:\\"))
        fmAddDrive("smb0:\\", "SMB");
}

// A memory card save folder's title, from its icon.sys ("" when it has none)
static void fmCardTitle(const char *name, char *out, int size)
{
    char path[FM_PATH];
    unsigned char iconSys[964];
    int fd, n;

    out[0] = '\0';
    snprintf(path, sizeof(path), "%.4s%s/icon.sys", fmDir, name); // mcman's form, "mc0:SAVE/icon.sys"
    if ((fd = open(path, O_RDONLY)) < 0)
        return;
    n = read(fd, iconSys, sizeof(iconSys));
    close(fd);
    if (n >= 0xC0 + 68)
        vmcSavesTitle(iconSys, n, out, size < FM_TITLE ? size : FM_TITLE);
}

static void fmLoad(void)
{
    int i;

    fmOpenFailed = 0;
    memset(fmMarked, 0, FM_MAX);
    if (!fmInFolder()) {
        fmScanDrives();
        return;
    }
    fmCount = fmList(fmDir, fmList_, FM_MAX);
    if (fmCount < 0) {
        fmCount = 0;
        fmOpenFailed = 1;
    }
    for (i = 0; i < fmCount; i++) {
        fmLabel[i][0] = '\0';
        if (fmList_[i].isDir && fmIsMcPath(fmDir) && strlen(fmDir) == 5) // saves live in a card's root
            fmCardTitle(fmList_[i].name, fmLabel[i], FM_ROW_TEXT);
    }
}

static void fmOpen(const char *dir)
{
    char was[FM_PATH];

    snprintf(was, sizeof(was), "%s", fmDir);
    snprintf(fmDir, sizeof(fmDir), "%s", dir);
    fmPage = 0;
    fmLoad();
    if (fmOpenFailed) {
        char msg[FM_PATH + 64];
        snprintf(msg, sizeof(msg), _l(_STR_FM_CANT_OPEN), dir);
        guiMsgBox(msg, 0, NULL);
        snprintf(fmDir, sizeof(fmDir), "%s", was);
        fmLoad();
    }
}

// Up a folder; from a device root, back to the drives
static void fmUp(void)
{
    char parent[FM_PATH];

    if (fmParent(parent, sizeof(parent), fmDir))
        fmOpen(parent);
    else {
        fmDir[0] = '\0';
        fmPage = 0;
        fmLoad();
    }
}

// ---- the page ----

static void fmFill(void)
{
    char size[24], clip[64], marked[32];
    int r, i, marks = 0;

    if (fmPage >= fmPages())
        fmPage = fmPages() - 1;
    for (i = 0; i < fmCount; i++)
        marks += fmMarked[i];

    diaSetLabel(diaFileManager, FM_PATH, fmInFolder() ? fmDir : _l(_STR_FM_DRIVES));
    clip[0] = marked[0] = '\0';
    if (fmClipCount > 0)
        snprintf(clip, sizeof(clip), _l(fmClipCut ? _STR_FM_CLIP_CUT : _STR_FM_CLIP_COPY), fmClipCount);
    if (marks > 0)
        snprintf(marked, sizeof(marked), _l(_STR_FM_MARKED), marks);
    if (fmInFolder() && fmCount == 0)
        snprintf(fmStatusText, sizeof(fmStatusText), "%s   %s", _l(_STR_FM_EMPTY), clip);
    else {
        int n = snprintf(fmStatusText, sizeof(fmStatusText), _l(_STR_FM_PAGE), fmPage + 1, fmPages(), fmCount);
        if (n > 0 && n < (int)sizeof(fmStatusText))
            snprintf(fmStatusText + n, sizeof(fmStatusText) - n, "   %s   %s", clip, marked);
    }
    diaSetLabel(diaFileManager, FM_STATUS, fmStatusText);

    for (r = 0; r < FM_ROWS; r++) {
        int e = fmEntryAt(r), id = FM_ROW_FIRST + r;
        diaSetVisible(diaFileManager, id, e != -2);
        if (e == -2)
            continue;
        if (e == -1)
            snprintf(fmRowText[r], FM_ROW_TEXT, "%s", _l(_STR_FM_UP));
        else if (!fmInFolder())
            snprintf(fmRowText[r], FM_ROW_TEXT, "%s", fmLabel[e]);
        else if (fmList_[e].isDir)
            snprintf(fmRowText[r], FM_ROW_TEXT, "%s%.60s/%s%s%s", fmMarked[e] ? "* " : "", fmList_[e].name,
                     fmLabel[e][0] ? "   (" : "", fmLabel[e], fmLabel[e][0] ? ")" : "");
        else {
            fmSizeText(fmList_[e].size, size, sizeof(size));
            snprintf(fmRowText[r], FM_ROW_TEXT, "%s%.60s   %s", fmMarked[e] ? "* " : "", fmList_[e].name, size);
        }
        diaSetLabel(diaFileManager, id, fmRowText[r]);
    }
    diaSetEnabled(diaFileManager, FM_PASTE_BTN, fmInFolder() && fmClipCount > 0 && gEnableWrite);
    // PSU files belong on a drive, not a memory card (onto a card, Paste here unpacks a .psu instead)
    diaSetEnabled(diaFileManager, FM_PASTE_PSU_BTN, fmInFolder() && fmClipCount > 0 && gEnableWrite && !fmIsMcPath(fmDir));
    diaSetEnabled(diaFileManager, FM_NEW_FOLDER_BTN, fmInFolder() && gEnableWrite);
}

// ---- doing ----

static int fmLastPercent;

static void fmProgressShow(const char *name, unsigned long long done, unsigned long long total)
{
    char text[FM_PATH];
    int percent = total > 0 ? (int)(done * 100 / total) : 100;
    if (percent == fmLastPercent)
        return; // one frame a percent: drawing each 64 KB would slow the copy
    fmLastPercent = percent;
    snprintf(text, sizeof(text), _l(_STR_FM_WORKING), name, percent);
    guiRenderTextScreen(text);
}

// The marked entries, or entry e if none are marked; how many
static int fmSelection(int e, int *out)
{
    int i, n = 0;
    for (i = 0; i < fmCount; i++)
        if (fmMarked[i])
            out[n++] = i;
    if (n == 0 && e >= 0)
        out[n++] = e;
    return n;
}

static void fmToClipboard(int e, int cut)
{
    static int sel[FM_MAX];
    int n = fmSelection(e, sel), i;

    fmClipCount = 0;
    fmClipCut = cut;
    for (i = 0; i < n && fmClipCount < FM_CLIP_MAX; i++) {
        fmPath(fmClip[fmClipCount], FM_PATH, sel[i]);
        if (fmClip[fmClipCount][0] == '\0')
            continue;
        fmClipIsDir[fmClipCount++] = (unsigned char)fmList_[sel[i]].isDir;
    }
    memset(fmMarked, 0, FM_MAX);
}

// A save folder (one with an icon.sys)
static int fmIsSaveFolder(const char *path)
{
    char icon[FM_PATH];
    return fmJoin(icon, sizeof(icon), path, "icon.sys") && fmExists(icon);
}

// Where a pasted entry goes: here, except that a save folder pasted onto a memory card lands in the card's
// root, where the console looks for saves (RIPPS2)
static void fmPasteTarget(const char *src, int isDir, char *out, int size)
{
    if (isDir && fmIsMcPath(fmDir) && fmIsSaveFolder(src))
        snprintf(out, size, "%.4s/", fmDir);
    else
        snprintf(out, size, "%s", fmDir);
}

// vmcsaves takes a folder with its separator on the end ("mass0:/SAVES/"); a memory card in mcman's own form,
// "mc0:", so a save's files are "mc0:SAVE/FILE"
static void fmDirSlash(char *out, int size, const char *dir)
{
    int n = strlen(dir);
    if (fmIsMcPath(dir))
        snprintf(out, size, "%.4s", dir);
    else if (n > 0 && (dir[n - 1] == '/' || dir[n - 1] == '\\'))
        snprintf(out, size, "%s", dir);
    else
        snprintf(out, size, "%s%c", dir, fmSep(dir));
}

// A vmcsaves result (1 done, -1 already there, 0 failed) as the words a failure shows; NULL for done
static const char *fmPsuWhy(int r)
{
    if (r == 1)
        return NULL;
    return r < 0 ? _l(_STR_FM_ERR_EXISTS) : _l(guiGameVMCSavesErrorText());
}

// Paste here (asPsu 0) or Paste as PSU (1): every clipboard entry into this folder. A failure is named and the
// rest still go; a name already here is never replaced.
static void fmPaste(int asPsu)
{
    char target[FM_PATH], parent[FM_PATH], failedName[FM_NAME];
    const char *why = NULL, *firstWhy = NULL;
    int i, failed = 0, done = 0, ok;

    if (!fmCanWrite() || fmClipCount == 0)
        return;
    failedName[0] = '\0';
    for (i = 0; i < fmClipCount; i++) {
        const char *name = fmBaseName(fmClip[i]);
        fmLastPercent = -1;
        fmProgressShow(name, 0, 1);
        why = NULL;
        if (asPsu) {
            // Paste as PSU: a save folder becomes <here>/<save>.psu (RIPPS2's PASTE AS PSU)
            if (!fmClipIsDir[i] || !fmIsSaveFolder(fmClip[i]) || !fmParent(parent, sizeof(parent), fmClip[i]))
                continue; // only save folders turn into PSUs
            fmDirSlash(parent, sizeof(parent), strcpy(target, parent));
            fmDirSlash(target, sizeof(target), fmDir);
            why = fmPsuWhy(vmcSavesFolderToPsu(parent, name, target));
        } else if (!fmClipIsDir[i] && fmIsMcPath(fmDir) && fmHasSuffix(name, ".psu")) {
            // a .psu pasted onto a memory card unpacks into its save, in the card's root (RIPPS2)
            fmDirSlash(target, sizeof(target), fmDir);
            why = fmPsuWhy(vmcSavesPsuToFolder(fmClip[i], target));
        } else {
            fmPasteTarget(fmClip[i], fmClipIsDir[i], target, sizeof(target));
            if (fmClipCut)
                ok = fmMove(fmClip[i], fmClipIsDir[i], target, &fmProgressShow);
            else
                ok = fmCopy(fmClip[i], fmClipIsDir[i], target, &fmProgressShow);
            if (!ok)
                why = fmErrText(fmError());
        }
        if (why == NULL)
            done++;
        else if (failed++ == 0) {
            firstWhy = why;
            snprintf(failedName, sizeof(failedName), "%s", name);
        }
    }
    if (fmClipCut && !asPsu)
        fmClipCount = 0; // what moved is gone from its old place; what did not is still there to cut again
    fmLoad();
    if (failed)
        fmShowFailure(failedName, firstWhy);
    else if (done == 0)
        fmShowFailure(_l(_STR_FM_PASTE_PSU), _l(_STR_FM_NO_SAVES));
}

static void fmDeleteSelection(int e)
{
    static int sel[FM_MAX];
    char msg[FM_PATH + 100], path[FM_PATH], failedName[FM_NAME];
    int n = fmSelection(e, sel), i, failed = 0, firstErr = FM_OK;

    if (n == 0 || !fmCanWrite())
        return;
    if (n == 1)
        snprintf(msg, sizeof(msg), _l(_STR_FM_DELETE_CONFIRM), fmList_[sel[0]].name);
    else
        snprintf(msg, sizeof(msg), _l(_STR_FM_DELETE_MARKED_CONFIRM), n);
    if (!guiMsgBox(msg, 1, NULL))
        return;
    failedName[0] = '\0';
    for (i = 0; i < n; i++) {
        fmPath(path, sizeof(path), sel[i]);
        snprintf(msg, sizeof(msg), _l(_STR_FM_DELETING), fmList_[sel[i]].name);
        guiRenderTextScreen(msg);
        if ((path[0] == '\0' || !fmDelete(path, fmList_[sel[i]].isDir)) && failed++ == 0) {
            firstErr = path[0] == '\0' ? FM_ERR_NAME : fmError();
            snprintf(failedName, sizeof(failedName), "%s", fmList_[sel[i]].name);
        }
    }
    fmLoad();
    if (failed)
        fmShowFailure(failedName, fmErrText(firstErr));
}

static void fmRenameEntry(int e)
{
    char name[FM_NAME], path[FM_PATH];

    if (!fmCanWrite())
        return;
    snprintf(name, sizeof(name), "%s", fmList_[e].name);
    if (!diaShowKeyb(name, FM_NAME - 1, 0, _l(_STR_RENAME)) || !strcmp(name, fmList_[e].name))
        return;
    fmPath(path, sizeof(path), e);
    if (!fmRename(path, name)) {
        fmShowFailure(fmList_[e].name, fmErrText(fmError()));
        return;
    }
    fmLoad();
}

static void fmNewFolder(void)
{
    char name[FM_NAME] = "";

    if (!fmCanWrite())
        return;
    if (!diaShowKeyb(name, FM_NAME - 1, 0, _l(_STR_FM_NEW_FOLDER)) || name[0] == '\0')
        return;
    if (!fmMakeDir(fmDir, name)) {
        fmShowFailure(name, fmErrText(fmError()));
        return;
    }
    fmLoad();
}

// Unpack PSU: the save in .psu e into its folder here (on a memory card that is the card's root, where saves live)
static void fmUnpackPsu(int e)
{
    char psu[FM_PATH], here[FM_PATH];
    const char *why;

    if (!fmCanWrite())
        return;
    fmPath(psu, sizeof(psu), e);
    fmDirSlash(here, sizeof(here), fmDir);
    guiRenderTextScreen(_l(_STR_PLEASE_WAIT));
    why = fmPsuWhy(vmcSavesPsuToFolder(psu, here));
    fmLoad();
    if (why != NULL)
        fmShowFailure(fmList_[e].name, why);
}

static void fmActions(int e)
{
    char path[FM_PATH];
    const fm_entry_t *f = &fmList_[e];
    int isElf = !f->isDir && fmHasSuffix(f->name, ".elf");
    int isPsu = !f->isDir && fmHasSuffix(f->name, ".psu");
    int ret, first;

    fmPath(path, sizeof(path), e);
    diaSetLabel(diaFileActions, FMA_TITLE, f->name);
    diaSetVisible(diaFileActions, FMA_OPEN, f->isDir);
    diaSetVisible(diaFileActions, FMA_RUN, isElf);
    diaSetLabel(diaFileActions, FMA_MARK, _l(fmMarked[e] ? _STR_FM_UNMARK : _STR_FM_MARK));
    diaSetVisible(diaFileActions, FMA_UNPACK, isPsu);
    diaSetEnabled(diaFileActions, FMA_CUT, gEnableWrite);
    diaSetEnabled(diaFileActions, FMA_RENAME, gEnableWrite);
    diaSetEnabled(diaFileActions, FMA_DELETE, gEnableWrite);
    diaSetEnabled(diaFileActions, FMA_UNPACK, gEnableWrite);

    first = f->isDir ? FMA_OPEN : FMA_MARK;
    if (isElf)
        first = FMA_RUN;
    ret = diaExecuteDialog(diaFileActions, first, 1, NULL);
    switch (ret) {
        case FMA_OPEN:
            fmOpen(path);
            break;
        case FMA_RUN:
            appLaunchElfPath(path); // back here only when nothing started
            break;
        case FMA_MARK:
            fmMarked[e] = !fmMarked[e];
            break;
        case FMA_COPY:
        case FMA_CUT:
            fmToClipboard(e, ret == FMA_CUT);
            break;
        case FMA_RENAME:
            fmRenameEntry(e);
            break;
        case FMA_DELETE:
            fmDeleteSelection(e);
            break;
        case FMA_UNPACK:
            fmUnpackPsu(e);
            break;
    }
}

void guiShowFileManager(void)
{
    int ret, focus = FM_ROW_FIRST;

    fmList_ = malloc(FM_MAX * sizeof(fm_entry_t));
    fmLabel = malloc(FM_MAX * sizeof(*fmLabel));
    fmMarked = malloc(FM_MAX);
    fmClip = malloc(FM_CLIP_MAX * sizeof(*fmClip));
    if (fmList_ == NULL || fmLabel == NULL || fmMarked == NULL || fmClip == NULL) {
        guiMsgBox(_l(_STR_FM_ERR_MEMORY), 0, NULL);
        goto done;
    }
    fmDir[0] = '\0';
    fmClipCount = 0;
    fmLoad();
    diaSetListKeys(diaFileManager);

    for (;;) {
        fmFill();
        ret = diaExecuteDialog(diaFileManager, focus, 1, NULL);
        focus = ret >= FM_ROW_FIRST && ret <= FM_ROW_LAST ? ret : FM_ROW_FIRST;
        if (ret == UIID_BTN_CANCEL) { // Circle: up a folder; out of the drive list, close
            if (!fmInFolder())
                break;
            fmUp();
        } else if (ret == UIID_BTN_OK || ret == -1) {
            break;
        } else if (ret == DIA_RESULT_PREV || ret == DIA_RESULT_NEXT) {
            fmPage = (fmPage + (ret == DIA_RESULT_NEXT ? 1 : fmPages() - 1)) % fmPages();
        } else if (ret == FM_PASTE_BTN || ret == FM_PASTE_PSU_BTN) {
            fmPaste(ret == FM_PASTE_PSU_BTN);
            focus = ret;
        } else if (ret == FM_NEW_FOLDER_BTN) {
            fmNewFolder();
            focus = FM_NEW_FOLDER_BTN;
        } else if (ret >= FM_ROW_FIRST && ret <= FM_ROW_LAST) {
            int e = fmEntryAt(ret - FM_ROW_FIRST), key = diaListKey();
            char path[FM_PATH];
            if (e == -2)
                continue;
            if (e == -1) {
                fmUp();
                focus = FM_ROW_FIRST;
            } else if (!fmInFolder()) {
                fmOpen(fmList_[e].name); // a drive, by its root
                focus = FM_ROW_FIRST;
            } else if (key == DIA_KEY_SQUARE) {
                fmMarked[e] = !fmMarked[e];
            } else if (key == DIA_KEY_CONFIRM && fmList_[e].isDir) {
                fmPath(path, sizeof(path), e);
                fmOpen(path);
                focus = FM_ROW_FIRST;
            } else {
                fmActions(e);
            }
        }
    }

done:
    diaSetListKeys(NULL);
    free(fmList_);
    free(fmLabel);
    free(fmMarked);
    free(fmClip);
    fmList_ = NULL;
    fmLabel = NULL;
    fmMarked = NULL;
    fmClip = NULL;
}
