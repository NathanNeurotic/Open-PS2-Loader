"""Compile reset payload bounds and verify the EE core uses the guarded offset."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "ee_core/src/iopmgr.c").read_text(encoding="utf-8")
assert "eeResetPayloadLength(arglen, RESET_ARG_MAX)" in source
assert "arg != NULL && payloadLen >= 0" in source
assert "arg[EE_RESET_PREFIX_BYTES]" in source
assert "arglen < (int)sizeof(reset_pkt.arg) - 1" in source
assert "reset_pkt.arg[arglen] = '\\0';" in source
assert "if (pIOP_buffer == NULL)" in source
assert "arglen > RESET_ARG_MAX - EE_RESET_SUFFIX_BYTES" in source
program = r'''
#include <assert.h>
#include <stdio.h>
#include "ee_core/include/reset_arg_bounds.h"
int main(void) {
    assert(eeResetPayloadLength(-1, 80) == -1);
    assert(eeResetPayloadLength(0, 80) == -1);
    assert(eeResetPayloadLength(9, 80) == -1);
    assert(eeResetPayloadLength(10, 80) == 0);
    assert(eeResetPayloadLength(11, 80) == 1);
    assert(eeResetPayloadLength(83, 80) == 73);
    assert(eeResetPayloadLength(84, 80) == -1);
    assert(eeResetPayloadLength(10, 6) == -1);
    assert(eeResetPayloadLength(2147483647, 80) == -1);
    puts("PASS: IOP reset payload boundary validation");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "test.c"
    exe = Path(d) / "test"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(root),
                    str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
