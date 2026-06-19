# OPL Theme Engine — Authoring Reference

This document describes the Open PS2 Loader theme format **as implemented by the parser**
(`src/themes.c`), so you can build your own themes. It covers every block type, property,
value token, and built-in asset name the engine understands, including this fork's
**`Coverflow`** render mode.

- A theme is a folder in the `THM` directory containing a **`conf_theme.cfg`** plus its
  image/font assets.
- Anything not supplied by the theme falls back to OPL's embedded defaults.
- OPL also ships two built-in themes you can study as references: the default `<OPL>` theme
  and this fork's `<Coverflow>` theme.

> Quick mental model: a theme is a flat list of **elements**, each positioned on a virtual
> **640×480** canvas. OPL scales that canvas to the real screen, and (with `scaled=1`)
> corrects for widescreen and the PS2's non-square pixels automatically.

---

## 1. File structure

`conf_theme.cfg` is a plain key/value file. Two kinds of lines exist:

- **Global (top-level) properties** — `key=value` at the start of the file.
- **Element blocks** — a `blockname:` line followed by indented `key=value` lines.

```ini
# lines starting with '#' are comments
bg_color=#182580          ; a global property

main0:                    ; an element block
	type=Background
	pattern=BG
```

Internally, a block property `foo` under block `main0` is read as the key `main0_foo`. You'll
mostly just write the indented form above.

### Block families

| Family | Drawn on | Notes |
|---|---|---|
| `main0`, `main1`, `main2`, … | The **game/app list** screen | The main browser layout. |
| `appsMain0`, `appsMain1`, … | The **apps** screen | Per-slot **override** of `mainN`. If `appsMainN` is absent for a slot, the matching `mainN` is used. |
| `info0`, `info1`, … | The **game info** screen | The details/metadata page. (`appsInfoN` overrides per slot, same as above.) |

### ⚠ Contiguous numbering rule

The parser reads blocks **in order starting from 0 and stops at the first gap.** If you define
`main0`, `main1`, `main3` (skipping `main2`), then `main3` is **never read**. When you remove
a block, **renumber** the ones after it so there are no holes.

---

## 2. Global properties

Put these at the top of the file (not inside a block).

### Colors (`#RRGGBB`)

| Key | Applies to |
|---|---|
| `bg_color` | Plasma/background tint |
| `text_color` | Default element text |
| `ui_text_color` | UI text (menus, buttons, hints) |
| `sel_text_color` | Selected-item text |

Colors are 8-bit-per-channel hex; alpha is fixed internally.

### Fonts

| Key | Value | Notes |
|---|---|---|
| `default_font` | font file path | Theme's main font; falls back to the built-in font if missing. |
| `font1` … `font15` | font file path | Extra fonts; each defaults to `default_font` if not set. |
| `default_font_size` | int (px) | Size for the default font. |
| `font1_size` … `font15_size` | int (px) | Per-font sizes. |

Reference a font from an element with `font=N` (0 = default). Use `font1=builtin` to force the
embedded font for a slot.

### Other global keys

| Key | Value | Meaning |
|---|---|---|
| `coverflow_cover_offset` | int (−1024…1024, default 0) | Horizontal nudge for the Coverflow carousel (see §8). |
| `use_default` | 0/1 | Use OPL's embedded default assets for anything the theme omits. |
| `use_real_height` | 0/1 | Lay out against the real screen height instead of 480. |
| `use_settings_bg` | 0/1 | Load the theme's `settings_bg.png` behind the settings menus. |

---

## 3. Common element properties

Every element block starts with `type=<ElementType>` (see §5). Most also accept these:

| Property | Type | Default | Notes |
|---|---|---|---|
| `x` | int or `POS_MID` | element-specific | Negative = measured from the **right** edge. `POS_MID` = horizontal center. |
| `y` | int or `POS_MID` | element-specific | Negative = measured from the **bottom** edge. `POS_MID` = vertical center. |
| `width` | int or `DIM_INF` | element-specific | `DIM_INF` = full screen width. |
| `height` | int or `DIM_INF` | element-specific | `DIM_INF` = full screen height. |
| `aligned` | `0` / `1` | element-specific | `0` = anchor top-left, `1` = center on (x, y). |
| `scaled` | `0` / `1` | element-specific | `0` = raw pixels, `1` = ratio-correct (handles widescreen + pixel-aspect). Use `1` for images you want undistorted. |
| `color` | `#RRGGBB` | `text_color` | Text/tint color. |
| `font` | `0`…`15` | `0` | Font index (see §2). |
| `reflection` | `0` / `1` | `0` | Draw a mirrored reflection beneath the element (used by `Coverflow`). |
| `enabled` | `0` / `1` | `1` | Set `0` to skip the element without deleting the block. |

