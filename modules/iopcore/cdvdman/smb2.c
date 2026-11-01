/*
  smb2.c: the in-game SMB2 reader. Built into smb2_cdvdman in place of smb.c (SMB1).

  It provides the same functions under the same names as smb.c, so device-smb.c, the oplutils
  exports and smb_mcemu (VMC) work unchanged with either module. The EE chooses the module from
  the Network page's SMB Version row; nothing in the settings block changes.

  What it speaks, and why
  - SMB 2.0.2 and 2.1 only. Every SMB2-capable server still offers them (Windows cannot turn them
    off without turning SMB3 off too; Samba's default floor is 2.0.2), and they keep signing to
    HMAC-SHA256. SMB 3.x would add AES-CMAC and secure-negotiate code to IOP RAM for no gain here:
    this client never encrypts.
  - NTLMv2 logon, computed here. smbinit's hash callback is deliberately not used: it computes
    SMB1 LM/NTLMv1 responses, which modern servers refuse, and smbinit is unloaded by the time the
    session is set up. Raw NTLMSSP tokens are sent without SPNEGO, which Windows and Samba accept.
  - Signing only when the server requires it (Windows 11 24H2 does by default). Responses are
    not verified.
  - One request in flight at a time, as smb.c. Reads stay at 8192 bytes per request for the same
    reason as smb.c's CLIENT_MAX_RECV_SIZE (the IOP TCP window).

  Return values match smb.c: smb_ReadFile returns the byte count, a short count at end of file,
  or a negative error; smb_WriteFile returns nbytes or <= 0; smb_OpenAndX returns 1 or < 0.

  Licenced under Academic Free License version 3.0.
*/

#include <stdio.h>
#include <errno.h>
#include <sysclib.h>
#include "smstcpip.h"
#include <thbase.h>
#include <thsemap.h>

#include "oplsmb.h"
#include "smb.h"
#include "cdvd_config.h"

#include "smsutils.h"
#include "smb2auth.h"

#define SMB2_READ_CHUNK  8192  // see smb.c CLIENT_MAX_RECV_SIZE
#define SMB2_WRITE_CHUNK 65536 // one credit's worth; VMC pages are far smaller
#define SMB2_BUF_SIZE    1536  // control messages only; READ/WRITE data bypasses it
#define SMB2_TI_MAX      512   // NTLM target info we keep for the AUTHENTICATE message
#define SMB2_MAX_FILES   (ISO_MAX_PARTS + 4)

#define SMB2_HDR_SIZE 64

#define SMB2_NEGOTIATE     0x0000
#define SMB2_SESSION_SETUP 0x0001
#define SMB2_TREE_CONNECT  0x0003
#define SMB2_CREATE        0x0005
#define SMB2_CLOSE         0x0006
#define SMB2_READ          0x0008
#define SMB2_WRITE         0x0009

#define SMB2_FLAGS_SERVER_TO_REDIR 0x00000001
#define SMB2_FLAGS_ASYNC_COMMAND   0x00000002
#define SMB2_FLAGS_SIGNED          0x00000008

#define STATUS_SUCCESS                  0x00000000
#define STATUS_PENDING                  0x00000103
#define STATUS_MORE_PROCESSING_REQUIRED 0xC0000016
#define STATUS_END_OF_FILE              0xC0000011

#define SMB2_NEGOTIATE_SIGNING_ENABLED  0x0001
#define SMB2_NEGOTIATE_SIGNING_REQUIRED 0x0002

#define NTLMSSP_NEGOTIATE_UNICODE                  0x00000001
#define NTLMSSP_REQUEST_TARGET                     0x00000004
#define NTLMSSP_NEGOTIATE_SIGN                     0x00000010
#define NTLMSSP_NEGOTIATE_NTLM                     0x00000200
#define NTLMSSP_NEGOTIATE_ANONYMOUS                0x00000800
#define NTLMSSP_NEGOTIATE_ALWAYS_SIGN              0x00008000
#define NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY 0x00080000
#define NTLMSSP_NEGOTIATE_TARGET_INFO              0x00800000
#define NTLMSSP_NEGOTIATE_128                      0x20000000

#define NTLM_CLIENT_FLAGS (NTLMSSP_NEGOTIATE_UNICODE | NTLMSSP_REQUEST_TARGET | NTLMSSP_NEGOTIATE_SIGN | NTLMSSP_NEGOTIATE_NTLM | \
                           NTLMSSP_NEGOTIATE_ALWAYS_SIGN | NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY | NTLMSSP_NEGOTIATE_TARGET_INFO | NTLMSSP_NEGOTIATE_128)

