"""Prepare a controlled background comparison from the exact Beta 3608 source.

Both variants suppress per-game BG requests without changing saved settings. The
single-pass variant restores opaque background alpha and disables the duplicate
main1 plate, retaining the released PNG/palette. This is not a production fix.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess

RELEASE = "d41785a6e455637188234d9e3ad9b3a3590a24a2"
BACKGROUND_SHA = "70398bd373ec92cf97e6991cc8db5f76b1ebfce66381b83f69c8bd5c8c698537"


def prepare(root, variant):
    root = Path(root)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != RELEASE:
        raise RuntimeError("Diagnostic requires the exact Beta 3608 Korium source")
    background = root / "gfx/background.png"
    if hashlib.sha256(background.read_bytes()).hexdigest() != BACKGROUND_SHA:
        raise RuntimeError("Unexpected release background; refusing to patch")
    source = root / "src/themes.c"
    text = source.read_text()
    gate = 'cache->suffix != NULL && strcmp(cache->suffix, "BG") == 0 && !gEnableBGArt'
    if text.count(gate) != 1:
        raise RuntimeError("Unexpected BG admission gate")
    configs = [root / "misc" / name for name in ("conf_theme_OPL.cfg", "theme_coverflow.cfg")]
    blocks = []
    for config in configs:
        cfg = config.read_text()
        block = "main1:\n\ttype=StaticImage\n\tdefault=background\n"
        if cfg.count(block) != 1:
            raise RuntimeError("Unexpected background plate in " + str(config))
        blocks.append((config, cfg, block))
    # Keep the released compressed PNG, palette ordering and indices identical.
    # Change only the decoded background alpha, not the general PNG decoder.
    textures = root / "src/textures.c"
    texture_text = textures.read_text()
    clut = "            png_get_tRNS(pngPtr, infoPtr, &pngTexture.trans, &pngTexture.numTrans, NULL);\n"
    if texture_text.count(clut) != 1:
        raise RuntimeError("Unexpected palette conversion")
    # Validate every input before modifying the isolated build checkout.
    if variant == "single-pass":
        texture_text = texture_text.replace(clut, clut +
            "            if (texId == BACKGROUND_PICTURE)\n"
            "                pngTexture.numTrans = 0; // Diagnostic: opaque built-in fallback only.\n")
    source.write_text(text.replace(gate, 'cache->suffix != NULL && strcmp(cache->suffix, "BG") == 0'))
    if variant == "single-pass":
        textures.write_text(texture_text)
        for config, cfg, block in blocks:
            config.write_text(cfg.replace(block, block + "\tenabled=0\n"))
    manifest = (
        "KORIUM BACKGROUND DIAGNOSTIC - NOT A RELEASE\n"
        "Source: " + RELEASE + "\nVariant: " + variant + "\n"
        "Per-game BG lookup: suppressed in both variants; saved setting untouched.\n"
        "Use the built-in OPL or Coverflow theme. External themes are not this comparison.\n"
        "Compare on the same console/display at the same video mode, then repeat in\n"
        "a 24-bit mode (480p or VGA) and a 16-bit mode (720p or 1080i).\n"
        "Control: released two translucent passes. Single-pass: opaque background alpha,\n"
        "duplicate main1 disabled. Grain is retained in both; this isolates composition.\n"
        "The released PNG bytes and palette are identical in both variants.\n"
        "No RA changes from PR 894 are included. No hardware result is claimed.\n"
    )
    (root / "KORIUM-BACKGROUND-DIAGNOSTIC.txt").write_text(manifest)
    print(manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("variant", choices=("control", "single-pass"))
    args = parser.parse_args()
    prepare(args.root, args.variant)
