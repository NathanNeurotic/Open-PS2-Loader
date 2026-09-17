#!/usr/bin/env python3
"""Exercise hddAddPartitionHere's production block-size expression at i == 31."""

import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT / "modules/hdd/apa/src/hdd.c").read_text(encoding="utf-8")
    match = re.search(
        r"if \(\((?P<expression>\(u32\)1 << i)\) >= params->size && emptyBlocks\[i\] != 0\)",
        source,
    )
    if match is None:
        raise SystemExit("hddAddPartitionHere block-size expression not found")

    harness = f"""
#include <assert.h>
#include <stdint.h>
typedef uint32_t u32;
static u32 block_size(u32 i)
{{
    return {match.group('expression')};
}}
int main(void)
{{
    assert(block_size(0) == UINT32_C(1));
    assert(block_size(30) == UINT32_C(0x40000000));
    assert(block_size(31) == UINT32_C(0x80000000));
    return 0;
}}
"""
    with tempfile.TemporaryDirectory(prefix="opl-apa-shift-") as directory:
        executable = Path(directory) / "test"
        subprocess.run(
            [
                "cc",
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=undefined",
                "-fsanitize-undefined-trap-on-error",
                "-x",
                "c",
                "-o",
                str(executable),
                "-",
            ],
            input=harness,
            text=True,
            check=True,
        )
        subprocess.run([str(executable)], check=True)
    print("APA block-size shift passed at i == 31 under UBSan")


if __name__ == "__main__":
    main()
