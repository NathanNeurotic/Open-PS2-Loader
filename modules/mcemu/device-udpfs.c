/*
   Copyright 2006-2008, Romz
   Copyright 2010, Polo
   Licenced under Academic Free License version 3.0
   Review OpenUsbLd README & LICENSE files for further details.
   */

#include "mcemu.h"

/* fd is the server's handle for the VMC, opened read-write by the menu and kept open across the IOP
   reset (src/sources/udpfssupport.cpp). cdvdman's udpfs_vmc_read/udpfs_vmc_write move whole pages. */

int DeviceWritePage(int mc_num, void *buf, u32 page_num)
{
    u32 offset;
    int vmc_fd;

    offset = page_num * vmcSpec[mc_num].cspec.PageSize;
    vmc_fd = vmcSpec[mc_num].fd;

    DPRINTF("writing page 0x%lx at offset 0x%lx\n", page_num, offset);

    return udpfs_vmc_write(vmc_fd, offset, vmcSpec[mc_num].cspec.PageSize, buf) ? 1 : 0;
}

int DeviceReadPage(int mc_num, void *buf, u32 page_num)
{
    u32 offset;
    int vmc_fd;

    offset = page_num * vmcSpec[mc_num].cspec.PageSize;
    vmc_fd = vmcSpec[mc_num].fd;

    DPRINTF("fd: %i reading page 0x%lx at offset 0x%lx\n", vmc_fd, page_num, offset);

    return udpfs_vmc_read(vmc_fd, offset, vmcSpec[mc_num].cspec.PageSize, buf) ? 1 : 0;
}

void DeviceShutdown(void)
{
}