#define MSV_AV_EOL       0
#define MSV_AV_TIMESTAMP 7

int smb_io_sema = -1;

// !!! ps2ip exports functions pointers !!! (set by device-smb.c)
extern int (*plwip_close)(int s);
extern int (*plwip_connect)(int s, struct sockaddr *name, socklen_t namelen);
extern int (*plwip_recv)(int s, void *mem, int len, unsigned int flags);
extern int (*plwip_send)(int s, void *dataptr, int size, unsigned int flags);
extern int (*plwip_socket)(int domain, int type, int protocol);
extern int (*plwip_setsockopt)(int s, int level, int optname, const void *optval, socklen_t optlen);
extern u32 (*pinet_addr)(const char *cp);

extern struct cdvdman_settings_smb cdvdman_settings;

static int main_socket = -1;
static struct in_addr server_addr;
static u16 server_port;

static u64 next_msg_id;
static u64 session_id;
static u32 tree_id;
static u16 dialect;
static u8 sign_required, signing;
static u8 session_key[16];
static u32 max_read, max_write;

static char user_name[33];
static char pass_word[33];

static u8 ntlm_ti[SMB2_TI_MAX];

static struct
{
    u8 id[16];
    u8 used;
} files[SMB2_MAX_FILES];

// [0..3] NetBIOS session header (type, 24-bit big-endian length), then the SMB2 message.
static u8 pkt[4 + SMB2_BUF_SIZE] __attribute__((aligned(4)));
#define HDR  (pkt + 4)
#define BODY (pkt + 4 + SMB2_HDR_SIZE)

//-------------------------------------------------------------------------
static void wr16(u8 *p, u16 v)
{
    p[0] = (u8)v;
    p[1] = (u8)(v >> 8);
}

static void wr32(u8 *p, u32 v)
{
    p[0] = (u8)v;
    p[1] = (u8)(v >> 8);
    p[2] = (u8)(v >> 16);
    p[3] = (u8)(v >> 24);
}

static void wr64(u8 *p, u64 v)
{
    wr32(p, (u32)v);
    wr32(p + 4, (u32)(v >> 32));
}

static u16 rd16(const u8 *p)
{
    return (u16)(p[0] | (p[1] << 8));
}

static u32 rd32(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static u64 rd64(const u8 *p)
{
    return (u64)rd32(p) | ((u64)rd32(p + 4) << 32);
}

static int bytes_equal(const u8 *a, const u8 *b, int n)
{
    while (n-- > 0)
        if (*a++ != *b++)
            return 0;
    return 1;
}

/*
  UTF-8 to UTF-16LE, optionally upper-cased (ASCII only, as NTOWFv2 needs); returns the byte length
  written (no terminator). The names come from the menu, which got them from smb2man's directory
  listing, and libsmb2 returns those as UTF-8: a file called "Café.iso" must be requested as the
  same UTF-16 the server listed it under. A byte that is not valid UTF-8 is passed through as
  Latin-1, so an 8-bit name from an old config still makes a request of the same length.
*/
static int put_utf16(u8 *out, const char *in, int upper)
{
    int len = 0;

    while (*in != '\0') {
        u32 c = (u8)*in++;
        int more = 0;

        if (c >= 0xC2 && c <= 0xDF)
            more = 1, c &= 0x1F;
        else if (c >= 0xE0 && c <= 0xEF)
            more = 2, c &= 0x0F;
        else if (c >= 0xF0 && c <= 0xF4)
            more = 3, c &= 0x07;

        if (more) {
            const u8 *p = (const u8 *)in;
            int i;

            for (i = 0; i < more && (p[i] & 0xC0) == 0x80; i++)
                c = (c << 6) | (p[i] & 0x3F);
            if (i == more && c >= 0x80 && c <= 0x10FFFF && (c < 0xD800 || c > 0xDFFF))
                in += more; // a well-formed sequence
            else
                c = (u8)in[-1]; // not UTF-8: the lead byte alone, as Latin-1
        }

        if (upper && c >= 'a' && c <= 'z')
            c -= 'a' - 'A';

        if (c >= 0x10000) { // a surrogate pair
            c -= 0x10000;
            out[len] = (u8)(c >> 10);
            out[len + 1] = (u8)(0xD8 | (c >> 18));
            out[len + 2] = (u8)c;
            out[len + 3] = (u8)(0xDC | ((c >> 8) & 0x03));
            len += 4;
        } else {
            out[len] = (u8)c;
            out[len + 1] = (u8)(c >> 8);
            len += 2;
        }
    }

    return len;
}

//-------------------------------------------------------------------------
static int SendData(int sock, const void *buf, int size)
{
    const u8 *ptr = (const u8 *)buf;
    int remaining = size, result;

    while (remaining > 0) {
        result = plwip_send(sock, (void *)ptr, remaining, 0);
        if (result <= 0)
            return -1;
        ptr += result;
        remaining -= result;
    }

    return size;
}

static int RecvData(int sock, void *buf, int size)
{
    u8 *ptr = (u8 *)buf;
    int remaining = size, result;

    while (remaining > 0) {
        result = plwip_recv(sock, ptr, remaining, 0);
        if (result <= 0)
            return -1;
        ptr += result;
        remaining -= result;
    }

    return size;
}

// Read and throw away n bytes of the current message.
static int Drain(int n)
{
    u8 sink[64];

    while (n > 0) {
        int chunk = n > (int)sizeof(sink) ? (int)sizeof(sink) : n;
        if (RecvData(main_socket, sink, chunk) < 0)
            return -1;
        n -= chunk;
    }

    return 0;
}

static int OpenTCPSession(void)
{
    int sock, opt;
    struct sockaddr_in sock_addr;

    sock = plwip_socket(PF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock < 0)
        return -1;

    opt = 1;
    plwip_setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, (char *)&opt, sizeof(opt));

    memset(&sock_addr, 0, sizeof(sock_addr));
    sock_addr.sin_addr = server_addr;
    sock_addr.sin_family = AF_INET;
    sock_addr.sin_port = htons(server_port);

    if (plwip_connect(sock, (struct sockaddr *)&sock_addr, sizeof(sock_addr)) < 0) {
        plwip_close(sock);
        return -1;
    }

    return sock;
}

