#!/usr/bin/env python3
"""On-screen keyboard keys are drawn as readable keycaps (src/dia.c).

zackcage6 (2026-11-09): the rename / IGR-path keyboard's letters and specials could not be seen and
'.' looked like an empty space. The key grid drew bare glyphs in uiTextColor (default 0x5868B4, a dim
blue under the darkened background) with a selection box only as wide as the glyph.

This checks the source, not a console: every key of the grid goes through diaDrawKeyCap, the key
glyphs use the theme's text colour, and the cap geometry the source declares keeps caps inside the
grid (no overlap between neighbours or rows, the last column clear of the command icons at x=436).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/dia.c"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def const(text, name):
    m = re.search(r"(?:constexpr int %s = |#define %s\s+)(\d+)" % (name, name), text)
    if not m:
        fail(f"{name} not declared")
    return int(m.group(1))


def main():
    text = SRC.read_text(encoding="utf-8")

    helper = re.search(r"static void diaDrawKeyCap\(.*?\n}\n", text, re.S)
    if not helper:
        fail("diaDrawKeyCap missing")
    body = helper.group(0)
    if "uiTextColor" in body:
        fail("key glyphs must not use uiTextColor")
    if body.count("label, colour)") < 2:
        fail("key glyph is not drawn twice in the colour it is given")
    if "ALIGN_HCENTER" not in body:
        fail("key glyph is not centred in its cap")

    keyb = re.search(r"int diaShowKeyb\(.*?\n}\n", text, re.S).group(0)
    grid = re.search(r"for \(j = 0; j < KEYB_HEIGHT; j\+\+\) \{(.*?)\n        \}\n", keyb, re.S)
    if not grid:
        fail("keyboard grid loop not found")
    g = grid.group(1)
    if "diaDrawKeyCap(" not in g or "gTheme->textColor)" not in g:
        fail("keyboard grid does not draw keycaps in the theme text colour")
    if "uiTextColor" in g or "diaDrawBoundingBox" in g:
        fail("keyboard grid still draws bare uiTextColor glyphs or the glyph-width box")

    m = re.search(r"diaDrawKeyCap\((\d+) \+ i \* KEYB_PITCH, (\d+) \+ 3 \* UI_SPACING_H \* j", g)
    if not m:
        fail("keycap position expression changed; update this test")
    x0, y0 = int(m.group(1)), int(m.group(2))
    pitch, cap_w, cap_h = const(text, "KEYB_PITCH"), const(text, "KEYB_CAP_W"), const(text, "KEYB_CAP_H")
    width, height = const(text, "KEYB_WIDTH"), const(text, "KEYB_HEIGHT")
    # UI_SPACING_H lives in include/diaint.h (RiptOPL) or src/dia.c (OPL); read it from either.
    header = ROOT / "include/diaint.h"
    spacing_src = text + (header.read_text(encoding="utf-8") if header.exists() else "")
    row_pitch = 3 * const(spacing_src, "UI_SPACING_H")

    if cap_w >= pitch:
        fail(f"caps overlap horizontally: width {cap_w} >= pitch {pitch}")
    if cap_h >= row_pitch:
        fail(f"caps overlap vertically: height {cap_h} >= row pitch {row_pitch}")
    right = x0 + (width - 1) * pitch + cap_w
    if right >= 436:
        fail(f"last column ends at {right}, into the command icons at 436")
    top, bottom = y0, y0 + (height - 1) * row_pitch + cap_h
    if top <= 138 or bottom >= 417:
        fail(f"grid {top}..{bottom} crosses the text separator (138) or the footer (417)")

    cmd = re.search(r"// Commands\n(.*?)\n        \}\n", keyb, re.S)
    if not cmd or "uiTextColor" in cmd.group(1) or "commands[i], gTheme->textColor)" not in cmd.group(1):
        fail("the command column does not draw its labels in the theme text colour")
    pad = re.search(r"int diaShowNumPad\(.*?\n}\n", text, re.S).group(0)
    if "diaDrawKeyCap(" not in pad or "u64 col = gTheme->textColor;" not in pad:
        fail("the number pad does not draw keycaps in the text colour")

    print(f"PASS: keyboard and number pad keys are keycaps in the text colour, commands too; grid x {x0}..{right}, y {top}..{bottom}")


if __name__ == "__main__":
    main()
