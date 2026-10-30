/*
 * Grid view: covers in rows and columns (docs/MULTI-VIEW-THEMES-PLAN.md step 6; multi-view themes idea by
 * KrahJohlito). The layout and navigation arithmetic lives here so the host tests can check it.
 */
#ifndef GRID_H
#define GRID_H

#define GRID_DEFAULT_ROWS    3
#define GRID_DEFAULT_COLUMNS 4
#define GRID_MAX_ROWS        4
#define GRID_MAX_COLUMNS     8  // RIPPS2's 8 x 3 Compact on a 16:9 picture
#define GRID_MAX_CELLS       24 // a page; the cover cache holds two (one slides out as the next slides in)
#define GRID_DEFAULT_SPACING 16

// Clamps a theme's rows/columns so the grid stays within GRID_MAX_CELLS; columns win over rows.
static inline void gridClamp(int *rows, int *columns)
{
    if (*columns < 1)
        *columns = GRID_DEFAULT_COLUMNS;
    if (*columns > GRID_MAX_COLUMNS)
        *columns = GRID_MAX_COLUMNS;
    if (*rows < 1)
        *rows = GRID_DEFAULT_ROWS;
    if (*rows > GRID_MAX_ROWS)
        *rows = GRID_MAX_ROWS;
    while (*rows > 1 && *rows * *columns > GRID_MAX_CELLS)
        (*rows)--;
}

// The first row on screen. The grid shows whole pages, rows high: the page holding the selection stays
// still while the cursor moves on it and turns as a whole when the cursor leaves it, so a cover never
// changes cell under the cursor (RIPPS2 build 82, by akilluminati47). A short last page keeps its covers
// in their cells, from the top.
static inline int gridTopRow(int count, int index, int rows, int columns)
{
    if (count <= 0 || index < 0 || rows < 1 || columns < 1)
        return 0;
    if (index >= count)
        index = count - 1;
    return index / columns / rows * rows;
}

// L1 (dir < 0) or R1 (dir > 0): a whole page back or on, the cursor keeping its place on the page. On the
// last page R1 takes its last cover when the cursor would land past the end. -1 when there is no page
// that way: the caller wraps to the other end, as L1/R1 do in the list (RIPPS2 build 98, akilluminati47).
static inline int gridPageStep(int count, int index, int rows, int columns, int dir)
{
    if (count <= 0 || rows < 1 || columns < 1 || index < 0 || index >= count)
        return -1;
    int page = rows * columns;
    if (dir < 0)
        return index >= page ? index - page : -1;
    if (index - index % page + page >= count)
        return -1;
    return index + page < count ? index + page : count - 1;
}

// The selected cover is drawn this much larger (percent) and last, over its neighbours (RIPPS2 build 78).
#define GRID_SELECTED_SCALE 112

// Up (dir < 0) or Down (dir > 0) one row, keeping the column. A short last row takes its last cover.
// -1 when there is no row that way: the cursor stays when the device sidebar is on (devices change there,
// as in RIPPS2's grid), else the caller switches device page, as Up/Down do in Coverflow.
static inline int gridRowStep(int count, int index, int columns, int dir)
{
    if (count <= 0 || columns < 1 || index < 0 || index >= count)
        return -1;
    int row = index / columns, lastRow = (count - 1) / columns;
    if (dir < 0)
        return row == 0 ? -1 : index - columns;
    if (row == lastRow)
        return -1;
    return index + columns < count ? index + columns : count - 1;
}

// Settings > Interface > Coverflow Settings > Grid Layout, after RIPPS2's (build 91/98, akilluminati47): 0 the
// theme's own layout, else a preset that replaces the theme's rows, columns, cover size and spacing. A 16:9
// picture draws a cover at three quarters of its width, so each preset has a wider twin for it.
#define GRID_LAYOUTS 4 // presets, after "Theme"
typedef struct
{
    int columns, rows, width, height, spacing;
} grid_layout_t;

// 1 and the preset in *out for layout 1..GRID_LAYOUTS; 0 (the theme's) for anything else.
static inline int gridLayoutPreset(int layout, int wide, grid_layout_t *out)
{
    static const grid_layout_t sd[GRID_LAYOUTS] = {{4, 2, 107, 150, 12}, {5, 2, 86, 120, 10}, {3, 2, 112, 157, 16}, {6, 3, 66, 92, 8}};
    static const grid_layout_t hd[GRID_LAYOUTS] = {{6, 2, 107, 150, 12}, {7, 2, 96, 135, 10}, {5, 2, 112, 157, 16}, {8, 3, 66, 92, 8}};
    if (layout < 1 || layout > GRID_LAYOUTS)
        return 0;
    *out = wide ? hd[layout - 1] : sd[layout - 1];
    return 1;
}

// Is index in the page's first column? Left there opens the device sidebar.
static inline int gridAtRowStart(int count, int index, int columns)
{
    return count <= 0 || columns < 1 || index < 0 || index % columns == 0;
}

// The page slide (RIPPS2 build 82): how far (0..1) the new page has come in, t the slide's elapsed fraction.
// Eased out, cubic, as RIPFLOW's carousel is.
static inline float gridSlideEase(float t)
{
    if (t <= 0.0f)
        return 0.0f;
    if (t >= 1.0f)
        return 1.0f;
    float r = 1.0f - t;
    return 1.0f - r * r * r;
}

#endif