//-------------------------------------------------------------------------
// Fill the 64-byte sync header for a request.
static void SetHeader(u16 command)
{
    memset(HDR, 0, SMB2_HDR_SIZE);
    HDR[0] = 0xFE;
    HDR[1] = 'S';
    HDR[2] = 'M';
    HDR[3] = 'B';
    wr16(HDR + 4, SMB2_HDR_SIZE);
    wr16(HDR + 6, (dialect >= 0x0210) ? 1 : 0); // CreditCharge: must be 0 for 2.0.2
    wr16(HDR + 12, command);
    wr16(HDR + 14, 8); // CreditRequest
    wr64(HDR + 24, next_msg_id);
    wr32(HDR + 36, tree_id);
    wr64(HDR + 40, session_id);
}

/*
  Send the header plus `bodylen` bytes of BODY, followed by `plen` bytes of `payload` (WRITE data,
  sent straight from the caller's buffer). Signs when the session requires it.
*/
static int SendRequest(int bodylen, const void *payload, int plen)
{
    u32 total = SMB2_HDR_SIZE + bodylen + plen;

    pkt[0] = 0;
    pkt[1] = (u8)(total >> 16);
    pkt[2] = (u8)(total >> 8);
    pkt[3] = (u8)total;

    if (signing) {
        // Static, not on the stack: callers include MCEMU's thread (0xB00 bytes of stack), and
        // every request is sent under smb_io_sema or before any other caller can run.
        static smb2auth_hmac_t mac;
        static u8 digest[32];

        wr32(HDR + 16, rd32(HDR + 16) | SMB2_FLAGS_SIGNED);
        smb2auth_hmac_init(&mac, SMB2AUTH_SHA256, session_key, sizeof(session_key));
        smb2auth_hmac_update(&mac, HDR, SMB2_HDR_SIZE + bodylen);
        if (plen > 0)
            smb2auth_hmac_update(&mac, payload, plen);
        smb2auth_hmac_final(&mac, digest);
        memcpy(HDR + 48, digest, 16);
    }

    next_msg_id++;

    if (SendData(main_socket, pkt, 4 + SMB2_HDR_SIZE + bodylen) < 0)
        return -1;
    if (plen > 0 && SendData(main_socket, payload, plen) < 0)
        return -1;

    return 0;
}

