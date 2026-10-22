"""A device POPS/ folder holding an older release's BDMA pair: the launch equip must say so.

PR #1024 changed the shipped iLink driver's size (usbhdfsd.irx.ilink 21609 -> 21977). Anyone who
updates RIPTOPL.ELF but not the drive's POPS/ folder used to get, on every iLink VCD launch, the old
pair copied to the card, the size check after it failing, and "Error writing the BDMA modules to the
memory card" -- a card write error that never happened.

Compiles the real equip and launch code of src/vcdsupport.c (vcdWriteBdmaMarker through
vcdApplyUsbModeForLaunch) against an in-memory memory card and devices. MMCE paths have no
SEEK_END, as on the console. Pass a git revision to run it against that revision's source instead:
`python3 test_bdma_stale_pair.py origin/rebuild/main` shows the old write-error toast.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
if len(sys.argv) > 1:
    source = subprocess.check_output(['git', 'show', sys.argv[1] + ':src/vcdsupport.c'], text=True, cwd=root)
else:
    source = (root / 'src/vcdsupport.c').read_text(encoding='utf-8')
source = source.replace('\r\n', '\n')


def block(pattern):
    match = re.search(pattern, source, re.M | re.S)
    if match is None:
        sys.exit('missing ' + pattern)
    return match.group(0)


start = source.index('static int vcdWriteBdmaMarker(')
end = source.index('\n}', source.index('void vcdApplyUsbModeForLaunch(')) + 2
region = source[start:end]

suffixes = ['usbexfat', 'mx4sio', 'mmce', 'ata', 'ilink', 'udpfs']
shipped = [[(root / 'POPS' / f'{name}.{suffix}').stat().st_size for name in ['usbd.irx', 'usbhdfsd.irx']]
           for suffix in suffixes]

PROGRAM = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LOG(...) ((void)0)
#define O_RDONLY 0
#define SEEK_SET 0
#define SEEK_END 2
#define POPS_FOLDER "POPS"
#define VCD_COPY_CHUNK (16 * 1024)
#define MAX_BDM_DEVICES 4
#define BDM_DEVICE_ROOT_MAX 32
#define BDM_TYPE_USB 0
#define BDM_TYPE_ILINK 1
#define BDM_TYPE_SDC 2
#define BDM_TYPE_ATA 3
enum { VCD_BDMA_FAT32 = 0, VCD_BDMA_USBEXFAT, VCD_BDMA_MX4SIO, VCD_BDMA_MMCE, VCD_BDMA_ATA, VCD_BDMA_ILINK, VCD_BDMA_UDPFS, VCD_BDMA_MODE_COUNT };
enum { VCD_BDMA_SRC_USB = 0, VCD_BDMA_SRC_MX4SIO, VCD_BDMA_SRC_MMCE, VCD_BDMA_SRC_HDD, VCD_BDMA_SRC_ILINK, VCD_BDMA_SRC_COUNT };
enum { _STR_BDMA_ERR_SRC, _STR_BDMA_ERR_SPACE, _STR_BDMA_ERR_IO, _STR_BDMA_ERR_OLD };
static const char *labels[] = {"BDMA_ERR_SRC", "BDMA_ERR_SPACE", "BDMA_ERR_IO", "BDMA_ERR_OLD"};
static const char *_l(int id) { return labels[id]; }
static const char *warned;
static void guiWarning(const char *text, int count) { (void)count; warned = text; }

static char gPopstarterPath[256], gBootDir[256];
static char vcdCustomPopsFor[sizeof(gPopstarterPath)], vcdCustomPopsElf[256];
static const char *vcdResolveCustomPopstarter(void)
{
    snprintf(vcdCustomPopsFor, sizeof(vcdCustomPopsFor), "%s", gPopstarterPath);
    vcdCustomPopsElf[0] = '\0';
    return NULL;
}
static int gBdmaApplyOnLaunch;

/* Files on every device and the card, by full path. */
static struct { char path[128]; int size; char data[32]; int used; } files[64];
static struct { int file, pos, used; } fds[16];
static int copies, cardDir, hddCommon, mmcePresent, devType[MAX_BDM_DEVICES];
static int find(const char *p)
{
    for (int i = 0; i < 64; i++)
        if (files[i].used && !strcmp(files[i].path, p))
            return i;
    return -1;
}
static int put(const char *p, int size)
{
    int f = find(p);
    for (int i = 0; f < 0 && i < 64; i++)
        if (!files[i].used)
            f = i;
    if (f < 0)
        abort();
    memset(&files[f], 0, sizeof(files[f]));
    snprintf(files[f].path, sizeof(files[f].path), "%s", p);
    files[f].size = size;
    files[f].used = 1;
    return f;
}
static int fake_open(const char *p, int flags)
{
    int f = find(p);
    (void)flags;
    if (f < 0)
        return -1;
    for (int fd = 0; fd < 16; fd++)
        if (!fds[fd].used) {
            fds[fd].file = f;
            fds[fd].pos = 0;
            fds[fd].used = 1;
            return fd;
        }
    abort();
}
static int fake_close(int fd)
{
    if (fd < 0 || fd >= 16 || !fds[fd].used)
        abort();
    fds[fd].used = 0;
    return 0;
}
static int fake_read(int fd, void *buf, int n)
{
    int left = files[fds[fd].file].size - fds[fd].pos;
    if (n > left)
        n = left;
    if (fds[fd].pos < (int)sizeof(files[0].data))
        memcpy(buf, files[fds[fd].file].data + fds[fd].pos, n < (int)sizeof(files[0].data) - fds[fd].pos ? n : (int)sizeof(files[0].data) - fds[fd].pos);
    fds[fd].pos += n;
    return n;
}
static int fake_lseek(int fd, int offset, int whence)
{
    if (whence == SEEK_END) {
        if (!strncmp(files[fds[fd].file].path, "mmce", 4))
            return -1; /* MMCE's newlib has no SEEK_END */
        offset += files[fds[fd].file].size;
    }
    return fds[fd].pos = offset;
}
static int fake_unlink(const char *p)
{
    int f = find(p);
    if (f < 0)
        return -1;
    files[f].used = 0;
    return 0;
}
#define open fake_open
#define close fake_close
#define read fake_read
#define lseek fake_lseek
#define unlink fake_unlink
typedef struct { int unused; } DIR;
static DIR theDir;
static DIR *opendir(const char *p) { return (mmcePresent && !strcmp(p, "mmce0:/")) ? &theDir : NULL; }
static int closedir(DIR *d) { (void)d; return 0; }
static void mmceLoadModules(void) {}
static void bdmEnsureSourceModules(int type, int timeout) { (void)type; (void)timeout; }
static int bdmGetDeviceSlotsByType(int type, int *slots, int max)
{
    int n = 0;
    for (int i = 0; i < MAX_BDM_DEVICES && n < max; i++)
        if (devType[i] == type)
            slots[n++] = i;
    return n;
}
static int vcdFindPopstarterMc(char *out, int n)
{
    snprintf(out, n, "%s", cardDir ? "mc0:/POPSTARTER" : "");
    return cardDir;
}
static int vcdResolvePopstarterMc(char *out, int n)
{
    cardDir = 1;
    return vcdFindPopstarterMc(out, n);
}
static void vcdStampPopstarterIcons(const char *mcDir, const char *srcDir) { (void)mcDir; (void)srcDir; }
static int vcdSafeCopyFile(const char *src, const char *dst)
{
    int s = find(src);
    if (s < 0)
        return -1;
    char data[32];
    int size = files[s].size;
    memcpy(data, files[s].data, sizeof(data));
    memcpy(files[put(dst, size)].data, data, sizeof(data));
    copies++;
    return 0;
}
static int vcdSafeWriteFile(const char *dst, const void *buf, int len)
{
    if (len >= 32)
        abort();
    memcpy(files[put(dst, len)].data, buf, len);
    return 0;
}
static int hddEquipPopstarterBdmaFromCommon(int mode, char *diag, int diagSize);

@BLOCKS@

@REGION@

static int hddEquipPopstarterBdmaFromCommon(int mode, char *diag, int diagSize)
{
    return hddCommon ? vcdEquipBdmaFromPops("pfs0:/POPS/", mode, diag, diagSize) : -4;
}

static const int shipped[][2] = @SHIPPED@;
static int failures;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s (launch toast: %s, card copies: %d)\n", __LINE__, #x, warned ? warned : "none", copies); failures++; } } while (0)
#define TOAST(name) (warned != NULL && !strcmp(warned, name))

static void reset(void)
{
    memset(files, 0, sizeof(files));
    memset(fds, 0, sizeof(fds));
    copies = hddCommon = mmcePresent = 0;
    cardDir = gBdmaApplyOnLaunch = 1;
    warned = NULL;
    gBootDir[0] = gPopstarterPath[0] = '\0';
    for (int i = 0; i < MAX_BDM_DEVICES; i++)
        devType[i] = -1;
}
static void pair(const char *dir, int mode, int usbd, int hdfsd)
{
    char p[128];
    snprintf(p, sizeof(p), "%s%s.%s", dir, vcdBdmaModule[0], vcdBdmaSuffix[mode]);
    put(p, usbd);
    snprintf(p, sizeof(p), "%s%s.%s", dir, vcdBdmaModule[1], vcdBdmaSuffix[mode]);
    put(p, hdfsd);
}
static void dropPair(const char *dir, int mode)
{
    char p[128];
    for (int i = 0; i < 2; i++) {
        snprintf(p, sizeof(p), "%s%s.%s", dir, vcdBdmaModule[i], vcdBdmaSuffix[mode]);
        fake_unlink(p);
    }
}
static void card(int mode, int usbd, int hdfsd)
{
    put("mc0:/POPSTARTER/usbd.irx", usbd);
    put("mc0:/POPSTARTER/usbhdfsd.irx", hdfsd);
    vcdSafeWriteFile("mc0:/POPSTARTER/" VCD_BDMA_MARKER, vcdBdmaSuffix[mode], (int)strlen(vcdBdmaSuffix[mode]));
}
static int cardHdfsd(void)
{
    int f = find("mc0:/POPSTARTER/usbhdfsd.irx");
    return f < 0 ? -1 : files[f].size;
}

int main(void)
{
    const int u = vcdBdmaPairSig[VCD_BDMA_ILINK].usbdSize, h = vcdBdmaPairSig[VCD_BDMA_ILINK].hdfsdSize;
    const int old = h > 22025 ? 22025 : 21609; /* Beta 4221, or the pre-#1024 pair. */
    char diag[160];

    /* Card and iLink drive both still hold an actual previous release's pair. Nothing is copied, and the
       toast names the old drivers instead of a card write error. */
    reset();
    devType[1] = BDM_TYPE_ILINK;
    pair("mass1:/POPS/", VCD_BDMA_ILINK, u, old);
    card(VCD_BDMA_ILINK, u, old);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK);
    CHECK(TOAST("BDMA_ERR_OLD"));
    CHECK(copies == 0);
    CHECK(cardHdfsd() == old && vcdReadBdmaMode() == VCD_BDMA_ILINK);

    /* A card with no POPSTARTER folder: no folder is made for a pair that will not be installed. */
    reset();
    cardDir = 0;
    devType[1] = BDM_TYPE_ILINK;
    pair("mass1:/POPS/", VCD_BDMA_ILINK, u, old);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK);
    CHECK(TOAST("BDMA_ERR_OLD") && copies == 0 && !cardDir);

    /* An old pair earlier in the seek order (the boot device) does not shadow the game device's
       current one: that one is installed, silently. */
    reset();
    strcpy(gBootDir, "mass0:/RIPTOPL/");
    devType[0] = BDM_TYPE_USB;
    devType[1] = BDM_TYPE_ILINK;
    pair("mass0:/POPS/", VCD_BDMA_ILINK, u, old);
    pair("mass1:/POPS/", VCD_BDMA_ILINK, u, h);
    card(VCD_BDMA_ILINK, u, old);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK);
    CHECK(warned == NULL && cardHdfsd() == h && vcdBdmaEnvironmentValid(VCD_BDMA_ILINK));

    /* MMCE has no SEEK_END: the source is measured by reading it (usbhdfsd.irx.mmce is > one chunk). */
    reset();
    mmcePresent = 1;
    pair("mmce0:/POPS/", VCD_BDMA_MMCE, vcdBdmaPairSig[VCD_BDMA_MMCE].usbdSize, vcdBdmaPairSig[VCD_BDMA_MMCE].hdfsdSize - 368);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_MMCE, VCD_BDMA_MMCE);
    CHECK(TOAST("BDMA_ERR_OLD") && copies == 0);
    reset();
    mmcePresent = 1;
    pair("mmce0:/POPS/", VCD_BDMA_MMCE, vcdBdmaPairSig[VCD_BDMA_MMCE].usbdSize, vcdBdmaPairSig[VCD_BDMA_MMCE].hdfsdSize);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_MMCE, VCD_BDMA_MMCE);
    CHECK(warned == NULL && vcdBdmaEnvironmentValid(VCD_BDMA_MMCE));

    /* UDPFS: an old pair on the server's POPS/ (probed first) does not stop the search through the
       other sources and __common; with none holding the current pair, the toast says the pair is old. */
    const int uu = vcdBdmaPairSig[VCD_BDMA_UDPFS].usbdSize, uh = vcdBdmaPairSig[VCD_BDMA_UDPFS].hdfsdSize;
    reset();
    devType[0] = BDM_TYPE_USB;
    mmcePresent = 1;
    pair("udpfs:/POPS/", VCD_BDMA_UDPFS, uu, uh - 368);
    pair("mmce0:/POPS/", VCD_BDMA_UDPFS, uu, uh);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_USB, VCD_BDMA_UDPFS);
    CHECK(warned == NULL && vcdBdmaEnvironmentValid(VCD_BDMA_UDPFS));
    dropPair("mmce0:/POPS/", VCD_BDMA_UDPFS);
    fake_unlink("mc0:/POPSTARTER/usbhdfsd.irx");
    copies = 0;
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_USB, VCD_BDMA_UDPFS);
    CHECK(TOAST("BDMA_ERR_OLD") && copies == 0);
    hddCommon = 1;
    warned = NULL;
    pair("pfs0:/POPS/", VCD_BDMA_UDPFS, uu, uh);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_USB, VCD_BDMA_UDPFS);
    CHECK(warned == NULL && vcdBdmaEnvironmentValid(VCD_BDMA_UDPFS));

    /* The USB fat32/exFAT launch dialog takes the same path. */
    reset();
    devType[0] = BDM_TYPE_USB;
    pair("mass0:/POPS/", VCD_BDMA_USBEXFAT, vcdBdmaPairSig[VCD_BDMA_USBEXFAT].usbdSize, vcdBdmaPairSig[VCD_BDMA_USBEXFAT].hdfsdSize - 368);
    vcdApplyUsbModeForLaunch(VCD_BDMA_USBEXFAT);
    CHECK(TOAST("BDMA_ERR_OLD") && copies == 0);

    /* Unchanged: no pair anywhere is "not found"; Apply on Launch Off does nothing; and the Settings
       page's manual equip still installs the pair the user put there, whatever its size. */
    reset();
    devType[1] = BDM_TYPE_ILINK;
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK);
    CHECK(TOAST("BDMA_ERR_SRC"));
    reset();
    gBdmaApplyOnLaunch = 0;
    devType[1] = BDM_TYPE_ILINK;
    pair("mass1:/POPS/", VCD_BDMA_ILINK, u, old);
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK);
    CHECK(warned == NULL && copies == 0);
    reset();
    devType[1] = BDM_TYPE_ILINK;
    pair("mass1:/POPS/", VCD_BDMA_ILINK, u, old);
    CHECK(vcdEquipBdma(VCD_BDMA_SRC_ILINK, VCD_BDMA_ILINK, diag, sizeof(diag)) == 0 && cardHdfsd() == old);

    /* Every pair in the release's POPS/ folder, on its own device, installs at launch without a toast. */
    static const int source[] = {0, VCD_BDMA_SRC_USB, VCD_BDMA_SRC_MX4SIO, VCD_BDMA_SRC_MMCE, VCD_BDMA_SRC_HDD, VCD_BDMA_SRC_ILINK, VCD_BDMA_SRC_USB};
    static const int type[] = {0, BDM_TYPE_USB, BDM_TYPE_SDC, -1, BDM_TYPE_ATA, BDM_TYPE_ILINK, BDM_TYPE_USB};
    for (int mode = 1; mode < VCD_BDMA_MODE_COUNT; mode++) {
        reset();
        mmcePresent = 1;
        devType[0] = type[mode];
        pair(mode == VCD_BDMA_MMCE ? "mmce0:/POPS/" : "mass0:/POPS/", mode, shipped[mode - 1][0], shipped[mode - 1][1]);
        if (mode == VCD_BDMA_USBEXFAT)
            vcdApplyUsbModeForLaunch(mode);
        else
            vcdEnsureBdmaForLaunch(source[mode], mode);
        CHECK(warned == NULL && vcdBdmaEnvironmentValid(mode));
    }

    if (failures)
        return 1;
    puts("BDMA: an older release's device pair is named as old and never copied; a current pair later in the seek order wins");
    return 0;
}
'''

blocks = '\n'.join([
    block(r'^static const char \*vcdBdmaSuffix\[VCD_BDMA_MODE_COUNT\] = \{[^;]*\};'),
    block(r'^static const char \*vcdBdmaModule\[2\] = \{[^;]*\};'),
    block(r'^#define VCD_BDMA_MARKER .*?$'),
])
program = (PROGRAM.replace('@BLOCKS@', blocks).replace('@REGION@', region)
           .replace('@SHIPPED@', '{' + ','.join('{%d,%d}' % tuple(p) for p in shipped) + '}'))
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / 'stale.c'
    exe = Path(temp) / 'stale.exe'
    c.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    result = subprocess.run([str(exe)], timeout=15)
    sys.exit(result.returncode)
