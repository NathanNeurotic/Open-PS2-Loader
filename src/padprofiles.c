/*
  padprofiles.c the user's .pad USB pad profiles: read for a launch and for the menu's USB pad driver

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2): its ripps2pads.c, with the
  PADS folder beside the settings rather than beside the ELF, every read on the caller's own stack (a launch and the
  menu's boot read may run at once, on two threads), the menu's copy handed between threads with interrupts off, and a
  profile whose decoder= is not generic left out.

  As a game starts (sbPrepare, before the drives are let go), the PADS folder beside the settings is read: up to
  PAD_DEFS_MAX VVVV_PPPP.pad profiles, checked by the reference reader (padfile.c), and PADS/GAMES/<the game's ID>.pad,
  the game's button map. They are packed into the block PADEMU gets after its settings (system.c places it after the
  modules, ee_core hands it over): a profiled USB pad then plays, and the map applies, with nothing read in the game.
  A file that is not right is left out, and the debug log and DIAG.TXT say why; no file, no block, and PADEMU starts
  exactly as before. The absence of the folder is never remembered: the file manager or Set Up A USB Pad can make it.
*/

#ifdef PADEMU

#include "include/opl.h"
#include "include/ioman.h"   // LOG
#include "include/diaglog.h" // why a file was left out, in DIAG.TXT for a release build too
#include "include/padfile.h"
#include "include/padprofiles.h"
#include <libds34usb.h>

// A .pad's text, NUL ended (RIPPS2's launcher size). A bigger file is left out rather than cut: a cut text can still
// parse, with its last line cut short
#define PADS_TEXT_SIZE 4096
#define PADS_TOO_BIG   "larger than 4095 bytes"

int padProfilesDir(char *out, int size)
{
    char home[256];
    int len;

    if (out == NULL || size <= 0)
        return -1;
    out[0] = '\0';
    // The settings folder (configInit/configSetMove; configGetDir() is only its device), copied at once: the settings
    // code may move it while another thread reads it
    snprintf(home, sizeof(home), "%s", configGetHomePath());
    len = strlen(home);
    // '?': "mc?:OPL" with no memory card found. hdd...: raw APA, a partition namespace and not a file system (the test
    // configPathRedirectLocation in opl.c makes before it opens anything there)
    if (len == 0 || strchr(home, '?') != NULL || !strncmp(home, "hdd", 3))
        return -1;
    // the join configBuildPath and diagSave use
    if (snprintf(out, size, "%s%sPADS", home, home[len - 1] == '/' || home[len - 1] == ':' ? "" : "/") >= size) {
        out[0] = '\0';
        return -1;
    }
    return 0;
}

// A file's text, NUL ended, and its length: -1 when it cannot be read, -2 when it is larger than size - 1 bytes
static int padsRead(const char *path, char *buf, int size)
{
    int fd, n = 0, r = 0, big = 0;
    char more;

    if ((fd = open(path, O_RDONLY)) < 0)
        return -1;
    while (n < size - 1 && (r = read(fd, buf + n, size - 1 - n)) > 0)
        n += r;
    if (r >= 0 && n == size - 1)
        big = read(fd, &more, 1) > 0;
    close(fd);
    if (r < 0)
        return -1;
    if (big)
        return -2;
    buf[n] = '\0';
    return n;
}

static void padsLeftOut(const char *name, const char *why)
{
    LOG("PADS: %s left out: %s\n", name, why);
    diagLog("pads: %s left out: %s", name, why);
}

// PADS read and packed into out: the number of profiles (0 with only a game map), or -1 with nothing to pack (out is
// then untouched). Everything it keeps is on its caller's stack, so a launch on the GUI thread and the menu's read on
// the IO thread can run it at the same time. With no PADS folder its whole cost is one failed opendir
static int padsCollect(const char *gameId, unsigned char out[PAD_BLOCK_SIZE])
{
    char dir[256], path[320], text[PADS_TEXT_SIZE], err[96];
    pad_def_t defs[PAD_DEFS_MAX];
    unsigned char map[PAD_B_COUNT];
    int count = 0, mapped = 0, n;
    unsigned vid, pid;
    struct dirent *e;
    DIR *d;

    if (padProfilesDir(dir, sizeof(dir)) != 0)
        return -1;
    if ((d = opendir(dir)) == NULL)
        return -1;
    while ((e = readdir(d)) != NULL) {
        if (padFileId(e->d_name, &vid, &pid) != 0)
            continue;
        if (count == PAD_DEFS_MAX) {
            snprintf(err, sizeof(err), "the first %d profiles fill the block", PAD_DEFS_MAX);
            padsLeftOut(e->d_name, err);
            continue;
        }
        n = snprintf(path, sizeof(path), "%s/%s", dir, e->d_name) < (int)sizeof(path) ? padsRead(path, text, sizeof(text)) : -1;
        if (n < 0) {
            padsLeftOut(e->d_name, n == -2 ? PADS_TOO_BIG : "could not be read");
            continue;
        }
        if (padDefParse(text, n, vid, pid, &defs[count], err, sizeof(err)) != 0) {
            padsLeftOut(e->d_name, err);
            continue;
        }
        // PADEMU ignores decoder= (its DualShock and guitar decoders take no profile): such a profile would be a dead pad
        if (defs[count].decoder != PAD_DEC_GENERIC) {
            padsLeftOut(e->d_name, "decoder= is not generic, and the Pad Emulator plays generic profiles only");
            continue;
        }
        count++;
    }
    closedir(d);
    memset(map, PAD_REMAP_SAME, sizeof(map));
    if (gameId != NULL && gameId[0] != '\0' && snprintf(path, sizeof(path), "%s/GAMES/%s.pad", dir, gameId) < (int)sizeof(path)) {
        n = padsRead(path, text, sizeof(text));
        if (n == -2)
            padsLeftOut(path, PADS_TOO_BIG);
        else if (n >= 0 && padMapParse(text, n, map, err, sizeof(err)) != 0)
            padsLeftOut(path, err);
        else if (n >= 0)
            mapped = !padMapIsSame(map);
    }
    if (count == 0 && !mapped)
        return -1;
    padBlockPack(defs, count, map, out);
    LOG("PADS: %d profile(s)%s packed\n", count, mapped ? " and the game's button map" : "");
    return count;
}

