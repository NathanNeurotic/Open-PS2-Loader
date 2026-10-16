#!/usr/bin/env python3
"""Source-wiring regression checks for the per-game _LGO artwork toggle."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class LogoArtToggle(unittest.TestCase):
    def test_default_enabled_and_persistence(self):
        opl = source("src/opl.c")
        config = source("include/config.h")
        self.assertIn('CONFIG_OPL_ENABLE_LOGOART             "enable_logoart"', config)
        self.assertIn("gEnableLogoArt = 1;", opl)
        self.assertIn("configGetInt(configOPL, CONFIG_OPL_ENABLE_LOGOART, &gEnableLogoArt)", opl)
        self.assertIn("configSetInt(configOPL, CONFIG_OPL_ENABLE_LOGOART, gEnableLogoArt)", opl)

    def test_artwork_ui_reads_and_writes_toggle(self):
        dialogs = source("src/dialogs.c")
        gui = source("src/gui.c")
        self.assertIn("UICFG_ENABLE_LOGOART, 1, 1, _STR_HINT_LOGOART", dialogs)
        self.assertIn("_STR_LOGOART", dialogs)
        self.assertIn("diaSetInt(diaArtworkConfig, UICFG_ENABLE_LOGOART, gEnableLogoArt)", gui)
        self.assertIn("diaGetInt(diaArtworkConfig, UICFG_ENABLE_LOGOART, &gEnableLogoArt)", gui)

    def test_logo_and_disc_art_guarded_at_cache_and_draw_sites(self):
        themes = source("src/themes.c")
        self.assertIn('!gEnableDiscArt && strcmp(cache->suffix, "ICO") == 0', themes)
        self.assertIn('!gEnableLogoArt && strcmp(cache->suffix, "LGO") == 0', themes)
        self.assertIn("if (isHiddenArtworkCache(cache))", themes)
        self.assertIn("if (isHiddenArtworkCache(gameImage->cache))", themes)
        self.assertIn("if (!cimg || isHiddenArtworkCache(cimg->cache))", themes)
        self.assertGreaterEqual(themes.count("!isHiddenArtworkCache(itemsList->decoratorImage->cache)"), 3)
        self.assertNotIn("isDiscArtCache(", themes)

    def test_language_ids_are_appended(self):
        labels = source("lng_tmpl/_base.yml")
        self.assertLess(labels.index("- label: NEUTRINO_DVR_FILE_MISSING"), labels.index("- label: LOGOART"))
        self.assertLess(labels.index("- label: LOGOART"), labels.index("- label: HINT_LOGOART"))


if __name__ == "__main__":
    unittest.main()
