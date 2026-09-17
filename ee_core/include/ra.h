/*
  RetroAchievements support inside the running game. See src/ra.c.
*/
#ifndef RA_H
#define RA_H

/* Lab probe ladder, 0 in every real build: how much of our half the
   game gets. See iopmgr.c. */
#ifndef RA_PROBE
#define RA_PROBE 0
#endif

/* Copy the watch list out of the loader config before the game
   overwrites loader memory. Call once during ee_core init. */
void RA_SetupWatchList(void);

/* Per-frame hook, called from the VBLANK_END interrupt handler. */
void RA_OnVblank(void);

#endif