// This launch's block: built and read on the launching thread only (sbPrepare, then sysLaunchLoaderElf)
static unsigned char launchBlock[PAD_BLOCK_SIZE];
static int launchReady = 0;

int padProfilesPrepare(const char *gameId)
{
    launchReady = 0;
    launchReady = padsCollect(gameId, launchBlock) >= 0;
    return launchReady ? 0 : -1;
}

const unsigned char *padProfilesBlock(void)
{
    return launchReady ? launchBlock : NULL;
}

void padProfilesClear(void)
{
    launchReady = 0;
}

/* The menu reads a profiled pad too: the same profiles (no game map) go to the menu's USB pad driver, at boot
   (deferredInit, the IO thread) and after Set Up A USB Pad saves (the GUI thread), and are sent on the GUI thread
   (readPads), the one that talks to the driver. The copy and its flags change only with interrupts off, the diaglog.c
   idiom: on the EE's single core nothing else runs then. */
static unsigned char menuBlock[PAD_BLOCK_SIZE];
static volatile int menuPending = 0;  // menuBlock waits for the next readPads
static volatile int menuHas = 0;      // menuBlock holds profiles (0: all zero, a block the driver refuses, so it holds none)
static volatile int menuLearning = 0; // Set Up A USB Pad is open: nothing is sent until it closes

static int padsLock(void)
{
    int on = DIntr(); // whether interrupts were on, so a caller that had them off keeps them off
    __asm__ __volatile__("" ::
                             : "memory");
    return on;
}

static void padsUnlock(int on)
{
    __asm__ __volatile__("" ::
                             : "memory");
    if (on)
        EIntr();
}

void padProfilesMenuLoad(void)
{
    unsigned char b[PAD_BLOCK_SIZE];
    int has = padsCollect(NULL, b) > 0, on;

    if (!has)
        memset(b, 0, sizeof(b));
    on = padsLock();
    if (has || menuHas) { // nothing now and nothing sent before: the driver is left exactly as it is today, uncalled
        memcpy(menuBlock, b, sizeof(menuBlock));
        menuHas = has;
        menuPending = 1;
    }
    padsUnlock(on);
}

void padProfilesMenuTick(void)
{
    unsigned char b[PAD_BLOCK_SIZE];
    int on, send = 0;

    if (!menuPending) // a frame's whole cost while nothing waits
        return;
    on = padsLock();
    if (menuPending && !menuLearning) {
        memcpy(b, menuBlock, sizeof(b));
        menuPending = 0; // before the call: a load that lands while it blocks is sent the next frame
        send = 1;
    }
    padsUnlock(on);
    if (send && !ds34usb_set_profiles(b, PAD_BLOCK_SIZE, 0)) {
        on = padsLock();
        menuPending = 1; // the driver is not bound (yet): the next frame tries again
        padsUnlock(on);
    }
}

int padProfilesMenuLearn(int on)
{
    static const unsigned char none[PAD_BLOCK_SIZE];
    unsigned char b[PAD_BLOCK_SIZE];
    int i, has;

    i = padsLock();
    menuLearning = on != 0;
    menuPending = 0; // this call sends the newest copy itself
    memcpy(b, on ? none : menuBlock, sizeof(b));
    has = menuHas;
    padsUnlock(i);
    // open: no profile, so a pad being set up again steers nothing while it is learnt, and both ports, so it is taken
    // beside a DualShock in the first; closed: the profiles again and the menu's one port (sysReset loads it with 1)
    if (ds34usb_set_profiles(b, PAD_BLOCK_SIZE, on != 0) && ds34usb_reinit_ports(on ? 3 : 1))
        return 0;
    if (on) // not open after all: back to the menu's own state, as a close leaves it
        padProfilesMenuLearn(0);
    else if (has) { // the profiles did not reach the driver: readPads tries again
        i = padsLock();
        menuPending = 1;
        padsUnlock(i);
    }
    return -1;
}

void padProfilesMenuResend(void)
{
    int on = padsLock();

    if (menuHas) // none sent: nothing to send again, and the driver stays as it is today
        menuPending = 1;
    padsUnlock(on);
}

#endif
