#ifndef _CHEATCONFIG_H_
#define _CHEATCONFIG_H_

#include "cheatman.h"

/*
  Remembered cheat picks (ported from upstream Open-PS2-Loader PR #1748): the cheats a player turns
  on in the Select-mode picker are kept in the game's own CFG and matched back by NAME, so a
  reordered or extended .cht keeps them. Master codes are always on and cannot be switched off.
*/

// 1 for the standard required-code headings: "Mastercode", "Master Code", "Enable Code (Must Be On)"
// (case and spacing ignored).
int cheatConfigIsMasterCode(const char *name);

// Optional cheats off, master codes on, then every cheat this game's CFG remembers switched back on.
void cheatConfigLoadSelections(config_set_t *configSet);

// The enabled optional cheats, written over the game's earlier picks as numbered CFG values.
void cheatConfigSaveSelections(config_set_t *configSet);

#endif /* _CHEATCONFIG_H_ */
