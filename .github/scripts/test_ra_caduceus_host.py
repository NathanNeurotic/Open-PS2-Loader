"""Keep every Caduceus menu request pinned to the configured SMB host.

Compile the actual target construction; the remaining assertions guard all
call sites against accidental reintroduction of broadcast discovery.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "src/ranet.c").read_text()
start = src.index("static int caduceus_target(struct sockaddr_in *to)")
end = src.index("\n}\n", start) + 2
helper = src[start:end]
sections = {
    "account browser": src[src.index("int raCaduceusPage("):src.index("static int raExpectedChunkLength(")],
    "support checks": src[src.index("int raAskPC("):src.index("void raLaunchNetworkUp(")],
    "launch readiness": src[src.index("void raLaunchNetworkUp("):src.index("int raNetTestLink(")],
    "link test": src[src.index("int raNetTestLink("):],
}
for name, section in sections.items():
    assert "caduceus_target(&to)" in section, f"{name} lacks configured-host gating"

harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint8_t u8;
struct sockaddr_in {
    int sin_family;
    unsigned short sin_port;
    struct { u32 s_addr; } sin_addr;
};
#define AF_INET 2
#define RA_CADUCEUS_PORT 18197
#define htons(x) (x)
static u8 pc_ip[4];
""" + helper + r"""
int main(void)
{
    struct sockaddr_in target;
    memset(&target, 0xa5, sizeof(target));
    assert(!caduceus_target(&target)); /* No configured host: no discovery. */
    pc_ip[0] = 192;
    pc_ip[1] = 168;
    pc_ip[2] = 1;
    pc_ip[3] = 10;
    assert(caduceus_target(&target));
    assert(target.sin_family == AF_INET);
    assert(target.sin_port == RA_CADUCEUS_PORT);
    assert(target.sin_addr.s_addr == 0x0a01a8c0u);
    memset(pc_ip, 255, sizeof(pc_ip));
    assert(!caduceus_target(&target)); /* Broadcast is not a paired host. */
    puts("PASS: Caduceus menu/browser/launch/link targets require configured unicast peer");
    return 0;
}
"""

with tempfile.TemporaryDirectory(prefix="ra-caduceus-host-") as tmp:
    path = Path(tmp) / "test.c"
    exe = Path(tmp) / "test"
    path.write_text(harness)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    str(path), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
