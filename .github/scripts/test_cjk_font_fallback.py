#!/usr/bin/env python3
"""Host regression for optional glyph fallback without a PS2 toolchain.

Compile the actual face-selection block from src/fntsys.c against small stubs.
This covers the decision made by BOTH text measurement and rendering because
they share fntCacheGlyph(). It does not simulate PS2 glyph atlas/VRAM behavior.
"""
import pathlib
import re
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[2]
font = (root / "src/fntsys.c").read_text(encoding="utf-8")
language = (root / "src/lang.c").read_text(encoding="utf-8")
header = (root / "include/fntsys.h").read_text(encoding="utf-8")
start = "    // Select a second face only for characters missing from the active font."
end = "    // calc page id and in-page index from glyph id"
assert font.count(start) == 1 and font.count(end) == 1
selection = font.split(start, 1)[1].split(end, 1)[0]
assert "FT_Get_Char_Index(font->face, gid) == 0" in selection
assert "FT_Get_Char_Index(fonts[fallbackFontID].face, gid) != 0" in selection
assert "int fntLoadFallback(char *path)" in font
assert "int fntLoadFallback(char *path);" in header
assert "lngInitFallbackFont();" in language
assert "configGetHomePath()" in language
assert "fntLoadDefault(NULL);" in language  # Existing UI-language reset retained.
assert '"font_CJK.ttf"' in language and '"font_Japanese.ttf"' in language

harness = r"""
#include <assert.h>
#include <stdint.h>
#define FNT_DEFAULT 0
#define FNT_MAX_COUNT 16
typedef struct { int isValid; void *face; } font_t;
static font_t fonts[FNT_MAX_COUNT];
static int fallbackFontID = -1;
/* Fake font: 1 = Latin + Japanese; 2 = Japanese + Greek; 3 = Latin. */
static int FT_Get_Char_Index(void *ptr, uint32_t cp)
{
    int face = (int)(intptr_t)ptr;
    if (face == 1) return cp == 0x3042 || cp == 'A';
    if (face == 2) return cp == 0x3042 || cp == 0x03A9;
    if (face == 3) return cp == 'A';
    return 0;
}
static font_t *resolve(font_t *font, uint32_t gid)
{
""" + start + selection + """
    return font;
}
int main(void)
{
    fonts[0] = (font_t){1, (void *)(intptr_t)3}; /* Default Latin UI font. */
    fonts[1] = (font_t){1, (void *)(intptr_t)2}; /* Optional fallback. */
    fallbackFontID = 1;
    assert(resolve(&fonts[0], 0x3042) == &fonts[1]); /* Japanese. */
    assert(resolve(&fonts[0], 0x03A9) == &fonts[1]); /* Greek. */
    assert(resolve(&fonts[0], 'A') == &fonts[0]); /* Never steal ASCII. */
    assert(resolve(&fonts[1], 0x3042) == &fonts[1]); /* No recursion. */
    fonts[2] = (font_t){1, (void *)(intptr_t)1};
    assert(resolve(&fonts[2], 0x3042) == &fonts[2]); /* Keep active face. */
    fonts[1].isValid = 0;
    assert(resolve(&fonts[0], 0x3042) == &fonts[0]); /* Safe if unavailable. */
    fallbackFontID = -1;
    assert(resolve(&fonts[0], 0x3042) == &fonts[0]); /* Safe if absent. */
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="cjk-font-test-") as td:
    source = pathlib.Path(td) / "fallback.c"
    binary = pathlib.Path(td) / "fallback"
    source.write_text(harness, encoding="utf-8")
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-o", str(binary), str(source)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
print("PASS: CJK fallback is opt-in, font-preserving and selected only for missing Unicode glyphs")
