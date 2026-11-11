#!/usr/bin/env python3
"""The PSBBN Flow and Grid position counters ("N/M") are drawn without a clip box.

#287 (zackcage6): the PSBBN Flow counter showed as "1/". Both counters measured the text, then drew it
with that same measured width as the clip box. fntRenderString scales the box back to display pixels
and drops any glyph whose bitmap crosses it, so a pixel lost in rounding (overscan) or a weighted
glyph wider than its advance cut the last digits. The fix draws the counter with width 0 (no clip);
the measured width is still used to right-align it.

This checks the source: every fntRenderString of a counter passes width 0.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "src/gfx/psbbnflow.cpp", ROOT / "src/gfx/grid.cpp", ROOT / "src/themes.c"]


def main():
    seen = 0
    for src in SOURCES:
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        for m in re.finditer(r"fntRenderString\(([^;]*?)\bcounter, gTheme->textColor\);", text, re.S):
            args = [a.strip() for a in m.group(1).split(",") if a.strip()]
            # id, x, y, aligned, width, height, then the string
            width = args[4] if len(args) >= 6 else None
            seen += 1
            if width != "0":
                line = text.count("\n", 0, m.start()) + 1
                print(f"FAIL: {src.relative_to(ROOT)}:{line} draws the counter clipped to width {width!r}")
                sys.exit(1)
    if seen < 2:
        print(f"FAIL: expected the PSBBN Flow and Grid counters, found {seen} counter draws; update this test")
        sys.exit(1)
    print(f"PASS: {seen} position counters drawn unclipped")


if __name__ == "__main__":
    main()
