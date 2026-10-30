/*
  igrovl_main.c the in-game menu overlay's entry points (ee_core/include/igrovl.h)

  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  igrmenu.c and igrmbox.c are built into this overlay as they are, with igrovl_side.h turning what they take
  from ee_core into the calls ee_core lends in igrovl_api_t. The launcher zeroes the overlay's bss when it copies
  it in; ee_core calls run() from the IGR thread and link() at every IOP reset, always with the same api.
*/

#include <tamtypes.h>
#include <string.h>
#include "igrovl.h"
#include "igrmenu.h"

extern u8 _igrovl_end[];

const igrovl_api_t *igrovlApi;

void IGR_MboxLink(void);

static int igrovlRun(const igrovl_api_t *api, u16 (*buttons)(void))
{
    igrovlApi = api;
    return IGR_MenuRun(buttons);
}

static void igrovlLink(const igrovl_api_t *api)
{
    igrovlApi = api;
    IGR_MboxLink();
}

const igrovl_hdr_t igrovlHeader __attribute__((section(".igrovl.hdr"), used)) = {
    IGROVL_MAGIC,
    IGROVL_ABI,
    igrovlRun,
    igrovlLink,
    (u32)_igrovl_end,
};

// igrmenu.c's only libc call: ee_core takes it from libkernel, the overlay links no libc
size_t strlen(const char *s)
{
    const char *p = s;
    while (*p)
        p++;
    return p - s;
}
