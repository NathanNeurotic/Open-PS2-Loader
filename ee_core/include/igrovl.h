/*
  igrovl.h the in-game menu as an overlay outside ee_core (IGR_OVERLAY builds)

  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  RetroAchievements editions have no room in ee_core's ram84 for the menu (igrmenu.c, igrmbox.c): RA's own code fills
  it. There the menu is a small EE program of its own, igrovl.elf (ee_core/igrovl), linked at IGROVL_BASE, which
  the launcher copies into the top of the module storage region only for a launch with In-Game Menu on (and only
  at the default storage address, with room above the modules). With the menu off nothing is copied and the
  storage is what it always was; ee_core keeps only the stub in igrovl_stub.c.

  The overlay does not link against ee_core: ee_core hands it what it needs in igrovl_api_t, and the overlay's
  igrovl_hdr_t, at IGROVL_BASE, says where its entry points are.
*/

#ifndef IGROVL_H
#define IGROVL_H

#include <tamtypes.h>

#define IGROVL_BASE  0x000CC000 // up to 0xD0000, the top of the module storage region (ee_core/linkfile)
#define IGROVL_SIZE  0x4000     // code, data and bss
#define IGROVL_MAGIC 0x4F524749 // "IGRO"
#define IGROVL_ABI   1          // igrovl_api_t's layout; the launcher only copies an overlay of the same ABI

struct EECoreConfig_t;
struct igr_cheats;

typedef struct
{
    struct EECoreConfig_t *config;
    int (*CheatLiveApply)(const void *b);
    int (*CheatLiveFits)(const void *b, u32 at);
    u32 **codeentry;
    void (*CopyToIop)(void *eedata, unsigned int size, void *iopptr);
    int (*LoadOPLModule)(int id, int mode, int arg_len, const char *args);
    const u64 *gsRegs;         // GSMSourceGSRegs[11]
    const u16 *setGsCrt;       // GSMSourceSetGsCrt[3]
    int (*FlushCache)(int op); // the kernel calls too, so the overlay links no libkernel (4 KB of syscall stubs)
    u64 (*GsGetIMR)(void);
    u64 (*GsPutIMR)(u64 imr);
} igrovl_api_t;

typedef struct
{
    u32 magic; // IGROVL_MAGIC
    u32 abi;   // IGROVL_ABI
    int (*run)(const igrovl_api_t *api, u16 (*buttons)(void));
    void (*link)(const igrovl_api_t *api); // at every IOP reset: load igrmbox.irx
    u32 end;                               // the first byte past the overlay's bss
} igrovl_hdr_t;

#endif
