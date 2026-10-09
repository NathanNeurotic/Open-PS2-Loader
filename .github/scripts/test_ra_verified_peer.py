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