/*
  Receive the header of the reply to the request just sent. Skips NetBIOS keep-alives, interim
  STATUS_PENDING replies and anything not addressed to that request (an unsolicited oplock break).
  Returns the number of body bytes still to be read for this reply, or < 0 on a broken connection.
*/
static int RecvHeader(void)
{
    u64 expected = next_msg_id - 1;
    int len;

    for (;;) {
        if (RecvData(main_socket, pkt, 4) < 0)
            return -1;
        len = ((int)pkt[1] << 16) | ((int)pkt[2] << 8) | pkt[3];
        if (pkt[0] != 0) { // keep-alive or other session-service message
            if (Drain(len) < 0)
                return -1;
            continue;
        }
        if (len < SMB2_HDR_SIZE) {
            Drain(len);
            return -1;
        }
        if (RecvData(main_socket, HDR, SMB2_HDR_SIZE) < 0)
            return -1;
        len -= SMB2_HDR_SIZE;

        if (HDR[0] != 0xFE || HDR[1] != 'S' || HDR[2] != 'M' || HDR[3] != 'B') {
            Drain(len);
            return -1;
        }

        if (!(rd32(HDR + 16) & SMB2_FLAGS_SERVER_TO_REDIR) || rd64(HDR + 24) != expected ||
            ((rd32(HDR + 16) & SMB2_FLAGS_ASYNC_COMMAND) && rd32(HDR + 8) == STATUS_PENDING)) {
            if (Drain(len) < 0)
                return -1;
            continue;
        }

        return len;
    }
}

// Read the rest of a reply into BODY (what fits; the excess is drained). Returns the bytes kept.
static int RecvBody(int len)
{
    int keep = len > SMB2_BUF_SIZE - SMB2_HDR_SIZE ? SMB2_BUF_SIZE - SMB2_HDR_SIZE : len;

    if (RecvData(main_socket, BODY, keep) < 0)
        return -1;
    if (Drain(len - keep) < 0)
        return -1;

    return keep;
}

// A whole control exchange: send, then read the complete reply. Returns the body length or < 0.
static int Transact(int bodylen)
{
    int len;

    if (SendRequest(bodylen, NULL, 0) < 0)
        return -1;
    len = RecvHeader();
    if (len < 0)
        return -1;

    return RecvBody(len);
}

static u32 ReplyStatus(void)
{
    return rd32(HDR + 8);
}

//-------------------------------------------------------------------------
static int Negotiate(void)
{
    static const u8 client_guid[16] = {'O', 'P', 'L', '-', 'S', 'M', 'B', '2', 'P', 'S', '2', 'I', 'O', 'P', 'v', '1'};
    int len;

    next_msg_id = 0;
    session_id = 0;
    tree_id = 0;
    dialect = 0;
    signing = 0;

    SetHeader(SMB2_NEGOTIATE);
    memset(BODY, 0, 40);
    wr16(BODY + 0, 36);                             // StructureSize
    wr16(BODY + 2, 2);                              // DialectCount
    wr16(BODY + 4, SMB2_NEGOTIATE_SIGNING_ENABLED); // SecurityMode
    memcpy(BODY + 12, client_guid, 16);
    wr16(BODY + 36, 0x0202);
    wr16(BODY + 38, 0x0210);

    len = Transact(40);
    if (len < 0)
        return -1;
    if (ReplyStatus() != STATUS_SUCCESS || len < 64 || rd16(BODY) != 65)
        return -1000;

    dialect = rd16(BODY + 4);
    if (dialect != 0x0202 && dialect != 0x0210)
        return -1000;

    sign_required = (rd16(BODY + 2) & SMB2_NEGOTIATE_SIGNING_REQUIRED) ? 1 : 0;
    max_read = rd32(BODY + 32);
    max_write = rd32(BODY + 36);

    return 1;
}

int smb_NegotiateProtocol(char *SMBServerIP, int SMBServerPort, char *Username, char *Password, u32 *capabilities, OplSmbPwHashFunc_t hash_callback)
{
    iop_sema_t smp;

    (void)hash_callback; // SMB1-only; see the top of this file

    smp.initial = 1;
    smp.max = 1;
    smp.option = 0;
    smp.attr = 1;
    smb_io_sema = CreateSema(&smp);

    strncpy(user_name, Username, sizeof(user_name) - 1);
    user_name[sizeof(user_name) - 1] = '\0';
    strncpy(pass_word, Password, sizeof(pass_word) - 1);
    pass_word[sizeof(pass_word) - 1] = '\0';

    server_addr.s_addr = pinet_addr(SMBServerIP);
    server_port = (u16)SMBServerPort;
    *capabilities = 0;

    // As smb.c: keep trying until the server answers. Without it there is no game to boot.
    for (;;) {
        main_socket = OpenTCPSession();
        if (main_socket >= 0) {
            if (Negotiate() > 0)
                return 1;
            plwip_close(main_socket);
            main_socket = -1;
        }
        DelayThread(500 * 1000);
    }
}

