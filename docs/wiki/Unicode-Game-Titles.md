# Unicode / Japanese Game Titles

**RiptOPL supports optional Unicode/CJK fallback for game-name rendering.** You can leave the interface in English and still display Japanese game names, provided their filenames are valid UTF-8 and you supply a font that contains the required characters.

## Activate it

1. Install a build containing [CJK font fallback PR #917](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/917).
2. Put a properly licensed, preferably subsetted Japanese-capable font in the **same folder as `settings_riptopl.cfg`**. Call it `font_CJK.ttf` (or `font_CJK.otf`, `font_Japanese.ttf`, `font_Japanese.otf`).
3. Restart RiptOPL. No menu toggle is needed; fallback is enabled automatically if the font successfully loads.

Example: `mc0:/APPS/APP_RIPTOPL/font_CJK.ttf` beside `mc0:/APPS/APP_RIPTOPL/settings_riptopl.cfg`. Your own settings home might be elsewhere. The optional font is **not included** in the ELF artifact.

**Important:** `LNG/font_Japanese.ttf` is used when the Japanese *interface language* is selected; for Japanese game titles with English menus, install a **copy beside the settings file** as `font_CJK.ttf`.

This does not change the game's filename, launch ID, or artwork identity. It does not convert Shift-JIS to UTF-8, translate titles automatically, or use per-game CFG `Title` as a game-list override (tracked in [#918](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/918)). Large, unsubsetted CJK fonts use significant PS2 RAM and the glyph atlas has a limited capacity.

Full setup, limitations and troubleshooting: [Unicode Game Titles guide](https://nathanneurotic.github.io/Open-PS2-Loader/unicode-titles.html) / [source reference](https://github.com/NathanNeurotic/Open-PS2-Loader/blob/rebuild/main/docs/UNICODE-GAME-TITLES.md).

PR #917 [tested build artifact (OFFICIALROLLING)](https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/38251591567/artifacts/11747219931) (GitHub sign-in may be required; artifacts expire). [Merged setup website](https://nathanneurotic.github.io/Open-PS2-Loader/unicode-titles.html).
