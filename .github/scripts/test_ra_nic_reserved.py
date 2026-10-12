"""RA menu actions must not claim the NIC a selected-but-unloaded UDP transport needs.

raNetNicReserved() is compiled from src/ranet.c against stubs: it is true while UDPBD/UDPFS is
loaded (raNetNicBusy) OR while the user's selected protocol is a UDP transport that has not loaded
yet. Menu-side RA actions (Caduceus page, support check, link test, achievements browser) use it;
the launch path keeps raNetNicBusy, because a game's IOP reset frees the NIC either way.
"""
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ranet = (ROOT / "src/ranet.c").read_text(encoding="utf-8")
achievements = (ROOT / "src/achievements.c").read_text(encoding="utf-8")


def body(source, signature):
    start = source.index(signature)
    end = source.index("\n}\n", start) + 3
    return source[start:end]


reserved = body(ranet, "int raNetNicReserved(void)")
harness = r'''
#include <assert.h>
#include <stdio.h>
enum { NET_PROTO_OFF, NET_PROTO_SMB, NET_PROTO_UDPFS, NET_PROTO_UDPFSBD, NET_PROTO_UDPBD, NET_PROTO_HTTP };
static int gNetworkProtocol, loaded;
static int raNetNicBusy(void) { return loaded; }
@RESERVED@
int main(void)
{
    static const int udp[] = {NET_PROTO_UDPFS, NET_PROTO_UDPFSBD, NET_PROTO_UDPBD};
    static const int other[] = {NET_PROTO_OFF, NET_PROTO_SMB, NET_PROTO_HTTP};
    for (unsigned i = 0; i < 3; i++) {
        gNetworkProtocol = udp[i];
        loaded = 0;
        assert(raNetNicReserved()); /* selected, not loaded yet: still reserved */
        gNetworkProtocol = other[i];
        assert(!raNetNicReserved()); /* SMB/HTTP/Off: RA may raise SMB */
        loaded = 1;
        assert(raNetNicReserved()); /* a resident UDP chain always owns it */
    }
    puts("ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "reserved.c"
    exe = Path(tmp) / "reserved"
    src.write_text(harness.replace("@RESERVED@", reserved), encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, capture_output=True)

# Menu-side actions use the reserved check; the launch path keeps the loaded-only check.
for signature in ("int raCaduceusPage(", "int raAskPC(", "int raNetTestLink("):
    fn = ranet[ranet.index(signature):]
    fn = fn[:fn.index("open_pc_socket(")]
    assert "raNetNicReserved()" in fn and "raNetNicBusy()" not in fn, signature
launch = body(ranet, "void raLaunchNetworkUp(void)")
assert "raNetNicBusy()" in launch and "raNetNicReserved()" not in launch
assert re.search(r"raNetNicReserved\(\)\s*\|\|\s*!ethEnsureSMBShareConnected\(\)", achievements)
print("PASS: RA menu actions leave a selected UDP transport's NIC alone; launches unchanged")
