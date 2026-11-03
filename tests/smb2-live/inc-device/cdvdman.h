#ifndef HOST_CDVDMAN_H
#define HOST_CDVDMAN_H
/* host: the values of the PS2SDK's libcdvd-common.h that device-smb.c returns */
enum {
    SCECdErNO = 0x00,
    SCECdErREAD = 0x30,
};
enum {
    SCECdComplete = 0x02,
};
#endif
