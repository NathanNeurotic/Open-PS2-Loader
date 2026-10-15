"""Exercise the actual menu RA chunk-layout validator with adversarial replies."""

from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/ranet.c").read_text()
start = source.index("static int raExpectedChunkLength(")
function = source[start:source.index("\n}\n", start) + 2]
start = source.index("static int raParseChunkHeader(")
parser = source[start:source.index("\n}\n", start) + 2]
assert "raParseChunkHeader(g_rx, got, &idx, &len, &hdr)" in source
assert "raExpectedChunkLength(total, chunks, 0) < 0" in source
assert "len != raExpectedChunkLength(total, chunks, i)" in source

harness = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define RA_MAX_BYTES (20 * 1024)
#define RA_CHUNK 896
""" + function + parser + r"""
int main(void)
{
    assert(raExpectedChunkLength(1, 1, 0) == 1);
    assert(raExpectedChunkLength(896, 1, 0) == 896);
    assert(raExpectedChunkLength(897, 2, 0) == 896);
    assert(raExpectedChunkLength(897, 2, 1) == 1);
    assert(raExpectedChunkLength(1793, 3, 2) == 1);
    assert(raExpectedChunkLength(20480, 23, 21) == 896);
    assert(raExpectedChunkLength(20480, 23, 22) == 768);
    /* Malformed source advertises too many/few chunks or a zero/oversize body. */
    assert(raExpectedChunkLength(0, 1, 0) < 0);
    assert(raExpectedChunkLength(-1, 1, 0) < 0);
    assert(raExpectedChunkLength(20481, 23, 0) < 0);
    assert(raExpectedChunkLength(1000, 1, 0) < 0);
    assert(raExpectedChunkLength(1000, 3, 0) < 0);
    assert(raExpectedChunkLength(1000, 2, -1) < 0);
    assert(raExpectedChunkLength(1000, 2, 2) < 0);
    assert(raExpectedChunkLength(1000, 0, 0) < 0);
    /* No short middle packet can be accepted to create a gap. */
    assert(raExpectedChunkLength(1000, 2, 0) != 100);
    assert(raExpectedChunkLength(1000, 2, 1) != 896);
    {
        char reply[1024];
        int idx, len, hdr;
        for (int first = 0; first < 256; first++) {
            memset(reply, ' ', sizeof(reply));
            int body = snprintf(reply, sizeof(reply), "RAC1 1 896 ");
            memset(reply + body, 'x', 896);
            reply[body] = (char)first;
            reply[960] = 0;
            assert(raParseChunkHeader(reply, 960, &idx, &len, &hdr));
            assert(idx == 1 && len == 896 && hdr == body);
            assert((unsigned char)reply[hdr] == first);
            assert(!raParseChunkHeader(reply, body - 1, &idx, &len, &hdr));
        }
        assert(!raParseChunkHeader("RAC1 1 896x", 11, &idx, &len, &hdr));
        assert(!raParseChunkHeader("RAC1 1", 6, &idx, &len, &hdr));
    }
    puts("PASS: RA fixed-stride chunk lengths, counts and bounds");
    return 0;
}
"""

with tempfile.TemporaryDirectory() as directory:
    program = Path(directory) / "chunk.c"
    binary = Path(directory) / "chunk"
    program.write_text(harness)
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
         str(program), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
