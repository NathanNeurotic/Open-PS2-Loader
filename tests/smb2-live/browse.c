/* Host harness for modules/network/smb2man/smb2man.c: drives its iomanX ops and devctls the way the
   OPL menu does, against a live SMB server. Built and run by run.sh. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "iomanX.h"
#include "ps2smb.h"

static iop_device_t *dev;
int AddDrv(iop_device_t *d)
{
    dev = d;
    return d->ops->init(d);
}
int DelDrv(const char *n)
{
    (void)n;
    return 0;
}
int smb2man_start(int argc, char *argv[]);

#define OPS dev->ops
static int fails;
#define CHECK(c, ...)            \
    do {                         \
        if (!(c)) {              \
            fails++;             \
            printf("FAIL: ");    \
            printf(__VA_ARGS__); \
            printf("\n");        \
        } else {                 \
            printf("ok: ");      \
            printf(__VA_ARGS__); \
            printf("\n");        \
        }                        \
    } while (0)

static int logon(const char *ip, int port, const char *user, const char *pw)
{
    smbLogOn_in_t l;
    memset(&l, 0, sizeof(l));
    strcpy(l.serverIP, ip);
    l.serverPort = port;
    strcpy(l.User, user);
    /* the menu: GETPASSWORDHASHES first; on failure the password goes as PLAINTEXT */
    smbGetPasswordHashes_in_t in;
    smbGetPasswordHashes_out_t out;
    strcpy(in.password, pw);
    int r = OPS->devctl(NULL, "", SMB_DEVCTL_GETPASSWORDHASHES, &in, sizeof(in), &out, sizeof(out));
    if (r == 0) {
        l.PasswordType = HASHED_PASSWORD;
        memcpy(l.Password, &out, 32);
    } else {
        l.PasswordType = PLAINTEXT_PASSWORD;
        strcpy(l.Password, pw);
    }
    return OPS->devctl(NULL, "", SMB_DEVCTL_LOGON, &l, sizeof(l), NULL, 0);
}
static int openshare(const char *name)
{
    smbOpenShare_in_t o;
    memset(&o, 0, sizeof(o));
    strcpy(o.ShareName, name);
    o.PasswordType = NO_PASSWORD;
    return OPS->devctl(NULL, "", SMB_DEVCTL_OPENSHARE, &o, sizeof(o), NULL, 0);
}

