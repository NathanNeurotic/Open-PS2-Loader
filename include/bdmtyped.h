#ifndef __BDM_TYPED_H
#define __BDM_TYPED_H

// Typed BDM device names for ELF app handoffs.
//
// bdmfs_fatfs registers every mounted volume as mass<N>: (N = global mount order) and, when the block
// driver fills in bd->path, ALSO as <path><k>: where k counts the mounted devices with the same path, in
// mount order (fs_driver_resolve_volume). RiptOPL itself only ever uses mass<N>:. These helpers spell a
// mass<N>:/... path the typed way so an app that infers "mass means USB" is told which device it is
// really on. Pure string code; the I/O that finds the slot's type and k lives in bdmsupport.c.

#include <stdio.h>
#include <string.h>
#include "include/opl.h" // tamtypes, time_t, base_game_info_t for bdmsupport.h
#include "include/bdmsupport.h"

// The SDK path token for a device type, or NULL where the SDK defines none (UDPBD is Neutrino's own
// driver, PC CARD CF never got a path upstream). Must match the bd->path strings the drivers set.
static inline const char *bdmTypedPathToken(int bdmType)
{
    switch (bdmType) {
        case BDM_TYPE_USB:
            return "usb";
        case BDM_TYPE_ILINK:
            return "ilink";
        case BDM_TYPE_SDC:
            return "mx4sio";
        case BDM_TYPE_ATA:
            return "ata";
        default:
            return NULL;
    }
}

// Parse the slot number out of "mass<N>:..." (digits required, the bare "mass:" is not a slot).
// Returns the slot, or -1 when path is not a numbered mass path; *rest points at the ':' on success.
static inline int bdmParseMassSlot(const char *path, const char **rest)
{
    int slot = 0, digits = 0;
    const char *p;

    if (path == NULL || strncmp(path, "mass", 4) != 0)
        return -1;
    for (p = path + 4; *p >= '0' && *p <= '9'; p++) {
        slot = slot * 10 + (*p - '0');
        digits++;
        if (digits > 2)
            return -1;
    }
    if (digits == 0 || *p != ':')
        return -1;
    if (rest != NULL)
        *rest = p;
    return slot;
}

// Rewrite "mass<N>:<rest>" as "<token><k>:<rest>" for the device type bdmType and typed index k.
// Returns 1 and fills out on success; 0 when the type has no typed name, the path is not a numbered mass
// path (out untouched), or out is too small (out emptied).
static inline int bdmFormatTypedPath(int bdmType, int typedIndex, const char *massPath, char *out, int outLen)
{
    const char *token = bdmTypedPathToken(bdmType);
    const char *rest;
    int ret;

    if (token == NULL || typedIndex < 0 || out == NULL || outLen <= 0)
        return 0;
    if (bdmParseMassSlot(massPath, &rest) < 0)
        return 0;
    ret = snprintf(out, outLen, "%s%d%s", token, typedIndex, rest);
    if (ret < 0 || ret >= outLen) {
        out[0] = '\0';
        return 0;
    }
    return 1;
}

#endif
