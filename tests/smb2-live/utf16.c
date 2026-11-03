/* put_utf16() (modules/iopcore/cdvdman/smb2.c): UTF-8 names to UTF-16LE, checked byte for byte.
   smb2.c is included, not linked, so its static converter can be called directly. Built and run by run.sh. */
#include <stdio.h>
#include <string.h>
#include "smb2.c"

int (*plwip_close)(int s);
int (*plwip_connect)(int s, struct sockaddr *name, socklen_t namelen);
int (*plwip_recv)(int s, void *mem, int len, unsigned int flags);
int (*plwip_send)(int s, void *dataptr, int size, unsigned int flags);
int (*plwip_socket)(int domain, int type, int protocol);
int (*plwip_setsockopt)(int s, int level, int optname, const void *optval, socklen_t optlen);
u32 (*pinet_addr)(const char *cp);
struct cdvdman_settings_smb cdvdman_settings;

static int fails;

static void check(const char *label, const char *in, int upper, const unsigned short *want, int nwant)
{
    u8 out[64];
    int i, len;

    memset(out, 0xAA, sizeof(out));
    len = put_utf16(out, in, upper);
    if (len != nwant * 2) {
        printf("FAIL %s: %d bytes, want %d\n", label, len, nwant * 2);
        fails++;
        return;
    }
    for (i = 0; i < nwant; i++) {
        unsigned short got = (unsigned short)(out[2 * i] | (out[2 * i + 1] << 8));
        if (got != want[i]) {
            printf("FAIL %s: unit %d is %04X, want %04X\n", label, i, got, want[i]);
            fails++;
            return;
        }
    }
    if (out[len] != 0xAA) { /* nothing written past the returned length */
        printf("FAIL %s: wrote past its length\n", label);
        fails++;
        return;
    }
    printf("ok   %s\n", label);
}

#define CHECK(label, in, upper, ...)                                 \
    do {                                                             \
        static const unsigned short w[] = {__VA_ARGS__};             \
        check(label, in, upper, w, (int)(sizeof(w) / sizeof(w[0]))); \
    } while (0)

int main(void)
{
    CHECK("ASCII", "a.iso", 0, 'a', '.', 'i', 's', 'o');
    CHECK("ASCII upper-cased (NTOWFv2)", "ps2user", 1, 'P', 'S', '2', 'U', 'S', 'E', 'R');
    CHECK("upper-casing leaves non-ASCII alone", "\xC3\xA9", 1, 0x00E9);
    CHECK("two-byte", "Caf\xC3\xA9", 0, 'C', 'a', 'f', 0x00E9);
    CHECK("three-byte", "\xE2\x82\xAC", 0, 0x20AC);
    CHECK("four-byte: a surrogate pair", "\xF0\x9F\x8E\xAE", 0, 0xD83C, 0xDFAE);
    CHECK("highest code point", "\xF4\x8F\xBF\xBF", 0, 0xDBFF, 0xDFFF);
    /* Not UTF-8: every byte that does not start a well-formed sequence goes through as Latin-1. */
    CHECK("Latin-1 byte", "Caf\xE9", 0, 'C', 'a', 'f', 0x00E9);
    CHECK("overlong two-byte lead", "\xC0\xAF", 0, 0x00C0, 0x00AF);
    CHECK("overlong three-byte (E0 82 80 is not U+0080)", "\xE0\x82\x80", 0, 0x00E0, 0x0082, 0x0080);
    CHECK("overlong four-byte", "\xF0\x82\x82\xAC", 0, 0x00F0, 0x0082, 0x0082, 0x00AC);
    CHECK("lone surrogate (ED A0 80)", "\xED\xA0\x80", 0, 0x00ED, 0x00A0, 0x0080);
    CHECK("past U+10FFFF", "\xF4\x90\x80\x80", 0, 0x00F4, 0x0090, 0x0080, 0x0080);
    CHECK("truncated sequence", "\xE2\x82", 0, 0x00E2, 0x0082);
    CHECK("lead byte then ASCII", "\xC3x", 0, 0x00C3, 'x');
    printf("%s (%d failures)\n", fails ? "FAILED" : "ALL PASSED", fails);
    return fails != 0;
}
