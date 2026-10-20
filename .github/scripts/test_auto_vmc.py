"""Automatic VMC creation assigns a card only when one really exists (#935).

guiGameAutoCreateVmc() (src/guigame.c) used to treat every probe result but -1 as "card exists" and
ignored whether genvmc accepted the create request, then assigned and saved the card. The real
function is compiled against stubs and fault-injected:

- probe > 0: an existing card of that size is assigned, nothing is created;
- probe 0 (malformed image) or another failure: never replaced, never assigned;
- create rejected (-2/-3), or the formatter already busy with another job: not assigned;
- an accepted job that reports success is re-probed: assigned only if the card is now there;
- the user's abort stays in the menu; a game that changed during the wait is not assigned.

sysCheckVMC's contract: probe (size 0) returns MB, 0 = malformed, -1 = absent; a create request
returns -1 when genvmc accepted it, SYS_VMC_REPLACE_REQUIRES_DELETE (-2), SYS_VMC_CREATE_FAILED (-3).
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
guigame = (ROOT / "src/guigame.c").read_text(encoding="utf-8")
start = guigame.index("#define AUTO_VMC_SIZE_MB")
end = guigame.index("\n}\n", guigame.index("int guiGameAutoCreateVmc(")) + 3
helper_start = guigame.index("static int guiGameCreateVMC(")
helper_end = guigame.index("\n}\n", helper_start) + 3
function = guigame[helper_start:helper_end] + guigame[start:end]

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define SYS_VMC_REPLACE_REQUIRES_DELETE (-2)
#define SYS_VMC_CREATE_FAILED (-3)
enum { BDM_MODE, ETH_MODE, HDD_MODE, HTTP_MODE, APP_MODE, FAV_MODE, UDPFS_MODE };
enum { LIB_VIEW_ISO, LIB_VIEW_PS1 };
enum { _STR_AUTO_VMC_CREATING, _STR_AUTO_VMC_FAILED, _STR_VMC_FRAGMENTED_ON_CREATE, _STR_AUTO_VMC_INVALID, _STR_AUTO_VMC_STILL_RUNNING };
#define CONFIG_ITEM_CORE_LOADER "$CoreLoader"
#define LOG(...) ((void)0)
typedef struct { int dummy; } config_set_t;
typedef struct { int VMC_status, VMC_error, VMC_progress; char VMC_msg[64]; } statusVMCparam_t;
typedef struct item_list item_list_t;
struct item_list {
    int mode;
    int (*itemCheckVMC)(item_list_t *, char *, int);
    char *(*itemGetStartup)(item_list_t *, int);
    int (*itemCreateVMC)(item_list_t *, char *, int, int);
};
static int gAutoCreateVmc = 1, gDefaultCoreLoader = 0;
static int probeResult, reprobeResult, submitResult, probes, submits, aborts, saves, assigned, msgs, lastMsg, cancelAt = -1, frame;
static int busyBefore, statusPolls, finishAfter = 3, jobError;
static char startupNow[32] = "SLUS_123.45", assignedName[32];
static char startupBuf[32];
static int guiIsActive(void) { return 1; }
static int libListRowView(item_list_t *l, int id) { (void)l; (void)id; return LIB_VIEW_ISO; }
static int favGetItemSourceMode(int id) { (void)id; return BDM_MODE; }
static int udpbdSupport;
static int bdmSupportIsUDPBD(const item_list_t *s) { (void)s; return udpbdSupport; }
static int bdmModeIsPCCF(int m) { (void)m; return 0; }
static int bdmModeIsUDPBD(int m) { (void)m; return 0; }
static int configGetInt(config_set_t *c, const char *k, int *v) { (void)c; (void)k; (void)v; return 0; }
static int configGetVMC(config_set_t *c, char *out, int size, int slot) { (void)c; (void)size; (void)slot; out[0] = 0; return 0; }
static int configGetVMCDisable(config_set_t *c, int slot, int *v) { (void)c; (void)slot; *v = 0; return 0; }
static void configSetVMC(config_set_t *c, const char *vmc, int slot) { (void)c; (void)slot; assigned++; snprintf(assignedName, sizeof(assignedName), "%s", vmc); }
static int menuSaveConfig(void) { saves++; return 1; }
static const char *getGroupIdForTitleId(const char *id) { return id; }
static int checkVMC(item_list_t *l, char *name, int size)
{
    (void)l; (void)name;
    if (size == 0)
        return probes++ == 0 ? probeResult : reprobeResult;
    submits++;
    return submitResult;
}
static int requestedContiguous;
static int createVMC(item_list_t *l, char *name, int size, int requireContiguous)
{
    requestedContiguous = requireContiguous;
    return checkVMC(l, name, size);
}
static int flipAfterSubmit;
static int guiLocked;
static void guiLock(void) { if (guiLocked) abort(); guiLocked = 1; }
static void guiUnlock(void) { if (!guiLocked) abort(); guiLocked = 0; memset(startupBuf, 0x5a, sizeof(startupBuf) - 1); }
static char *getStartup(item_list_t *l, int id)
{
    (void)l; (void)id;
    assert(guiLocked);
    snprintf(startupBuf, sizeof(startupBuf), "%s", flipAfterSubmit && submits > 0 ? "SLUS_999.99" : startupNow);
    return startupBuf;
}
static int fileXioDevctl(const char *dev, int cmd, void *arg, unsigned int al, void *buf, unsigned int bl)
{
    (void)dev; (void)arg; (void)al; (void)bl;
    if (cmd == 0xC0DE0002) { aborts++; return 0; }
    if (cmd == 0xC0DE0003) {
        statusVMCparam_t *s = buf;
        memset(s, 0, sizeof(*s));
        if (submits == 0) { s->VMC_status = busyBefore; return 0; }  /* before our job: another job's state */
        statusPolls++;
        s->VMC_status = statusPolls < finishAfter;
        s->VMC_error = s->VMC_status ? 0 : jobError;
        return 0;
    }
    return -1;
}
static void readPads(void) { frame++; }
static int guiCancelKey(void) { return 1; }
static int getKeyOn(int key) { (void)key; return frame == cancelAt; }
static const char *_l(int id) { return id == _STR_AUTO_VMC_CREATING ? "Creating" : "msg"; }
static void guiRenderTextScreen(const char *s) { (void)s; }
static int guiMsgBox(const char *t, int a, void *b) { (void)t; (void)a; (void)b; msgs++; return 0; }
static int sysVMCLayoutWarning(void) { return -1; }
'''

tests = r'''
static item_list_t list = {BDM_MODE, checkVMC, getStartup, NULL};
static config_set_t cfg;
static void reset(int probe, int submit, int reprobe)
{
    probeResult = probe; submitResult = submit; reprobeResult = reprobe;
    probes = submits = aborts = saves = assigned = msgs = frame = statusPolls = 0;
    cancelAt = -1; busyBefore = 0; finishAfter = 3; jobError = 0;
    list.mode = BDM_MODE; udpbdSupport = 0; gDefaultCoreLoader = 0;
    strcpy(startupNow, "SLUS_123.45");
    assignedName[0] = 0;
}
int main(void)
{
    /* existing_valid_card: assigned, nothing created */
    reset(8, -1, 8);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 1 && saves == 1 && submits == 0 && !strcmp(assignedName, "SLUS_123.45_0"));

    /* malformed_existing_image: never replaced, never assigned */
    reset(0, -1, 8);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && saves == 0 && submits == 0 && msgs == 1);

    /* other_probe_failure */
    reset(SYS_VMC_CREATE_FAILED, -1, 8);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && submits == 0);

    /* neutrino_odd_size_card: Neutrino takes the file as it is (no size check on that path), so the
       game's own card is assigned as before -- never replaced, nothing created, no message */
    reset(0, -1, 8);
    gDefaultCoreLoader = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 1 && saves == 1 && submits == 0 && msgs == 0 && !strcmp(assignedName, "SLUS_123.45_0"));

    /* neutrino_unreadable_card: a probe that could not read the file is still never assigned */
    reset(SYS_VMC_CREATE_FAILED, -1, 8);
    gDefaultCoreLoader = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && submits == 0 && msgs == 1);
    gDefaultCoreLoader = 0;

    /* udpfs_odd_size_card: UDPFS always launches through Neutrino, whatever the global default */
    reset(0, -1, 8);
    list.mode = UDPFS_MODE;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 1 && submits == 0 && msgs == 0);

    /* udpbd_odd_size_card: so does the UDPBD block device */
    reset(0, -1, 8);
    udpbdSupport = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 1 && submits == 0 && msgs == 0);

    /* smb_odd_size_card_under_neutrino_default: SMB always launches native, which refuses the card */
    reset(0, -1, 8);
    list.mode = ETH_MODE;
    gDefaultCoreLoader = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && msgs == 1);

    /* create_rejected: a failed submission is never assigned, and the stale formatter status is not read as success */
    reset(-1, SYS_VMC_CREATE_FAILED, -1);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && saves == 0 && submits == 1 && statusPolls == 0 && msgs == 1);
    reset(-1, SYS_VMC_REPLACE_REQUIRES_DELETE, -1);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && submits == 1);

    /* formatter_busy: another job is running -- ours is not submitted, nothing is assigned, and the
       menu stays: a launch now would reset the IOP under the running job and orphan a partial card */
    reset(-1, -1, 8);
    busyBefore = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 0);
    assert(assigned == 0 && submits == 0 && msgs == 1);

    /* pending_job_is_not_a_card: a full-size file a running job is still formatting is not assigned */
    reset(8, -1, 8);
    busyBefore = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 0);
    assert(assigned == 0 && submits == 0 && probes == 0);

    /* accepted_and_confirmed: created, re-probed at the requested size, assigned */
    reset(-1, -1, 8);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(submits == 1 && assigned == 1 && saves == 1 && probes == 2);

    /* accepted_but_unconfirmed: the job said success but the card is not there */
    reset(-1, -1, -1);
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(submits == 1 && assigned == 0 && msgs == 1);

    /* job_failed: reported error, not assigned */
    reset(-1, -1, 8);
    jobError = -5;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 0 && msgs == 1);

    /* user_abort: stays in the menu, formatter told to stop, nothing assigned */
    reset(-1, -1, 8);
    finishAfter = 100;
    cancelAt = 2;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 0);
    assert(assigned == 0 && aborts == 1);

    /* slow_job_is_waited_for: no deadline on a working job (slow MMCE/SMB) -- leaving early let the
       next launch reset the IOP mid-format and orphan a broken card; Back is the way out */
    reset(-1, -1, 8);
    finishAfter = 120 * 60 + 50;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(assigned == 1 && aborts == 0);

    /* cancelled_job_never_winds_down: the device is wedged, so after Back the wait is bounded --
       stay in the menu and say it is still running */
    reset(-1, -1, 8);
    finishAfter = 1 << 30;
    cancelAt = 2;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 0);
    assert(assigned == 0 && aborts == 1 && msgs == 1);

    /* identity_changed: a refresh moved another game onto the row during the wait */
    reset(-1, -1, 8);
    flipAfterSubmit = 1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(submits == 1 && assigned == 0 && saves == 0);
    flipAfterSubmit = 0;
    reset(-1, -1, 8);
    list.itemCreateVMC = createVMC;
    requestedContiguous = -1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(requestedContiguous == 1 && assigned == 1);
    reset(-1, -1, 8);
    gDefaultCoreLoader = 1;
    requestedContiguous = -1;
    assert(guiGameAutoCreateVmc(&list, 0, &cfg) == 1);
    assert(requestedContiguous == 0 && assigned == 1);
    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "vmc.c"
    exe = Path(tmp) / "vmc.exe"
    src.write_text(harness + function + tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", "-Wno-unused-variable", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: automatic VMC assigns only a card that exists")
