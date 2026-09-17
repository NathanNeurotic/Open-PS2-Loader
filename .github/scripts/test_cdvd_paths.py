#!/usr/bin/env python3
"""Compile cdrom_preparePath and exercise its fixed-buffer boundaries."""

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIGNATURE = "static int cdrom_preparePath(char *path, size_t capacity, const char *source)"


def extract_function(source):
    start = source.index(SIGNATURE)
    opening = source.index("{", start)
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[start : offset + 1]
    raise ValueError("unterminated cdrom_preparePath")


def main():
    source = (ROOT / "modules/iopcore/cdvdman/ioops.c").read_text(encoding="utf-8")
    function = extract_function(source)
    harness = f"""
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <string.h>
{function}

static void make_source(char *source, size_t length, int suffix)
{{
    memset(source, 'A', length);
    if (suffix == 1)
        source[length - 1] = ';';
    else if (suffix == 2) {{
        source[length - 2] = ';';
        source[length - 1] = '1';
    }}
    source[length] = '\\0';
}}

static void check_case(size_t length, int suffix, int succeeds)
{{
    char source[132];
    unsigned char output[130];
    size_t expected_length = length;
    int result;

    make_source(source, length, suffix);
    memset(output, 0xa5, sizeof(output));
    result = cdrom_preparePath((char *)output, 128, source);
    if (!succeeds) {{
        assert(result == -ENAMETOOLONG);
        for (size_t i = 0; i < sizeof(output); i++)
            assert(output[i] == 0xa5);
        return;
    }}

    assert(result >= 0);
    if (length >= 3 && suffix == 0)
        expected_length += 2;
    else if (length >= 3 && suffix == 1)
        expected_length += 1;
    assert(strlen((char *)output) == expected_length);
    assert(output[expected_length] == '\\0');
    assert(output[128] == 0xa5 && output[129] == 0xa5);
    if (length >= 3) {{
        assert(output[expected_length - 2] == ';');
        assert(output[expected_length - 1] == '1');
    }}
}}

int main(void)
{{
    check_case(0, 0, 1);
    check_case(1, 0, 1);
    check_case(2, 0, 1);
    check_case(3, 0, 1);
    for (size_t length = 124; length <= 130; length++) {{
        check_case(length, 0, length <= 125);
        check_case(length, 1, length <= 126);
        check_case(length, 2, length <= 127);
    }}
    return 0;
}}
"""
    with tempfile.TemporaryDirectory(prefix="opl-cdvd-path-") as directory:
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
    print("CD/DVD path capacity cases 124-130 passed with sentinels and UBSan")


if __name__ == "__main__":
    main()
