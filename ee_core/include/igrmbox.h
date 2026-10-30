/*
  igrmbox.h the in-game menu's mailbox to igrmbox.irx (modules/iopcore/common/igrmbox.h); see src/igrmbox.c.
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#ifndef IGRMBOX_EE_H
#define IGRMBOX_EE_H

#include <tamtypes.h>

// At an IOP reset, with ee_core's own SIF RPC live and In-Game Menu on (loads igrmbox.irx); the rest only while
// the game is paused. Every call is a no-op when the module is not there.
void IGR_MboxLink(void);
// an IOP buffer of size bytes (a multiple of 16): its address, or 0 (none to spare)
u32 IGR_MboxBegin(u32 size);
// size bytes of it from offset into data (64-byte aligned)
int IGR_MboxSend(u32 offset, void *data, u32 size);
void IGR_MboxEnd(void);
void IGR_MboxHush(void); // the menu opened: the SPU2 silent and its voices held
void IGR_MboxWake(void); // RESUME: the sound goes on where it stopped

#endif
