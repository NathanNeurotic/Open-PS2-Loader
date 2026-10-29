#ifndef _CHEATAPI_H_
#define _CHEATAPI_H_

#include "include/cheat_engine.h"
#include "include/ee_core.h"

void EnableCheats(void);
void DisableCheats(void);
void LinkImage(void);

#include "igrcheats.h"
// The in-game menu's cheat page (igrcheats.h): rebuild the code set from the rows ticked (0: busy, try later), and
// whether one more row still fits a set
int CheatLiveApply(const igr_cheats_t *b);
int CheatLiveFits(const igr_cheats_t *b, u32 at);

/**
 * code_t - a code object
 * @addr: code address
 * @val: code value
 */
typedef struct
{
    u32 addr;
    u32 val;
} code_t;

#endif /* _CHEATAPI_H_ */
