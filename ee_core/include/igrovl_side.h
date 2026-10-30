/*
  igrovl_side.h what igrmenu.c and igrmbox.c take from ee_core, as the overlay reaches it (IGR_OVERLAY_SIDE)

  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Included after every other header of those two files, so the prototypes ee_core's headers declare are left
  alone and only the uses below them are turned into calls through igrovlApi (ee_core/include/igrovl.h).
*/

#ifndef IGROVL_SIDE_H
#define IGROVL_SIDE_H

#include "igrovl.h"

extern const igrovl_api_t *igrovlApi;

#define g_ee_core_config             (*igrovlApi->config)
#define CheatLiveApply(b)            igrovlApi->CheatLiveApply(b)
#define CheatLiveFits(b, at)         igrovlApi->CheatLiveFits(b, at)
#define codeentry                    (*igrovlApi->codeentry)
#define CopyToIop(d, n, p)           igrovlApi->CopyToIop(d, n, p)
#define LoadOPLModule(id, m, n, arg) igrovlApi->LoadOPLModule(id, m, n, arg)
#define GSMSourceGSRegs              (igrovlApi->gsRegs)
#define GSMSourceSetGsCrt            (igrovlApi->setGsCrt)
#define FlushCache(op)               igrovlApi->FlushCache(op)
#define GsGetIMR()                   igrovlApi->GsGetIMR()
#define GsPutIMR(imr)                igrovlApi->GsPutIMR(imr)

#endif
