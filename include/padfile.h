/*
  padfile.h .pad, HID device profiles for PADEMU (RIPPS2 build 126): the packed block

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  The format is RIPPS2's (its pad-spec.md, version 1; docs/PAD-PROFILES.md here). A launcher reads the text files (PADS/VVVV_PPPP.pad,
  PADS/GAMES/<ELF name>.pad), checks them, and hands PADEMU one fixed block of PAD_BLOCK_SIZE bytes, the way PADEMU's settings
  already ride to it: the IOP never parses text or opens a file during a game. Everything here is plain C with no PS2
  headers, so the same file builds into a launcher, ee_core, an IRX or a PC tool. All multi-byte fields are little endian.
*/

#ifndef __PADFILE_H
#define __PADFILE_H

#ifdef __cplusplus
extern "C" {
#endif

#define PAD_FORMAT      1   // the text format's version (format=1) and the block's (byte 2)
#define PAD_DEFS_MAX    4   // user profiles in one block
#define PAD_DEF_SIZE    40  // one profile, packed
#define PAD_BLOCK_SIZE  180 // 4 header + 4 x 40 profiles + 16 game map
#define PAD_REF_NONE    0xFF
#define PAD_BYTE_MAX    31 // a button's byte, after offset (5 bits)
#define PAD_AXIS_INVERT 0x80
#define PAD_REMAP_SAME  0xFF

// decoder= : generic is the profile's own map; the others name PADEMU's built-in decoders (pressure, touchpad, frets)
enum { PAD_DEC_GENERIC = 0,
       PAD_DEC_DS3,
       PAD_DEC_DS4,
       PAD_DEC_GUITAR_GH,
       PAD_DEC_GUITAR_RB,
       PAD_DEC_COUNT };

// flags
#define PAD_F_RUMBLE_DS3 0x01
#define PAD_F_RUMBLE_DS4 0x02
#define PAD_F_LED_DS3    0x04
#define PAD_F_LED_DS4    0x08
#define PAD_F_INIT_DS3   0x10 // send the F4 enable packet
#define PAD_F_REPORT_ID  0x20 // reports start with report_id, which is skipped

// The DualShock 2's buttons in its own bit order (bit n of the 16-bit button word, active low on the wire)
enum {
    PAD_B_SELECT = 0,
    PAD_B_L3,
    PAD_B_R3,
    PAD_B_START,
    PAD_B_UP,
    PAD_B_RIGHT,
    PAD_B_DOWN,
    PAD_B_LEFT,
    PAD_B_L2,
    PAD_B_R2,
    PAD_B_L1,
    PAD_B_R1,
    PAD_B_TRIANGLE,
    PAD_B_CIRCLE,
    PAD_B_CROSS,
    PAD_B_SQUARE,
    PAD_B_COUNT
};

enum { PAD_AX_LX = 0,
       PAD_AX_LY,
       PAD_AX_RX,
       PAD_AX_RY,
       PAD_AX_COUNT };

// One profile as it is packed (PAD_DEF_SIZE bytes, in this order, no padding)
typedef struct
{
    unsigned short vid, pid;           // from the file name
    unsigned char decoder;             // PAD_DEC_*
    unsigned char reportId;            // with PAD_F_REPORT_ID
    unsigned char offset;              // bytes skipped before byte 0 of the map
    unsigned char flags;               // PAD_F_*
    unsigned char deadzone;            // axis units round the centre that read as the centre
    unsigned char hat;                 // the d-pad's hat byte, or PAD_REF_NONE (then up/down/left/right are buttons)
    unsigned char axis[PAD_AX_COUNT];  // byte, PAD_AXIS_INVERT for a3-; PAD_REF_NONE: centred
    unsigned char button[PAD_B_COUNT]; // bits 0-4 the byte, bits 5-7 the bit; for an axis button the axis byte
    unsigned short present;            // bit n: button n is mapped
    unsigned short activeLow;          // bit n: button n is pressed at 0 (!b1.2)
    unsigned short fromAxis;           // bit n: button n is an axis pressed past half (l2=a7)
    unsigned char spare[4];
} pad_def_t;

// Text in, one profile out. vid and pid come from the file name (padFileId). 0 when it is usable, else -1 and err says
// why (a line number and what was wrong), never a half-filled profile
int padDefParse(const char *text, int len, unsigned vid, unsigned pid, pad_def_t *out, char *err, int errSize);

// A game's button map (PADS/GAMES/<ELF name>.pad): map[n] the button the game gets when button n is pressed
// (PAD_REMAP_SAME for itself). 0, or -1 with err
int padMapParse(const char *text, int len, unsigned char map[PAD_B_COUNT], char *err, int errSize);

// "054C_0268.pad" -> 0x054C, 0x0268; 0 when the name is a profile's
int padFileId(const char *name, unsigned *vid, unsigned *pid);

// The block PADEMU gets: "PD", PAD_FORMAT, the count, the profiles, the game map (NULL: none). Returns PAD_BLOCK_SIZE
int padBlockPack(const pad_def_t *defs, int count, const unsigned char *map, unsigned char out[PAD_BLOCK_SIZE]);

// The reverse, for the IRX and tests: 0 when the block is a version this code reads
int padBlockUnpack(const unsigned char *in, int size, pad_def_t defs[PAD_DEFS_MAX], int *count, unsigned char map[PAD_B_COUNT]);

// One report through a generic profile: the DS2 button word (active low, as the game reads it) and the four axes
// (0-255, 128 centre). The decoder PADEMU's generic path runs and the setup screen previews with
void padTranslate(const pad_def_t *def, const unsigned char *report, int len, unsigned short *buttons, unsigned char axes[4]);

// The game map on a DS2 button word (active low): each pressed button becomes the one the map names (PAD_REMAP_SAME
// itself, 0xFE nothing). padMapIsSame: 1 when the map changes nothing (the decoder skips it)
unsigned short padApplyMap(unsigned short buttons, const unsigned char map[PAD_B_COUNT]);
int padMapIsSame(const unsigned char map[PAD_B_COUNT]);

#ifdef __cplusplus
}
#endif

#endif