//-------------------------------------------------------------------------
// 8 bytes that differ per logon. Not cryptographic: it only has to keep the NTLMv2 blob unique.
static void ClientChallenge(u8 *out, const u8 *server_challenge)
{
    smb2auth_hash_t h;
    iop_sys_clock_t clk;
    u8 digest[16];

    GetSystemTime(&clk);
    smb2auth_init(&h, SMB2AUTH_MD5);
    smb2auth_update(&h, &clk, sizeof(clk));
    smb2auth_update(&h, server_challenge, 8);
    smb2auth_update(&h, &session_id, sizeof(session_id));
    smb2auth_final(&h, digest);
    memcpy(out, digest, 8);
}

// Put an NTLMSSP security-buffer descriptor (length, max length, offset).
static void PutSecBuf(u8 *p, u16 len, u32 off)
{
    wr16(p, len);
    wr16(p + 2, len);
    wr32(p + 4, off);
}

static int SessionSetupRequest(int tokenlen)
{
    memset(BODY, 0, 24);
    wr16(BODY + 0, 25);                       // StructureSize
    BODY[3] = SMB2_NEGOTIATE_SIGNING_ENABLED; // SecurityMode
    wr16(BODY + 12, SMB2_HDR_SIZE + 24);      // SecurityBufferOffset
    wr16(BODY + 14, (u16)tokenlen);           // SecurityBufferLength

    return Transact(24 + tokenlen);
}

