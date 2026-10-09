"""Compile the real verified-peer cache used for in-game passive RA networking.

A random successful UDP read is not proof of a valid RA peer. A previously
confirmed peer is discarded on mode/host changes or network settings apply.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/ranet.c").read_text()
start = source.index("static u32 g_raReplyIP;")
end = source.index("static unsigned char g_wl[RA_MAX_BYTES];", start)
peer = source[start:end]
assert "raNetForgetPeer();" in source[source.index("int raAskPC("):source.index("    if (raNetNicBusy())",source.index("int raAskPC("))]
assert "raNetRememberPeer(g_raReplyIP);" in source
assert "raNetRememberPeer(from.sin_addr.s_addr);" in source
assert "raNetForgetPeer();" in (root/"src/gui.c").read_text()
harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint8_t u8;
#define INADDR_BROADCAST 0xffffffffu
#define htonl(x) (x)
#define RA_MODE_CADUCEUS 1
static int gRAMode;
static u8 pc_ip[4] = {192, 168, 1, 10};
"""
harness += peer
harness += r"""
int main(void) {
    gRAMode=RA_MODE_CADUCEUS;
    g_raReplyIP=42;
    assert(raNetPeerIP()==0); /* Unvalidated datagram is never a launch peer. */
    raNetRememberPeer(42);
    assert(raNetPeerIP()==42);
    gRAMode=0;
    assert(raNetPeerIP()==0); /* Can't reuse a Caduceus host as Xerabora. */
    gRAMode=RA_MODE_CADUCEUS;
    assert(raNetPeerIP()==42);
    pc_ip[3]=11;
    assert(raNetPeerIP()==0); /* Changed SMB server invalidates selected host. */
    pc_ip[3]=10;
    raNetForgetPeer();
    assert(raNetPeerIP()==0);
    raNetRememberPeer(INADDR_BROADCAST);
    assert(raNetPeerIP()==0);
    raNetRememberPeer(0);
    assert(raNetPeerIP()==0);
    puts("PASS: only verified peers, mode/SMB-host binding, explicit invalidation, no broadcast/zero");
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="ra-verified-peer-") as tmp:
    path = Path(tmp) / "peer.c"
    exe = Path(tmp) / "peer"
    path.write_text(harness)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror", str(path), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# Compile the actual link-reply condition. A malformed RAO1 prefix must not
# become a trusted destination, and a pinned peer rejects foreign sources.
start_reply = source.index('if (got >= 8 && strncmp(rx, "RAO1 OK ", 8) == 0')
end_reply = source.index("found = 1;", start_reply)
condition = source[start_reply:end_reply].strip()[3:].strip()
link_harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#define INADDR_BROADCAST 0xffffffffu
#define htonl(x) (x)
static int accepted(const char *rx, int got, u32 target, u32 sender) {
    struct { struct { u32 s_addr; } sin_addr; } to, from;
    to.sin_addr.s_addr=target; from.sin_addr.s_addr=sender;
    return @PREDICATE@;
}
int main(void) {
    const char *ok="RAO1 OK test";
    assert(accepted(ok,strlen(ok),INADDR_BROADCAST,42));
    assert(accepted(ok,strlen(ok),42,42));
    assert(!accepted(ok,strlen(ok),42,99));
    assert(!accepted("RAO1 FAIL",9,INADDR_BROADCAST,42));
    assert(!accepted("RAO1 BAD",8,42,42));
    assert(!accepted("RAO1",4,INADDR_BROADCAST,42));
    puts("PASS: only valid RAO1 OK replies from expected peer establish a link");
    return 0;
}
""".replace("@PREDICATE@", condition)
with tempfile.TemporaryDirectory(prefix="ra-link-peer-") as tmp:
    src=Path(tmp)/"link.c"
    exe=Path(tmp)/"link"
    src.write_text(link_harness)
    subprocess.run(["cc","-std=gnu99","-Wall","-Werror",str(src),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
