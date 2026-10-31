# Multi-view themes: plan

Status: steps 1 to 4 are ported from RiptOPL (its PR #102) and live here; the rest is open. Nothing here is
hardware-tested. RiptOPL is the main line; this legacy tree gets every feature too.
Design idea: KrahJohlito (one theme cfg defines several views; views share elements and override only
what they declare; a button or setting switches views).

## Goal

One `conf_theme.cfg` can describe several **views** of the main and info pages: List, Coverflow,
PSBBN Flow and Grid. A view inherits every block it does not declare. The user picks the view with a
setting, and holding L3 cycles views. Themes that declare a single view keep working unchanged.

The unified All Games list is a separate, OPL-side feature. It decides which rows a page shows; a view
decides how rows are drawn. Neither touches the other's configuration.

## How themes work before this change

- `<Coverflow>` and `<PSBBN Flow>` were separate built-in themes, each with its own embedded cfg
  (`misc/theme_coverflow.cfg`, `misc/theme_psbbn_flow.cfg`). The List look is `misc/conf_theme_OPL.cfg`.
  Coverflow differs from List only in the presenter block (`Coverflow` instead of `ItemCover`); the menu
  icons, items list and the whole info page are identical.
- `main2:` in a cfg is a section prefix: the parser stores `main2_type`, `main2_y` and so on.
- Elements are parsed into families (main/info for games, apps, favs, vcd and the opt-in favsVcd/favsApps).
  A family inherits **by block index**: `appsMain<j>` if present, else `main<j>`.
- Textures and cover caches are shared between families by `findDuplicate`.
- There are four global `ItemsList` slots (games, apps, favs, vcd), claimed in parse order.

## Config syntax

```
views=list,coverflow
default_view=list

# base = List view
main2:
	type=StaticImage
	default=ip
# Coverflow replaces block 2
coverflow.main2:
	type=Coverflow
	default=cover
# kinds still work inside a view
coverflow.appsMain2:
	type=Coverflow
	default=coverapp
# switch a base block off in this view
coverflow.main16_enabled=0
# a view may add blocks past the base count
coverflow.main20:
	type=StaticText
	value=Hello
```

View names: `list`, `coverflow`, `psbbn`, `grid`. Unprefixed blocks are the base. The base should be the
List view so stock OPL and other forks, which ignore the prefixed keys, still load the theme as a list.

### Resolution order

For block `j` in view `V` and family kind `K` (for example `apps`), the first block present wins:

1. `V.KMain<j>` (for example `coverflow.appsMain2`)
2. `V.main<j>`
3. today's chain for `K` (for example `appsMain<j>`, and for vcd `vcdMain<j>` then `appsMain<j>`)
4. `main<j>`

`info<j>` resolves the same way. A view block replaces the whole base block (block-level, like
`appsMain` today); it never merges single keys from the base block, so a view that changes `type` gets
no stale keys.

`V.main<j>_enabled=0` (or any `V.<family><j>_enabled=0`) removes the block in that view only.

A view can declare blocks past the end of the base list. The block count of a view is the larger of the
base count and the view's own count.

### View-scoped global keys

`V.<key>` overrides a theme-wide key in that view, for example `coverflow.coverflow_cover_offset` or
`psbbn.use_real_height`. Colour keys follow today's rules (built-in themes carry none, see #574).

### Declared views

- `views=` lists the views the theme supports (L3 cycles them in the fixed order list, coverflow, psbbn, grid). Absent: the theme supports only its
  native view (detected from its base blocks: `PSBBNFlow` = psbbn, `Coverflow` = coverflow, else list),
  plus any view it declares blocks for.
- `default_view=` is the view used when the user has not chosen one. Absent: the native view.
- `auto_views=0` stops the loader from synthesising views the theme does not declare (step 5).

## Prerequisite: config key length

`CONFIG_KEY_NAME_LEN` was 32, and `favsVcdMain12_reflection_offset` is already 31 characters. A view
prefix would silently truncate keys, so the limit goes to 48 first (step 1). The longest prefixed key,
`coverflow.favsVcdMain12_reflection_offset`, is 41 characters. The cost is 16 bytes per loaded config
entry. Longer keys are still truncated as before: rejecting them would drop conf_apps.cfg titles that
load today. A side effect: app titles in conf_apps.cfg can now be up to 47 characters instead of 31.

## Switching

- A **Theme View** setting on the Interface page is the source of truth, saved as `theme_view=` in the
  OPL config. It is one choice for all themes: a theme that does not offer it shows its default view.
- **Hold L3** (about half a second) cycles to the next declared view; a tap on L3 stays the
  library-view ring and R3 stays favourites. The hint bar names the view.
- Phase 1 applies a view change by reloading the theme. It costs no extra EE RAM. Phase 2 keeps every
  declared view resident for an instant switch, only if the reload is too slow on real hardware.

## Auto-normalised views (fallback views)

For a view the theme does not declare, the loader keeps the theme's background, colours, fonts, menu icons,
hints and info page, and swaps only the presenter, using per-view rules by element type:

- Coverflow: hide `ItemCover` in main, add a `Coverflow` element from the built-in template.
- PSBBN Flow: hide `ItemCover`, add `PSBBNFlow`, move `ItemsList` to the template position.
- Grid: hide `ItemsList` and `ItemCover`, add `Grid`.
- List: hide flow elements, add `ItemsList`/`ItemCover` if the theme has none.

Shipped on by default for every disk theme without `views=` (owner's call, 2026-10-29): see
[THEME_ENGINE.md, Fallback views](THEME_ENGINE.md#fallback-views). Built for the active view only, from the
built-in template cfg of that view (`thmViewSynthesize`). NOT TESTED against community themes in PCSX2 yet.

## Steps

1. Raise `CONFIG_KEY_NAME_LEN` to 48; host test. (Done.)
2. View-aware block lookup in the theme loader: `views=`, `default_view=`, prefixed blocks, append and
   disable, view-scoped globals, `<view>.inherit=0`. Active view chosen at load; switching reloads.
   Host test of the resolution order. (Done.)
3. Built-in `<OPL>` offers List, Coverflow and PSBBN Flow as views. Each view keeps its own embedded cfg
   instead of one merged cfg, because editions (Korium) replace some of those cfgs at build time; the
   view picks the buffer. The separate `<Coverflow>` / `<PSBBN Flow>` entries are gone from the theme
   list; a saved name loads `<OPL>` with that view, and the next save writes `<OPL>` plus
   `theme_view=`. (Done; agreed 2026-10-28.)
4. **Theme View** setting (Interface page; Default, List, Coverflow, PSBBN Flow) saved as
   `theme_view=<name>` in the OPL config, and hold L3 (0.5 s) cycles the views the theme offers. A tap
   on L3 still advances the library-view ring; with a multi-view theme it acts on release. (Done.)
5. Auto-normalised views behind a setting.
6. `Grid` element: rows and columns of covers (theme-defined, default 3x4, at most 16 visible because
   `COVER_CACHE_SLOTS` is 20), Left/Right one cover, Up/Down one row, leaving for the next device page
   from the top or bottom row. Built-in `<OPL>` offers it as its fourth view. (Done.)
7. Phase 2 resident views, only if needed.
8. Theme-maker docs: `THEME_ENGINE.md`, site and wiki.
9. Port to legacy Open-PS2-Loader (`src/themes.c` has the same structure). (Steps 1 to 4 done.)

## Testing

Host tests (`.github/scripts/test_themeviews.py`, `.github/scripts/test_psbbn_flow.py`), a build, PCSX2 screenshots of each view
for the built-in theme and a few community themes, then one hardware pass: switch views, launch a game,
return, launch a second game, change theme with a view saved, cold and warm boot.

## SD and HD layouts

Separate 4:3 and 16:9 layouts live in the same file through `_sd`/`_hd` key variants, the uOPL/wOPL
`wsX` key and the opt-in `hd_autofit=1` (ideas: KrahJohlito and Berion). They are applied to the cfg
before the view is resolved, so they combine with every view rule above; see
[THEME_ENGINE.md, SD and HD layouts](THEME_ENGINE.md#sd-and-hd-layouts-_sd--_hd--this-fork).

## Alternate background

A second theme background in the same file, picked by **Settings → Interface → Alternate Background**:
`alt=` beside an element's `default=`, or once at the top level for every Background (idea:
KrahJohlito). It is applied after the SD/HD pass, so it combines with views and `_hd` keys; see
[THEME_ENGINE.md, Alternate background](THEME_ENGINE.md#alternate-background-alt--this-fork).

## Open questions

- Remember the view per theme only, or per device page too (like the L3 ring)?
- Auto-normalised views on by default, or opt-in?
- Is hold-L3 reliable on testers' pads and adapters?
- Grid shape: theme-defined rows and columns (decided; default 3x4).
- Can a theme force a different view for apps or PS1 pages?
