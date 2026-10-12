/*
  RetroAchievements unlock notice over the running game; see
  src/ra_overlay.c.
*/
#ifndef RA_OVERLAY_H
#define RA_OVERLAY_H

/* Where raudp DMAs events to (struct ra_event, 128 bytes, aligned to 64).
   iopmgr.c passes this address to the module. Without a reserved card packet,
   both event routing and VBLANK handling fall back to the gold pulse. */
void *RA_OverlayEventBuffer(void);
void RA_OverlaySetPacketBuffer(void *buffer);
void *RA_PulseEventBuffer(void);
void RA_PulseOnVblank(unsigned int frames);

/* Per-frame hook, called from RA_OnVblank() with the frame counter that
   ra.c keeps. Picks up new events and runs the pulse, or experimental card
   IMAGE DMA when explicitly opted in. */
void RA_OverlayOnVblank(unsigned int frames);

#endif
