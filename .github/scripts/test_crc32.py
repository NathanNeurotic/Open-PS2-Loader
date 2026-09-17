#!/usr/bin/env python3
"""Compile the three UL CRC implementations with UBSan and run known vectors."""

import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATIONS = (
    ("pc/iso2opl/src/iso2opl.c", "uint32_t crc32(const char *string)", "crc32", False),
    ("pc/opl2iso/src/opl2iso.c", "uint32_t crc32(const char *string)", "crc32", False),
    ("src/system.c", "u32 USBA_crc32(const char *string)", "USBA_crc32", True),
)


def extract_function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[start : offset + 1]
    raise ValueError(f"unterminated function: {signature}")


def test_implementation(relative, signature, function_name, bounded):
    source = (ROOT / relative).read_text(encoding="utf-8")
    table = re.search(r"^(?:static )?(?:u32|uint32_t) crctab\[0x400\];$", source, re.MULTILINE)
    if table is None:
        raise ValueError(f"CRC table declaration not found in {relative}")
    function = extract_function(source, signature)
    bounded_vector = (
        f'if ({function_name}("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") '
        f'!= UINT32_C(0x280AF065)) return 5;'
        if bounded
        else
        f'if ({function_name}("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") '
        f'!= UINT32_C(0xF25611F7)) return 5;'
    )
    harness = f"""
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint32_t u32;
{table.group(0)}
{function}
int main(void)
{{
    const char high_bytes[] = {{(char)0xff, (char)0x80, '\\0'}};

    if ({function_name}("") != UINT32_C(0x00000000)) return 1;
    if ({function_name}("123456789") != UINT32_C(0xEA4C6FE1)) return 2;
    if ({function_name}("Open PS2 Loader") != UINT32_C(0x45E5C9C1)) return 3;
    if ({function_name}(high_bytes) != UINT32_C(0x35A0C1E5)) return 4;
    {bounded_vector}
    return 0;
}}
"""
    with tempfile.TemporaryDirectory(prefix="opl-crc32-") as directory:
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
    print(f"CRC vectors and UBSan passed: {relative}")


def main():
    for implementation in IMPLEMENTATIONS:
        test_implementation(*implementation)


if __name__ == "__main__":
    main()
