/*
   Copyright 2006-2008, Romz
   Copyright 2010, Polo
   Licenced under Academic Free License version 3.0
   Review OpenUsbLd README & LICENSE files for further details.
   */

#include "mcemu.h"

/* smb_WriteFile() and smb_ReadFile() return the requested byte count when the server reports every byte
   transferred (a WRITE_ANDX reply's Count, a READ_ANDX reply's data length).
   Otherwise they return 0 or a negative error code, or for a read that reached the end of the file, the
   smaller count read before it. smb_OpenAndX() returns 1 on success and a negative code on failure. */

int DeviceWritePage(int mc_num, void *buf, u32 page_num)
{
    u32 offset;

    offset = page_num * vmcSpec[mc_num].cspec.PageSize;
    DPRINTF("writing page 0x%lx at offset 0x%lx\n", page_num, offset);

    return (smb_WriteFile(vmcSpec[mc_num].fid, offset, 0, buf, vmcSpec[mc_num].cspec.PageSize) == vmcSpec[mc_num].cspec.PageSize ? 1 : 0);
}

int DeviceReadPage(int mc_num, void *buf, u32 page_num)
{
    u32 offset;

    offset = page_num * vmcSpec[mc_num].cspec.PageSize;
    DPRINTF("reading page 0x%lx at offset 0x%lx\n", page_num, offset);

    if (vmcSpec[mc_num].fid == 0xFFFF) {
        if (smb_OpenAndX(vmcSpec[mc_num].fname, &vmcSpec[mc_num].fid, 1) <= 0)
            return 0;
    }

    return (smb_ReadFile(vmcSpec[mc_num].fid, offset, 0, buf, vmcSpec[mc_num].cspec.PageSize) == vmcSpec[mc_num].cspec.PageSize ? 1 : 0);
}

void DeviceShutdown(void)
{
    int i;

    for (i = 0; i < 2; i++) {
        if (vmcSpec[i].active) {
            smb_Close(vmcSpec[i].fid);
            vmcSpec[i].fid = 0xFFFF;
            vmcSpec[i].active = 0;
        }
    }
}
