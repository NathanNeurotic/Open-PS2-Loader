#ifndef __VMCSAVES_H
#define __VMCSAVES_H

// Saves inside a VMC image, handled as if the card were a folder (RIPPS2, akilluminati47; see vmcsaves.c).

enum {
    VMCSAVES_OK = 0,
    VMCSAVES_ERR_OPEN,      // the image cannot be opened
    VMCSAVES_ERR_NOT_CARD,  // not a PS2 card image, or a layout this does not know
    VMCSAVES_ERR_READ_ONLY, // an image with ECC (PCSX2's .ps2): read only here
    VMCSAVES_ERR_READ,      // a read failed, or the card's tables are damaged
    VMCSAVES_ERR_WRITE,     // a write failed
    VMCSAVES_ERR_NO_ROOM,   // not enough free space on the card
    VMCSAVES_ERR_NO_SAVE,   // no such save (or an empty folder)
    VMCSAVES_ERR_EXISTS,    // a save of that name is already there
    VMCSAVES_ERR_TOO_BIG,   // more than 64 files, or more than 8 MB
    VMCSAVES_ERR_NAME,      // a name longer than a card allows (32)
    VMCSAVES_ERR_MEMORY,
};

typedef struct
{
    char name[33];  // the save's folder name
    char title[69]; // its icon.sys title, in ASCII; empty when it has none
} vmc_save_t;

// Why the last call failed (VMCSAVES_ERR_*).
int vmcSavesError(void);
// 1 a card image this can change, 2 one with ECC (read only), 0 not a card image.
int vmcSavesProbe(const char *image);
// The saves in the card's root, up to max: their count, or -1. freeKb (may be NULL) gets the free space.
int vmcSavesList(const char *image, vmc_save_t *out, int max, unsigned int *freeKb);
// The save folders under parent ("mass0:/VMC/SAVES/"), up to max: their count (0 when parent is missing).
int vmcSavesListFolder(const char *parent, vmc_save_t *out, int max);
// One save from the card to <parent><save>/ (parent is made if missing). 1 done, -1 already there, 0 failed.
int vmcSavesExport(const char *image, const char *save, const char *parent);
// <parent><save>/ into the card's root. 1 done, -1 a save of that name is on the card, 0 failed.
int vmcSavesImport(const char *parent, const char *save, const char *image);
// One save off the card. 1 done, 0 failed.
int vmcSavesDelete(const char *image, const char *save);
// An icon.sys head (at least 0xC0 + 68 bytes) to its title in ASCII.
void vmcSavesTitle(const unsigned char *iconSys, int size, char *out, int outSize);

#endif
