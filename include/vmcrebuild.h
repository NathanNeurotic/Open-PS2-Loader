#ifndef VMCREBUILD_H
#define VMCREBUILD_H

/* Rebuild a native VMC the native core cannot map (#986): a verified, reserved copy replaces the card,
 * and the card is kept beside it as "<name>.bak". One rebuild at a time, like genvmc itself.
 * Outcomes of vmcRebuildStart (0 = genvmc accepted the copy job) and vmcRebuildFinish. */
enum vmc_rebuild_result {
    VMC_REBUILD_DONE = 0,      // the card is the rebuilt copy; the old card is "<name>.bak"
    VMC_REBUILD_FAILED = -1,   // nothing changed (the copy, if any was made, is gone)
    VMC_REBUILD_NO_ROOM = -2,  // not enough unbroken free space for a mappable copy; nothing changed
    VMC_REBUILD_ABORTED = -3,  // cancelled; nothing changed
    VMC_REBUILD_LEFTOVER = -4, // "<name>.bak" or "<name>.new" is already there; never overwritten
    VMC_REBUILD_STUCK = -5,    // a rename failed half way: "<name>.bak" and "<name>.new" are both kept
    VMC_REBUILD_UNSYNCED = -6, // swapped, but PFS could not commit it: the old card is still "<name>.bak"
};

// The card at path (<prefix>VMC/<name>.bin, sizeMb MB) for the native core: 1 it maps, 0 it does not
// but a rebuilt copy could (BDM fragmented, HDD PFS map too long), -1 the store cannot tell.
int vmcRebuildLayout(const char *path, int sizeMb);
// Start the copy job for the card at path. 0 = started; otherwise a vmc_rebuild_result.
int vmcRebuildStart(const char *path, int sizeMb);
// Once genvmc reports the started job finished: check the copy's layout and swap it in.
int vmcRebuildFinish(int jobError);

#endif
