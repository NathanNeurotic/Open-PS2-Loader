"""The vendored ps2ips RPC server returns the resolved IPv4 address, not a pointer to it.

lwIP's gethostbyname() returns h_addr_list[0] as a POINTER to the address bytes. ps2sdk's
do_gethostbyname copied &h_addr_list[0] -- the pointer itself -- into the 4-byte reply, so the EE got an
IOP address as the "IP". The RA edition's HTTPS lookup is the first RiptOPL user of DNS. The real
function is compiled from modules/network/ps2ips/ps2ips.c against an lwIP-shaped hostent.
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "modules/network/ps2ips/ps2ips.c").read_text(encoding="utf-8", errors="replace")
start = source.index("static void do_gethostbyname(")
end = source.index("\n}\n", start) + 3
function = source[start:end]

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef short s16;
typedef int s32;
typedef struct { unsigned int addr; } ip_addr_t;
struct hostent_res { s16 h_addrtype; s16 h_length; ip_addr_t h_addr; };
typedef struct { s32 result; struct hostent_res hostent; } gethostbyname_res_pkt;
struct hostent { char *h_name; char **h_aliases; int h_addrtype; int h_length; char **h_addr_list; };
static char _rpc_buffer[128];
/* As lwIP's lwip_gethostbyname: h_addr_list[0] points at the address. */
static ip_addr_t s_hostent_addr = {0x0401a8c0}; /* 192.168.1.4 */
static char *s_phostent_addr[2] = {(char *)&s_hostent_addr, NULL};
static struct hostent s_hostent = {"retroachievements.org", NULL, 2, 4, s_phostent_addr};
static int fail;
static struct hostent *gethostbyname(const char *name) { (void)name; return fail ? NULL : &s_hostent; }
@FUNCTION@
int main(void)
{
    gethostbyname_res_pkt pkt;
    memset(&pkt, 0xAA, sizeof(pkt));
    strcpy(_rpc_buffer, "retroachievements.org");
    do_gethostbyname(&pkt, sizeof(pkt));
    assert(pkt.result == 0 && pkt.hostent.h_length == 4);
    assert(pkt.hostent.h_addr.addr == 0x0401a8c0); /* the address, not &s_hostent_addr */
    fail = 1;
    do_gethostbyname(&pkt, sizeof(pkt));
    assert(pkt.result == -1);
    puts("ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "dns.c"
    exe = Path(tmp) / "dns.exe"
    src.write_text(harness.replace("@FUNCTION@", function), encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: ps2ips gethostbyname returns the IPv4 address")