**Value tokens:** `POS_MID`, `DIM_INF` (above), and `#RRGGBB` for colors. `x`/`y` accept
negative numbers for right/bottom-relative placement.

---

## 4. Image & overlay properties

Image-type elements (`StaticImage`, `GameImage`, `Background`, `AttributeImage`, `ItemCover`,
`Coverflow`) add:

| Property | Type | Notes |
|---|---|---|
| `default` | asset name | The image to draw (built-in name from §7, or a file in the theme folder). |
| `pattern` | cache suffix | For dynamic art: `COV` (cover), `SCR`/`SCR2` (screenshots), `ICO`, `DISC`, … |
| `count` | int | Number of cache slots for `pattern` (min 2 for `COV`). |
| `overlay` | asset name | An optional frame drawn over the image (e.g. a case/bezel). |
| `overlay_ulx`,`overlay_uly` | int | Upper-left corner of the inlaid image inside the overlay. |
| `overlay_urx`,`overlay_ury` | int | Upper-right corner. |
| `overlay_llx`,`overlay_lly` | int | Lower-left corner. |
| `overlay_lrx`,`overlay_lry` | int | Lower-right corner. |

The overlay corners describe where the *inner* art sits within the overlay frame, in the
element's own coordinate space (i.e. relative to `width`/`height`). They scale with the drawn
element, so the window tracks the art at any size.

---

## 5. Element types

Set with `type=`. Elements marked **item** redraw when you move the selection.

