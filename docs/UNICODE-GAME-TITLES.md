# Unicode and Japanese game titles

RiptOPL can render UTF-8 game names in Japanese and other Unicode scripts without changing the interface language. **CJK glyph fallback is optional**: the selected theme/translation fonts remain in use, and a secondary font is consulted only when the active font lacks a character.

## Enable it

1. Use a RiptOPL build that includes the Unicode fallback introduced in [PR #917](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/917). Older ELFs do not use the fallback file.
2. Obtain a legitimately licensed, preferably subsetted Japanese-capable **TTF or OTF** font. The font itself is **not included** in this feature or its ELF artifacts.
3. Name it **`font_CJK.ttf`** (preferred), **`font_CJK.otf`**, **`font_Japanese.ttf`**, or **`font_Japanese.otf`**. These names are tried in that order, and only the first successfully loaded font is used.
4. Place it **directly in RiptOPL's settings home**: the same directory containing `settings_riptopl.cfg` (or the directory where RiptOPL saves that file). Do **not** put it only in `LNG/` if you want fallback with the English UI.
5. Completely restart RiptOPL. **There is no Settings toggle**: finding the font at startup enables fallback automatically.
6. Use UTF-8 game filenames/titles for the Unicode characters to appear. No rename is necessary if a filename is already valid UTF-8.

Example with RiptOPL installed on the memory card:

```text
mc0:/APPS/APP_RIPTOPL/
  RIPTOPL.ELF
  settings_riptopl.cfg
  font_CJK.ttf
```

The example is illustrative. Your installation may use another path, including another memory card, USB or HDD. Follow the actual **settings file**, not a fixed `mc0:` assumption. If your RiptOPL installation loads settings from a different location, place the font beside that settings file.

### Distinct from interface translation fonts

The `RIPTOPL-LANGS` ZIP contains translated `.lng` files and matching fonts such as `LNG/font_Japanese.ttf`. Those fonts support the **Japanese UI language** when that language is selected in **Settings → Interface → Language**. A fallback font in the settings home is different: it works while **English remains selected**, and also while a custom theme is active. You can copy a suitable, appropriately licensed font from a language pack into the settings home and rename it `font_CJK.ttf`; the copy does not replace your language pack.

### What it supports

- UTF-8 titles on ISO/ZSO/VCD game lists and other text already supplied to RiptOPL's Unicode renderer, with mixed English/Japanese characters.
- Font fallback for built-in, language-pack and theme fonts that lack the relevant glyphs.
- No changes to disc/startup ID, game filename, art lookup, launch path, VMC, or favorites identity.

### Current limits

- This does **not** translate game names automatically or convert Shift-JIS / legacy code-page filenames into UTF-8.
- Per-game `CFG/<game-id>.cfg` `Title` metadata can already appear as **theme AttributeText**, but it **does not override the game-list row**. Display-only overrides are tracked separately in [issue #918](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/918). **Do not modify `#Name` to force a translation**; it is device-derived metadata tied to game identity.
- The optional font consumes PS2 EE RAM; very large Japanese fonts may exhaust memory. Prefer a font subset covering characters in your collection. Font glyph caches are capped at four 256×256 texture atlas pages **per font**, so very large libraries with many unique glyphs can exceed the cache capacity.
- The font is loaded only on startup, not per frame. Adding or changing it requires a full restart.
- Builds and host tests do not substitute for hardware testing; keep a backup known-good ELF, settings and save cards before updating.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| English text works but Japanese becomes boxes | Confirm a Japanese-capable TTF/OTF is named exactly as above and placed beside `settings_riptopl.cfg`; restart fully. |
| Japanese interface works, English interface does not show Japanese game names | Your `LNG/font_Japanese.ttf` applies to the selected Japanese UI only; copy a suitable font to the settings home as `font_CJK.ttf`. |
| Name displays garbage rather than boxes | Verify the original filename bytes are valid UTF-8. This feature is not Shift-JIS transcoding. |
| Some Kanji work, others do not | Check font glyph coverage and the fixed atlas budget; consider a more appropriate font subset. |
| Font works with one installation but not another | Check which directory holds the active `settings_riptopl.cfg`. It can change with your boot/install location. |
| A custom CFG `Title` doesn't change the game-list name | Expected in the current version; see [issue #918](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/918). |

### Development and testing

See [Languages](LANGUAGES.md), [Interface](INTERFACE.md) and [Testing a PR artifact](TEST-BUILDS.md). The optional glyph fallback is implemented in `src/fntsys.c` and loaded by `src/lang.c`; `.github/scripts/test_cjk_font_fallback.py` tests the face-selection logic. [PR #917](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/917) provides the implementation history and verified build matrix. For a test build, use the artifact from the PR's matching GitHub Actions run, not an unrelated rolling release.
