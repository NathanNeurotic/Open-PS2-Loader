/*
 * Grid view: covers in rows and columns (docs/MULTI-VIEW-THEMES-PLAN.md step 6; multi-view themes idea by
 * KrahJohlito). The layout and navigation arithmetic lives here so the host tests can check it.
 */
#ifndef GRID_H
#define GRID_H

#define GRID_DEFAULT_ROWS    3
#define GRID_DEFAULT_COLUMNS 4
#define GRID_MAX_ROWS        4
#define GRID_MAX_COLUMNS     6
#define GRID_MAX_CELLS       16 // the visible covers plus room to warm must fit COVER_CACHE_SLOTS (20)
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

// The first row on screen: the selected row sits in the middle where the list allows, and the grid
// never scrolls past its last row.
static inline int gridTopRow(int count, int index, int rows, int columns)
{
    int totalRows = (count + columns - 1) / columns;
    int top = index / columns - (rows - 1) / 2;
    if (top > totalRows - rows)
        top = totalRows - rows;
    return top < 0 ? 0 : top;
}

// Up (dir < 0) or Down (dir > 0) one row, keeping the column. A short last row takes its last cover.
// -1 when there is no row that way: the caller switches device page instead, as Up/Down do in Coverflow.
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

#endif
