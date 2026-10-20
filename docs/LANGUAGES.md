# Languages / translations — how they work and how to maintain them

RiptOPL's on-screen text is built from three sources that `tools/lang_compiler.py` merges at
build time. This doc explains the pipeline and the exact steps to add or update strings.

## The pieces

| Piece | What it is | Do you edit it? |
|---|---|---|
| `lng_tmpl/_base.yml` | The fork's **master list** of every string + its **English** text. Source of truth. | **Yes** — add strings here. |
| `lng_fork/<Language>.yml` | The fork's **own translations** of fork strings (and overrides). | **Yes** — add translations here. |
| `lng_src/` (git-ignored) | The **upstream** community translations, cloned from [`ps2homebrew/Open-PS2-Loader-lang`](https://github.com/ps2homebrew/Open-PS2-Loader-lang) by `tools/download_lng.sh`. | **No** — upstream owns these. |
| `tools/lang_compiler.py` | The tool that assembles everything into the binary `.lng` files + the C sources. | No (it's the machinery). |

### `_base.yml` entry format
```yaml
- label: MMCE_PREFIX
  string: MMCE Prefix Path
```

### `lng_fork/<Language>.yml` entry format
```yaml
translations:
  MMCE_PREFIX: Chemin du préfixe MMCE
```

## The build flow (`make languages`, all via `tools/lang_compiler.py`)

1. **`--make_header` / `--make_source`** → generate `include/lang_autogen.h` (the `_STR_*`
   enum every `.c` file uses) and `src/lang_internal.c` (the built-in **English fallback**)
   straight from `_base.yml`. So English is always complete and automatic — you never
   translate English, and a missing translation always falls back to English, never blank.
2. **`--update_translation_yml`** → sync each upstream `lng_src/<Lang>.yml` against
   `_base.yml`; any label it lacks is marked `untranslated`.
3. **`--overlay_translation_yml --overlay lng_fork/<Lang>.yml`** → pour the fork's own
   translations on top. If upstream later translates a label, the overlay quietly steps
   aside (upstream wins). Idempotent — safe to re-run.
4. **`--make_lng`** → compile the merged `.yml` into the binary `lng/lang_<Lang>.lng`.

`lang_autogen.h` and `lang_internal.c` are generated (git-ignored) — never hand-edit them.

## How to ADD a new string

1. Add it to the **END** of `lng_tmpl/_base.yml`, below the APPEND-ONLY banner (~line 923):

   ```yaml
   - label: MY_NEW_SETTING
     string: My New Setting
   ```

   External `lang_*.lng` files are consumed by **line position** (`lang.c`), so inserting a
   label mid-list shifts every later string ID and makes stale user language packs show the
   **wrong text** — never an English fallback.
2. Use `_STR_MY_NEW_SETTING` in code (the enum id is auto-generated).
3. That's enough to ship — it shows English everywhere until translated.

## How to TRANSLATE a string (per language)

Add the key under `translations:` in the target `lng_fork/<Language>.yml`:
```yaml
translations:
  MY_NEW_SETTING: Mon nouveau réglage
```
Repeat per language you want to cover. Untranslated languages fall back to English.

## Important: there is **no auto-translator** in the build

`tools/lang_compiler.py` only *merges* translations that already exist in `lng_fork/*.yml`. The
initial bulk fill of the 31 fork-language overlays was a **one-off external step** (a machine
translation pass), not part of this repo's build. So to keep translations current you must
supply the translated text for `lng_fork/*.yml` yourself (by hand, an external MT tool, or
an assistant) — the build will not invent it.

## Which languages are built, and adding one

The `TRANSLATIONS` list in the `Makefile` decides which `lang_<Language>.lng` files get built. A
language exists upstream as `lng_src/<Language>.yml`; to ship it, add its name to that list.

- **Fonts.** A language that needs glyphs the built-in font lacks has a `font_<Language>.ttf` (or
  `.otf`) in the upstream repo's `thirdparty/` folder. `tools/lng_pack.sh` copies it beside the
  `.lng` in the `RIPTOPL-LANGS` pack, and the loader picks it up from the same folder.
- **Serbian** has no font upstream, and the built-in font has no `č`, `ć` or `đ`. Serbian Latin uses
  exactly Croatian's letters, so `lng_pack.sh` ships `font_Croatian.ttf` as `font_Serbian.ttf`.
  Check a new language's characters against the built-in font before assuming it needs no font.
- **Fork strings.** A language with no `lng_fork/<Language>.yml` (Galician and Serbian today) shows
  the fork's own strings in English until someone adds that file.

## Optional Japanese/CJK game-title font

The full [Unicode Game Titles setup and troubleshooting guide](UNICODE-GAME-TITLES.md) explains enabling the feature, the difference from `LNG/` language fonts, supported names, and limitations.


RiptOPL already decodes UTF-8 in the text renderer. If a Japanese ISO or VCD
filename renders as missing glyphs while the UI is in English, put an
appropriately licensed **TrueType or OpenType font** that contains the needed
Japanese glyphs in the same directory as `settings_riptopl.cfg`, named
`font_CJK.ttf` or `font_CJK.otf`. `font_Japanese.ttf` and
`font_Japanese.otf` are also accepted as fallbacks.

Restart RiptOPL after adding the file. It is read **once at startup**, not
from the game list or while scrolling. This is a *fallback*: the currently
selected interface language and theme fonts retain their glyphs and style.
The existing per-language `font_<Language>.ttf` behavior is unchanged.

**PS2 memory:** use a compact, subsetted font that covers the game-title
characters you need. Unsubsetted CJK font families can consume many megabytes
of the PS2's 32 MiB RAM; an absent/unloadable fallback leaves the normal font
in use. The current glyph atlas is bounded (four 256×256 pages per font), so
extremely large distinct-character libraries can exhaust the atlas. Font
fallback does not convert Shift-JIS filenames; game names must be valid UTF-8
on the storage device.

## Building just the languages

```sh
make languages
```
Requires `python3` + `PyYAML` (`py3-yaml`) and network access for `tools/download_lng.sh` (first
run clones the upstream lang repo into `lng_src/`). CI does this automatically.

## Where the fork strings live

Fork-added strings are the labels in `lng_tmpl/_base.yml` that upstream doesn't have. To
see which are still English-only in a given language, run `make languages` and look for
`untranslated` entries in `lng_src/<Language>.yml` after the overlay step.

## Auditing actual translation coverage

The release builds **33 external languages**, but the fork currently maintains overlays for
**31** of them; Galician and Serbian do not have fork overlays. The upstream
community's older strings remain intact. New fork-only menu labels are **not
automatically translated** and appear in English until a matching overlay
entry is supplied. Packaging 33 complete-length `.lng` files therefore does
**not** mean every string is translated in all 33 languages.

Run `python3 tools/audit_translations.py` to print per-language coverage,
including the most recently appended 60 UI labels; pass `--json` for a
machine-readable report. The tool uses the same translation precedence as
`make languages`, and reads `lng_src/` if `make download_lng` has been
run. Run `python3 tools/audit_translations.py --strict` to reject invalid
format placeholders and obsolete overlay keys without blocking valid
English fallback. CI runs the strict audit on translation and source changes.

To translate recent strings, review the report, add genuinely localized text
to each `lng_fork/<Language>.yml`, and rerun the audit. **Do not mark
untranslated English copies as completed translations**. Preserve all
`%s`, `%d`, `%i` placeholders and keep their order. Inspect the result
on a PS2; a syntactically valid translation can still be confusing, truncated,
or missing font glyphs. Missing status is distinct from broken packaging.

## Installing and selecting language files

From the release matching your ELF, download `RIPTOPL-LANGS-*.zip` and
extract your chosen `lang_<Language>.lng`. Copy its matching
`font_<Language>.ttf` or `font_<Language>.otf` (if included) beside the
language file. Keep the original filenames.

Languages are discovered in this precedence order:

1. **Beside RiptOPL's launched ELF (CWD)**, e.g.
   `mass0:/APPS/APP_RIPTOPL/lang_French.lng`.
2. **CWD/LNG/**, e.g. `mass0:/APPS/APP_RIPTOPL/LNG/lang_French.lng`.
3. **Existing locations**, including `mc0:/OPL/` and each enabled
   device's `LNG/` directory.

The language menu shows a language only once: the higher-priority location
wins when duplicates exist. Scans retry an initially inaccessible boot path
after the storage drivers mount. Language registration grows dynamically rather
than stopping at 15 files. Restart RiptOPL after copying files into folders
already scanned during the current session.

Select **Settings → Interface → Language** (also under General & System
where available), confirm, and **Save Settings**. English is always built
in; missing newer translations fall back to English. Games and OSDSYS keep
their own independent language settings.
