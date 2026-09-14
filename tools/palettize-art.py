#!/usr/bin/env python3
"""Convert the deployed art to indexed PNG8, per-pattern, per SHELF-PHASE1.md.

    tools/palettize-art.py [--dither riemersma|o8x8|none] [art-dir]

This is the `ps2art.sh` Phase 1 specified and nobody wrote. The art batch on the
card is still CT24/CT32 truecolor, which is why the details page sits at 1.4 MB
of a 1.9 MB pool when Phase 1's own arithmetic says it should sit near 0.6 MB.

  indexed PNG8  ->  GS_PSM_T8 + a 256-entry CLUT   (textures.c:502)

## Re-runnable by construction

Truecolor originals are copied to `_art-truecolor/` on first run and every
conversion is derived from *there*, never from the previous output. Quantising
an already-quantised image compounds error; this cannot, so changing dither mode
is a free re-run rather than a slow degradation.

## Dithering

Only backgrounds have an open question. Everything else is `+dither` and always
was -- dithering costs visible noise on lettering and flat colour and buys
nothing there.

**Dithering does not change VRAM cost.** All three modes produce the same T8
texture and the same CLUT. The choice is purely what it looks like, so it can be
re-decided at any point with no budget consequence.

The default here is `none`. Phase 1 chose Riemersma to avoid banding, reasoning
about a CRT; the display turned out to be a sharp 16:9 flat panel fed 480p
progressive over HDMI, where the opposite risk applies -- a sharp screen resolves
dither noise as grain, and there is no interlace flicker or phosphor bloom to
absorb it. `none` is the conservative choice for that panel. It is a default, not
a verdict: run the other two and look.

## Alpha patterns stay CT32, and Phase 1 was wrong about this

LGO, PANEL and BTN carry genuine antialiased edges -- the LGO originals have
about 10% of their pixels at intermediate alpha, which is the ring around the
lettering. Phase 1 assumed `-colors 255` would preserve that through tRNS, since
tRNS on a palette image *is* a per-entry alpha array. In principle it can. With
the tooling actually on this machine it does not:

  magick ... PNG8:out         -> tRNS with ONE entry: binary transparency,
                                 so the antialiased ring is thrown away and the
                                 logo gets jagged edges on the white/black field
  magick ... -type PaletteAlpha -> no tRNS chunk at all, and the alpha channel
                                 reads back as zero everywhere

The first is a visible quality regression; the second would make the logo
disappear. pngquant, which does emit multi-level tRNS properly, is not installed.

So these three keep their CT32 source. It is close to free: on the details page
the three together cost 172,032 against the 90,112 they would cost as T8 -- about
82 KB out of a 1.9 MB pool, against a pool that has over 1.2 MB spare once the
opaque patterns are converted. Correct edges are worth 82 KB.

The savings that mattered were never here anyway. BG and COVHD are 30 MB of the
42 MB batch; LGO, PANEL and BTN together are under 5 MB.

Revisit if pngquant ever gets installed -- `pngquant --force 255` produces the
multi-level tRNS this needs, and then all three can convert.

## Verification

Every output is checked by reading the IHDR colour type, and the run aborts if
one is not 3. `magick identify -format '%[channels]'` is NOT used: ImageMagick 7
reports `srgb` for a genuine palette PNG, so the recipe Phase 1 documented fails
files that are correct.
"""
import os
import shutil
import struct
import subprocess
import sys

DITHER = "none"
args = sys.argv[1:]
if args and args[0] == "--dither":
    DITHER = args[1]
    args = args[2:]
ART = args[0] if args else "_deploy/ART"
KEEP = "_art-truecolor"

if DITHER not in ("riemersma", "o8x8", "none"):
    raise SystemExit(f"unknown dither mode: {DITHER}")

# Pattern -> (target_w, target_h, mode). This table is the single source of
# truth for both size and format, because keeping them in two places is how a
# resize done by hand gets silently undone by the next quantise pass.
#
# The target is the texel count the element actually *draws*, which is not its
# declared width: GameImage defaults to SCALING_RATIO, and rmSetupQuad computes
# `X_SCALE(w * iAspectWidth) >> 2` -- three quarters of the declared width in
# 16:9. Heights stay at the virtual value rather than the 448/480 the current
# mode scans, so the art does not silently break on another video mode.
#
#   quant  quantise to 256 with the dither policy below
#   exact  build an exact RGBA palette; lossless, for art with alpha
#   keep   leave truecolor
RECIPES = {
    "BG":    (418, 180, "quant"),   # scaled=0, so declared width is drawn width
    "HERO":  (612, 244, "quant"),   # the SHELF Library hero, 640 - SHELF_RAIL_W wide
    "COV":   (None, None, "quant"),  # classic grid; sized by stage-device.sh
    "COVHD": (90,  180, "quant"),   # declared 120, RATIO -> 90
    # The details page's cover, and the reason it is not COVHD: that rect is 108
    # virtual wide, which is 324 PHYSICAL at 1080i, so 90 texels was a 3.6x
    # stretch while the grid beside it upscales 1.65x. 216 brings it to 1.50x.
    # A separate pattern rather than a bigger COVHD because Home caches seven
    # COVHD at a 42-wide rect, where 216 would be a megabyte of VRAM for nothing.
    "COVXL": (216, 432, "quant"),
    "SCR":   (101, 101, "quant"),   # declared 135, RATIO -> 101
    "SCR2":  (101, 101, "quant"),
    "LGO":   (150, 120, "keep"),    # 236 alpha levels; see the docstring
    "PANEL": (96,    4, "exact"),
    "BTN":   (90,   26, "exact"),   # declared 120, RATIO -> 90
}


