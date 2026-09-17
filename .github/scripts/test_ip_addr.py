#!/usr/bin/env python3
"""Compile both ministack IP_ADDR definitions with boundary UBSan coverage."""

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HEADERS = (
    ("ministack.h", ROOT / "modules/network/smap_udpbd/src"),
    ("ministack_ip.h", ROOT / "modules/network/udpfs_ministack/include"),
)


def main():
    for header, include_dir in HEADERS:
        harness = f"""
#include <stdint.h>
#include "{header}"
_Static_assert(IP_ADDR(255, 255, 255, 255) == UINT32_C(0xffffffff),
               "IP_ADDR must construct the full uint32_t range");
int main(void)
{{
    volatile uint32_t broadcast = IP_ADDR(255, 255, 255, 255);
    volatile uint32_t loopback = IP_ADDR(127, 0, 0, 1);
    volatile uint32_t masked = IP_ADDR(0x1ff, 0x100, -1, 0x101);
    if (broadcast != UINT32_C(0xffffffff)) return 1;
    if (loopback != UINT32_C(0x7f000001)) return 2;
    if (masked != UINT32_C(0xff00ff01)) return 3;
    return 0;
}}
"""
        with tempfile.TemporaryDirectory(prefix="opl-ip-addr-") as directory:
            executable = Path(directory) / "test"
            subprocess.run(
                [
                    "cc",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fsanitize=undefined",
                    "-fsanitize-undefined-trap-on-error",
                    "-I",
                    str(include_dir),
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
        print(f"IP_ADDR boundary vectors and UBSan passed: {header}")


if __name__ == "__main__":
    main()
