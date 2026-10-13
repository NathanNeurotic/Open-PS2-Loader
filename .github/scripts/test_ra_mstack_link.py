"""RA menu requests go through the ministack's mstack: device while a UDPFS chain owns the NIC.

The menu's lwIP stack cannot run while UDPFS holds the adapter, so src/ranet.c opens a "link"
instead of a socket: a real socket when the NIC is free, the RA_LINK_MSTACK sentinel when the NIC
is reserved and udpfs_ministack's mstack: device answers, else RA_LINK_BUSY (-8, "network busy").
ask() runs each attempt as one devctl on the mstack link, with the same retry count, the same
reply-source filtering and the same g_raReplyIP as the socket path. ask(), open_pc_link() and
close_pc_link() are compiled from src/ranet.c against stubs.
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ranet = (ROOT / "src/ranet.c").read_text(encoding="utf-8")


def body(signature):
    start = ranet.index(signature)
    end = ranet.index("\n}\n", start) + 3
    return ranet[start:end]


def until(signature, marker):
    fn = body(signature)
    return fn[:fn.index(marker)] if marker in fn else fn


source = "\n".join(body(sig) for sig in (
    "static int ask_mstack(",
    "static int ask(",
    "static int open_pc_link(",
    "static void close_pc_link(",
    "int raCaduceusPage(",
))

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "modules/network/udpfs_ministack/include/mstack_xchg.h"
#include "modules/network/common/ra_client.h"
typedef unsigned int u32;
typedef unsigned char u8;
typedef int socklen_t;
#define RA_TRY 12
#define RA_POLL_MS 25
#define RA_RECV_MAX 992
#define RA_MY_PORT 18196
#define RA_MSG_DONTWAIT 0x08
#define INADDR_BROADCAST 0xFFFFFFFFu
#define RA_LINK_MSTACK 0x10000
#define RA_LINK_BUSY (-8)
struct sockaddr { int x; };
struct sockaddr_in { int sin_family; unsigned short sin_port; struct { u32 s_addr; } sin_addr; };
static u32 htonl(u32 v) { return v; }
static unsigned short htons(unsigned short v) { return (unsigned short)((v >> 8) | (v << 8)); }
static unsigned short ntohs(unsigned short v) { return htons(v); }
static u32 g_raReplyIP;
static mstack_xchg_req_t g_xreq;
static mstack_xchg_reply_t g_xreply;
static int reserved, sends, recvs, closes, ethinits, probe = 1;
int ps2_ip[4] = {192, 168, 1, 10};
static int raNetNicReserved(void) { return reserved; }
static int open_pc_socket(char *myaddr, int sz, u8 ip[4]) { (void)ip; snprintf(myaddr, sz, " 10.0.0.2 18196"); return 5; }
static int ethLoadInitModules(void) { ethinits++; return 0; }
static void disconnect(int s) { assert(s == 5); closes++; }
static int sendto(int s, const char *b, int n, int f, struct sockaddr *a, int l) { (void)s; (void)b; (void)f; (void)a; (void)l; sends++; return n; }
static int recvfrom(int s, char *b, int n, int f, struct sockaddr *a, socklen_t *l) { (void)s; (void)b; (void)n; (void)f; (void)a; (void)l; recvs++; return -1; }
static void DelayThread(int us) { (void)us; }
#define RA_MODE_CADUCEUS 1
static int gRAMode = RA_MODE_CADUCEUS;
static char g_rx[2048];
static int caduceus_target(struct sockaddr_in *to) { memset(to, 0, sizeof(*to)); to->sin_port = htons(RA_CADUCEUS_PORT); to->sin_addr.s_addr = 0x1401a8c0u; return 1; }
static int ports[16];
/* Scripted mstack: device. Each UDP_XCHG call takes the next scripted reply (src 0 = timeout). */
static int xchgs, script_n;
static u32 script_src[16];
static const char *script_text[16];
static int script_len[16];
static mstack_xchg_req_t last_req;
static unsigned int last_arglen;
static int fileXioDevctl(const char *name, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen)
{
    assert(!strcmp(name, "mstack:"));
    if (cmd == MSTACK_DEVCTL_VERSION)
        return probe;
    assert(cmd == MSTACK_DEVCTL_UDP_XCHG && buflen >= sizeof(mstack_xchg_reply_t));
    memcpy(&last_req, arg, arglen);
    last_arglen = arglen;
    if (xchgs < 16)
        ports[xchgs] = last_req.dst_port;
    int i = xchgs++;
    if (i >= script_n || script_src[i] == 0)
        return -116; /* -ETIMEDOUT */
    mstack_xchg_reply_t *r = buf;
    int len = script_len[i] ? script_len[i] : (int)strlen(script_text[i]);
    r->src_ip = script_src[i];
    r->len = (unsigned short)len;
    if (script_len[i])
        memset(r->data, 'z', len);
    else
        memcpy(r->data, script_text[i], len);
    return len;
}
'''

tests = r'''
#define IP20 0x1401a8c0u /* 192.168.1.20 as sin_addr.s_addr on little endian */
#define IP21 0x1501a8c0u
#define IP77 0x4d01a8c0u
static struct sockaddr_in target(u32 ip) { struct sockaddr_in t; memset(&t, 0, sizeof(t)); t.sin_port = htons(18194); t.sin_addr.s_addr = ip; return t; }
static void reset(void) { xchgs = script_n = sends = recvs = 0; g_raReplyIP = 0; }
int main(void)
{
    char myaddr[32], out[1100];
    u8 ip[4];
    struct sockaddr_in to;
    int link;

    /* not_reserved_uses_socket */
    reset(); reserved = 0;
    link = open_pc_link(myaddr, sizeof(myaddr), ip);
    assert(link == 5);
    to = target(IP20);
    ask(link, &to, "RAQ1 x", out, sizeof(out));
    assert(sends > 0 && xchgs == 0);
    close_pc_link(link);
    assert(closes == 1);

    /* reserved_with_mstack_uses_devctl */
    reset(); reserved = 1; probe = 1;
    link = open_pc_link(myaddr, sizeof(myaddr), ip);
    assert(link == RA_LINK_MSTACK);
    assert(!strcmp(myaddr, " 192.168.1.10 18196"));
    assert(ip[0] == 192 && ip[1] == 168 && ip[2] == 1 && ip[3] == 10);
    script_n = 1; script_src[0] = IP20; script_text[0] = "RAA1 OK 5"; script_len[0] = 0;
    assert(ask(link, &to, "RAQ1 abc 192.168.1.10 18196", out, sizeof(out)) == 9);
    assert(!strcmp(out, "RAA1 OK 5") && g_raReplyIP == IP20);
    assert(sends == 0 && recvs == 0);
    assert(last_req.dst_ip == IP20 && last_req.dst_port == 18194 && last_req.timeout_ms == 250);
    assert(last_req.len == 27 && !memcmp(last_req.data, "RAQ1 abc 192.168.1.10 18196", 27));
    assert(last_arglen == MSTACK_XCHG_REQ_HDR + 27);
    close_pc_link(link);
    assert(closes == 1); /* the mstack link is not a socket */
    assert(ethinits == 0);

    /* reserved_without_mstack_is_busy */
    reset(); probe = -19;
    assert(open_pc_link(myaddr, sizeof(myaddr), ip) == RA_LINK_BUSY);
    assert(ethinits == 0);
    probe = 1;

    /* retry_count_matches */
    reset();
    assert(ask(RA_LINK_MSTACK, &to, "RAQ1 x", out, sizeof(out)) == -1);
    assert(xchgs == RA_TRY);

    /* source_filter_matches */
    reset(); script_n = 2;
    script_src[0] = IP21; script_text[0] = "STRANGER"; script_len[0] = 0;
    script_src[1] = IP20; script_text[1] = "RAA1 NO"; script_len[1] = 0;
    assert(ask(RA_LINK_MSTACK, &to, "RAQ1 x", out, sizeof(out)) == 7);
    assert(!strcmp(out, "RAA1 NO") && g_raReplyIP == IP20 && xchgs == 2);

    /* broadcast_accepts_any */
    reset(); script_n = 1;
    script_src[0] = IP77; script_text[0] = "RAO1 OK v"; script_len[0] = 0;
    to = target(0xFFFFFFFFu);
    assert(ask(RA_LINK_MSTACK, &to, "RAP1 192.168.1.10 18196", out, sizeof(out)) == 9);
    assert(g_raReplyIP == IP77);

    /* truncates_to_outmax */
    reset(); script_n = 1;
    script_src[0] = IP77; script_text[0] = ""; script_len[0] = MSTACK_XCHG_REPLY_MAX;
    memset(out, 0x5A, sizeof(out));
    assert(ask(RA_LINK_MSTACK, &to, "RAG1 x", out, 64) == 63);
    assert(out[63] == 0 && out[64] == 0x5A);

    /* caduceus_page_over_mstack: probe on 18197, then the paired request on 18198 */
    reset(); reserved = 1; probe = 1; script_n = 2;
    script_src[0] = IP20; script_text[0] = "CADR2 " RA_PROBE_HASH " READY UNKNOWN"; script_len[0] = 0;
    script_src[1] = IP20; script_text[1] = "CADB1 7 OK\tG"; script_len[1] = 0;
    assert(raCaduceusPage("CADA1 7 G 0 0 0 secret", 7, out, sizeof(out)) == 0);
    assert(ports[0] == RA_CADUCEUS_PORT && ports[1] == 18198 && xchgs == 2);
    assert(!memcmp(last_req.data, "CADA1 7 G 0 0 0 secret", 22));
    assert(!strcmp(out, "OK\tG") && sends == 0 && closes == 1);
    reserved = 0;

    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "link.c"
    exe = Path(tmp) / "link.exe"
    src.write_text(harness + source + tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function", "-I", str(ROOT),
                    str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, capture_output=True)

# The support check and link test open a link; neither keeps its own NIC refusal or raw socket loop.
for signature in ("int raAskPC(", "int raNetTestLink("):
    fn = body(signature)
    assert "open_pc_link(" in fn and "open_pc_socket(" not in fn, signature
    assert "disconnect(sock)" not in fn, signature
assert "sendto(" not in body("int raNetTestLink("), "the RAP1 link test still has its own socket loop"
assert "raNetNicReserved()" in body("static int open_pc_link(")
# The Caduceus browser's UDP pages follow the link too (its key comes from the UDPFS share).
cad = body("int raCaduceusPage(")
assert "open_pc_link(" in cad and "open_pc_socket(" not in cad and "disconnect(sock)" not in cad
assert "raNetNicReserved()" not in cad[:cad.index("open_pc_link(")]
# The browsers' TCP paths need lwIP: they keep refusing while the NIC is reserved.
assert "raNetNicReserved()" in until("int raNetXeraboraIdentify(", "open_pc_socket(")
assert "raNetNicReserved()" in until("int raNetHttpGet(", "socket(")
# ps2sdk's newlib port refuses fileXio headers unless the file opts in first (as every other
# fileXio user in src/ does); the RA build fails otherwise.
include = ranet.index("#include <fileXio_rpc.h>")
assert "#define NEWLIB_PORT_AWARE" in ranet[:include], "fileXio_rpc.h included without NEWLIB_PORT_AWARE"
print("PASS: RA requests use mstack: while UDPFS owns the NIC, sockets otherwise, same retries and filtering")
