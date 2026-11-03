/* Host harness: the in-game SMB reader opens the longest image names the menu lists.

   The menu lists an image whose name is up to ISO_GAME_NAME_MAX bytes (include/supportbase.h) with a
   four-byte extension, and in the old format with a startup and a dot in front ("SLUS_209.46.Name.iso").
   The EE's SMB launch (in its ethsupport source) writes that file name into the settings block,
   cdvdman_settings_smb.filename. In the game, modules/iopcore/cdvdman/device-smb.c builds
   "\<prefix>\DVD\<file name>" from the block, opens it and reads the image through it. device-smb.c is
   compiled here whole, with the real cdvd_config.h and either smb2.c (smb2_cdvdman) or, built with
   LONGNAME_SMB1, smb.c (smb_cdvdman), and runs against a live SMB server: a block that cut the name
   sends the server looking for a file that does not exist, and no sector of the image can be read.

   argv: ip port user pass share local_share_root format prefix [name_length]
     format       old (startup.name.iso), plain (name.iso), utf8 (name.iso, with UTF-8 in the name:
                  SMB2 only, as smb.c sends each byte as one UTF-16 unit), ul (a USBExtreme game in two
                  parts, opened as "\<prefix>\<file name>.00" and ".01") or missing (an old-format
                  name with no image behind it: the read must fail, not return what its buffer held)
     prefix       prefix (the longest one the settings block holds) or none
     name_length  the name's length in bytes, ISO_GAME_NAME_MAX if left out
   The image files are created under local_share_root, which the server shares, before the launch.
   Built and run by longname.sh, which run.sh sources. tests/smb2-live/launchname.c checks every
   format and boundary length without a server, and .github/scripts/test_smb_launch_name.py that the
   snprintf calls below are the EE's. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "smstcpip.h"
#include "internal.h"

#ifndef ISO_GAME_NAME_MAX
#error longname.sh passes ISO_GAME_NAME_MAX from include/supportbase.h
#endif

#define SECTORS 8 // per image file

// cdvdman.c's patch zone, which the EE fills before the IOP reset.
struct cdvdman_settings_smb cdvdman_settings;

// What device-smb.c needs from the rest of cdvdman and from the IOP kernel.
struct irx_export_table _exp_oplsmb;

int RegisterLibraryEntries(struct irx_export_table *exports)
{
    (void)exports;
    return 0;
}

void cdvdman_vmc_io_begin(int is_write)
{
    (void)is_write;
}

void cdvdman_vmc_io_end(void)
{
}

// ps2ip's exports, in the slots device-smb.c's ps2ip_init() takes them from.
static int h_close(int s) { return close(s); }
static int h_connect(int s, struct sockaddr *n, socklen_t l) { return connect(s, n, l); }
static int h_recv(int s, void *m, int l, unsigned int f) { return (int)recv(s, m, l, f); }
static int h_send(int s, void *d, int l, unsigned int f) { return (int)send(s, d, l, f); }
static int h_socket(int d, int t, int p) { return socket(d, t, p); }
static int h_setsockopt(int s, int lv, int o, const void *v, socklen_t l) { return setsockopt(s, lv, o, v, l); }
static u32 h_inet(const char *c) { return inet_addr(c); }

static int recv_all(int s, u8 *p, int n)
{
    int got = 0, r;

    while (got < n) {
        if ((r = (int)recv(s, p + got, n - got, 0)) <= 0)
            return r;
        got += r;
    }
    return got;
}

// SMSTCPIP's recvfrom (modules/network/SMSTCPIP/sockets.c), which smb.c's READ_ANDX uses, on a host
// stream socket. With an index, a message's first 63 bytes go to header (a shorter message whole), and
// its data, from header[index] + 4 on (the low byte of the response's DataOffset, after the 4-byte
// session header), goes to payload; the count includes the bytes before the data. Without an index it
// is a plain recv.
static int h_recvfrom(int s, void *header, int index, void *payload, int plen, unsigned int flags, struct sockaddr *from, socklen_t *fromlen)
{
    u8 *h = header, pad[256];
    int len, start, r;

    (void)from;
    (void)fromlen;
    if (index == 0)
        return (int)recv(s, payload, plen, flags);
    if ((r = recv_all(s, h, 4)) != 4)
        return r;
    len = 4 + ((h[1] << 16) | (h[2] << 8) | h[3]);
    if (len < 63) // an error response, or a keepalive
        return (r = recv_all(s, h + 4, len - 4)) == len - 4 ? len : r;
    if ((r = recv_all(s, h + 4, 63 - 4)) != 63 - 4)
        return r;
    start = h[index] + 4;
    if (start < 63 || start > len)
        return -1; // not a READ_ANDX response as smb.c expects one
    if (start > 63 && (r = recv_all(s, pad, start - 63)) != start - 63)
        return r;
    if (start == len)
        return len;
    r = (int)recv(s, payload, plen < len - start ? plen : len - start, flags);
    return r <= 0 ? r : start + r;
}

int getModInfo(char *modname, modinfo_t *info)
{
    static void *exports[32];

    if (strcmp(modname, "ps2ip") != 0)
        return 0;
    exports[6] = (void *)h_close;
    exports[7] = (void *)h_connect;
    exports[9] = (void *)h_recv;
    exports[10] = (void *)h_recvfrom;
    exports[11] = (void *)h_send;
    exports[13] = (void *)h_socket;
    exports[19] = (void *)h_setsockopt;
    exports[24] = (void *)h_inet;
    info->version = 0x0100;
    info->exports = exports;
    return 1;
}

static void hash_cb(server_specs_t *ss)
{
#ifdef LONGNAME_SMB1
    // smbinit's hash callback computes the LM and NTLM responses. The SMB1 cases log on as an unknown
    // user, whom the server maps to its guest account without checking a response.
    memset(ss->Password, 0, sizeof(ss->Password));
    ss->PasswordLen = 24;
    ss->HashedFlag = 1;
#else
    (void)ss;
    fprintf(stderr, "hash callback must not be called\n");
    exit(9);
#endif
}

static u8 pattern(int seed, long i)
{
    return (u8)(i * 13 + seed * 101 + 7);
}

static int make_image(const char *path, int seed)
{
    FILE *f = fopen(path, "wb");
    long i;

    if (f == NULL) {
        printf("cannot create %s: %s\n", path, strerror(errno));
        return -1;
    }
    for (i = 0; i < SECTORS * 2048L; i++)
        fputc(pattern(seed, i), f);
    return fclose(f);
}

// Reads the image's first sectors through device-smb.c, from lsn on, and compares them with the file.
static int read_back(u32 lsn, int seed)
{
    static u8 buf[SECTORS * 2048];
    long i;
    int rv;

    memset(buf, 0xEE, sizeof(buf));
    rv = DeviceReadSectors(lsn, buf, SECTORS);
    if (rv != SCECdErNO) {
        printf("FAIL: read at lsn 0x%x: error 0x%x\n", (unsigned)lsn, rv);
        return 1;
    }
    for (i = 0; i < (long)sizeof(buf); i++) {
        if (buf[i] != pattern(seed, i)) {
            printf("FAIL: read at lsn 0x%x: byte %ld differs\n", (unsigned)lsn, i);
            return 1;
        }
    }
    printf("read at lsn 0x%x: %d sectors match\n", (unsigned)lsn, SECTORS);
    return 0;
}

// Reads the first sectors of an image that does not exist: the open failed, and the read must too.
static int read_missing(void)
{
    static u8 buf[SECTORS * 2048];
    int rv = DeviceReadSectors(0, buf, SECTORS);

    if (rv == SCECdErNO) {
        printf("FAIL: a read from the missing image reports success\n");
        return 1;
    }
    printf("read from the missing image fails: error 0x%x\n", rv);
    return 0;
}

int main(int argc, char **argv)
{
    static const char startup[] = "SLUS_209.46"; // the scan takes an old-format name's first 11 bytes
    static const char extension[] = ".iso";
    const unsigned int crc = 0x1234ABCDu; // USBA_crc32(game->name) on the EE
    char name[ISO_GAME_NAME_MAX + 1], prefix[sizeof(cdvdman_settings.smb_prefix)];
    char file[512], dir[1024], path[1600];
    int i, len, namelen, parts = 1, fails = 0;

    setvbuf(stdout, NULL, _IOLBF, 0); // so a sanitizer report, which exits at once, keeps the lines before it
    if (argc != 9 && argc != 10) {
        fprintf(stderr, "usage: longname ip port user pass share local_share_root old|plain|utf8|ul|missing prefix|none [name_length]\n");
        return 2;
    }
    const char *root = argv[6], *format = argv[7];
    const int usbld = strcmp(format, "ul") == 0, missing = strcmp(format, "missing") == 0;
    const int plain = strcmp(format, "plain") == 0 || strcmp(format, "utf8") == 0;
    namelen = argc == 10 ? atoi(argv[9]) : ISO_GAME_NAME_MAX;
    if (namelen < 1 || namelen > ISO_GAME_NAME_MAX || (!plain && !usbld && !missing && strcmp(format, "old") != 0)) {
        fprintf(stderr, "longname: bad format or name length\n");
        return 2;
    }

    // The longest prefix the settings block holds (gETHPrefix is as long), or none.
    memset(prefix, 0, sizeof(prefix));
    if (strcmp(argv[8], "prefix") == 0) {
        for (i = 0; i < (int)sizeof(prefix) - 1; i++)
            prefix[i] = "PS2-Games-"[i % 10];
    }

    // A namelen-byte name: for utf8 with two-byte UTF-8 characters in it, as the menu stores a name like
    // "Cafe" with an acute e that smb2man listed.
    len = 0;
    if (strcmp(format, "utf8") == 0) {
        while (len + 6 <= namelen) {
            memcpy(name + len, "Caf\xC3\xA9 ", 6);
            len += 6;
        }
    }
    while (len < namelen) {
        name[len] = (len % 10 == 4) ? ' ' : (char)('a' + (len * 7) % 26);
        len++;
    }
    name[len] = '\0';

    // The file name, and the settings block as the EE's launch fills it for each format.
    memset(&cdvdman_settings, 0, sizeof(cdvdman_settings));
    cdvdman_settings.common.NumParts = usbld ? 2 : 1; // sbPrepare: game->parts
    cdvdman_settings.common.media = 0x14;             // a DVD: device-smb.c opens it in DVD
    if (!plain && !usbld) {
        snprintf(file, sizeof(file), "%s.%s%s", startup, name, extension);
        snprintf(cdvdman_settings.filename, sizeof(cdvdman_settings.filename), "%s.%s%s", startup, name, extension);
    } else if (plain) {
        snprintf(file, sizeof(file), "%s%s", name, extension);
        snprintf(cdvdman_settings.filename, sizeof(cdvdman_settings.filename), "%s%s", name, extension);
    } else {
        parts = 2;
        snprintf(file, sizeof(file), "ul.%08X.%s", crc, startup);
        snprintf(cdvdman_settings.filename, sizeof(cdvdman_settings.filename), "ul.%08X.%s", crc, startup);
        cdvdman_settings.common.flags |= IOPCORE_SMB_FORMAT_USBLD;
    }
    snprintf(cdvdman_settings.smb_ip, sizeof(cdvdman_settings.smb_ip), "%s", argv[1]);
    cdvdman_settings.smb_port = (u16)atoi(argv[2]);
    snprintf(cdvdman_settings.smb_share, sizeof(cdvdman_settings.smb_share), "%s", argv[5]);
    snprintf(cdvdman_settings.smb_prefix, sizeof(cdvdman_settings.smb_prefix), "%s", prefix);
    snprintf(cdvdman_settings.smb_user, sizeof(cdvdman_settings.smb_user), "%s", argv[3]);
    snprintf(cdvdman_settings.smb_password, sizeof(cdvdman_settings.smb_password), "%s", argv[4]);

    printf("file name %d bytes, prefix %d bytes, settings block %d bytes\n", (int)strlen(file), (int)strlen(prefix),
           (int)sizeof(cdvdman_settings));
    if (strcmp(cdvdman_settings.filename, file) != 0) {
        printf("FAIL: the settings block holds only %d bytes of the file name\n", (int)strlen(cdvdman_settings.filename));
        fails++;
    }

    // The image where the server shares it: <root>[/<prefix>]/DVD/<file name>, or the parts of a
    // USBExtreme game, <root>[/<prefix>]/<file name>.00 and .01, which device-smb.c opens without DVD.
    // A missing image has its directory, but no file in it.
    snprintf(dir, sizeof(dir), "%s%s%s%s", root, prefix[0] ? "/" : "", prefix, usbld ? "" : "/DVD");
    if (prefix[0]) {
        snprintf(path, sizeof(path), "%s/%s", root, prefix);
        mkdir(path, 0755);
    }
    mkdir(dir, 0755);
    for (i = 0; i < parts && !missing; i++) {
        if (usbld)
            snprintf(path, sizeof(path), "%s/%s.%02x", dir, file, i);
        else
            snprintf(path, sizeof(path), "%s/%s", dir, file);
        if (make_image(path, i) != 0)
            return 2;
    }

    // The launch, as the IOP runs it: negotiate, then mount (logon, tree connect, open), then read.
    smb_NegotiateProt(hash_cb);
    DeviceFSInit();
    if (missing)
        fails += read_missing();
    for (i = 0; i < parts && !missing; i++)
        fails += read_back((u32)i * 0x80000, i); // part i holds the sectors from i * 0x80000 on
    DeviceUnmount();

    printf("DONE (%d failed checks)\n", fails);
    return fails ? 10 : 0;
}