int smb_SessionSetupAndX(u32 capabilities)
{
    static const u8 ntlmssp_sig[8] = {'N', 'T', 'L', 'M', 'S', 'S', 'P', 0};
    u8 *tok = BODY + 24;
    u8 server_challenge[8], client_challenge[8], timestamp[8], ntowf[16], nt_proof[16], digest[16];
    static u8 domain[64];
    static smb2auth_hmac_t mac;
    static smb2auth_hash_t h;
    int len, off, tilen, domlen, ulen, has_timestamp = 0, anonymous;
    u32 secoff, seclen, status, tioff;

    (void)capabilities;

    // 1: NEGOTIATE_MESSAGE.
    SetHeader(SMB2_SESSION_SETUP);
    memset(tok, 0, 32);
    memcpy(tok, ntlmssp_sig, 8);
    wr32(tok + 8, 1);
    wr32(tok + 12, NTLM_CLIENT_FLAGS);
    len = SessionSetupRequest(32);
    if (len < 0)
        return -1;
    if (ReplyStatus() != STATUS_MORE_PROCESSING_REQUIRED || len < 8)
        return -1000;

    // 2: CHALLENGE_MESSAGE. Everything is bounds-checked against what was actually received.
    session_id = rd64(HDR + 40);
    secoff = rd16(BODY + 4);
    seclen = rd16(BODY + 6);
    if (secoff < SMB2_HDR_SIZE + 8 || secoff - SMB2_HDR_SIZE + seclen > (u32)len || seclen < 48)
        return -1000;
    tok = BODY + (secoff - SMB2_HDR_SIZE);
    if (!bytes_equal(tok, ntlmssp_sig, 8) || rd32(tok + 8) != 2)
        return -1000;
    memcpy(server_challenge, tok + 24, 8);

    /*
      DomainName: empty, as the menu's logon. The menu checked these credentials through smb2man,
      and libsmb2 logs on with no domain (smb2->domain is unset): the server resolved the user in
      its own account database. The server recomputes NTOWFv2 with the UserDom the client sent
      (MS-NLMP 3.3.2), so hashing and sending the CHALLENGE's TargetName instead (the usmb2 way)
      asks it to look the same user up under that name. On a domain-joined Windows machine that
      name is the domain, and a local account is not found there: the browse logon succeeds and
      the in-game logon fails with the same password. The two logons now ask the same question.
    */
    domlen = 0;

    // TargetInfo (40): copied into the NTLMv2 blob. Look for the server's timestamp in it.
    tilen = 0;
    if (seclen >= 48) {
        tilen = rd16(tok + 40);
        tioff = rd32(tok + 44);
        if (tilen > SMB2_TI_MAX || tioff > seclen || (u32)tilen > seclen - tioff)
            return -1000;
        memcpy(ntlm_ti, tok + tioff, tilen);
    }
    for (off = 0; off + 4 <= tilen;) {
        u16 id = rd16(ntlm_ti + off), avlen = rd16(ntlm_ti + off + 2);
        if (id == MSV_AV_EOL || off + 4 + avlen > tilen)
            break;
        if (id == MSV_AV_TIMESTAMP && avlen == 8) {
            memcpy(timestamp, ntlm_ti + off + 4, 8);
            has_timestamp = 1;
        }
        off += 4 + avlen;
    }
    if (!has_timestamp)
        memset(timestamp, 0, sizeof(timestamp)); // no clock on the IOP; servers that check send one

    // 3: AUTHENTICATE_MESSAGE, laid out as a 64-byte header followed by its fields.
    anonymous = (user_name[0] == '\0');
    SetHeader(SMB2_SESSION_SETUP);
    tok = BODY + 24;
    memset(tok, 0, 64);
    memcpy(tok, ntlmssp_sig, 8);
    wr32(tok + 8, 3);
    off = 64;

    memcpy(tok + off, domain, domlen); // DomainName
    PutSecBuf(tok + 28, (u16)domlen, off);
    off += domlen;

    ulen = put_utf16(tok + off, user_name, 0); // UserName
    PutSecBuf(tok + 36, (u16)ulen, off);
    off += ulen;

    PutSecBuf(tok + 44, 0, off); // Workstation: empty
    PutSecBuf(tok + 52, 0, off); // EncryptedRandomSessionKey: none (no KEY_EXCH)

    if (anonymous) {
        tok[off] = 0; // LmChallengeResponse Z(1), NtChallengeResponse empty (MS-NLMP 3.1.5.1.2)
        PutSecBuf(tok + 12, 1, off);
        off += 1;
        PutSecBuf(tok + 20, 0, off);
        wr32(tok + 60, NTLM_CLIENT_FLAGS | NTLMSSP_NEGOTIATE_ANONYMOUS);
    } else {
        u8 *nt, *blob;
        static u8 pw16[64];
        u8 nthash[16];
        int bloblen, pwlen;

        // NTOWFv2 = HMAC_MD5(MD4(UTF16(password)), UTF16(UPPER(user)) . domain)
        pwlen = put_utf16(pw16, pass_word, 0);
        smb2auth_init(&h, SMB2AUTH_MD4);
        smb2auth_update(&h, pw16, pwlen);
        smb2auth_final(&h, nthash);
        memset(pw16, 0, sizeof(pw16));

        ulen = put_utf16(pw16, user_name, 1);
        smb2auth_hmac_init(&mac, SMB2AUTH_MD5, nthash, 16);
        smb2auth_hmac_update(&mac, pw16, ulen);
        smb2auth_hmac_update(&mac, domain, domlen);
        smb2auth_hmac_final(&mac, ntowf);
        memset(nthash, 0, sizeof(nthash));

        ClientChallenge(client_challenge, server_challenge);

        // LmChallengeResponse: Z(24) when the server sent a timestamp, else LMv2 (MS-NLMP 3.3.2).
        if (has_timestamp) {
            memset(tok + off, 0, 24);
        } else {
            smb2auth_hmac_init(&mac, SMB2AUTH_MD5, ntowf, 16);
            smb2auth_hmac_update(&mac, server_challenge, 8);
            smb2auth_hmac_update(&mac, client_challenge, 8);
            smb2auth_hmac_final(&mac, tok + off);
            memcpy(tok + off + 16, client_challenge, 8);
        }
        PutSecBuf(tok + 12, 24, off);
        off += 24;

        // NtChallengeResponse = NTProofStr . blob
        nt = tok + off;
        blob = nt + 16;
        memset(blob, 0, 28);
        blob[0] = 1; // RespType
        blob[1] = 1; // HiRespType
        memcpy(blob + 8, timestamp, 8);
        memcpy(blob + 16, client_challenge, 8);
        memcpy(blob + 28, ntlm_ti, tilen);
        memset(blob + 28 + tilen, 0, 4);
        bloblen = 28 + tilen + 4;

        smb2auth_hmac_init(&mac, SMB2AUTH_MD5, ntowf, 16);
        smb2auth_hmac_update(&mac, server_challenge, 8);
        smb2auth_hmac_update(&mac, blob, bloblen);
        smb2auth_hmac_final(&mac, nt_proof);
        memcpy(nt, nt_proof, 16);
        PutSecBuf(tok + 20, (u16)(16 + bloblen), off);
        off += 16 + bloblen;

        // Session key (no KEY_EXCH: the session base key itself), used for signing.
        smb2auth_hmac_init(&mac, SMB2AUTH_MD5, ntowf, 16);
        smb2auth_hmac_update(&mac, nt_proof, 16);
        smb2auth_hmac_final(&mac, digest);
        memcpy(session_key, digest, 16);
        memset(ntowf, 0, sizeof(ntowf));

        wr32(tok + 60, NTLM_CLIENT_FLAGS);
    }

    len = SessionSetupRequest(off);
    if (len < 0)
        return -1;
    status = ReplyStatus();
    if (status != STATUS_SUCCESS || len < 8)
        return -1000;

    // Guest and anonymous sessions have no key to sign with; servers do not require it of them.
    signing = (sign_required && !anonymous && !(rd16(BODY + 2) & 0x0003)) ? 1 : 0;

    return 1;
}