int main(int argc, char **argv)
{
    /* argv: ip port user password share iso-path-on-share local-copy-of-the-iso */
    if (argc < 8) {
        fprintf(stderr, "usage\n");
        return 2;
    }
    const char *ip = argv[1], *user = argv[3], *pw = argv[4], *share = argv[5], *iso = argv[6], *local = argv[7];
    int port = atoi(argv[2]);
    CHECK(smb2man_start(0, NULL) == 0, "module start");
    CHECK(logon(ip, port, user, "wrongpw") == 0, "logon records credentials");
    CHECK(openshare(share) < 0, "openshare with a wrong password fails (%d)", openshare(share));
    CHECK(logon(ip, port, user, pw) == 0, "logon");
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_ECHO, NULL, 0, NULL, 0) == 0, "echo");

    static ShareEntry_t shares[8] __attribute__((aligned(64)));
    smbGetShareList_in_t gl = {shares, 8};
    int ns = OPS->devctl(NULL, "", SMB_DEVCTL_GETSHARELIST, &gl, sizeof(gl), NULL, 0);
    CHECK(ns >= 1, "share list: %d", ns);
    for (int i = 0; i < ns; i++)
        printf("   share %s (%s)\n", shares[i].ShareName, shares[i].ShareComment);

    CHECK(openshare(share) == 0, "openshare %s", share);

    iop_file_t f = {0}, d = {0};
    iox_dirent_t de;
    iox_stat_t st;
    CHECK(OPS->dopen(&d, "\\") == 0, "dopen root");
    int n = 0, sawdvd = 0;
    while (OPS->dread(&d, &de) > 0) {
        n++;
        if (!strcmp(de.name, "DVD"))
            sawdvd = (de.stat.mode & FIO_S_IFDIR) != 0;
    }
    OPS->dclose(&d);
    CHECK(sawdvd, "root lists DVD as a directory (%d entries)", n);
    CHECK(OPS->dopen(&d, "\\DVD") == 0, "dopen \\DVD");
    int sawiso = 0;
    while (OPS->dread(&d, &de) > 0)
        if (!strcmp(de.name, "TEST.iso")) {
            sawiso = 1;
            printf("   TEST.iso size %u mtime %u-%02u-%02u %02u:%02u\n", de.stat.size, de.stat.mtime[6] | (de.stat.mtime[7] << 8), de.stat.mtime[5], de.stat.mtime[4], de.stat.mtime[3], de.stat.mtime[2]);
        }
    OPS->dclose(&d);
    CHECK(sawiso, "\\DVD lists TEST.iso");

    CHECK(OPS->getstat(&f, "\\DVD\\TEST.iso", &st) == 0 && st.size == 5244114, "getstat size %u", st.size);
    CHECK(OPS->getstat(&f, "\\DVD\\NOPE.iso", &st) < 0, "getstat missing file fails");

    /* read-only open, read in 100000-byte calls (crosses libsmb2's per-call cap), compare */
    int fd = OPS->open(&f, iso, FIO_O_RDONLY, 0);
    CHECK(fd >= 0, "open read-only %d", fd);
    FILE *ref = fopen(local, "rb");
    static unsigned char a[300000], b[300000];
    long total = 0;
    int mism = 0, r;
    while ((r = OPS->read(&f, a, 300000)) > 0) {
        if (fread(b, 1, r, ref) != (size_t)r)
            mism++;
        if (memcmp(a, b, r))
            mism++;
        total += r;
        if (r < 300000)
            break;
    }
    fclose(ref);
    CHECK(total == 5244114 && mism == 0, "read whole image %ld bytes, %d mismatched blocks", total, mism);
    CHECK(OPS->read(&f, a, 100) == 0, "read at EOF returns 0");
    CHECK(OPS->lseek(&f, 0, 2) == 5244114, "lseek SEEK_END");
    CHECK(OPS->lseek(&f, 4096, 0) == 4096 && OPS->read(&f, a, 16) == 16 && a[0] == (unsigned char)((4096 * 7 + 3) & 0xff), "lseek SEEK_SET + read");
    CHECK(OPS->lseek64(&f, 0, 2) == 5244114, "lseek64 SEEK_END");
    CHECK(OPS->write(&f, a, 16) < 0, "write to a read-only handle fails");
    CHECK(OPS->close(&f) == 0, "close");

    /* create + write + reopen read-write, as VMC creation and config saves do */
    CHECK(OPS->mkdir(&f, "\\CFGTEST", 0) == 0, "mkdir");
    CHECK(OPS->mkdir(&f, "\\CFGTEST", 0) == 0, "mkdir existing folder is ok");
    fd = OPS->open(&f, "\\CFGTEST\\new.bin", FIO_O_WRONLY | FIO_O_CREAT | FIO_O_TRUNC, 0666);
    CHECK(fd >= 0, "open create %d", fd);
    for (int i = 0; i < 200000; i++)
        a[i] = (unsigned char)(i * 13);
    CHECK(OPS->write(&f, a, 200000) == 200000, "write 200000");
    OPS->close(&f);
    fd = OPS->open(&f, "\\CFGTEST\\new.bin", FIO_O_RDWR, 0);
    CHECK(fd >= 0, "reopen read-write");
    CHECK(OPS->read(&f, b, 200000) == 200000 && !memcmp(a, b, 200000), "read back 200000");
    CHECK(OPS->lseek(&f, 0, 0) == 0 && OPS->write(&f, "XY", 2) == 2, "overwrite in place");
    OPS->close(&f);
    fd = OPS->open(&f, "\\CFGTEST\\new.bin", FIO_O_WRONLY | FIO_O_CREAT | FIO_O_TRUNC, 0666);
    CHECK(fd >= 0 && OPS->write(&f, "short", 5) == 5, "truncating rewrite");
    OPS->close(&f);
    CHECK(OPS->getstat(&f, "\\CFGTEST\\new.bin", &st) == 0 && st.size == 5, "rewrite left no old tail (size %u)", st.size);
    CHECK(OPS->open(&f, "\\CFGTEST\\new.bin", FIO_O_WRONLY | FIO_O_CREAT | FIO_O_EXCL, 0) < 0, "O_EXCL on an existing file fails");
    CHECK(OPS->rename(&f, "\\CFGTEST\\new.bin", "\\CFGTEST\\renamed.bin") == 0, "rename");
    CHECK(OPS->remove(&f, "\\CFGTEST\\renamed.bin") == 0, "remove");
    CHECK(OPS->rmdir(&f, "\\CFGTEST") == 0, "rmdir");
    CHECK(OPS->open(&f, "\\DVD\\NOPE.iso", FIO_O_RDONLY, 0) < 0, "open missing file fails (%d)", OPS->open(&f, "\\DVD\\NOPE.iso", FIO_O_RDONLY, 0));

    char longp[700];
    memset(longp, 'a', 699);
    longp[0] = '\\';
    longp[699] = 0;
    CHECK(OPS->open(&f, longp, FIO_O_RDONLY, 0) == -ENAMETOOLONG, "over-long path refused, not truncated");

    /* close share and reopen (the menu's reconnect) */
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_CLOSESHARE, NULL, 0, NULL, 0) == 0, "closeshare");
    CHECK(OPS->open(&f, iso, FIO_O_RDONLY, 0) < 0, "open after closeshare fails");
    CHECK(openshare(share) == 0, "reopen share");
    fd = OPS->open(&f, iso, FIO_O_RDONLY, 0);
    CHECK(fd >= 0 && OPS->read(&f, a, 2048) == 2048, "read after reconnect");
    OPS->close(&f);
    /* a handle left open across LOGOFF is closed by the driver */
    fd = OPS->open(&f, iso, FIO_O_RDONLY, 0);
    CHECK(OPS->devctl(NULL, "", SMB_DEVCTL_LOGOFF, NULL, 0, NULL, 0) == 0, "logoff with a handle open");
    CHECK(OPS->read(&f, a, 16) < 0, "stale handle after logoff is refused");
    /* ...and stays refused once a new session reuses its slot for another open */
    CHECK(logon(ip, port, user, pw) == 0 && openshare(share) == 0, "logon + openshare after logoff");
    iop_file_t g = {0};
    CHECK(OPS->open(&g, iso, FIO_O_RDONLY, 0) >= 0, "reopen the iso in a fresh session");
    CHECK(OPS->read(&f, a, 16) == -EBADF, "stale handle does not reach the file now in its slot");
    CHECK(OPS->close(&f) == -EBADF, "stale close leaves the new file open");
    CHECK(OPS->read(&g, a, 16) == 16, "the new handle still reads");
    OPS->close(&g);
    printf("%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
