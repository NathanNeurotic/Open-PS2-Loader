# Fresh-start defaults

These are the defaults for a fresh standard RiptOPL configuration. They apply
when no saved master configuration is loaded. Updating the ELF does not reset
saved settings, and a new installation folder can still discover settings on
another device.

| Setting | Fresh default | Where to change it |
| --- | --- | --- |
| Menu aspect ratio | 4:3; Widescreen off | Settings → Interface |
| Menu video mode | Auto; regional interlaced output | Settings → Interface |
| Theme | Built-in `<OPL>` | Settings → Interface → Theme |
| Theme View | Default (List for `<OPL>`); Coverflow (3), Coverflow (5), PSBBN Flow and Grid are optional views | Settings → Interface → Theme View, or hold L3 |
| Alternate Background | Off (the theme's `default=` background) | Settings → Interface → Alternate Background |
| Boot Theme Wait | Off (0 s: the menu opens without waiting for the saved theme) | Settings → Interface → Boot Theme Wait |
| Cover and disc artwork | On | Settings → Interface → Artwork Settings |
| Notifications | On | Settings → Interface |
| PS2 logo | On | Settings → Game Launching |
| Sound effects, boot sound, background music | Off; stored volume 90 | Settings → Audio Settings |
| USB and other storage transports | Off | Settings → Game Sources |
| Device/tab start modes, including network, Apps and Favorites | Off | Settings → Game Sources |
| Default menu preference | Apps, once enabled | Settings → General & System |
| Confirm button | Circle; configurable | Settings → General & System |
| Remember last played | Off | Settings → General & System |
| Automatic VMC creation | Off | Settings → Game Launching |
| All Games List | Off | Settings → Interface → Library, or Settings → Game Sources |
| Show Hidden Games | Off | Settings → Game Sources |
| Sort Games | A to Z (an out-of-range saved value also reads as A to Z) | Settings → Interface |
| Button Glyphs | Theme (the theme's own glyphs, or its `glyph_set` key) | Settings → Interface |
| GameID barcode | PS1 half On, PS2 half Off (shown as *On (PS1 only)*) | Settings → Interface |

The boot device can be enabled during discovery so that a loader started from
USB can still find its own files. This is a boot-path exception to the disabled
storage defaults, not a different display preset.

To use the previous widescreen/carousel presentation, select **Widescreen: On**
and **Theme View: Coverflow (3)** or **Coverflow (5)** under **Settings → Interface** (theme `<OPL>`), apply the changes,
then save. Coverflow works in both 4:3 and 16:9; selecting it does not enable
widescreen. A theme supplied with a separate package may have a different name.

For the PSBBN Definitive Project Game Collection look, choose **Theme View: PSBBN Flow** on the same page,
then apply and save. It also supports 4:3 and 16:9 without changing the aspect setting.
Both flow views use Left/Right to browse covers and Up/Down to change sources; R3 remains Favorite.
See [PSBBN Flow](THEME_ENGINE.md#psbbn-flow) for artwork and authoring details.

Existing `settings_riptopl.cfg` values override these defaults. The legacy
`conf_riptopl.cfg` can also be migrated. If the menu looks different after an
upgrade, inspect the active settings and configuration location rather than
deleting settings or saves to force a reset.

Menu video settings do not force the same video mode in games. **Triangle + Cross**
at boot is an explicit 480p menu-recovery override, not the fresh default;
**Triangle + Circle** selects Auto/interlaced recovery. Use the override suitable
for the connected display.

Implementation references: `setDefaults()` and saved-setting loading in
[src/opl.c](../src/opl.c), and the initial built-in theme and saved theme selection
in [src/themes.c](../src/themes.c). Coverflow tuning defaults are three covers,
Large center scale (45), 200 ms animation, and side-cover dimming off; they take
effect when a theme uses the `Coverflow` renderer. PSBBN Flow keeps its own fixed perspective
layout (rounded square focal cover, six-cover turned tail) and 25-frame cubic animation; these tuning values do not change it.

Experimental PC CARD CF and DESR DVR ISO discovery both default to **Off**. Enable them explicitly in Game Sources; hardware checks still apply. See [PC CARD CF](PC-CARD-CF.md) and [DESR DVR](DESR-DVR.md).