def ihdr(path):
    d = open(path, "rb").read(26)
    w, h = struct.unpack(">II", d[16:24])
    return w, h, d[24], d[25]


def gsize(w, h, psm):
    """gsKit_texture_size: 256-byte blocks, block counts rounded to 4x8."""
    bw, bh = {"T8": (16, 16), "T4": (32, 16)}.get(psm, (8, 8))
    bx = -(-(-(-w // bw)) // 4) * 4
    by = -(-(-(-h // bh)) // 8) * 8
    return bx * by * 256


def cost(path):
    w, h, bd, ct = ihdr(path)
    if ct == 3:
        return gsize(w, h, "T8" if bd == 8 else "T4") + gsize(16, 16, "CT32")
    return gsize(w, h, "CT32")


if not os.path.isdir(ART):
    raise SystemExit(f"no art dir: {ART}")
os.makedirs(KEEP, exist_ok=True)

files = sorted(f for f in os.listdir(ART) if f.endswith(".png"))
if not files:
    raise SystemExit(f"no PNGs in {ART}")

# Preserve the truecolor originals once. A file already banked is never
# re-banked, so a second run cannot overwrite an original with a palettised one.
banked = 0
for f in files:
    if not os.path.exists(os.path.join(KEEP, f)):
        shutil.copy2(os.path.join(ART, f), os.path.join(KEEP, f))
        banked += 1
if banked:
    print(f"banked {banked} truecolor original(s) into {KEEP}/")

before = after = 0
converted = skipped = 0
per_pattern = {}

for f in files:
    pattern = f.rsplit("_", 1)[-1][:-4]
    recipe = RECIPES.get(pattern)
    src = os.path.join(KEEP, f)          # always from the pristine copy
    dst = os.path.join(ART, f)
    before += cost(src)

    if pattern not in RECIPES:
        print(f"  ?? no recipe for pattern {pattern!r} ({f}) -- left alone")
        after += cost(dst)
        skipped += 1
        continue

    tw, th, mode = recipe
    resize = ["-filter", "Lanczos", "-resize", f"{tw}x{th}!"] if tw else []

    if mode == "keep":
        # Truecolor by choice. Resize from the bank so a re-run cannot compound,
        # and so a hand-made resize cannot be silently undone by this pass.
        subprocess.run(["magick", src, *resize, "-strip", dst], check=True)
        after += cost(dst)
        skipped += 1
        continue

    if mode == "exact":
        # Alpha-bearing: resize here, then hand it to the RGBA palettiser, which
        # is lossless when the image has at most 256 distinct RGBA values and
        # verifies that by decoding its own output.
        subprocess.run(["magick", src, *resize, "-strip", dst], check=True)
        subprocess.run([sys.executable, "tools/palettize-rgba.py", dst],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        dither = ["+dither"]
        if pattern == "BG" and DITHER != "none":
            dither = ["-dither", "Riemersma"] if DITHER == "riemersma" \
                else ["-ordered-dither", "o8x8"]
        subprocess.run([
            "magick", src, *resize, *dither, "-colors", "256",
            "-define", "png:color-type=3", "-define", "png:bit-depth=8",
            "-strip", f"PNG8:{dst}",
        ], check=True)

    w, h, bd, ct = ihdr(dst)
    if ct != 3:
        raise SystemExit(
            f"FAILED: {f} came out colour type {ct}, not 3 (palette).\n"
            f"An RGBA fallback is invisible until VRAM runs out, so this stops here."
        )
    if tw and (w, h) != (tw, th):
        raise SystemExit(f"FAILED: {f} is {w}x{h}, expected {tw}x{th}")
    c = cost(dst)
    after += c
    converted += 1
    p = per_pattern.setdefault(pattern, [0, 0, 0])
    p[0] += 1
    p[1] += cost(src)
    p[2] += c

print(f"\n{converted} converted, {skipped} left alone   "
      f"(backgrounds: dither={DITHER})\n")
print(f"{'pattern':<8} {'n':>3} {'was':>12} {'now':>12} {'saved':>12}")
for pattern in sorted(per_pattern):
    n, b, a = per_pattern[pattern]
    print(f"{pattern:<8} {n:>3} {b:>12,} {a:>12,} {b - a:>12,}")
print(f"{'TOTAL':<8} {converted:>3} {before:>12,} {after:>12,} {before - after:>12,}")
