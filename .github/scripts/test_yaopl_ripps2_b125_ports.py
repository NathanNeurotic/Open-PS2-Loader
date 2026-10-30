#!/usr/bin/env python3
"""Host regression test for the YAOPL / RIPPS2 build 125 ports.

1. About page: the version and build options are passed as literals, never through a 40-byte buffer (YAOPL 9847f4ca).
2. findDuplicate never shares a cache between an AttributeImage and game art (YAOPL cc3d59f0).
3. A Colours change reaches every screen's text, not only the main list (YAOPL d21b3bc5).
4. A Background keeps its last game art while the next one loads (YAOPL 2bc4d161).
5. The boot greeting waits, bounded, for the saved disk theme's drive (RIPPS2 build 125, 14adac2).
"""
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[2]
read = lambda p: (root / p).read_text(encoding="utf-8")

gui = read("src/gui.c")
body = gui[gui.index("void guiShowAbout()") :]
body = body[: body.index("diaExecuteDialog")]
assert "char OPLVersion[" not in body and "char OPLBuildDetails[" not in body, "About still formats into fixed buffers"
assert 'diaSetLabel(diaAbout, ABOUT_TITLE, "Open PS2 Loader " OPL_VERSION);' in body
assert '" - IGS " IGS_VERSION' in body and '"GSM " GSM_VERSION' in body

elems = read("src/themes.c")
fd = elems[elems.index("static void findDuplicate(") :]
fd = fd[: fd.index("\n}\n")]
assert "(type == ELEM_TYPE_ATTRIBUTE_IMAGE) == (elem->type == ELEM_TYPE_ATTRIBUTE_IMAGE)" in fd, "cache sharing must be same-kind only"
calls = re.findall(r"findDuplicate\(theme->\w+\.first, (\w+),", elems)
assert calls and all(c == "type" for c in calls), calls
assert "int type, const char *cachePattern" in read("src/themes.c")

themes = read("src/themes.c")
sc = themes[themes.index("static void thmSetColors(theme_t *theme)") :]
sc = sc[: sc.index("\n}\n")]
for g in ("infoElems", "appsMainElems", "appsInfoElems", "favsMainElems", "favsInfoElems", "vcdMainElems",
          "vcdInfoElems", "favsVcdMainElems", "favsVcdInfoElems", "favsAppsMainElems", "favsAppsInfoElems"):
    assert "&theme->" + g in sc, "colour change misses " + g
rf = themes[themes.index("static void thmRecolorFollowers(") :]
rf = rf[: rf.index("\n}\n")]
assert "ELEM_TYPE_BACKGROUND" in rf and "continue;" in rf, "images keep their colour"
assert "elem->color == oldText" in rf, "theme-set colours are left alone"

assert "texture = holdLastBackground(gameImage, menu, &item->item, texture);" in elems
hb = elems[elems.index("static GSTEXTURE *holdLastBackground(") :]
hb = hb[: hb.index("\n}\n")]
assert "cacheLookupTexture(cache, &lastId, &lastUid)" in hb, "the kept art must be revalidated against the cache"
assert "!gEnableBGArt" in hb and "!gEnableArt" in hb, "art switched off holds nothing"
assert "state >= 0 || (state == -1" in hb, "known-absent art (-2/-3) draws the default"
assert "mutableImage->lastCacheId = -1;" in elems

splash = read("src/gui.c")
assert "#define THEME_HOLD_MS 6000" in splash
assert "thmSavedThemePending()" in splash and "(clock() - tInitDone) <" in splash, "the hold must be bounded"
pend = themes[themes.index("int thmSavedThemePending(void)") :]
pend = pend[: pend.index("\n}\n")]
assert "temp[0] == '<'" in pend, "built-in themes never hold the boot"

print("PASS: YAOPL About/theme fixes, Background hold and the RIPPS2 boot theme hold are in place")
