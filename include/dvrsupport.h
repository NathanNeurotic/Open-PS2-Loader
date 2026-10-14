#ifndef __DVR_SUPPORT_H
#define __DVR_SUPPORT_H

#include "include/iosupport.h"

/* DESR-only, compile-time opt-in (make DVRP=1), settings-default Off.
 * Exclusive read-only DVRP storage source; requires pcm720 Neutrino bsd-dvr
 * as an EXTERNAL installation, never changes or flashes DVRP firmware. */
#ifdef DVRP
int dvrIsAvailable(void);
item_list_t *dvrGetObject(int initOnly);
#endif

#endif