//-------------------------------------------------------------------------
int smb_TreeConnectAndX(char *ShareName)
{
    int len, plen;

    SetHeader(SMB2_TREE_CONNECT);
    memset(BODY, 0, 8);
    plen = put_utf16(BODY + 8, ShareName, 0);
    wr16(BODY + 0, 9);                 // StructureSize
    wr16(BODY + 4, SMB2_HDR_SIZE + 8); // PathOffset
    wr16(BODY + 6, (u16)plen);         // PathLength

    len = Transact(8 + plen);
    if (len < 0)
        return -1;
    if (ReplyStatus() != STATUS_SUCCESS)
        return -1000;

    tree_id = rd32(HDR + 36);

    return 1;
}

//-------------------------------------------------------------------------
int smb_OpenAndX(char *filename, u8 *FID, int Write)
{
    int len, nlen, slot;
    u16 fid;

    WaitSema(smb_io_sema);

    for (slot = 0; slot < SMB2_MAX_FILES; slot++)
        if (!files[slot].used)
            break;
    if (slot == SMB2_MAX_FILES) {
        SignalSema(smb_io_sema);
        return -EMFILE;
    }

    // SMB2 names are relative to the share root: no leading separator.
    while (*filename == '\\' || *filename == '/')
        filename++;

    SetHeader(SMB2_CREATE);
    memset(BODY, 0, 56);
    nlen = put_utf16(BODY + 56, filename, 0);
    if (nlen == 0)
        BODY[56] = 0, BODY[57] = 0;                   // the buffer must not be empty
    wr16(BODY + 0, 57);                               // StructureSize
    wr32(BODY + 4, 2);                                // ImpersonationLevel: Impersonation
    wr32(BODY + 24, Write ? 0x0012019F : 0x00120089); // DesiredAccess: generic read(/write) rights
    wr32(BODY + 32, 0x00000007);                      // ShareAccess: read | write | delete
    wr32(BODY + 36, 1);                               // CreateDisposition: FILE_OPEN
    wr32(BODY + 40, 0x00000040);                      // CreateOptions: FILE_NON_DIRECTORY_FILE
    wr16(BODY + 44, SMB2_HDR_SIZE + 56);              // NameOffset
    wr16(BODY + 46, (u16)nlen);                       // NameLength

    len = Transact(56 + (nlen ? nlen : 2));
    if (len < 0) {
        SignalSema(smb_io_sema);
        return -1;
    }
    if (ReplyStatus() != STATUS_SUCCESS || len < 80) {
        SignalSema(smb_io_sema);
        return -1000;
    }

    memcpy(files[slot].id, BODY + 64, 16);
    files[slot].used = 1;
    fid = (u16)slot;
    memcpy(FID, &fid, 2);

    SignalSema(smb_io_sema);

    return 1;
}

//-------------------------------------------------------------------------
// Do not call WaitSema() from this function: as with smb.c, callers already hold it or run alone.
int smb_Close(int FID)
{
    int len;

    if (FID < 0 || FID >= SMB2_MAX_FILES || !files[FID].used)
        return -EBADF;
    files[FID].used = 0; // whatever the server answers, the slot is free again

    SetHeader(SMB2_CLOSE);
    memset(BODY, 0, 24);
    wr16(BODY + 0, 24); // StructureSize
    memcpy(BODY + 8, files[FID].id, 16);

    len = Transact(24);
    if (len < 0 || ReplyStatus() != STATUS_SUCCESS)
        return -EIO;

    return 0;
}

//-------------------------------------------------------------------------
// One READ. Returns bytes read, 0 at end of file, or < 0.
static int ReadChunk(int slot, u64 offset, void *readbuf, int nbytes)
{
    int len, pad;
    u32 datalen;
    u8 *rsp;

    SetHeader(SMB2_READ);
    memset(BODY, 0, 49);
    wr16(BODY + 0, 49);           // StructureSize
    BODY[2] = SMB2_HDR_SIZE + 16; // Padding: where we would like the data
    wr32(BODY + 4, (u32)nbytes);  // Length
    wr64(BODY + 8, offset);       // Offset
    memcpy(BODY + 16, files[slot].id, 16);

    if (SendRequest(49, NULL, 0) < 0)
        return -2;
    len = RecvHeader();
    if (len < 0)
        return -2;

    if (ReplyStatus() != STATUS_SUCCESS) {
        if (Drain(len) < 0)
            return -2;
        return (ReplyStatus() == STATUS_END_OF_FILE) ? 0 : -EIO;
    }

    // The fixed part of the response, then (after any padding) the data straight into readbuf.
    if (len < 16 || RecvData(main_socket, BODY, 16) < 0)
        return -2;
    len -= 16;
    rsp = BODY;
    datalen = rd32(rsp + 4);
    pad = (int)rsp[2] - (SMB2_HDR_SIZE + 16);
    if (pad < 0 || pad > len || datalen > (u32)(len - pad) || datalen > (u32)nbytes) {
        Drain(len);
        return -EIO;
    }
    if (Drain(pad) < 0)
        return -2;
    len -= pad;
    if (datalen > 0 && RecvData(main_socket, readbuf, (int)datalen) < 0)
        return -2;
    len -= (int)datalen;
    if (Drain(len) < 0)
        return -2;

    return (int)datalen;
}

