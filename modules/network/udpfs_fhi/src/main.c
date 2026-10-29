#include <loadcore.h>
#include <irx.h>

#include "main.h"

int udpfs_fhi_init(void);
void udpfs_fhi_start(void);

IRX_ID(MODNAME, 0x2, 0x1A);

extern struct irx_export_table _exp_udpfsfhi __attribute__((section("data")));

int _start(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    if (udpfs_fhi_init() < 0)
        return MODULE_NO_RESIDENT_END;
    if (RegisterLibraryEntries(&_exp_udpfsfhi) != 0) {
        M_DEBUG("udpfs_fhi: module already loaded\n");
        return MODULE_NO_RESIDENT_END;
    }
    udpfs_fhi_start();

    return MODULE_RESIDENT_END;
}
