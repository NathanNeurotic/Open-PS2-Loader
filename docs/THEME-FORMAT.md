# OPL `conf_theme.cfg` — Format Reference (derived from source)

**Source of truth:** [ps2homebrew/Open-PS2-Loader](https://github.com/ps2homebrew/Open-PS2-Loader),
`main` branch @ `3e3f34e` (2026-06-06), version string `v1.2.0-Beta`.

Everything below was read out of the C renderer, not from documentation. Primary files:

| File | What it governs |
|---|---|
| `src/themes.c` | element table, per-type defaults, attribute parsing, validation/injection |
| `src/config.c` | the flat cfg parser (`splitAssignment`, `parsePrefix`, `strToColor`) |
| `src/util.c` | line reader (`readFileBuffer`) — BOM, CRLF |
| `src/renderman.c` | `rmDrawPixmap` geometry: align, scale, widescreen |
| `src/fntsys.c` | `fntRenderString` geometry: baseline, centering, clipping, wrapping |
| `src/menusys.c` | the element draw loop (draw order) |
| `src/textures.c` | `texDiscoverLoad` — how an asset filename is resolved |
| `src/texcache.c`, `src/bdmsupport.c` | game-art cache and `ART/<STARTUP>_<PATTERN>.png` naming |
| `misc/conf_theme_OPL.cfg` | OPL's own built-in theme (copied to `docs/reference-conf_theme_OPL.cfg`) |

Where the [official theme guide](https://www.ps2homebrew.org/Open-PS2-Loader-User-Guide/theme-guide.html)
disagrees with the code, the code wins and the disagreement is recorded in
[§10 Documentation discrepancies](#10-documentation-discrepancies).

Judgment calls made while reading ambiguous code are logged in
[§11 Judgment calls](#11-judgment-calls).

---

## 1. The file format itself

### 1.1 Line reading (`readFileBuffer`, `src/util.c:285`)

* Lines are split on `\n`. A single trailing `\r` is stripped, so CRLF files work (`util.c:341`).
* A UTF-8 BOM at the very start of the file is skipped (`util.c:250`).
* There is **no comment syntax**. See §1.4.

### 1.2 Two ways to write a key (`configReadFileBuffer`, `src/config.c:468`)

Each line is tried as an assignment first, then as a prefix:

**(a) Flat form** — `key=value`:

```
main0_type=Background
main0_x=0
```

Leading whitespace before the key is skipped (`splitAssignment`, `config.c:75`). The key is
everything before the **first** `=`; the value is everything after it, **verbatim** — trailing
spaces and inline `#` are part of the value, and there is no quoting or escaping.

**(b) Prefix form** — a line containing `:` and not `=`, followed by indented assignments:

```
main0:
	type=Background
	x=0
```

`parsePrefix` (`config.c:99`) takes the text before the first `:` as the prefix. Subsequent lines
whose **first character is whitespace** (space or tab, `isWS`) get stored as `<prefix>_<key>`
(`config.c:495`). A line that does **not** start with whitespace clears the prefix
(`config.c:487`) — so indentation is load-bearing, not cosmetic.

Both forms produce identical keys. OPL's own theme uses form (b); this tool preserves whichever
form a file already uses.

### 1.3 Limits

* Key: `CONFIG_KEY_NAME_LEN` = **32** bytes, `strncpy`-truncated (`config.h:131`, `config.c:128`).
* Value: `CONFIG_KEY_VALUE_LEN` = **256** bytes, truncated the same way.
* Keys are stored in a linked list in file order; lookup is first-match, so **the first
  occurrence of a duplicate key wins** for reads (`getConfigItemForName`, `config.c:149`) even
  though `configSetStr` overwrites in place on load — net effect: last write into the same slot,
  first slot position. In practice: a duplicated key keeps its original position and takes the
  **last** value seen.

### 1.4 Comments — there is no comment character

A line with no `=` and no `:` is logged as malformed and **ignored** (`config.c:503`), so
`# a note` happens to be harmless. But `# note = something` **does** parse: it becomes key
`# note ` with value ` something`. Keys beginning with `#` are stored like any other; they're only
special in that they don't set the `modified` flag (`config.c:291`).

Worse, a `#` line containing a **colon** and no `=` satisfies `parsePrefix` and becomes a **section
header**. This:

```
main0:
	type=Background
	# note: watch out
	x=7
```

stores `x` as `<tab># note_x`, not `main0_x` — the comment silently re-homes every key below it
until the next header. Any `:` in a comment does this, and OPL logs nothing. The previewer raises
`COMMENT_PREFIX` for it.

Consequence for a round-trip writer: `#`-lines are unstructured text that must be preserved
byte-for-byte, and a `#` line containing `=` or `:` is structurally significant.

### 1.5 Colors (`strToColor`, `src/config.c:30`)

```
text_color=#RRGGBB
```

* The value **must** start with `#`, else the function returns 0 — **but `configGetColor` returns 1
  regardless** (`config.c:356`), and `strToColor` has already zeroed the buffer.
  **`text_color=FFFFFF` therefore yields black, not white.** This is a silent trap and the
  previewer flags it.
* Parsing is 2 hex digits per channel, R→G→B, stopping at the first non-hex character. There is no
  length validation: `#F` → `(0x0F, 0, 0)`; `#ABCDEF00` → the extra digits fall off the end of the
  3-byte array in the loop's terms but `n` stops mattering after B (the code keeps incrementing `n`
  past 2 — writing past `color[2]` is possible with >6 hex digits; treat >6 digits as malformed).
* Alpha is never read from the theme. Every theme color becomes `RGBA(r, g, b, 0x80)`, and `0x80`
  is PS2 "fully opaque" (`themes.c:739`).

### 1.6 Integers

`configGetInt` is `atoi` on the raw string (`config.c:342`): leading spaces tolerated, trailing
garbage ignored, non-numeric → `0`. `atoi("POS_MID")` is `0` — which is why `x`/`y`/`width`/`height`
are read as *strings* and special-cased before falling back to `atoi` (`themes.c:684`).

---

## 2. Element enumeration and numbering

### 2.1 Screens

Four independent element chains are built (`thmLoad`, `themes.c:1309-1339`):

| Key prefix | Chain | Screen |
|---|---|---|
| `main<N>` | `mainElems` | main game-list page |
| `info<N>` | `infoElems` | game info page |
| `appsMain<N>` | `appsMainElems` | main page, APPS mode |
| `appsInfo<N>` | `appsInfoElems` | info page, APPS mode |

`N` starts at **0** and must be consecutive.

### 2.2 The scan loop and the gap rule

```c
int i = 1;  snprintf(path, "main0");
while (addGUIElem(..., path))
    snprintf(path, "main%d", i++);
```

`addGUIElem` returns **0 only when `<name>_type` is absent** (`themes.c:1096`). So:

* **A numbering gap stops the scan.** If `main0..main4` and `main6..main9` exist, `main5_type`
  is missing → the loop ends → `main6`+ are **never read**, silently. This is the single most
  common theme bug and the previewer warns about it explicitly.
* **An unknown/misspelled `type` does NOT stop the scan.** `type` is present, so the function
  returns 1; none of the `strcmp` branches match, `elem` stays `NULL`, nothing is appended, and
  numbering continues to the next index. The element simply vanishes.
* **`<name>_enabled=0` does NOT stop the scan either.** The whole body is skipped and 1 is
  returned (`themes.c:1019`). This is the supported way to switch an element off without
  renumbering everything after it.

### 2.3 Apps-page inheritance (`themes.c:1314-1323`)

After the `main` scan ends with counter `i`, for each `j` in `0 .. i-1`:

1. try `appsMain<j>`;
2. if that returns 0 (no `appsMain<j>_type`), fall back to instantiating `main<j>` **again** into
   the apps chain.

So the apps page mirrors the main page element-for-element **by index**, and you override one slot
by defining `appsMain<j>` with the same index. Setting `appsMain<j>_enabled=0` returns 1 → the
fallback is skipped → the element is removed from the apps page only. `info`/`appsInfo` work
identically.

Note the fallback re-runs `initBasic`/`init*`, producing a *second independent instance* of the
element (its own cache linkage is resolved by `findDuplicate`, §6.4).

### 2.4 Draw order

`menuRenderElements` (`src/menusys.c:924`) walks the singly-linked list front to back and calls
`drawElem`. The list is appended to in scan order, so:

> **Elements draw in ascending numeric order; higher numbers paint on top.**

Exception: an injected default Background is spliced in at the **head** (§4), and an injected
default ItemsList is spliced in as the **second** element.

---

## 3. Element types

`type` is compared with `strcmp` — **case-sensitive, exact match** (`themes.c:1023`). The complete
table is `elementsType[]` (`themes.c:62`):

| `type=` | Internal `elem->type` | Draw function | Notes |
|---|---|---|---|
| `AttributeText` | `ATTRIBUTE_TEXT` | `drawAttributeText` | needs `attribute` |
| `StaticText` | `STATIC_TEXT` | `drawStaticText` | needs `value` |
| `AttributeImage` | `ATTRIBUTE_IMAGE` | `drawAttributeImage` | needs `attribute` |
| `GameImage` | `GAME_IMAGE` | `drawGameImage` | needs `pattern` |
| `StaticImage` | `STATIC_IMAGE` | `drawStaticImage` | needs `default` |
| `Background` | `BACKGROUND` | varies (§4) | only valid as the first element |
| `MenuIcon` | `MENU_ICON` | `drawMenuIcon` | no extra attributes |
| `MenuText` | `MENU_TEXT` | `drawMenuText` | no extra attributes |
| `ItemsList` | `ITEMS_LIST` | `drawItemsList` | at most 2 per theme (§5) |
| `ItemIcon` | **`GAME_IMAGE`** | `drawGameImage` | preset `pattern=ICO count=20` |
| `ItemCover` | **`GAME_IMAGE`** | `drawGameImage` | preset `pattern=COV count=10` |
| `ItemText` | `ITEM_TEXT` | `drawItemText` | no extra attributes |
| `HintText` | `HINT_TEXT` | `drawHintText` | no extra attributes |
| `InfoHintText` | `INFO_HINT_TEXT` | `drawInfoHintText` | no extra attributes |
| `LoadingIcon` | `LOADING_ICON` | *(not in chain)* | see §3.2 |
| `BdmIndex` | `BDM_INDEX` | `drawBDMIndex` | added 2024-07-30 |
| `GameCountText` | **`STATIC_TEXT`** | `drawGameCountText` | added 2024-11-15 |

Two aliasing quirks that matter:

* `ItemIcon` and `ItemCover` **are** `GameImage` internally. They are therefore eligible targets for
  an `ItemsList` `decorator` (§5.2), and their `pattern`/`count`/`default`/`overlay` keys behave
  exactly like `GameImage`'s (they just start from different presets).
* `GameCountText` is registered as `STATIC_TEXT`, so it inherits `StaticText`'s defaults — but its
  `_value` is generated, not read.

### 3.1 `Background` is positional

`Background` is only instantiated **if the chain is still empty** (`themes.c:1042`). A `Background`
at `main3` is silently discarded — no element is created, and the index is consumed. Then §4's
validation notices `mainElems.first` isn't a Background and injects a default one.

### 3.2 `LoadingIcon` is not part of the chain

`theme->loadingIcon` is assigned but `elem` is left `NULL`, so nothing is appended to the list
(`themes.c:1077`). It's drawn separately by `guiDrawBusy` (`src/gui.c:1089`) using only
`posX/posY/aligned/width/height/scaled`. Only the **first** `LoadingIcon` in a theme is kept.
The previewer renders it as an overlay, off by default.

---

## 4. `Background` semantics

`initBackground` (`themes.c:759`) picks the draw function from what's configured:

1. `pattern` present → `drawGameImage` — per-game background art (`ART/<STARTUP>_<pattern>.png`),
   falling back to `default`, and if that's missing too, to the animated plasma.
2. else `default` present → `drawStaticImage` — one fixed image.
3. else → `drawBackground` → `guiDrawBGPlasma()` — the procedural Perlin plasma tinted by
   `bg_color`.

`Background` ignores `overlay` entirely (`themes.c:487` guards the overlay lookup with
`type != ELEM_TYPE_BACKGROUND`).

**Injection (`validateBackgroundElems`, `themes.c:947`).** If the first element of `mainElems` is
not a `Background`, OPL prepends one built as
`initBasic("bg", BACKGROUND, x=0, y=0, aligned=ALIGN_NONE, w=640, h=480, scaled=SCALING_NONE)` +
`initBackground(pattern="BG", count=1)`. Same for `infoElems` — but **only if `infoElems` is
non-empty**; an entirely absent info page stays absent. The injected element reads `bg_*` keys from
the cfg (e.g. `bg_default`, `bg_x`) if you define them.

**Validation is skipped for the built-in theme.** `validateGUIElems` only runs when `themePath` is
non-NULL (`themes.c:1341`), i.e. for on-disk themes. All user themes get it.

---

## 5. `ItemsList`

### 5.1 Geometry and item count

```c
if (elem->width  == DIM_UNDEF) elem->width  = 640;
if (elem->height == DIM_UNDEF) elem->height = usedHeight - (MENU_POS_V + HINT_HEIGHT); // 480-50-32 = 398
itemsList->displayedItems = elem->height / MENU_ITEM_HEIGHT;                            // 398/19 = 20
```

`MENU_POS_V` = 50, `HINT_HEIGHT` = 32 (`themes.c:13`), `MENU_ITEM_HEIGHT` = **19**
(`include/opl.h:222`). **There is no `items` attribute** — the row count is derived from `height`
and cannot be set directly (see §10).

At most **two** `ItemsList` elements exist per theme: the first becomes `gamesItemsList`, the
second `appsItemsList`; a third is ignored (`themes.c:1052`). Note the second one is built from a
*different* set of positional defaults (`42,42,400,360`) than the first (`0,0,DIM_UNDEF,DIM_UNDEF`).

### 5.2 Row drawing (`drawItemsList`, `themes.c:840`)

```c
posX = elem->posX;  posY = elem->posY;
if (elem->aligned) { posX -= elem->width >> 1;  posY -= elem->height >> 1; }
for each visible row:
    color = (row == selected) ? gTheme->selTextColor : elem->color;
    if (decoratorImage) {
        rmDrawPixmap(icon, posX, posY, aligned, 20, 20, scaled, gDefaultCol);
        fntRenderString(font, elem->posX + 20, posY, aligned, width, height, text, color);
    } else {
        fntRenderString(font, elem->posX,      posY, aligned, width, height, text, color);
    }
    posY += 19;
```

Three behaviors worth calling out, all reproduced by the previewer:

* Selected-row color is `sel_text_color` (theme-level), **not** any per-element attribute.
  `<name>_color` only colors the unselected rows.
* `DECORATOR_SIZE` is hard-coded **20×20** (`themes.c:15`); the decorator element's own
  `width`/`height` are ignored here.
* **Quirk:** with `aligned=1` *and* a decorator, the icon is placed at the centered `posX` but the
  text at the **uncentered** `elem->posX + 20`. The two disagree by `width/2`. This looks like an
  oversight in OPL, but it is the shipped behavior.

### 5.3 `decorator`

`<name>_decorator=<pattern>` names a **pattern string**, not an element name. In a second pass
(`validateItemsList`, `themes.c:968`) OPL walks `mainElems` for the first element with
`type == GAME_IMAGE` whose cache `suffix` equals that string — which includes `ItemIcon`
(`ICO`) and `ItemCover` (`COV`).

Guard: the decorator is only attached **if `gameImage->cache->count >= displayedItems`**
(`themes.c:980`) — "if the user wants to cache fewer than the displayed items, disable itemslist
icons, else it would load constantly". So `decorator=ICO` with `ItemIcon`'s default `count=20` and
an `ItemsList` tall enough for 21 rows silently drops the decorator. The previewer surfaces this.

Also: `validateItemsList` dereferences `gameImage->cache` without a NULL check. A `GameImage`
whose `pattern` is missing has no cache — in OPL that is a potential null deref; the previewer
just skips such elements and warns.

**Injection.** If no `ItemsList` was declared, OPL adds one as
`initBasic("il", ITEMS_LIST, x=42, y=42, aligned=ALIGN_NONE, w=373, h=316, scaled=SCALING_RATIO,
color=text_color)` and splices it in **right after the Background** (`themes.c:992`). 316/19 = 16
rows. It reads `il_*` keys if present.

---

## 6. Attributes

### 6.1 Common attributes (`initBasic`, `themes.c:668`)

Read for **every** element type. Per-type defaults are in §7.

| Key | Type | Parsing | Notes |
|---|---|---|---|
| `<n>_enabled` | int | `atoi` | `0` skips the element (scan continues). Default 1. |
| `<n>_type` | string | exact `strcmp` | **Mandatory.** Absent ⇒ scan stops (§2.2). |
| `<n>_x` | string | `POS_MID` → `320`, else `atoi` | **If negative: `x = 640 + x`** (from the right edge). |
| `<n>_y` | string | `POS_MID` → `240`, else `atoi` | **If negative: `y = ceil((480 + y) * usedHeight / 480)`**, which is `480 + y` since `usedHeight` is always 480 (§8). |
| `<n>_width` | string | `DIM_INF` → `640`, else `atoi` | No value ⇒ per-type default; `-1` (`DIM_UNDEF`) ⇒ use the texture's own width. |
| `<n>_height` | string | `DIM_INF` → `480`, else `atoi` | Same, `-1` ⇒ texture height. |
| `<n>_aligned` | int | `0` → `ALIGN_NONE`, **anything else** → `ALIGN_CENTER` | Not a bitfield in the cfg. |
| `<n>_scaled` | int | `0` → `SCALING_NONE`, else `SCALING_RATIO` | Widescreen aspect correction, §9.2. |
| `<n>_color` | color | `#RRGGBB` | Alpha forced to `0x80`. |
| `<n>_font` | int | accepted only if `0 < v < 16` | **`font=0` is rejected** by the `intValue > 0` test, so it leaves the per-type default (which is `fonts[0]` anyway — same result). |

`POS_MID` / `DIM_INF` are matched with `strncmp(temp, "POS_MID", 7)` — a **prefix** match, so
`POS_MIDDLE` or `POS_MIDx` also match.

### 6.2 Text attributes (`initMutableText`, `themes.c:99`)

Apply to `StaticText`, `AttributeText`, `GameCountText`.

| Key | Applies to | Meaning |
|---|---|---|
| `<n>_value` | `StaticText` | The literal string. **Mandatory** — without it the element is created but never drawn (`themes.c:198`). |
| `<n>_attribute` | `AttributeText` | Per-game config key to display (`Title`, `Genre`, `Release`, `Developer`, `Size`, `Description`, or `#`-prefixed raw keys). **Mandatory**, same failure mode. |
| `<n>_title` | `AttributeText` | Overrides the printed label. Default: the attribute name with a leading `#` stripped. |
| `<n>_display` | text | `0` = `DISPLAY_ALWAYS` (label shown even with no value), `1` = `DISPLAY_DEFINED`, `2` = `DISPLAY_NEVER` (value only, no label). Default **0** for all three text types. |
| `<n>_wrap` | text | `>0` ⇒ `SIZING_WRAP` (word wrap via `fntFitString`). Default: no wrap. |

**Sizing mode is derived, not just declared** (`themes.c:122`):

* If **both** `width` and `height` are unset (`DIM_UNDEF`) → `SIZING_NONE`: `fntRenderString` is
  called with `width=0, height=0`, meaning **no clipping and no newline handling at all**.
* If **either** is set → mode becomes `SIZING_CLIP` (unless `_wrap` raised it to `SIZING_WRAP`),
  and the unset dimension is filled with 640 / 480.

The known label strings are localized; `Size` gets a `" MiB"` suffix appended to its value
(`themes.c:256`). With `wrap=1` an `AttributeText` label ends in `":\n"` instead of `": "`
(`themes.c:164`).

### 6.3 Image attributes (`initMutableImage`, `themes.c:457`)

Apply to `StaticImage`, `AttributeImage`, `GameImage`, `ItemIcon`, `ItemCover`, `Background`.

| Key | Applies to | Meaning |
|---|---|---|
| `<n>_pattern` | `GameImage`, `Background` | Art suffix, e.g. `COV`, `ICO`, `BG`, `SCR`. **Mandatory for `GameImage`** — without it the element never draws (`themes.c:594`). |
| `<n>_count` | `GameImage`, `Background` | Number of cache slots (§6.5). |
| `<n>_attribute` | `AttributeImage` | Per-game config key whose *value* selects the image. Mandatory. |
| `<n>_default` | all image types | Fallback image, **filename without extension**, relative to the theme folder. |
| `<n>_overlay` | all except `Background` | Overlay frame image, extension-less. |
| `<n>_overlay_ulx/uly/urx/ury/llx/lly/lrx/lry` | overlay users | Corner offsets of the inlay quad, in 640×480 units, relative to the overlay quad's top-left. Default **uninitialized** — see §11.3. |

### 6.4 How an asset filename is resolved

`initImageTexture` (`themes.c:355`) builds `themePath + imgName` and calls `texDiscoverLoad`
(`src/textures.c:552`), which appends exactly one extension:

```c
snprintf(filePath, "%s.%s", path, "png");
```

> **`default` and `overlay` values must not include an extension, and only `.png` is ever tried.**

`.jpg` and `.bmp` support was removed in commit `c5a12a0` (2024-10-22). Themes made for OPL ≤1.1.0
that ship `.jpg` art will render those elements blank on current main.

`findDuplicate` (`themes.c:305`) scans all four chains and shares an already-loaded cache /
default texture / overlay texture when the pattern or filename string matches, so re-using the
same image across elements costs memory only once.

### 6.5 `count` and per-game art

Game art lives outside the theme, in the device's `ART` folder. `bdmGetImage`
(`src/bdmsupport.c:578`) builds:

```
<device>ART/<STARTUP>_<PATTERN>.png      e.g.  mass:ART/SLUS_200.02_COV.png
```

`<STARTUP>` is the game's startup id (`SLUS_200.02`), `<PATTERN>` the element's `pattern`.
Conventional patterns: `COV` (front cover), `COV2` (back), `ICO` (icon), `BG` (background),
`SCR`/`SCR2` (screenshots), `LGO` (logo). None of these are hard-coded in the renderer — `pattern`
is an arbitrary string; only `ItemIcon`/`ItemCover` preset it.

`count` (`cacheInitCache`, `src/texcache.c:80`) allocates `count` decoded textures held in RAM
simultaneously. **This is the PS2 out-of-memory lever:** cost = `count × source width × height × 3
bytes` (decoded to `GS_PSM_CT24`). A 512×512 cover with `count=20` is ~15 MB against a 32 MB console.

Note the dimensions are those of the **image file**, not the element. `texLoad` decodes the PNG at
its native size; the element's `width`/`height` only scale the draw quad. Shrinking an element saves
no memory at all — only smaller art files or a lower `count` do.

### 6.6 Which attributes are valid for which type

| Attribute | AttrText | StaticText | GameCountText | AttrImage | GameImage | StaticImage | ItemIcon/ItemCover | Background | ItemsList | others |
|---|---|---|---|---|---|---|---|---|---|---|
| `enabled`, `type`, `x`, `y`, `width`, `height`, `aligned`, `scaled`, `color`, `font` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `value` | – | **req** | – | – | – | – | – | – | – | – |
| `attribute` | **req** | – | – | **req** | – | – | – | – | – | – |
| `title`, `display`, `wrap` | ✓ | ✓ | ✓ | – | – | – | – | – | – | – |
| `pattern` | – | – | – | – | **req** | – | ✓ | ✓ | – | – |
| `count` | – | – | – | – | ✓ | – | ✓ | ✓ | – | – |
| `default` | – | – | – | ✓ | ✓ | **req** | ✓ | ✓ | – | – |
| `overlay`, `overlay_*` | – | – | – | ✓ | ✓ | ✓ | ✓ | – | – | – |
| `decorator` | – | – | – | – | – | – | – | – | ✓ | – |

"req" = element is constructed but never draws if the key is missing. Unknown keys are simply
never read — they cost nothing and are preserved on round-trip.

---

## 7. Per-type defaults (verbatim from `addGUIElem`, `themes.c:1023-1083`)

Arguments are `initBasic(name, type, x, y, aligned, width, height, scaled, color, font)`.
`-1` = `DIM_UNDEF` (use the texture's intrinsic size). `TEXT` = `theme->textColor`;
`TINT` = `gDefaultCol` = `RGBA(0x80,0x80,0x80,0x80)` (neutral texture multiply).

| `type=` | x | y | aligned | width | height | scaled | color | font |
|---|---|---|---|---|---|---|---|---|
| `AttributeText` | 0 | 0 | CENTER | -1 | -1 | RATIO | TEXT | 0 |
| `StaticText` | 0 | 0 | CENTER | -1 | -1 | RATIO | TEXT | 0 |
| `GameCountText` | 0 | 0 | CENTER | -1 | -1 | RATIO | TEXT | 0 |
| `AttributeImage` | 0 | 0 | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `GameImage` | 0 | 0 | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `StaticImage` | 0 | 0 | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `Background` | 0 | 0 | **NONE** | **640** | **480** | **NONE** | TINT | 0 |
| `MenuIcon` | **320** | **400** | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `MenuText` | **320** | **20** | CENTER | **200** | **20** | RATIO | TEXT | 0 |
| `ItemsList` (1st) | 0 | 0 | **NONE** | -1→640 | -1→398 | RATIO | TEXT | 0 |
| `ItemsList` (2nd) | **42** | **42** | NONE | **400** | **360** | RATIO | TEXT | 0 |
| `ItemIcon` | 0 | 0 | CENTER | **64** | **64** | RATIO | TINT | 0 |
| `ItemCover` | 0 | 0 | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `ItemText` | 0 | 0 | CENTER | -1 | -1 | RATIO | TEXT | 0 |
| `HintText` | **16** | **-32 → 448** | NONE | **12** | **20** | RATIO | TEXT | 0 |
| `InfoHintText` | **16** | **-32 → 448** | NONE | **12** | **20** | RATIO | TEXT | 0 |
| `LoadingIcon` | **-40 → 600** | **-60 → 420** | CENTER | -1 | -1 | RATIO | TINT | 0 |
| `BdmIndex` | **320** | **355** | CENTER | -1 | -1 | RATIO | TINT | 0 |
| injected `bg` | 0 | 0 | NONE | 640 | 480 | NONE | TINT | 0 |
| injected `il` | 42 | 42 | NONE | **373** | **316** | RATIO | TEXT | 0 |

Type-specific extra presets: `ItemIcon` → `pattern=ICO count=20`; `ItemCover` → `pattern=COV
count=10`; `GameImage` → `count=1`; `AttributeImage` → `count=1`; injected `bg` → `pattern=BG
count=1`.

For `HintText`/`InfoHintText`, `width` is not a box width — it's the **gap between hint items**
(`themes.c:927`, `x += elem->width`).

---

## 8. Theme-level settings (`thmLoad`, `themes.c:1246`)

| Key | Default | Effect |
|---|---|---|
| `bg_color` | `#28C5F9` | Tint of the procedural plasma background. Only used when no Background image resolves. |
| `text_color` | `#FFFFFF` | Default `color` for all text-ish elements. |
| `ui_text_color` | `#5868B4` | OPL's own menus/dialogs — **never** used by main/info page elements. Out of scope for the previewer. |
| `sel_text_color` | `#00AEFF` | Selected `ItemsList` row. Not overridable per element. |
| `use_default` | `1` | If `1`, icons missing from the theme fall back to OPL's built-in graphics. If `0`, they're absent. |
| `use_real_height` | `0` | Sets `usedHeight = screenHeight`. **Currently a no-op** — see below. |
| `default_font` | built-in | TTF filename (with extension) relative to the theme folder → font slot 0. |
| `default_font_size` | `17` | `FNTSYS_DEFAULT_SIZE`; `<= 0` falls back to 17. |
| `font1` … `font15` | = slot 0 | Additional TTFs → slots referenced by `<n>_font`. |
| `font1_size` … | `17` | Per-slot size. |

`use_real_height`: `rmGetScreenExtents` **always returns 640×480** by definition
(`src/renderman.c:257`) — the whole theme space is virtual and renderman scales it to the real
video mode. So `screenHeight == 480 == usedHeight` unconditionally, and the negative-`y` formula
`ceil((480 + y) * usedHeight / 480)` collapses to `480 + y`. Left in the previewer for fidelity but
it changes nothing.

Ordering note: `thmSetColors` (`themes.c:1194`) resets **every element's color to `textColor`** —
but it's called *before* elements are parsed during load, so per-element `color` wins. It's called
again on `thmSetGuiValue` only for the built-in theme.

---

### 8.1 Things a theme cannot control (they live in `conf_opl.cfg`)

Repeatedly mistaken for theme keys. All of these are global OPL settings, edited
in OPL's own Settings screen or in `conf_opl.cfg`, and no `conf_theme.cfg` key
influences them.

| Key | Default | What it does |
|---|---|---|
| `autosort` | **1 (on)** | Sorts each device's list. `submenuSort` (`menusys.c:561`) is a bubble sort on `strcasecmp` of the displayed title, so **case-insensitive alphabetical**. Runs once per list refresh, after the list is built. |
| `scrolling` | 1 | **Not** text scrolling and not list scrolling — it is the D-pad auto-repeat delay. `0/1/2` maps to `500/300/100` ms (`gui.c:1636`). |
| `remember_last` | 0 | Stores one `last_played` string in `conf_last.cfg` and preselects that entry on the device's list (`opl.c:660`, `opl.c:685`). It is a **single** value, not a history. |
| `autostart_last` | 0 | Launches that entry after a countdown. |
| `enable_coverart` | 1 | Master switch for all `GameImage` art (`gEnableArt`). With it off, every art element falls back to its `default`. |

**There is no recently-played list in OPL's data.** `OSDHistory.c` does maintain
the PS2's own OSD history — `name[16]`, `LaunchCount`, `DateStamp` per title —
but OPL only ever *writes* to it (`AddHistoryRecordUsingFullPath`, `system.c:813`).
Nothing reads it back for display, and no element type exposes it.

**Sorting is not selectable at runtime.** There is one comparator and no key
bound to change it. Themes have no input handling of any kind, so a "sort" button
cannot come from a `conf_theme.cfg`. (`patches/02-opl-sort-and-recent.patch` adds
a `sort_mode` setting cycled with R3, and a real recently-played list with
`RecentImage`/`RecentText` elements to display it.)

## 9. Rendering geometry

The theme space is a virtual **640×480 square-pixel** canvas
(`rmGetScreenExtents`, `renderman.c:257`); renderman maps it to whatever the real video mode is.

### 9.1 Images (`rmSetupQuad`, `renderman.c:279`)

```c
if (w == DIM_UNDEF) w = txt->Width;
if (h == DIM_UNDEF) h = txt->Height;
w = (scaled & SCALING_RATIO) ? (w * iAspectWidth) >> 2 : w;      // aspect correction
if (aligned & ALIGN_HCENTER) ul.x = x - (w >> 1); else ul.x = x;  // ALIGN_RIGHT unreachable from cfg
if (aligned & ALIGN_VCENTER) ul.y = y - (h >> 1); else ul.y = y;
```

Since `_aligned` maps only to `ALIGN_NONE` (0) or `ALIGN_CENTER` (`VCENTER|HCENTER`), the practical
rule is: **`aligned=0` ⇒ `(x,y)` is the top-left corner; `aligned=1` ⇒ `(x,y)` is the center.**
Images are **stretched** to `width`×`height`; aspect ratio is never preserved.

### 9.2 Widescreen — what `scaled` actually does

`iAspectWidth` is **4** in 4:3 and **3** in 16:9 (`rmSetAspectRatio`, `renderman.c:412`). With
`SCALING_RATIO`, width is multiplied by `iAspectWidth/4`, i.e. **× 0.75 in 16:9**. The whole 640×480
canvas is then stretched horizontally to fill a 16:9 display, and the two cancel out.

> `scaled=1` means "keep this element's real-world aspect ratio in widescreen".
> `scaled=0` means "let it stretch with the screen".
> **Positions (`x`, `y`) are never aspect-corrected** — only widths.

This is why the previewer's 16:9 toggle must multiply `width` by 0.75 for `scaled=1` elements
*before* stretching the canvas, rather than just stretching the final image.

### 9.3 Text (`fntRenderString`, `fntsys.c:502`)

```c
if (aligned & ALIGN_HCENTER)
    x -= (width ? min(textWidth, width) : textWidth) >> 1;
if (aligned & ALIGN_VCENTER) y += (fontSize - 4) >> 1;   //  +6 at size 17
else                         y += (fontSize - 2);        // +15 at size 17
```

The adjusted `y` is the **baseline**; each glyph is drawn at `y - bitmap_top` (`fntsys.c:465`).
So for the default size-17 font: `aligned=0` puts the baseline 15px below the declared `y`;
`aligned=1` puts it 6px below `y` **and** horizontally centers the string on `x`.

Clipping/wrapping (only active when `width != 0`, i.e. `SIZING_CLIP`/`SIZING_WRAP`):

* `\n` resets the pen to `x` and advances `y` by **19** (`MENU_ITEM_HEIGHT`, not the font size).
* `y > ymax` breaks out of the loop entirely.
* A glyph that would cross `xmax` sets `pen_x = xmax + 1`, so the **rest of the line is dropped**
  (no ellipsis, and no smaller following glyph sneaks in).
* Word wrap (`fntFitString`, `fntsys.c:735`) is applied **once at load time** and mutates the
  string in place, replacing spaces with `\n`. A word longer than the box gets a break forced
  after it, so it overflows.

Advance width is `glyph->shx >> 6` plus FreeType kerning — real font metrics, no fixed advance.

### 9.4 Font metrics to reproduce

The built-in font is **`thirdparty/PoeVeticaNew.ttf`** (`Makefile:706`, embedded via
`poeveticanew.c`), loaded at `FNTSYS_DEFAULT_SIZE = 17` with `FT_Set_Char_Size(17*64, 17*64, 72, 72)`
(`fntsys.c:460`, `fDPI = 72.0f`) — i.e. **17px em, 1:1 pixel aspect** in the virtual 640×480 space.

The TTF is copied to `assets/PoeVeticaNew.ttf` and the previewer loads it as a webfont, so glyph
advances and kerning come from the same file FreeType uses. Remaining differences vs. the console
are listed in the README: browser hinting/subpixel positioning vs. FreeType's, and the fact that on
a real PS2 the char size is re-derived from the video mode's pixel aspect ratio
(`fntUpdateAspectRatio`, `fntsys.c:440`) — the previewer assumes the square-pixel VGA case where
`ws = hs = 1`.

---

## 10. Documentation discrepancies

Code wins in every row below.

| # | Official guide says | Code does | Impact |
|---|---|---|---|
| 1 | "GameImage and StaticImage accept `.png` and `.jpg`" | `texDiscoverLoad` appends **only** `".png"`. JPG/BMP removed 2024-10-22 (`c5a12a0`). | High — `.jpg` themes silently lose images on 1.2.0. |
| 2 | `ItemsList` has an `items=` attribute for max display count | **No such key.** `displayedItems = height / 19`. | High — `items=` is silently ignored; authors must size by `height`. |
| 3 | "`-1` forces infinite width/height for frame scaling" | `-1` is `DIM_UNDEF` = *use the texture's own size*. The infinite value is the literal string **`DIM_INF`**. | High — opposite meaning. |
| 4 | `ItemIcon` cache default listed as both **20** and **30** | **20** (`count=20`). `ItemCover` is **10** ✓. | Medium |
| 5 | `ItemIcon` default `default=disc` | No default texture is preset in code; `disc` comes from the shipped theme cfg, not the engine. | Low |
| 6 | "Background … If placed elsewhere, it's ignored and replaced with a default" | Accurate, but incomplete: the index is still **consumed**, and the injected default reads `bg_*` keys. | Low |
| 7 | "color … defaults to theme's text_color" | True for text elements; **image** elements default to `gDefaultCol` (`#808080` neutral multiply), where `#FFFFFF` would *brighten* the texture 2×. | Medium |
| 8 | Numbering: "Gaps will cause OPL to ignore subsequent elements" ✓ | Confirmed — but the guide doesn't say that an **invalid `type` does *not* stop the scan**, nor that `enabled=0` doesn't either. | Medium |
| 9 | Doesn't mention it | **Negative `x`/`y` are relative to the right/bottom edge** (`640+x`, `480+y`) — used constantly by the shipped theme. | High (undocumented, essential) |
| 10 | Doesn't mention it | `POS_MID`/`DIM_INF` are matched by **7-char prefix**, so `POS_MIDDLE` also works. | Trivial |
| 11 | Doesn't mention it | A color without a leading `#` parses as **black**, not as an error. | Medium |
| 11b | Doesn't mention it | A **comment containing `:`** is parsed as a section header and silently re-homes every key under it (§1.4). | High (easy to hit, invisible) |
| 12 | `AttributeText` / `AttributeImage` listed as "Information Page Only" | Nothing in the code restricts them to `info*`; they work on `main*` too (they just need a per-game config to read). | Low |
| 13 | Doesn't mention it | `decorator` is dropped when the target's `count < displayedItems`. | Medium |
| 14 | Doesn't mention it | `GameCountText` (2024-11-15) and `BdmIndex` (2024-07-30) exist; `appsMain*`/`appsInfo*` (2024-08-16) exist. | Medium |

---

## 11. Judgment calls

Logged per the working-style instruction; each is a place where the C source was ambiguous,
untestable in a browser, or describes hardware behavior with no web equivalent.

1. **`use_real_height` is treated as a no-op.** The code path exists but `screenHeight` is a
   compile-time-constant 480, so it can never change anything. The previewer parses and displays
   the key, applies the formula literally, and notes it in the inspector.
2. **`ui_text_color` is parsed but never rendered.** It only affects OPL's own settings dialogs,
   which are explicitly out of scope. Shown in the theme-settings panel, unused by the canvas.
3. **Overlay corner offsets default to uninitialized memory.** `initImageTexture` mallocs
   `image_texture_t` and only assigns `upperLeft_x` etc. *if the key is present* (`themes.c:381`) —
   there is no zero-init. On a real PS2 an overlay with a partial set of `overlay_*` keys draws with
   garbage corners. The previewer defaults the missing ones to **0** (the sane interpretation) and
   emits a warning that OPL's behavior here is undefined.
4. **Duplicate-key resolution.** `configSetStr` overwrites the existing node's value in place, so
   the *last* value wins while keeping the *first* line's position. The previewer's writer edits
   the last occurrence and warns about the duplicate.
5. **`>6` hex digits in a color** can write past `color[2]` in `strToColor`. Rather than emulate a
   buffer overrun, the previewer parses the first 6 digits and warns.
6. **Plasma background.** `guiDrawBGPlasma` is a frame-incremental Perlin field with a color that
   eases toward `bg_color` over many frames (`gui.c:1269`), and only `PLASMA_ROWS_PER_FRAME` rows
   update per frame. The previewer renders a **static** approximation of the converged plasma
   tinted by `bg_color`, since animation isn't what a layout tool needs; toggleable to a flat fill.
7. **Text rendering.** Browser text layout can't match FreeType glyph-for-glyph even with the same
   TTF. The previewer uses the real `PoeVeticaNew.ttf` at 17px with the baseline offsets from
   §9.3, and measures via canvas `measureText` for the centering/clipping math. Sub-pixel
   differences of ±1px are expected and documented.
8. **`ItemsList` decorator misalignment (§5.2).** Reproduced as-is rather than "fixed", because
   the point of the tool is to show what OPL will actually draw. Flagged in the validation panel as
   an informational note when `aligned=1` and a decorator are combined.
9. **`_font=0`.** Rejected by `intValue > 0`, but the fallback is `fonts[0]`, so the outcome is
   identical to accepting it. Not warned about.
10. **Art suffix conventions** (`COV`/`ICO`/`BG`/`SCR`/`LGO`) are theme-community convention, not
    engine constants — only `ICO` and `COV` appear in the C source, as `ItemIcon`/`ItemCover`
    presets. The previewer offers these as suggestions but accepts any string.