int smb_ReadFile(u16 FID, u32 offsetlow, u32 offsethigh, void *readbuf, int nbytes)
{
    u64 offset = ((u64)offsethigh << 32) | offsetlow;
    int result, remaining = nbytes, chunk;
    u8 *ptr = (u8 *)readbuf;

    if (FID >= SMB2_MAX_FILES || !files[FID].used)
        return -EBADF;

    chunk = SMB2_READ_CHUNK;
    if (max_read != 0 && (u32)chunk > max_read)
        chunk = (int)max_read;

    WaitSema(smb_io_sema);

    while (remaining > 0) {
        int toRead = remaining > chunk ? chunk : remaining;

        result = ReadChunk(FID, offset, ptr, toRead);
        if (result <= 0) {
            SignalSema(smb_io_sema);
            // End of file: the bytes read before it, as a short count (see smb.c).
            return (result == 0) ? nbytes - remaining : result;
        }

        offset += result;
        ptr += result;
        remaining -= result;
    }

    SignalSema(smb_io_sema);

    return nbytes;
}

//-------------------------------------------------------------------------
// One WRITE. Returns the server's Count, or <= 0.
static int WriteChunk(int slot, u64 offset, void *writebuf, int nbytes)
{
    int len;
    u32 count;

    SetHeader(SMB2_WRITE);
    memset(BODY, 0, 48);
    wr16(BODY + 0, 49);                 // StructureSize
    wr16(BODY + 2, SMB2_HDR_SIZE + 48); // DataOffset
    wr32(BODY + 4, (u32)nbytes);        // Length
    wr64(BODY + 8, offset);             // Offset
    memcpy(BODY + 16, files[slot].id, 16);

    if (SendRequest(48, writebuf, nbytes) < 0)
        return -EIO;
    len = RecvHeader();
    if (len < 0)
        return -EIO;
    len = RecvBody(len);
    if (len < 0)
        return -EIO;
    if (ReplyStatus() != STATUS_SUCCESS || len < 8)
        return -EIO;

    count = rd32(BODY + 4);
    if (count > (u32)nbytes)
        return -EIO;

    return (int)count;
}

int smb_WriteFile(u16 FID, u32 offsetlow, u32 offsethigh, void *writebuf, int nbytes)
{
    u64 offset = ((u64)offsethigh << 32) | offsetlow;
    int result, remaining = nbytes, chunk;
    u8 *ptr = (u8 *)writebuf;

    if (FID >= SMB2_MAX_FILES || !files[FID].used)
        return -EBADF;

    chunk = SMB2_WRITE_CHUNK;
    if (max_write != 0 && (u32)chunk > max_write)
        chunk = (int)max_write;

    WaitSema(smb_io_sema);

    while (remaining > 0) {
        int toWrite = remaining > chunk ? chunk : remaining;

        result = WriteChunk(FID, offset, ptr, toWrite);
        if (result <= 0) {
            SignalSema(smb_io_sema);
            return result;
        }

        offset += result;
        ptr += result;
        remaining -= result;
    }

    SignalSema(smb_io_sema);

    return nbytes;
}

//-------------------------------------------------------------------------
int smb_ReadCD(unsigned int lsn, unsigned int nsectors, void *buf, int part_num)
{
    return smb_ReadFile(cdvdman_settings.FIDs[part_num], lsn * 2048, lsn >> 21, buf, (int)(nsectors * 2048));
}

void smb_CloseAll(void)
{
    int i, fd;

    for (i = 0; i < cdvdman_settings.common.NumParts; i++) {
        fd = cdvdman_settings.FIDs[i];
        if (fd >= 0) {
            smb_Close(fd);
            cdvdman_settings.FIDs[i] = -1;
        }
    }
}

int smb_Disconnect(void)
{
    if (main_socket >= 0) {
        plwip_close(main_socket);
        main_socket = -1;
    }

    return 1;
}
