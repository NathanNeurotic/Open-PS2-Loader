/* Host harness for modules/iopcore/cdvdman/smb2.c (the in-game SMB2 reader): calls it the way
   device-smb.c and smb_mcemu do, against a live SMB server. Built and run by run.sh. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "tamtypes.h"
#include "smstcpip.h"
#include "oplsmb.h"
#include "smb.h"
#include "cdvd_config.h"

int (*plwip_close)(int s);
int (*plwip_connect)(int s, struct sockaddr *name, socklen_t namelen);
int (*plwip_recv)(int s, void *mem, int len, unsigned int flags);
int (*plwip_send)(int s, void *dataptr, int size, unsigned int flags);
int (*plwip_socket)(int domain, int type, int protocol);
int (*plwip_setsockopt)(int s, int level, int optname, const void *optval, socklen_t optlen);
u32 (*pinet_addr)(const char *cp);
struct cdvdman_settings_smb cdvdman_settings;

static int h_close(int s) { return close(s); }
static int h_connect(int s, struct sockaddr *n, socklen_t l) { return connect(s, n, l); }
static int h_recv(int s, void *m, int l, unsigned f) { return (int)recv(s, m, l, f); }
static int h_send(int s, void *d, int l, unsigned f) { return (int)send(s, d, l, f); }
static u32 h_inet(const char *c) { return inet_addr(c); }

static void cb(server_specs_t *ss)
{
    (void)ss;
    fprintf(stderr, "hash callback must not be called\n");
    exit(9);
}

int main(int argc, char **argv)
{
    /* argv: ip port user pass share iso_path vmc_path */
    if (argc < 8) {
        fprintf(stderr, "usage\n");
        return 2;
    }
    plwip_close = h_close;
    plwip_connect = h_connect;
    plwip_recv = h_recv;
    plwip_send = h_send;
    plwip_socket = socket;
    plwip_setsockopt = setsockopt;
    pinet_addr = h_inet;
    u32 caps;
    int r, fails = 0;
    smb_NegotiateProtocol(argv[1], atoi(argv[2]), argv[3], argv[4], &caps, cb);
    printf("negotiate ok\n");
    r = smb_SessionSetupAndX(caps);
    printf("session setup %d\n", r);
    if (r <= 0)
        return 3;
    char path[256];
    snprintf(path, sizeof(path), "\\\\%s\\%s", argv[1], argv[5]);
    r = smb_TreeConnectAndX(path);
    printf("tree connect %d\n", r);
    if (r <= 0)
        return 4;

    u16 fid = 0xFFFF;
    r = smb_OpenAndX(argv[6], (u8 *)&fid, 0);
    printf("open iso %d fid %u\n", r, fid);
    if (r <= 0)
        return 5;
    /* Whole-file read through smb_ReadCD-sized requests, compared with the generator. */
    FILE *out = fopen("readback.bin", "wb");
    static u8 buf[16 * 2048];
    u32 lsn = 0;
    long total = 0;
    int shortcount = -1;
    for (;;) {
        int got = smb_ReadFile(fid, lsn * 2048, lsn >> 21, buf, sizeof(buf));
        if (got < 0) {
            printf("read error %d at lsn %u\n", got, lsn);
            return 6;
        }
        fwrite(buf, 1, got, out);
        total += got;
        if (got < (int)sizeof(buf)) {
            shortcount = got;
            break;
        }
        lsn += sizeof(buf) / 2048;
    }
    fclose(out);
    printf("read total %ld, final short count %d\n", total, shortcount);
    /* Read entirely past EOF: must be 0 (a short count of nothing), not an error. */
    r = smb_ReadFile(fid, 0x7FFFF000u, 0, buf, 2048);
    printf("past-eof read %d\n", r);
    fails += (r != 0);
    r = smb_Close(fid);
    printf("close %d\n", r);
    fails += (r < 0);
    r = smb_Close(fid);
    printf("double close %d (expect <0)\n", r);
    fails += (r >= 0);

    /* VMC-style: open for write, write pages, read them back. */
    u16 vfid = 0xFFFF;
    r = smb_OpenAndX(argv[7], (u8 *)&vfid, 1);
    printf("open vmc %d fid %u\n", r, vfid);
    if (r <= 0)
        return 7;
    u8 page[528], back[528];
    int bad = 0;
    for (int p = 0; p < 64; p++) {
        for (int i = 0; i < 528; i++)
            page[i] = (u8)(p * 31 + i);
        r = smb_WriteFile(vfid, p * 528, 0, page, 528);
        if (r != 528) {
            printf("write %d -> %d\n", p, r);
            bad++;
        }
    }
    for (int p = 0; p < 64; p++) {
        r = smb_ReadFile(vfid, p * 528, 0, back, 528);
        for (int i = 0; i < 528; i++)
            if (back[i] != (u8)(p * 31 + i)) {
                bad++;
                break;
            }
        if (r != 528)
            bad++;
    }
    /* A 100 KB write: crosses the 64 KB chunk. */
    static u8 big[100000];
    for (int i = 0; i < (int)sizeof(big); i++)
        big[i] = (u8)(i ^ 0x5A);
    r = smb_WriteFile(vfid, 1 << 20, 0, big, sizeof(big));
    printf("big write %d\n", r);
    fails += (r != (int)sizeof(big));
    static u8 bigb[100000];
    r = smb_ReadFile(vfid, 1 << 20, 0, bigb, sizeof(bigb));
    printf("big read %d match %d\n", r, memcmp(big, bigb, sizeof(big)) == 0);
    fails += (r != (int)sizeof(bigb) || memcmp(big, bigb, sizeof(big)) != 0);
    printf("vmc page mismatches %d\n", bad);
    fails += (bad != 0);
    smb_Close(vfid);

    /* A file that does not exist must fail cleanly. */
    u16 nf;
    r = smb_OpenAndX("\\DVD\\NOPE.iso", (u8 *)&nf, 0);
    printf("open missing %d (expect <0)\n", r);
    fails += (r >= 0);
    smb_Disconnect();
    printf("DONE (%d failed checks)\n", fails);
    return fails ? 10 : 0;
}
