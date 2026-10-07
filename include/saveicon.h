#ifndef __SAVEICON_H
#define __SAVEICON_H

/*
  3D save icons (fork-gaps OR1, ORBIT parity): the selected PS2 game's newest save -- in the game's own
  per-game VMC first, then on a physical memory card -- with its list icon spun, animated and lit
  inside a theme's SaveIcon element.

  Written from the published PS2 save formats (the icon.sys layout matches ps2sdk's mcIcon, the card
  filesystem matches OPL's own vmc_superblock_t); no code from other launchers. Threading: the IO
  worker finds and parses; the GUI thread alone owns the model on screen and its texture, adopting a
  finished load at draw time, so gsKit's texture manager is only ever touched by the thread that draws.
*/

#define SAVEICON_TEX_SIZE   128          // icon textures are 128x128, 16-bit A1B5G5R5
#define SAVEICON_MAX_SHAPES 32           // animation shapes (morph targets) per icon
#define SAVEICON_MAX_VERTS  6000         // ~2000 triangles: well inside one frame's gsKit queue
#define SAVEICON_MAX_POS    48000        // shapes x vertices: the morph-target storage bound
#define SAVEICON_MAX_KEYS   1024         // keys per shape
#define SAVEICON_MAX_FILE   (512 * 1024) // largest icon file read
#define SAVEICON_SYS_SIZE   964          // icon.sys
#define SAVEICON_SYS_LIST   0x104        // icon.sys: list-icon file name (64 bytes)
#define SAVEICON_PATH_SIZE  192          // a per-game VMC path: device prefix + "VMC/" + name + ".bin"

typedef struct
{
    float time;
    float value;
} saveicon_key_t;

typedef struct
{
    int shapes;
    int verts;           // a multiple of 3: a plain triangle list
    short *pos;          // [shape][vert][3] in 4.12 fixed point; +x right, +y DOWN, +z into the screen
    short *normal;       // [vert][3] in 4.12 fixed point
    short *uv;           // [vert][2] in 4.12 fixed point of the texture (4096 = full width)
    unsigned char *rgba; // [vert][4] already in the GS colour scale (0x80 = 1.0)
    int frameLength;     // animation length in frames (60 per second)
    float speed;         // animation speed factor; 0 means 1
    int keyCount[SAVEICON_MAX_SHAPES];
    saveicon_key_t *keys[SAVEICON_MAX_SHAPES];
    unsigned short *texels; // SAVEICON_TEX_SIZE^2 A1B5G5R5, or NULL for an untextured icon
} saveicon_model_t;

typedef struct
{
    float dir[3][3];   // three directional lights (icon.sys)
    float color[3][3]; // their colours, 1.0 = full
    float ambient[3];
    int valid;
} saveicon_light_t;

// Pure, bounds-checked parse of a PS2 icon file (.icn/.ico). 0 = *model filled (free with
// saveIconFreeModel); negative = a file that cannot be trusted, and *model is left empty.
int saveIconParseModel(const unsigned char *data, int size, saveicon_model_t *model);
void saveIconFreeModel(saveicon_model_t *model);

// icon.sys: copies the list-icon file name into listName (refused when it is not a plain file name)
// and the save's lights into *light. 1 = usable, 0 = not an icon.sys.
int saveIconParseSys(const unsigned char *data, int size, char *listName, int listSize, saveicon_light_t *light);

// "SLUS_200.62" -> "SLUS-20062", the product code inside a save folder name (BASLUS-20062...).
// 1 = done; 0 = not a retail boot-file name.
int saveIconSerialForStartup(const char *startup, char *serial, int serialSize);
// Does this memory-card folder name belong to that product code? (B + region + serial + anything)
int saveIconFolderMatches(const char *folder, const char *serial);

// Animation: each shape's weight at time t (frames), written to weights[shapes]; returns their sum.
float saveIconShapeWeights(const saveicon_model_t *model, float t, float *weights);

// A memory-card image -- a VMC .bin, with or without the per-page ECC spare -- read through readFn
// (bytes read, or < 0): the newest save folder of that product code in its root, its icon.sys lights
// and its list icon. 1 = *model filled; 0 = no such save, not a card image, or a damaged one.
typedef int (*saveicon_read_t)(void *ctx, unsigned int offset, void *buf, int size);
int saveIconFromCardImage(saveicon_read_t readFn, void *ctx, unsigned int imageSize, const char *serial,
                          saveicon_model_t *model, saveicon_light_t *light);

// GUI thread, every frame the element draws. startup = the selected PS2 game's boot file (NULL or ""
// for none); vmc0/vmc1 = full paths of its per-game VMCs ("" for a slot without one), meaningful only
// when vmcKnown (its per-game config has loaded). Cheap; the cards are read once the row settles.
void saveIconSelect(const char *startup, const char *vmc0, const char *vmc1, int vmcKnown);
// GUI thread. Draws the selected game's icon, once loaded, centred on (cx, cy) and fitted to a w x h
// box, all in virtual 640x480 units; xScale narrows x for a 16:9 display (1.0 at 4:3).
void saveIconDraw(int cx, int cy, int w, int h, float xScale);
// Forget everything: the setting turned off, or shutdown. GUI thread.
void saveIconReset(void);

#endif
