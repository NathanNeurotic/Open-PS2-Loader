#ifndef NATIVEVMC_H
#define NATIVEVMC_H

/* Rejected cards remain inactive; these reasons never bypass native write guards. */
enum native_vmc_error {
    NATIVE_VMC_OK,
    NATIVE_VMC_INVALID,
    NATIVE_VMC_FRAGMENTED,
    NATIVE_VMC_LBA_RANGE,
    NATIVE_VMC_LAYOUT_UNKNOWN,
    NATIVE_VMC_PFS_LIMIT
};

#endif
