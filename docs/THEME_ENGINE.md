# OPL Theme Engine — Authoring Reference

This document describes the Open PS2 Loader theme format **as implemented by the parser**
(`src/themes.c`), so you can build your own themes. It covers every block type, property,
value token, and built-in asset name the engine understands, including this fork's
**`Coverflow`**, **`PSBBNFlow`** and **`Grid`** render modes.

- A theme is a folder in the `THM` directory containing a **`conf_theme.cfg`** plus its
  image/font assets.
- Anything not supplied by the theme falls back to OPL's embedded defaults.
- OPL ships the built-in `<OPL>` theme with three views you can study as references: List
  (`misc/conf_theme_OPL.cfg`), Coverflow (`misc/theme_coverflow.cfg`) and PSBBN Flow
  (`misc/theme_psbbn_flow.cfg`). Configurations that saved the former `<Coverflow>` or
  `<PSBBN Flow>` themes load `<OPL>` with that view. A theme of your own can offer several views
  too: see [Views](#views-multi-view-themes--this-fork).

A fresh configuration starts with `<OPL>` in the List view, a 4:3 menu and Auto video mode.
Select the Coverflow or PSBBN Flow view under **Settings → Interface → Theme View** (or hold L3 on
the main page) and, if wanted, Widescreen under **Settings → Interface**, then apply and save. Saved theme and display choices remain in effect after an
ELF update. See [Fresh-start defaults](DEFAULTS.md).

## PSBBN Flow

With the `<OPL>` theme, select **PSBBN Flow** under **Settings → Interface → Theme View** (or hold L3 on the
main page until it appears), then apply and save.
It recreates the Game Collection of CosmicScale's
[PSBBN Definitive Project](https://github.com/CosmicScale/PSBBN-Definitive-Project): black header
and button-hint bands with thin rules, a blue star-field nebula between them, the page list where
PSBBN lists Collection and Disc, and a rounded square focal cover with a soft white rim. The game
title sits above that cover and the count (`3/12`) under its lower right corner. A tail of covers,
turned away into the distance, recedes on the left. When you browse, the outgoing cover swells
toward the viewer and fades while the next one turns to face you; the title and count return once
the covers settle. The layout was measured from the project's published videos; no PSBBN code or
artwork is used. The glide keeps the 25-frame cubic timing of dnunezx's LUNA Collection display
([PR #733](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/733)), which this theme started from.

PSBBN Flow uses the same native device pages, current selection, artwork cache, palette settings,
and launch/game-settings actions as Cover Flow. Left/Right browse the covers and Up/Down change
device pages. R3 remains **toggle favorite**; there is no separate screen or R3 display swap.
The chosen theme persists by name and remains selected when disk themes are added or removed.

The built-in theme uses ordinary `ART/<startup>_COV` artwork through each source's existing image
loader, including its archive and fallback handling. Like PSBBN, every cover shows as a square
tile: square art (such as the PSBBN art database's) fills it, and portrait or landscape art is
cropped to its centre square rather than stretched. Unlike the old PR's separate screen, this
adaptation does not require an `ART/PSBBN` directory. Missing covers use the native placeholder;
folder rows remain browsable, and APPS, PS1 and Favorites use the native family/cache resolution.

Custom themes can select the same renderer with `type=PSBBNFlow`, alongside an `ItemsList` for
the native title/navigation row. `pattern`, `default`, `count` and overlays use the native image
loader. `x` / `y` place the centre of the focal cover (default `x=-186`, `y=POS_MID`, which is
454, 240 on the 640×480 canvas), and `width` sets its side (default 204, up to 60% of the screen
height). Height and alignment do not set the cover shape or anchor. See the property table below and
[the built-in configuration](../misc/theme_psbbn_flow.cfg).
The existing Cover Flow count/scale settings belong to `Coverflow`; PSBBN Flow retains Collection's
fixed perspective layout.

### PSBBNFlow element properties

Use `type=PSBBNFlow` for the perspective fan. Keep a native `ItemsList` in the same
family for the title row and navigation: one row (`height=24`) placed just above the focal cover
gives PSBBN's title, and it hides while the covers move. Device, app, PS1 and Favorites families inherit
and override slots using the usual contiguous-numbering rules. Adding either flow type
rotates Left/Right and Up/Down on every main browse page in that theme, including pages
with a plain list; info and settings controls keep their normal layout.

| Property | PSBBNFlow behavior |
| --- | --- |
| `x` | Centre of the focal cover; default is screen width minus 186 (454). Negative values anchor to the right edge. |
| `y` | Centre of the focal cover; default is mid-screen (240). Negative values anchor relative to the bottom edge. |
| `width` | Side of the square focal cover; default 204, accepted up to 60% of the screen height. Art is cropped to its centre square. |
| `pattern`, `default`, `count` | Native artwork suffix (default `COV`), missing-art asset and cache capacity. `count` controls cache slots, not the visible tail length. |
| `overlay`, `overlay2`, overlay corners | Native frame layers, scaled with each cover. Author corners against the element's `width` / `height`. Framed covers are drawn flat, without the turn or rounded corners. |
| `font` | Font for the page list and the selected-row/total counter. |

The fan draws up to six neighboring covers, a seventh fading in or out at the far end, and the
outgoing cover. The header and hint bands with their rules, the star field, the stacked
Collection outline, the page list, the rim, the count, the cubic 25-frame animation and the
distance shading belong to this renderer. The nebula is the theme's own `Background`
(`default=psbbn_bg` in the built-in). The page list and count use the text colour, and the title
uses the selected-text colour, from **Settings → Interface → Colors**.
`coverflow_count`, `coverflow_scale`, `coverflow_anim`, `coverflow_dim` and
`coverflow_cover_offset` affect `Coverflow` only. `PSBBNFlow` fixes centered alignment and
aspect correction, supplies no mirrored reflection, and uses `width` for the square slot;
generic `height`, `aligned`, `scaled`, `color` and `reflection` do not change those choices.

A minimal custom theme, with normal app and PS1 fallbacks:

```ini
main0:
    type=Background
    default=psbbn_bg
    aligned=0
    width=DIM_INF
    height=DIM_INF
main1:
    type=PSBBNFlow
    default=cover
appsMain1:
    type=PSBBNFlow
    default=coverapp
vcdMain1:
    type=PSBBNFlow
    default=cover
main2:
    type=ItemsList
    x=340
    y=114
    width=260
    height=24
```

The built-in configuration adds the nebula background, a header label, the one-row title above
the cover, hints, a loading icon and an info-page layout.
See [`misc/theme_psbbn_flow.cfg`](../misc/theme_psbbn_flow.cfg) for the full example.

## Grid

### Grid element properties

Use `type=Grid` for the page's covers in rows and columns, the selected cover framed in the
selected-text colour and the others dimmed. Left/Right step one cover; Up/Down step one row and keep
the column (a short last row takes its last cover). Up on the top row and Down on the bottom row
switch to the previous/next device page, as Up/Down do in Coverflow. The selected row stays in the
middle of the grid where the list allows, and the grid never scrolls past its last row. A position
counter (`12/40`) sits under the grid's lower right corner. Idea: KrahJohlito (multi-view themes).

| Property | Grid behavior |
| --- | --- |
| `x`, `y` | Centre of the whole grid; default is the screen centre. |
| `width`, `height` | One cover; default 80 x 112. In widescreen the cover and the column pitch narrow with the aspect correction. |
| `<block>_rows`, `<block>_columns` | Grid shape, read from the theme's **first** `Grid` block only (navigation needs one column count): default 3 rows of 4, at most 6 columns and 4 rows, and never more than 16 covers (rows are dropped first). |
| `<block>_spacing` | Gap between covers in pixels, from the first `Grid` block; default 16. |
| `pattern`, `default`, `count` | Native artwork suffix (default `COV`), missing-art asset and cache capacity, as for `Coverflow`. |
| `overlay`, `overlay2`, overlay corners | Native frame layers, scaled with each cover. Author corners against the element's `width` / `height`. |
| `font` | Font for the position counter. |

Keep a one-row `ItemsList` in the same family for the selected title. Adding a `Grid` element turns
Left/Right into cover steps and Up/Down into row steps on every main browse page in that theme.

```ini
main1:
    type=Grid
    default=cover
    rows=3
    columns=4
    spacing=12
    y=250
    width=80
    height=111
main2:
    type=ItemsList
    y=60
    height=24
```

`rows=` written inside the block is the same key as `main1_rows` (the parser prefixes it). See
[the built-in configuration](../misc/theme_grid.cfg).

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

Element names carry a **family prefix** + an index (`<family>Main<N>` / `<family>Info<N>`). Each
family targets one screen/view and is a **per-slot override** of the base `mainN`/`infoN`: for every
slot the engine looks for the family's block and, if it's absent, falls back down a chain — so you
override only what differs and inherit the rest.

| Family (main / info) | Drawn on | Per-slot fallback chain |
|---|---|---|
| `main0…` / `info0…` | The **games** list / info — the base layout | *(none — this is the base)* |
| `appsMain0…` / `appsInfo0…` | The **apps** device list / info | → `mainN` / `infoN` |
| `favsMain0…` / `favsInfo0…` | The **Favorites** tab list / info | → `mainN` / `infoN` |
| `vcdMain0…` / `vcdInfo0…` | A device's homogeneous **PS1/VCD view**, plus every PS1 row's cover and info wherever it appears | main: → `appsMainN` → `mainN`  ·  info: → `infoN` |
| `favsVcdMain0…` / `favsVcdInfo0…` *(opt-in)* | The **Favorites PS1 view**, plus PS1 covers and info on the Favorites *All* shelf | main: → `vcdMainN` → `appsMainN` → `mainN`  ·  info: → `vcdInfoN` → `infoN` |
| `favsAppsMain0…` / `favsAppsInfo0…` *(opt-in)* | The **Favorites ELF view**, plus app covers and info on the Favorites *All* shelf | main: → `favsMainN` → `mainN`  ·  info: → `favsInfoN` → `infoN` |

**The VCD family** (new in this fork) lets PS1/VCD games have their own look. A device's homogeneous
PS1 view renders from `vcdMain*`. Because each `vcdMain` slot falls
back to `appsMain` — a **square** box, matching
PS1 jewel-case art — before `main`, a theme that defines *no* `vcdMain` blocks still shows PS1 games
in the square apps box. So you only add `vcdMain` blocks to make PS1 covers *differ* from apps;
`vcdInfo` falls back to the game `info` layout, preserving the rich PS1 metadata page.

**The Favorites per-kind families** (`favsVcd*`, `favsApps*`) let PS1 and app favorites look different
from the same games on their device pages — their own layout, list and cover proportions. They are
**opt-in**: a family is built only if the theme declares at least one of its blocks, and a theme that
declares none behaves exactly as before (the Favorites PS1 view keeps using `vcdMain*`, the ELF view
`favsMain*`, and the *All* shelf the `vcdMain*` / `appsMain*` covers).

- Once declared, every slot you leave out falls back along the chain in the table — the blocks that view
  used before — so you override only what differs.
- A **cover** is taken from these families only where you **declared** it. An undeclared cover slot keeps
  today's cover (the PS1 square from `vcdMain*`, the app square from `appsMain*`), never a fallback copy
  such as `favsMain`'s portrait case. This applies to `ItemCover` panels and both `Coverflow` / `PSBBNFlow` renderers, and a
  declared cover is only used where the page draws the same kind: a `Coverflow` in `favsVcdMain*` styles
  a carousel, never an `ItemCover` panel, and vice versa.
- An `ItemsList` declared in these families needs no special handling: it takes none of the four global
  list slots, and the page navigates with the list it draws.
- PS1 favorites keep sharing the PS1 cover cache and app favorites the shared one, so no extra cover
  memory is used.

#### Mixed lists: the page picks the family, each row picks its own cover

A **mixed** list holds more than one kind of media at once — the Favorites tab's *All* shelf, and a
device page under **PS2/PS1 Game Display = Mixed**. The page as a whole still renders from one family
(the base `main*` for a Mixed device page, `favsMain*` for Favorites): the background, the texts and
the `ItemsList` belong to the *page*, so they stay put while you scroll.

The **cover does not**. A PS2 case is portrait, a PS1 case and an app box are square, and forcing one
shape on all three stretches whichever kinds are not the page's own. So the cover element — the
`ItemCover` panel, the `Coverflow` carousel or `PSBBNFlow` fan — is resolved **per row, by media kind**:

| Row | Cover drawn from |
|---|---|
| PS2 disc game | the page's own family (`main2` / `favsMain2` / …) |
| PS1 / VCD | `vcdMain*` (→ `appsMain*` → `main*`); on Favorites, a cover declared in `favsVcdMain*` first |
| App / ELF | `appsMain*` (→ `main*`); on Favorites, a cover declared in `favsAppsMain*` first |

Only the cover is redirected — its `width`/`height`, `overlay`/`overlay2` and `default` placeholder.
Everything else on the page is untouched, and on a single-kind page the row's kind *is* the page's
kind, so nothing is redirected at all. The same rule picks the info screen's cover from the matching
`*Info*` family. In a Coverflow carousel the cover **width** stays uniform (so spacing stays even) and
only the height follows each row's own element aspect. Every cover stands on the same **bottom edge**
as a cover of the page's own shape, so portrait and square covers share one baseline and their
reflections start together.

> The games / apps / favs families share one cover-art cache (deduplicated by `pattern`). The **PS1/VCD
> view keeps its OWN cover cache**: separate PS2 and PS1 views reuse the device's game *list* indices,
> so a shared cache would thrash covers on every toggle. A mixed list therefore draws from **two**
> caches at once — PS1 rows from the VCD one, everything else from the shared one — and both are
> warmed. The VCD family automatically
> claims its own (4th) `ItemsList` slot and a separate cover cache — one small extra cache; the rest is
> shared. (A theme needs no extra `ItemsList` block for this; it is auto-claimed via the fallback.)

### ⚠ Contiguous numbering rule

The parser reads blocks **in order starting from 0 and stops at the first gap.** If you define
`main0`, `main1`, `main3` (skipping `main2`), then `main3` is **never read**. When you remove
a block, **renumber** the ones after it so there are no holes.

### Views (multi-view themes) — *this fork*

One `conf_theme.cfg` can describe several **views** of the main and info pages: `list`, `coverflow`,
`psbbn` and `grid`. The user picks a view under
**Settings → Interface → Theme View**, or holds **L3** for half a second on the main page to switch to
the next view the theme offers (a tap on L3 still cycles the library view). Idea and design:
KrahJohlito.

The unprefixed blocks are the **base**. A block named `<view>.<block>` replaces that block in that
view only, and every block a view does not declare is inherited from the base:

```ini
views=list,coverflow           # the views this theme offers
default_view=list              # used until the user picks one

main2:                         # base (List): a cover panel
	type=ItemCover
	default=cover

coverflow.main2:               # Coverflow: the carousel replaces block 2
	type=Coverflow
	default=cover
	reflection=1
coverflow.appsMain2:           # families work inside a view too
	type=Coverflow
	default=coverapp
coverflow.main1_enabled=0      # hide a base block in this view only
coverflow.main9:               # or add blocks after the base list's last block (here main8)
	type=StaticText
	value=Coverflow
coverflow.coverflow_cover_offset=12   # a theme-wide key for this view only
```

**How a block is chosen.** For slot `N` of a family in view `V`, the first block present wins:
`V.<family>N`, then `V.` + each step of that family's fallback chain (for example `V.mainN`), then
the base chain (`<family>N`, …, `mainN`). So `coverflow.main2` also replaces `appsMain2` in Coverflow
unless the theme adds `coverflow.appsMain2`. A view block replaces the **whole** base block; it does
not merge single keys from it, so a view that changes `type` gets no stale keys. `_enabled=0` counts
as present, which is how a view hides a base block. The [contiguous numbering
rule](#-contiguous-numbering-rule) applies to the merged list: the view's list ends at the first slot
where neither the view nor the base has a block.

| Key | Value | Meaning |
|---|---|---|
| `views` | comma list of `list`, `coverflow`, `psbbn`, `grid` | The views the theme offers. Holding L3 always steps through them in the fixed order list, coverflow, psbbn, grid, whatever order `views=` lists them in. Absent: the theme's own view (from its base blocks: a `PSBBNFlow` element = psbbn, a `Coverflow` element = coverflow, a `Grid` element = grid, else list) plus every view it declares a `<view>.` key for. |
| `default_view` | a view name | The view used until the user picks one, and when the user's pick is not offered. Absent (or naming a view the theme does not offer): the theme's own view if `views=` offers it, else the first offered view in the order list, coverflow, psbbn, grid. |
| `<view>.inherit` | `0` | That view never falls back to the base blocks: it brings its whole main and info layout. Use it when a view shares little with the base, instead of a long list of `<view>.mainN_enabled=0` lines. |
| `<view>.<global key>` | as the key | Overrides `use_default`, `use_real_height`, `coverflow_cover_offset` and the colour keys in that view. |

- Make the base the List view. Stock OPL and other forks ignore the prefixed blocks, so they still load
  the theme as a list.
- The user's Theme View choice is one setting for every theme (saved as `theme_view=`). A theme that
  does not offer it shows its `default_view`.
- Only the active view is built. Switching views reloads the theme, so it costs no extra memory.
- Names stay within 47 characters. The longest prefixed key,
  `coverflow.favsVcdMain12_reflection_offset`, is 41.
- The built-in `<OPL>` theme offers List, Coverflow and PSBBN Flow as views. Each still lives in its own
  file (`misc/conf_theme_OPL.cfg`, `misc/theme_coverflow.cfg`, `misc/theme_psbbn_flow.cfg`), which are
  good references for a view's blocks.

---

## 2. Global properties

Put these at the top of the file (not inside a block).

### Colors (`#RRGGBB`)

| Key | Applies to |
|---|---|
| `bg_color` | Plasma/background tint (the gradient's HIGH end) |
| `plasma_blend_color` | Plasma gradient's LOW end — historically hardcoded black; omit the key (or use `#000000`) for the classic look |
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
| `default_font_weight` | 100–900 | Draws the default font heavier. A variable font follows its `wght` axis within its range. A static font, or a weight past a variable font's range, has its outlines grown in code (about 1 px at 18 px for every 300 units). Omit the key for the font's own weight. *From RIPPS2 build 114.* |
| `font1_weight` … `font15_weight` | 100–900 | The same, per font. |

Reference a font from an element with `font=N` (0 = default). Use `font1=builtin` to force the
embedded font for a slot.

### Other global keys

| Key | Value | Meaning |
|---|---|---|
| `coverflow_cover_offset` | int (−1024…1024, default 0) | Horizontal nudge for the Coverflow carousel (see §8). |
| `use_default` | 0/1 | Use OPL's embedded default assets for anything the theme omits. |
| `use_real_height` | 0/1 | Lay out against the real screen height instead of 480. |
| `use_settings_bg` | 0/1 | Load the theme's `settings_bg.png` behind the settings menus. |

### Button hints and glyphs

These keys come from RIPPS2 (akilluminati47, build 90). A theme that sets none of them draws the hint bar
exactly as before.

| Key | Value | Meaning |
|---|---|---|
| `glyph_set` | `theme` / `builtin` / `standard` / `white` | The button pictures every hint draws. `theme` (the default) uses the theme's own glyph PNGs, with the built-in ones filling gaps when `use_default=1`. `builtin` uses the built-in glyphs. `standard` and `white` are two sets built into the ELF, drawn from RIPPS2's Adapt and Grunge themes. **Settings → Interface → Button Glyphs** overrides this on every theme; its **Theme** choice follows this key. |
| `hints_hide` | hint list | Hints the theme leaves off the bar, e.g. `hints_hide=star,view`. |
| `hints_order` | hint list | These hints come first, in this order. The rest follow in the order the page adds them. Example: `hints_order=run,info,menu`. |
| `hints_labels` | 0/1 | `0` draws the glyphs alone, without the labels. `1` (the default) draws a glyph and its label. |
| `hints_layout` | `row` / `column` | `column` draws one hint a line, down from the `HintText` element's `x`/`y`. A column that would run off the bottom ends on the last line instead. `row` is the default. |
| `hints_spacing` | int, 12–96 (default 28) | The line pitch of a column. |

A hint list names hints by what they do: `menu`, `run`, `info`, `options`, `refresh`, `star` (Favourite) and
`view` (the L3 view toggle). Their buttons work too: `start`, `select`, `r3`, `l3`, `cross`, `circle`, `square`
and `triangle`. Separate the names with commas or spaces. Unknown names are skipped, and a name given twice keeps its
first place.

The glyph slots a set replaces are cross, circle, square, triangle, start, select, L1, R1, L3, R3, left and right.

---

## 3. Common element properties

Every element block starts with `type=<ElementType>` (see §5). Most also accept these:

| Property | Type | Default | Notes |
|---|---|---|---|
| `x` | int or `POS_MID` | element-specific | Negative = measured from the **right** edge. `POS_MID` = horizontal center. |
| `y` | int or `POS_MID` | element-specific | Negative = measured from the **bottom** edge. `POS_MID` = vertical center. |
| `width` | int or `DIM_INF` | element-specific | `DIM_INF` = full screen width. |
| `height` | int or `DIM_INF` | element-specific | `DIM_INF` = full screen height. |
| `aligned` | `0` / `1` / `2` | element-specific | `0` = anchor top-left, `1` = center on (x, y), `2` = right-justified + vertically centered (wOPL/uOPL key; regular OPL renders it centered). |
| `scaled` | `0` / `1` | element-specific | `0` = raw pixels, `1` = ratio-correct (handles widescreen + pixel-aspect). Use `1` for images you want undistorted. |
| `color` | `#RRGGBB` | `text_color` | Text/tint color. |
| `font` | `0`…`15` | `0` | Font index (see §2). |
| `reflection` | `0` / `1` | `0` | Draw a mirrored reflection beneath the element (used by `Coverflow`). |
| `enabled` | `0` / `1` | `1` | Set `0` to skip the element without deleting the block. |
| `devices` | name list | *(none)* | **This fork.** Show the element only on the listed device pages — honored by `MenuIcon`, `ItemsList` and `HintText` (ignored elsewhere). See §5 “Per-device placement”. |

**Value tokens:** `POS_MID`, `DIM_INF` (above), and `#RRGGBB` for colors. `x`/`y` accept
negative numbers for right/bottom-relative placement.

---

## 4. Image & overlay properties

Image-type elements (`StaticImage`, `GameImage`, `Background`, `AttributeImage`, `ItemCover`,
`Coverflow`, `PSBBNFlow`, `Grid`) add:

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
| `overlay2` | asset name | An optional **second** overlay painted over `overlay`. Shares the element position/size; takes no corners of its own. |

The overlay corners describe where the *inner* art sits within the overlay frame, in the
element's own coordinate space (i.e. relative to `width`/`height`). They scale with the drawn
element, so the window tracks the art at any size.

`overlay2` stacks a second layer in the draw order **cover → `overlay` → `overlay2`**. Use it to
split a frame into parts that sit over a *centred* cover (e.g. a transparent plastic case in
`overlay` and foliage/decoration in `overlay2`), avoiding the off-centre window shift a single
asymmetric overlay would otherwise need. Both layers are shared across elements that name the same
asset, so a second layer costs no extra VRAM when reused.

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
| `ItemIcon` *(item)* | The selected item's icon: a `GameImage` bound to the `ICO` cache (64×64 by default). Per-row list icons come from the `ItemsList`'s own `decorator=` instead. |
| `ItemCover` *(item)* | The selected item's cover, with optional `overlay`. |
| `ItemText` *(item)* | The selected item's startup filename. |
| `HintText` | Button hints for the list screen. |
| `InfoHintText` | Button hints for the info screen. |
| `LoadingIcon` | The animated loading spinner. |
| `BdmIndex` | The block-device mode indicator. |
| `Coverflow` *(item)* | **This fork:** a cover-art carousel (see §8). |
| `PSBBNFlow` *(item)* | **This fork:** Collection perspective fan with native cover navigation (see [PSBBN Flow](#psbbn-flow)). |
| `Grid` *(item)* | **This fork:** the page's covers in rows and columns (see [Grid element properties](#grid-element-properties)). |
| `SaveIcon` *(item)* | **This fork:** a PS2 game's spinning 3D save icon or a PS1 game's animated VMC icon (see §9). |

Elements are drawn in the order the theme declares them, with one exception: every `ItemText` is
moved to the end of its screen's list, so the selected item's startup filename is never painted over by
art declared after it.

Images keyed on the **`ICO`** suffix — an `ItemIcon`, a `GameImage` with `pattern=ICO`, or an
`ItemsList` with `decorator=ICO` — are the theme's disc art. The user can hide them with **Disc Artwork**
(*Settings → Interface → Artwork Settings*, on by default), including the element's `default=` image.
The independent **Logo Artwork** option similarly controls art keyed on **`LGO`**, such as
`<GAME_ID>_LGO.png` files in `ART/` used by `GameImage pattern=LGO`, `ItemsList decorator=LGO`,
or a theme's custom image element. Disabling it also suppresses the default image and overlays
for those elements, including custom Coverflow elements with an `LGO` pattern. It does **not**
affect `COV` covers, `ICO` disc artwork, `BG` backgrounds, or the separate boot-splash
`logo` / `logo0`–`logo6` theme textures. Both toggles default to on and persist in
`settings_riptopl.cfg` as `enable_discart` and `enable_logoart`, respectively.

### Text element extras

| Property | Used by | Notes |
|---|---|---|
| `value` | `StaticText` | The literal string to show. |
| `attribute` | `AttributeText`, `AttributeImage` | The metadata key (§6). |
| `display` | text | `0` = always (label + value), `1` = only when the value exists, `2` = value only (no label). |
| `wrap` | text | `1` = word-wrap within `width`/`height`. |
| `show_run` | `InfoHintText` | **This fork:** `0` hides the Run hint, for a theme that draws its own launch prompt. Back is always shown. Default `1`. |
| `title` | `AttributeText` | Override the auto label for the attribute. |

**Long text never draws over other elements (*this fork*).** When a theme loads, each single-line text
element (`StaticText`, `AttributeText`, `ItemText`, the game count) and each `ItemsList` works out how
far its text can run on its row before it reaches another element of the same screen, or the screen
edge. Text longer than that scrolls inside the space, one character at a time, pausing at each end. In a
list only the highlighted row scrolls; the other rows end in "…".

- An element the text **starts inside** (a banner or panel you draw the text on) doesn't count; only
  what the text would run **into** does.
- A `width` you set still limits the text. It now scrolls there instead of being cut off.
- Centred text gets the same room on both sides.
- `wrap=1` text keeps wrapping as before.
- An image with no `width`/`height` is sized from its `default` image. A cover (`GameImage`) with
  neither is treated as 140×200.
- If the space works out smaller than about three characters, the element is drawn exactly as before.

### List extras

| Property | Used by | Notes |
|---|---|---|
| `decorator` | `ItemsList` | A `GameImage` pattern name to draw as per-row icons. |

### Per-device placement (`devices=`) — *this fork*

Normally one `MenuIcon`, one `ItemsList` and one `HintText` serve **every** device page, so they
share a single position. `devices=` lets a theme place them differently per device: an element
with the key draws **only** on the listed pages, and an unfiltered element of the same type
automatically stands down there (no key needed on it), staying the default everywhere else.

```ini
# The shared icon spot, used by every page not claimed below.
main3:
type=MenuIcon
x=POS_MID
y=400

# On the MMCE and APA-HDD pages, pin the icon top-right instead.
main4:
type=MenuIcon
devices=mmce,hdd
x=-40
y=24
```

**Device names** (comma-separated, case-insensitive):

| Name | Page |
|---|---|
| `usb` | USB mass storage (any slot) |
| `ilink` | iLink / FireWire |
| `mx4sio` | MX4SIO |
| `hdd_bd` | Internal HDD, exFAT (BDM) |
| `hdd` | Internal HDD, APA/PFS |
| `eth` | Network (SMB) |
| `smb` | Alias of `eth` |
| `mmce` | MMCE / memory-card emulator |
| `udpbd` | UDPBD network boot |
| `udpfs` | UDPFS network boot |
| `app` | The Apps tab |
| `fav` | The Favorites tab |
| `bdm` | The generic BDM page before its driver is identified (auto/manual start) |

Rules worth knowing:

- **Only `MenuIcon`, `ItemsList` and `HintText`** honor the key; on other element types it parses
  but has no effect.
- Matching follows the page's **visible device icon**, so a BDM page counts as `usb`/`mx4sio`/…
  once its driver is identified, and as `bdm` before that. In the PS1/VCD (L3) view the page keeps
  the device's identity — filters keep working there via the `vcdMain*` family.
- A filtered `ItemsList` is an **override**: it does not consume one of the theme's ItemsList
  slots (games/apps/favs/VCD, claimed in file order — see §1), and navigation/paging automatically
  follows whichever list is drawn. Give it its own `x`/`y`/`height` (its row count comes from
  `height`); `decorator=` works as usual.
- **Keep one unfiltered `ItemsList`.** If *every* list in the theme carries `devices=`, OPL adds a
  plain default list (373×316 at 42,42) on the pages nothing covers — navigation always needs a
  list — and it won't match your layout.
- Unknown device names are logged and skipped; if nothing valid remains, the element behaves as if
  the key were absent (shared placement) rather than disappearing.
- Two filtered elements of the same type may list different devices; listing the **same** device
  twice draws both — that's an authoring error, not a picker.
- Themes without the key are untouched — the filter only activates when `devices=` appears.

### Using RiptOPL themes on regular OPL

RiptOPL themes are designed to load on regular/upstream OPL and degrade gracefully — one theme can
serve both. Regular OPL's parser never aborts on fork content: keys it doesn't know (`devices=`,
`reflection_offset`, `overlay2`, `plasma_blend_color`, the entire `favsMain*`, `vcdMain*`,
`favsVcdMain*` and `favsAppsMain*` families…) are simply never read, and unknown element types (`Coverflow`, `PSBBNFlow`, `Grid`, `SaveIcon`) are skipped without
stopping the parse. What to expect there:

- **Invisible:** all pure-key extras above — regular OPL renders the theme as if they weren't
  written.
- **Cosmetic:** `aligned=2` renders centered; `#Size`/`#DiscType`/`#System` attributes and the
  Coverflow carousel and PSBBN Flow fan are silently absent.
- **Ugly but harmless:** `devices=` layouts — regular OPL draws *every* `MenuIcon`/`HintText` block
  on *every* page (overlapping), and treats a second `ItemsList` as the apps list while still
  drawing it on the games screen. Per-device layouts are effectively RiptOPL-only.
- **⚠ The one rule:** **always include one plain (unfiltered) `ItemsList`**. A theme with none —
  e.g. a Coverflow-only theme, or one where every list carries `devices=` — *crashes regular OPL on
  the first scroll* (a latent upstream bug in its default-list repair; RiptOPL fixed it on our
  side). Ship the plain list and the theme is safe everywhere.

---

## 6. `attribute=` values

### AttributeText (metadata text)

`Title`, `Developer`, `Description`, `Genre`, `Release`, `#Size` (the `#Size` value renders
with a `MiB` suffix). Labels are auto-localized; override with `title=`.

These fields are read from the selected game's CFG, not downloaded with its artwork.
For PS2 games, put metadata in `CFG/<startup ID>.cfg` on the game source, for example
`CFG/SLUS_212.07.cfg`. Keys are case-sensitive:

```ini
Title=Dragon Quest VIII
Genre=Role-playing
Developer=Level-5
```

`Release` and `Description` can be supplied in the same file. Missing or empty `Title`
falls back to the library's game name for display without changing the CFG. Other
missing metadata stays absent; `#Size` is supplied independently by the loader.
Artwork appearing while metadata is blank therefore does not establish that the
metadata CFG was found or contains those keys.

Fresh configurations use 4:3 and Large coverflow center enlargement. Existing saved
widescreen and coverflow settings take precedence. Center enlargement changes the
coverflow cover size, not a theme's separate disc image dimensions or source detail.

### AttributeImage (badge chosen by value)

A per-game **attribute** picks which glyph to draw. Where that glyph comes from depends on the theme:

* **Built-in `<OPL>` theme** (no theme folder) — draws the *embedded* glyph whose internal name equals
  the value, e.g. `#System=PS2` → the built-in `PS2`, `#Media=CD` → `CD`, `#Format=ISO` → `ISO`.
  Attributes with no embedded glyph (e.g. `#DiscType`) draw nothing on the built-in theme.
* **Disk theme** — loads **`<value>_<attribute>.png`** from the theme folder — *value first, then the
  attribute* (the same `<name>_<suffix>` shape cover art uses, e.g. `<id>_COV.png`). So `#System=PS2`
  → `PS2_#System.png`, `#Media=CD` → `CD_#Media.png`, `#DiscType=PS2DVD` → `PS2DVD_#DiscType.png`.

> ⚠️ The disk-theme file is **`<value>_<attribute>`**, *not* `<attribute>_<value>`. `PS2DVD_#DiscType.png`
> is correct; `#DiscType_PS2DVD.png` is never read. (The `#` is a literal character in the filename, and
> the extension must be lower-case **`.png`** — the PS2 HDD's filesystem is case-sensitive.)

Metadata attributes OPL sets automatically per game — on **every device** (USB/BDM, SMB, MMCE and the
internal HDD/HDL, including their PS1/VCD lists):

| `attribute=` | Value(s) OPL sets | Built-in glyph | Disk-theme file |
|---|---|---|---|
| `#System` | `PS1`, `PS2` | `PS1`, `PS2` | `PS1_#System.png`, `PS2_#System.png` |
| `#Media` | `CD`, `DVD` | `CD`, `DVD`, `APP` | `CD_#Media.png`, `DVD_#Media.png` |
| `#Format` | `ISO`, `ZSO`, `VCD`, `UL`, `ELF`, `HDL` | same names | `ISO_#Format.png`, `VCD_#Format.png`, … |
| `#DiscType` | `PS1CD`, `PS2CD`, `PS2DVD` | *(none — supply your own)* | `PS1CD_#DiscType.png`, `PS2CD_#DiscType.png`, `PS2DVD_#DiscType.png` |
| `#Size` | a byte count *(use with `AttributeText`, renders as `… MiB`)* | — | — |

Compatibility attributes whose value is *already* a full glyph name — `Vmode`, `Aspect`, `Scan`,
`Players`, `Rating` (e.g. `Vmode_ntsc`, `Aspect_w`, `Scan_480p`, `Rating_3`) — follow the same rules:
the built-in theme draws the matching embedded glyph, a disk theme uses `<value>_<attribute>.png`.

#### `#DiscType` worked example *(issue #49)*

`#System` says PS1 vs PS2 and `#Media` says CD vs DVD, but PS1-CD and PS2-CD both report `#Media=CD`, so
one `#Media` glyph can't tell them apart. `#DiscType` collapses console + media into a single token so a
theme can show **one** disc glyph per kind. There are no built-in `#DiscType` glyphs — a disk theme
supplies its own. In your theme's `conf_theme.cfg`, add an element to the page you want it on. The
`mainN` / `infoN` indices must be **contiguous** (the parser stops at the first gap), so use the next
free number — if your theme already has `main0`…`main8`, add `main9`:

```
main9:
	type=AttributeImage
	attribute=#DiscType
	x=55
	y=-252
	width=32
	height=16
```

Then drop three PNGs **in the theme folder, next to `conf_theme.cfg`**:

* `PS1CD_#DiscType.png`
* `PS2CD_#DiscType.png`
* `PS2DVD_#DiscType.png`

(Position with `x`/`y`/`width`/`height` — negative `x`/`y` anchor from the right/bottom edge. Copy the
coordinates from a neighbouring `AttributeImage` such as the `#Media` badge to line it up.)

---

## 7. Built-in `default=` asset names

You can point `default=`/`overlay=` at any of OPL's embedded textures (no file needed):

- **Covers / art:** `cover`, `coverapp`, `disc`, `screen`, `screens` (overlay), `missing`
- **Case overlays:** `case` (the shared frame, layer 1), `case_overlay` (layer 2, drawn over `case`), `apps_case` (legacy apps-only frame)
- **Device icons:** `usb`, `mmce`, `hdd`, `eth`, `app`, `fav`, `usb_bd`, `ilk_bd`, `m4s_bd`, `hdd_bd`, `udp_bd` (UDPBD), `udp_fs` (UDPFS)
- **BDM indicators:** `Index_0` … `Index_4`
- **Buttons:** `cross`, `circle`, `triangle`, `square`, `left`, `right`, `select`, `start`, `L3`, `R3`, `fav_mark`
- **Loading frames:** `load0` … `load7`
- **Boot logo:** `logo`, `logo0` … `logo6`
- **Backgrounds:** `incebtion` (default theme bg), `ip`, `psbbn_bg` (PSBBN Flow view nebula, 8-bit 160×120, filtered up)
- **Format icons:** `ELF`, `HDL`, `ISO`, `ZSO`, `UL`
- **Media icons:** `APP`, `CD`, `DVD`
- **Aspect / scan / vmode / rating** sets as listed in §6.

(`settings_bg` is theme-supplied; `Device_*` indicators are deprecated/removed in this fork.)

---

## 8. The Coverflow element (this fork)

`type=Coverflow` renders the game/app list as a centered cover carousel with a reflection.
It behaves like a `GameImage` (uses the `COV` cover cache) but draws 3 or 5 covers with a
slide animation.

While the user is idle, the carousel also *prefetches* the covers just outside the visible
window (up to 4 positions each side of the selection, wrapping around the list ends), so a
scroll step reveals a cover that is usually already loaded instead of the placeholder
(issue #296). The prefetch only starts once the selection's own cover has loaded, and it is
skipped entirely on MMCE-backed items (including MMCE-sourced favorites) to keep the shared
SIO2 bus quiet — those covers still load on selection, as before.

### Per-theme properties (in `conf_theme.cfg`)

| Property | Notes |
|---|---|
| `default` | Fallback cover (e.g. `cover`, or `coverapp` for the apps list). |
| `overlay` + `overlay_*` corners | The case art drawn around each cover (e.g. `case` / `apps_case`). The corners place the cover **inside** the case frame; the engine auto-centers the visible frame and keeps it aspect-correct in both 4:3 and widescreen. |
| `reflection` | `1` to draw the mirrored reflection below each cover (alpha-faded). |
| `x`, `y`, `width`, `height` | Position and per-cover size. `width`/`height` should match your case art's pixel size so the overlay corners line up. `y` is the vertical **center of a cover of this element's own shape**. On a mixed shelf (Favorites *All*, a Mixed device page) a cover of another shape stands on that cover's **bottom edge**, so every cover rests on one baseline and the reflections line up. On a single-kind page every cover is this shape, so `y` is simply each cover's center. |

A minimal example (the built-in Coverflow view uses values like these):

```ini
main2:
	type=Coverflow
	default=cover
	reflection=1
	y=233
	width=184
	height=256
	overlay=case
	overlay2=case_overlay
	overlay_ulx=0    overlay_uly=0    overlay_urx=184  overlay_ury=0
	overlay_llx=0    overlay_lly=256  overlay_lrx=184  overlay_lry=256
appsMain2:
	type=Coverflow
	default=coverapp
	reflection=1
	y=239
	width=184
	height=184
	overlay=case
	overlay2=case_overlay
	overlay_ulx=0    overlay_uly=0    overlay_urx=184  overlay_ury=0
	overlay_llx=0    overlay_lly=184  overlay_lrx=184  overlay_lry=184
vcdMain2:
	type=Coverflow
	default=cover
	reflection=1
	y=239
	width=184
	height=184
	overlay=case
	overlay2=case_overlay
	overlay_ulx=0    overlay_uly=0    overlay_urx=184  overlay_ury=0
	overlay_llx=0    overlay_lly=184  overlay_lrx=184  overlay_lry=184
```

Apps and PS1/VCD covers share the games frame but use a **square** element so the box matches
their square art, while games stay PS2-case **portrait**. The `vcdMain2` block above gives PS1/VCD
covers their own square element; omit it and PS1 games reuse `appsMain2` (see *Block families*). The element `width`/`height` set the box
aspect; the overlay corners (full-canvas of those dims) let the cover fill it.

More than one of these blocks is live at once on a **mixed** list — each row's cover picks the one
for its own media kind (see *Mixed lists* under *Block families*). Which trio is in play depends on
the page, because only the PS1 and app rows are redirected; the PS2 row keeps whatever the page
itself renders from:

- a **device page** set to Mixed → `main2` + `vcdMain2` + `appsMain2`
- the **Favorites** *All* shelf → `favsMain2` + `vcdMain2` + `appsMain2`, with `favsVcdMain2` /
  `favsAppsMain2` taking over the PS1 / app covers when the theme declares them

So a theme that overrides `favsMain2` should size it as its **PS2** cover, and define `vcdMain2` /
`appsMain2` for the other two kinds rather than leaving the whole shelf on one shape.

The Favorites PS1 and ELF views are homogeneous pages. With `favsVcdMain*` / `favsAppsMain*` declared,
they draw their own carousel from those blocks — its position, size and case, independent of the device
pages. For example, taller PS1 covers on Favorites only, with every device page unchanged:

```ini
favsVcdMain2:
	type=Coverflow
	default=cover
	reflection=1
	y=250
	width=200
	height=200
	overlay=case
	overlay2=case_overlay
	overlay_ulx=0    overlay_uly=0    overlay_urx=200  overlay_ury=0
	overlay_llx=0    overlay_lly=200  overlay_lrx=200  overlay_lry=200
```

Slots `favsVcdMain0`, `favsVcdMain1`, `favsVcdMain3`… are not declared here, so they fall back to
`vcdMain*` and the rest of the PS1 page looks as it did. The global Coverflow tuning below applies to
these carousels too.

This example assumes a theme that already uses Coverflow. A `Coverflow` block in **any** family makes
the whole theme use flow navigation: Left/Right steps through the list on every browse page. Adding one only to `favsVcdMain*` in a list-based theme therefore
changes navigation on the device pages as well.

### Global Coverflow tuning (NOT in the theme)

These live in **`settings_riptopl.cfg`** and are exposed in the **Settings → Interface → Coverflow Settings** menu. These values apply to any `Coverflow`
element, including one in a custom theme. They can be edited before selecting that theme.
`PSBBNFlow` uses its own fixed layout and 25-frame animation:

| Setting / key | Values | Effect |
|---|---|---|
| `coverflow_count` | 3 or 5 | Number of covers shown. |
| `coverflow_scale` | px | How much the center cover grows. |
| `coverflow_anim` | ms | Slide animation duration (0 = instant). |
| `coverflow_dim` | 0/1 | Dim the non-center covers. |

(The per-theme horizontal nudge `coverflow_cover_offset` is a global theme key — see §2.)

---

## 9. The SaveIcon element (this fork)

`type=SaveIcon` draws the selected PS2 game's own save icon — the 3D model the PS2 browser shows —
spinning, and moving too when the icon is animated. It comes from:

1. the game's **per-game VMC** (slot 1, then slot 2) when one is assigned and switched on, else
2. the **memory cards** in the console: the newest save of that game on either card. Slot 2 is
   skipped while MX4SIO is enabled, because that is where an MX4SIO sits.

`x`/`y`/`aligned` place the element and `width`/`height` (64×64 by default) give the box the whole icon
fits in, at every angle of its turn; `scaled=1` (the default) narrows it on a 16:9 screen like any
image. Lighting comes from the save's own `icon.sys`.

For PS1 titles, the same element displays the save's original 16×16 icon, including its one to three
animation frames. It reads `SLOT0.VMC` then `SLOT1.VMC` from `POPS/<VCD basename>/`, or `MC1.vmc`
then `MC2.vmc` from the listed Ember game folder. APA POPSTARTER cards live in `__common/POPS/`;
Ember cards stay in the game's owning partition. Favourites use their source device's location.
Ember's single-hop `SharedMC.txt` redirects are supported. The first valid active save in the
dedicated card supplies the icon; PS1 cards have no save timestamps. Deleted saves and damaged
card chains are ignored. PS1 icons retain their pixel art rather than acquiring a 3D spin.

It draws **nothing** while the user's **3D Save Icons** setting is off (*Settings → Interface →
Artwork Settings*, off by default), on an app row, or when the
game has no readable save. A theme can place it unconditionally, but should not put anything under it
that depends on it being there. The cards are read only once the cursor has rested on a game for a
quarter of a second, on the worker that also loads cover art.

```
main19:
	type=SaveIcon
	x=-128
	y=86
	width=64
	height=52
```

The built-in List and Coverflow views place one: List above the cover and Coverflow under the centre cover, and
both between the two screenshots of the info page. The built-in PSBBN Flow view does not
place a SaveIcon; custom PSBBN Flow themes can add the element.

---

## 10. A note on coordinates & scaling

- All positions/sizes are authored on a **640×480** canvas; OPL scales to the active video
  mode.
- With `scaled=1`, image **widths** are corrected for widescreen and the PS2's pixel aspect,
  so a square stays square in both 4:3 and 16:9. Positions are not aspect-scaled, so layouts
  fill the wider screen naturally.
- Negative `x`/`y` and `POS_MID`/`DIM_INF` let you anchor to edges/center without hardcoding
  resolution-specific numbers.

For a complete, working reference, open the bundled `<OPL>` theme's List, Coverflow and PSBBN Flow views and the
`misc/conf_theme_OPL.cfg`, `misc/theme_coverflow.cfg` and `misc/theme_psbbn_flow.cfg` sources in the repository.