| `type=` | Renders |
|---|---|
| `Background` | Full-screen background (`pattern=BG`, or a `default=` image). Auto-added if you omit it. |
| `StaticImage` | A fixed image from `default=`. |
| `StaticText` | Fixed text from `value=`. |
| `AttributeText` *(item)* | Game metadata text — see `attribute=` in §6. |
| `GameCountText` *(item)* | The number of items in the current list. |
| `GameImage` *(item)* | Dynamic art from `pattern=` (cover/screenshot/…) with `default=` fallback. |
| `AttributeImage` *(item)* | Badge image chosen by a game attribute — see §6. |
| `MenuIcon` | The current device/menu icon. |
| `MenuText` | The current menu name with left/right arrows. |
| `ItemsList` *(item)* | The scrolling list of games/apps. (Auto-added if omitted.) |
| `ItemIcon` *(item)* | Per-row decorator icons (uses the list's `decorator=` pattern). |
| `ItemCover` *(item)* | The selected item's cover, with optional `overlay`. |
| `ItemText` *(item)* | The selected item's startup filename. |
| `HintText` | Button hints for the list screen. |
| `InfoHintText` | Button hints for the info screen. |
| `LoadingIcon` | The animated loading spinner. |
| `BdmIndex` | The block-device mode indicator. |
| `Coverflow` *(item)* | **This fork:** a cover-art carousel (see §8). |

### Text element extras

| Property | Used by | Notes |
|---|---|---|
| `value` | `StaticText` | The literal string to show. |
| `attribute` | `AttributeText`, `AttributeImage` | The metadata key (§6). |
| `display` | text | `0` = always (label + value), `1` = only when the value exists, `2` = value only (no label). |
| `wrap` | text | `1` = word-wrap within `width`/`height`. |
| `title` | `AttributeText` | Override the auto label for the attribute. |

### List extras

| Property | Used by | Notes |
|---|---|---|
| `decorator` | `ItemsList` | A `GameImage` pattern name to draw as per-row icons. |

---

## 6. `attribute=` values

### AttributeText (metadata text)

`Title`, `Developer`, `Description`, `Genre`, `Release`, `#Size` (the `#Size` value renders
with a `MiB` suffix). Labels are auto-localized; override with `title=`.

### AttributeImage (badge chosen by value)

The engine looks up an image named `<attribute>_<value>` (built-in or theme file):

| `attribute=` | Looks up | Examples |
|---|---|---|
| `Media` | `Media_<v>` | `Media_CD`, `Media_DVD`, `Media_APP` |
| `Format` | `Format_<v>` | `Format_ISO`, `Format_ELF`, `Format_HDL` |
| `Vmode` | `Vmode_<v>` | `Vmode_ntsc`, `Vmode_pal`, `Vmode_multi` |
| `Aspect` | `Aspect_<v>` | `Aspect_s`, `Aspect_w`, `Aspect_w1`, `Aspect_w2` |
| `Scan` | `Scan_<v>` | `Scan_480i`, `Scan_480p`, `Scan_720p`, `Scan_1080i`, … |
| `Players` | `Players_<v>` | `Players_1`, `Players_2`, … |
| `Rating` | `Rating_<v>` | `Rating_0` … `Rating_5` |

---

## 7. Built-in `default=` asset names

You can point `default=`/`overlay=` at any of OPL's embedded textures (no file needed):

- **Covers / art:** `cover`, `coverapp`, `disc`, `screen`, `screens` (overlay), `missing`
- **Case overlays:** `case` (games), `apps_case` (apps)
- **Device icons:** `usb`, `mmce`, `hdd`, `eth`, `app`, `usb_bd`, `ilk_bd`, `m4s_bd`, `hdd_bd`
- **BDM indicators:** `Index_0` … `Index_4`
- **Buttons:** `cross`, `circle`, `triangle`, `square`, `left`, `right`, `select`, `start`
- **Loading frames:** `load0` … `load7`
- **Boot logo:** `logo`, `logo0` … `logo6`
- **Backgrounds:** `incebtion` (default theme bg), `ip`
- **Format icons:** `ELF`, `HDL`, `ISO`, `ZSO`, `UL`
- **Media icons:** `APP`, `CD`, `DVD`
- **Aspect / scan / vmode / rating** sets as listed in §6.

(`settings_bg` is theme-supplied; `Device_*` indicators are deprecated/removed in this fork.)

---

## 8. The Coverflow element (this fork)

`type=Coverflow` renders the game/app list as a centered cover carousel with a reflection.
It behaves like a `GameImage` (uses the `COV` cover cache) but draws 3 or 5 covers with a
slide animation.

### Per-theme properties (in `conf_theme.cfg`)

| Property | Notes |
|---|---|
| `default` | Fallback cover (e.g. `cover`, or `coverapp` for the apps list). |
| `overlay` + `overlay_*` corners | The case art drawn around each cover (e.g. `case` / `apps_case`). The corners place the cover **inside** the case frame; the engine auto-centers the visible frame and keeps it aspect-correct in both 4:3 and widescreen. |
| `reflection` | `1` to draw the mirrored reflection below each cover (alpha-faded). |
| `x`, `y`, `width`, `height` | Position and per-cover size. `width`/`height` should match your case art's pixel size so the overlay corners line up. |

A minimal example (this fork's `<Coverflow>` theme uses values like these):

```ini
main2:
	type=Coverflow
	default=cover
	reflection=1
	y=197
	width=256
	height=256
	overlay=case
	overlay_ulx=0    overlay_uly=0    overlay_urx=186  overlay_ury=0
	overlay_llx=0    overlay_lly=256  overlay_lrx=186  overlay_lry=256
appsMain2:
	type=Coverflow
	default=coverapp
	reflection=1
	y=239
	width=256
	height=256
	overlay=apps_case
	overlay_ulx=0    overlay_uly=0    overlay_urx=186  overlay_ury=0
	overlay_llx=0    overlay_lly=186  overlay_lrx=186  overlay_lry=186
```

### Global Coverflow tuning (NOT in the theme)

These live in **`conf_opl.cfg`** and are exposed in the **Coverflow Settings** menu (shown
while a Coverflow theme is active). They apply to *any* Coverflow theme:

| Setting / key | Values | Effect |
|---|---|---|
| `coverflow_count` | 3 or 5 | Number of covers shown. |
| `coverflow_scale` | px | How much the center cover grows. |
| `coverflow_anim` | ms | Slide animation duration (0 = instant). |
| `coverflow_dim` | 0/1 | Dim the non-center covers. |

(The per-theme horizontal nudge `coverflow_cover_offset` is a global theme key — see §2.)

---

## 9. A note on coordinates & scaling

- All positions/sizes are authored on a **640×480** canvas; OPL scales to the active video
  mode.
- With `scaled=1`, image **widths** are corrected for widescreen and the PS2's pixel aspect,
  so a square stays square in both 4:3 and 16:9. Positions are not aspect-scaled, so layouts
  fill the wider screen naturally.
- Negative `x`/`y` and `POS_MID`/`DIM_INF` let you anchor to edges/center without hardcoding
  resolution-specific numbers.

For a complete, working reference, open the bundled `<OPL>` and `<Coverflow>` themes and the
`misc/conf_theme_OPL.cfg` / `misc/theme_coverflow.cfg` sources in the repository.
