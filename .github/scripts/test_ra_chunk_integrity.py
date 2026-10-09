"""Exercise the actual menu RA chunk-layout validator with adversarial replies."""

from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/ranet.c").read_text()
start = source.index("static int raExpectedChunkLength(")
function = source[start:source.index("\n}\n", start) + 2]
assert "raExpectedChunkLength(total, chunks, 0) < 0" in source
assert "len != raExpectedChunkLength(total, chunks, i)" in source

harness = r"""
#include <assert.h>
#include <stdio.h>
#define RA_MAX_BYTES (20 * 1024)
#define RA_CHUNK 896
""" + function + r"""
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
